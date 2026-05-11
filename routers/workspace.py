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
    get_chat_history_file, check_workspace_owner
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
    if not os.path.exists(UPLOAD_ROOT):
        return {"workspaces": []}
    all_dirs = [d for d in os.listdir(UPLOAD_ROOT)
                if os.path.isdir(os.path.join(UPLOAD_ROOT, d)) and d != "__pycache__"]
    result = []
    for ws in sorted(all_dirs):
        owner_file = os.path.join(get_workspace_path(ws), ".owner")
        if os.path.exists(owner_file):
            with open(owner_file) as f:
                if f.read().strip() != username:
                    continue
        dn_file = os.path.join(get_workspace_path(ws), ".display_name")
        display_name = ws
        if os.path.exists(dn_file):
            with open(dn_file) as f:
                display_name = f.read().strip() or ws
        meta = {"name": display_name, "slug": ws, "last_message": None, "last_updated": None, "message_count": 0}
        try:
            chats = load_chats_metadata(ws)
            if chats:
                chats_sorted = sorted(chats, key=lambda c: c.get("updated_at") or c.get("created_at") or "")
                latest = chats_sorted[-1]
                meta["last_updated"] = latest.get("updated_at") or latest.get("created_at")
                hist = load_history(ws, latest.get("id"))
                if hist:
                    for m in reversed(hist):
                        if m.get("role") == "assistant":
                            meta["last_message"] = m.get("content", "")[:100]
                            break
                    meta["message_count"] = sum(1 for m in hist if m.get("role") == "user")
        except Exception:
            pass
        result.append(meta)
    result.sort(key=lambda x: x["last_updated"] or 0, reverse=True)
    return {"workspaces": result}


@router.post("/workspace/create")
async def create_workspace(data: WorkspaceRequest, username: str = Depends(_require_auth)):
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    base_slug = get_safe_name(data.workspace_name)
    if not base_slug:
        raise HTTPException(status_code=400, detail="Invalid workspace name")
    slug = get_safe_name(f"{username}-{base_slug}")
    path = get_workspace_path(slug)
    if os.path.exists(path):
        raise HTTPException(status_code=400, detail="Workspace already exists")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, ".owner"), "w") as f:
        f.write(username)
    with open(os.path.join(path, "history.json"), "w") as f:
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
    path = get_workspace_path(slug)
    check_workspace_owner(slug, username)
    try:
        chroma_delete_workspace(slug, username)
    except Exception:
        pass
    if os.path.exists(path):
        shutil.rmtree(path)
    sync_workspace_delete(slug, username)
    return {"message": f"Workspace {slug} deleted"}


@router.post("/workspace/rename")
async def rename_workspace(data: WorkspaceRenameRequest, username: str = Depends(_require_auth)):
    if not data.new_name or not data.new_name.strip():
        raise HTTPException(status_code=400, detail="New name cannot be empty")
    slug = get_safe_name(data.workspace_name)
    path = get_workspace_path(slug)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workspace not found")
    check_workspace_owner(slug, username)
    with open(os.path.join(path, ".display_name"), "w") as f:
        f.write(data.new_name.strip())
    return {"message": "Renamed", "slug": slug, "name": data.new_name.strip()}


@router.get("/workspace/{workspace_name}/history")
async def get_history(workspace_name: str, chat_id: Optional[str] = None,
                      username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"history": load_history(slug, chat_id)}


@router.get("/workspace/{workspace_name}/chats")
async def list_chats(workspace_name: str, username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    chats = load_chats_metadata(slug)
    chats.sort(key=lambda c: c.get("updated_at") or c.get("created_at") or "", reverse=True)
    return {"chats": chats}


@router.get("/workspace/{workspace_name}/files")
async def get_files(workspace_name: str, username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    path = get_workspace_path(slug)
    if not os.path.exists(path):
        return {"files": []}
    excluded = {"history.json", "chats.json", ".owner", ".display_name"}
    files = [f for f in os.listdir(path)
             if os.path.isfile(os.path.join(path, f))
             and f not in excluded
             and not f.startswith("chat_")]
    return {"files": sorted(files)}


@router.post("/chat/create")
async def create_chat(data: ChatCreateRequest, username: str = Depends(_require_auth)):
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    chat_id = str(uuid.uuid4())
    title = (data.chat_title or "").strip() or "New Chat"
    now = datetime.now().isoformat()
    chats = load_chats_metadata(slug)
    chats.append({"id": chat_id, "title": title, "created_at": now, "updated_at": now})
    save_chats_metadata(slug, chats)
    save_history(slug, [], chat_id)
    sync_chat_create(slug, chat_id, title, username)
    return {"chat": {"id": chat_id, "title": title, "created_at": now, "updated_at": now}}


@router.post("/chat/delete")
async def delete_chat(data: ChatDeleteRequest, username: str = Depends(_require_auth)):
    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not data.chat_id or not data.chat_id.strip():
        raise HTTPException(status_code=400, detail="chat_id cannot be empty")
    chats = [c for c in load_chats_metadata(slug) if c.get("id") != data.chat_id]
    save_chats_metadata(slug, chats)
    hist_path = get_chat_history_file(slug, data.chat_id)
    if os.path.exists(hist_path):
        os.remove(hist_path)
    sync_chat_delete(data.chat_id, username)
    return {"message": "Chat deleted"}
