import os
import json
import shutil
import logging
from typing import Optional
from datetime import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import (
    get_token, get_safe_name, get_workspace_path, UPLOAD_ROOT,
    load_chats_metadata, save_chats_metadata, load_history, save_history,
    get_chat_history_file, check_workspace_owner, workspace_exists,
    workspace_accessible, list_workspaces_for_user, _ensure_local_dir,
)
from backend.auth import get_current_user
from backend.retriever import delete_workspace as chroma_delete_workspace
from backend.persistence import (
    sync_workspace_create, sync_workspace_delete,
    sync_chat_create, sync_chat_delete
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workspaces"])


class WorkspaceRequest(BaseModel):
    workspace_name: str

class WorkspaceRenameRequest(BaseModel):
    workspace_name: str
    new_name: str

class ChatCreateRequest(BaseModel):
    workspace_name: str
    chat_title: Optional[str] = None

class ChatDeleteRequest(BaseModel):
    workspace_name: str
    chat_id: str


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


@router.get("/workspace/list")
async def list_workspaces(username: str = Depends(_require_auth)):
    workspaces = list_workspaces_for_user(username)
    if not workspaces:
        return {"workspaces": []}

    slugs = [ws["slug"] for ws in workspaces]
    result = [{**ws} for ws in workspaces]

    # Batch-fetch chats for all workspaces in one query
    chats_by_slug: dict = {}
    sb = None
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        # Get all chats for all user workspaces at once
        chats_res = sb.table("chats")\
            .select("id, workspace_slug, updated_at, created_at")\
            .in_("workspace_slug", slugs)\
            .order("updated_at", desc=True)\
            .execute()
        for c in (chats_res.data or []):
            ws = c["workspace_slug"]
            if ws not in chats_by_slug:
                chats_by_slug[ws] = c  # already sorted desc, first = latest
    except Exception as e:
        logger.warning(f"Batch chat fetch failed: {e}")

    # Batch-fetch message counts per workspace via chats we found
    msg_counts: dict = {}
    last_messages: dict = {}
    latest_chat_ids = [v["id"] for v in chats_by_slug.values()]
    if latest_chat_ids and sb:
        try:
            msgs_res = sb.table("messages")\
                .select("chat_id, role, content")\
                .in_("chat_id", latest_chat_ids)\
                .order("created_at", desc=False)\
                .execute()
            msgs_by_chat: dict = {}
            for m in (msgs_res.data or []):
                cid = m["chat_id"]
                if cid not in msgs_by_chat:
                    msgs_by_chat[cid] = []
                msgs_by_chat[cid].append(m)

            # Map back to workspace slugs
            chat_id_to_slug = {v["id"]: k for k, v in chats_by_slug.items()}
            for cid, msgs in msgs_by_chat.items():
                ws_slug = chat_id_to_slug.get(cid)
                if not ws_slug:
                    continue
                user_msgs = [m for m in msgs if m["role"] == "user"]
                asst_msgs = [m for m in msgs if m["role"] == "assistant"]
                msg_counts[ws_slug] = len(user_msgs)
                if asst_msgs:
                    last_messages[ws_slug] = asst_msgs[-1]["content"][:100]
        except Exception as e:
            logger.warning(f"Batch message fetch failed: {e}")

    # Enrich result
    for meta in result:
        slug = meta["slug"]
        if slug in chats_by_slug:
            c = chats_by_slug[slug]
            meta["last_updated"] = c.get("updated_at") or c.get("created_at")
        if slug in msg_counts:
            meta["message_count"] = msg_counts[slug]
        if slug in last_messages:
            meta["last_message"] = last_messages[slug]

    result.sort(key=lambda x: x.get("last_updated") or "", reverse=True)
    return {"workspaces": result}


@router.post("/workspace/create")
async def create_workspace(data: WorkspaceRequest, username: str = Depends(_require_auth)):
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    base_slug = get_safe_name(data.workspace_name)
    if not base_slug:
        raise HTTPException(status_code=400, detail="Invalid workspace name")
    slug = get_safe_name(f"{username}-{base_slug}")

    if workspace_exists(slug):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"detail": "Workspace already exists", "slug": slug}
        )

    # Create local dir (needed for file uploads during processing)
    _ensure_local_dir(slug)
    # Write .owner for local fallback
    with open(os.path.join(get_workspace_path(slug), ".owner"), "w") as f:
        f.write(username)
    with open(os.path.join(get_workspace_path(slug), "history.json"), "w") as f:
        json.dump([], f)

    try:
        sync_workspace_create(slug, data.workspace_name, username)
    except Exception as e:
        logger.warning(f"Supabase workspace sync failed: {e}")

    logger.info(f"Workspace {slug} created by {username}")
    return {"message": "Created", "slug": slug}


@router.post("/workspace/delete")
async def delete_workspace(data: WorkspaceRequest, username: str = Depends(_require_auth)):
    slug = get_safe_name(data.workspace_name)
    check_workspace_owner(slug, username)

    try:
        chroma_delete_workspace(slug, username)
    except Exception:
        pass

    # Delete local dir if it exists
    path = get_workspace_path(slug)
    if os.path.exists(path):
        shutil.rmtree(path)

    sync_workspace_delete(slug, username)
    return {"message": f"Workspace {slug} deleted"}


@router.post("/workspace/rename")
async def rename_workspace(data: WorkspaceRenameRequest, username: str = Depends(_require_auth)):
    if not data.new_name or not data.new_name.strip():
        raise HTTPException(status_code=400, detail="New name cannot be empty")
    slug = get_safe_name(data.workspace_name)

    if not workspace_accessible(slug):
        raise HTTPException(status_code=404, detail="Workspace not found")
    check_workspace_owner(slug, username)

    new_name = data.new_name.strip()

    # Update Supabase
    from backend.supabase_config import get_supabase
    sb = None
    try:
        sb = get_supabase()
        sb.table("workspaces").update({"display_name": new_name})\
            .eq("slug", slug).execute()
    except Exception as e:
        logger.warning(f"Supabase rename failed: {e}")

    # Local fallback
    path = get_workspace_path(slug)
    if os.path.exists(path):
        with open(os.path.join(path, ".display_name"), "w") as f:
            f.write(new_name)

    return {"message": "Renamed", "slug": slug, "name": new_name}


@router.get("/workspace/{workspace_name}/history")
async def get_history(workspace_name: str, chat_id: Optional[str] = None,
                      username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    if not workspace_accessible(slug):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"history": load_history(slug, chat_id)}


@router.get("/workspace/{workspace_name}/chats")
async def list_chats(workspace_name: str, username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    if not workspace_accessible(slug):
        raise HTTPException(status_code=404, detail="Workspace not found")
    chats = load_chats_metadata(slug)
    chats.sort(key=lambda c: c.get("updated_at") or c.get("created_at") or "", reverse=True)
    return {"chats": chats}


@router.get("/workspace/{workspace_name}/files")
async def get_files(workspace_name: str, username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)

    # Try Supabase documents table first
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        res = sb.table("documents")\
            .select("filename")\
            .eq("workspace_slug", slug)\
            .execute()
        if res.data:  # empty list falls through to disk fallback
            return {"files": sorted(r["filename"] for r in res.data)}
    except Exception as e:
        logger.warning(f"get_files Supabase failed, falling back to disk: {e}")

    # Local fallback
    path = get_workspace_path(slug)
    if not os.path.exists(path):
        return {"files": []}
    excluded = {"history.json", "chats.json", ".owner", ".display_name"}
    files = [
        f for f in os.listdir(path)
        if os.path.isfile(os.path.join(path, f))
        and f not in excluded
        and not f.startswith("chat_")
    ]
    return {"files": sorted(files)}


@router.post("/chat/create")
async def create_chat(data: ChatCreateRequest, username: str = Depends(_require_auth)):
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    slug = get_safe_name(data.workspace_name)
    if not workspace_accessible(slug):
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Ensure workspace row exists in Supabase (auto-repair if missing)
    try:
        sync_workspace_create(slug, data.workspace_name, username)
    except Exception:
        pass  # already exists or non-fatal

    # Ensure local dir exists for history files
    _ensure_local_dir(slug)

    chat_id = str(uuid.uuid4())
    title = (data.chat_title or "").strip() or "New Chat"
    now = datetime.now().isoformat()

    # Supabase (via sync)
    sync_chat_create(slug, chat_id, title, username)

    # Local fallback
    try:
        chats = load_chats_metadata(slug)
        chats.append({"id": chat_id, "title": title, "created_at": now, "updated_at": now})
        save_chats_metadata(slug, chats)
        save_history(slug, [], chat_id)
    except Exception as e:
        logger.warning(f"Local chat metadata save failed: {e}")

    return {"chat": {"id": chat_id, "title": title, "created_at": now, "updated_at": now}}


@router.post("/chat/delete")
async def delete_chat(data: ChatDeleteRequest, username: str = Depends(_require_auth)):
    slug = get_safe_name(data.workspace_name)
    if not workspace_accessible(slug):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not data.chat_id or not data.chat_id.strip():
        raise HTTPException(status_code=400, detail="chat_id cannot be empty")

    # Supabase
    sync_chat_delete(data.chat_id, username)

    # Local fallback cleanup
    try:
        chats = [c for c in load_chats_metadata(slug) if c.get("id") != data.chat_id]
        save_chats_metadata(slug, chats)
        hist_path = get_chat_history_file(slug, data.chat_id)
        if os.path.exists(hist_path):
            os.remove(hist_path)
    except Exception as e:
        logger.warning(f"Local chat delete cleanup failed: {e}")

    return {"message": "Chat deleted"}
