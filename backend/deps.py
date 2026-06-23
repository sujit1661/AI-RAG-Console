"""
Shared FastAPI dependencies.

Workspace metadata (owner, display_name, chats, history) is stored in
Supabase when available, with local disk as a transparent fallback for
local dev. Uploaded files are still written to disk temporarily for text
extraction, then discarded — they are the only thing that touches disk.
"""
import os
import re
import json
import logging
from typing import Optional, List
from fastapi import Request, HTTPException
from backend.auth import get_current_user

logger = logging.getLogger(__name__)

UPLOAD_ROOT = "uploads"
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _get_supabase():
    try:
        from backend.supabase_config import get_supabase
        return get_supabase()
    except Exception:
        return None

async def get_token(request: Request) -> Optional[str]:
    token = request.cookies.get("session_token")
    if token:
        return token
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth.split(" ")[1]
    return None

def get_safe_name(name: str) -> str:
    slug = re.sub(r'[^\w\s-]', '', name).strip().lower()
    return re.sub(r'[-\s]+', '-', slug)

def get_workspace_path(slug: str) -> str:
    return os.path.join(UPLOAD_ROOT, slug)

# ─────────────────────────────────────────────
# Workspace existence check
# Supabase is authoritative; local dir is the fallback.
# ─────────────────────────────────────────────

def workspace_exists(slug: str) -> bool:
    """
    Check if a workspace exists.
    Uses Supabase workspaces table as primary, local disk as fallback.
    """
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("workspaces").select("slug").eq("slug", slug).execute()
            if res.data:
                return True
        except Exception as e:
            logger.warning(f"workspace_exists Supabase failed: {e}")
    return os.path.exists(get_workspace_path(slug))

def workspace_accessible(slug: str) -> bool:
    """
    Broader check — workspace exists if it has a workspaces row,
    local dir, OR any documents/embeddings (for legacy workspaces).
    Used by chat endpoints to avoid blocking existing data.
    """
    if workspace_exists(slug):
        return True
    # Legacy: has data but no workspaces row
    sb = _get_supabase()
    if sb:
        try:
            doc_res = sb.table("documents").select("id").eq("workspace_slug", slug).limit(1).execute()
            if doc_res.data:
                return True
            emb_res = sb.table("embeddings").select("id").eq("workspace_slug", slug).limit(1).execute()
            if emb_res.data:
                return True
        except Exception:
            pass
    return False

def check_workspace_owner(slug: str, username: str):
    """Raise 403 if username doesn't own the workspace."""
    sb = _get_supabase()
    if sb:
        try:
            user_res = sb.table("users").select("id").eq("username", username).execute()
            if not user_res.data:
                raise HTTPException(status_code=403, detail="Not authorized")
            user_id = user_res.data[0]["id"]
            ws_res = sb.table("workspaces").select("owner_id").eq("slug", slug).execute()
            if ws_res.data and ws_res.data[0]["owner_id"] != user_id:
                raise HTTPException(status_code=403, detail="Not authorized")
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"check_workspace_owner Supabase failed, falling back: {e}")

    # Local fallback
    owner_file = os.path.join(get_workspace_path(slug), ".owner")
    if os.path.exists(owner_file):
        with open(owner_file) as f:
            if f.read().strip() != username:
                raise HTTPException(status_code=403, detail="Not authorized")

# ─────────────────────────────────────────────
# Chats metadata
# Supabase public.chats is the source of truth.
# ─────────────────────────────────────────────

def load_chats_metadata(slug: str) -> List[dict]:
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("chats")\
                .select("id, title, created_at, updated_at")\
                .eq("workspace_slug", slug)\
                .order("updated_at", desc=False)\
                .execute()
            return res.data or []
        except Exception as e:
            logger.warning(f"load_chats_metadata Supabase failed: {e}")

    # Local fallback
    path = _chats_file(slug)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_chats_metadata(slug: str, chats: List[dict]):
    """Local-only save — Supabase is updated via persistence.py upsert_chat."""
    _ensure_local_dir(slug)
    try:
        with open(_chats_file(slug), "w") as f:
            json.dump(chats, f, indent=4)
    except Exception as e:
        logger.warning(f"save_chats_metadata local failed: {e}")

def _chats_file(slug: str) -> str:
    return os.path.join(get_workspace_path(slug), "chats.json")

# ─────────────────────────────────────────────
# Chat history (messages)
# Supabase public.messages is the source of truth.
# ─────────────────────────────────────────────

def get_chat_history_file(slug: str, chat_id: str) -> str:
    return os.path.join(get_workspace_path(slug), f"chat_{chat_id}.json")

def load_history(slug: str, chat_id: str = None) -> List[dict]:
    if chat_id:
        # Try Supabase first
        sb = _get_supabase()
        if sb:
            try:
                res = sb.table("messages")\
                    .select("role, content")\
                    .eq("chat_id", chat_id)\
                    .order("created_at")\
                    .execute()
                if res.data is not None:
                    return [{"role": r["role"], "content": r["content"]} for r in res.data]
            except Exception as e:
                logger.warning(f"load_history Supabase failed: {e}")

        # Local fallback
        path = get_chat_history_file(slug, chat_id)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    # Legacy: no chat_id — return from legacy history.json
    legacy = os.path.join(get_workspace_path(slug), "history.json")
    if os.path.exists(legacy):
        try:
            with open(legacy) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_history(slug: str, history: List[dict], chat_id: str = None):
    """Local-only save — Supabase messages written via persistence.sync_message_add."""
    _ensure_local_dir(slug)
    try:
        if not chat_id:
            path = os.path.join(get_workspace_path(slug), "history.json")
        else:
            path = get_chat_history_file(slug, chat_id)
        with open(path, "w") as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        logger.warning(f"save_history local failed: {e}")

# ─────────────────────────────────────────────
# Workspace list — read from Supabase
# ─────────────────────────────────────────────

def list_workspaces_for_user(username: str) -> List[dict]:
    """
    Return workspace metadata list for a user.
    Uses Supabase when available; falls back to local dirs.
    """
    sb = _get_supabase()
    if sb:
        try:
            user_res = sb.table("users").select("id").eq("username", username).execute()
            if not user_res.data:
                return []
            user_id = user_res.data[0]["id"]
            ws_res = sb.table("workspaces")\
                .select("slug, name, display_name, updated_at")\
                .eq("owner_id", user_id)\
                .execute()
            result = []
            for ws in (ws_res.data or []):
                result.append({
                    "slug": ws["slug"],
                    "name": ws.get("display_name") or ws["name"],
                    "last_message": None,
                    "last_updated": ws.get("updated_at"),
                    "message_count": 0,
                })
            return result
        except Exception as e:
            logger.warning(f"list_workspaces_for_user Supabase failed: {e}")

    # Local fallback
    if not os.path.exists(UPLOAD_ROOT):
        return []
    result = []
    for ws in sorted(os.listdir(UPLOAD_ROOT)):
        if not os.path.isdir(os.path.join(UPLOAD_ROOT, ws)) or ws == "__pycache__":
            continue
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
        result.append({
            "slug": ws,
            "name": display_name,
            "last_message": None,
            "last_updated": None,
            "message_count": 0,
        })
    return result

# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _ensure_local_dir(slug: str):
    os.makedirs(get_workspace_path(slug), exist_ok=True)
