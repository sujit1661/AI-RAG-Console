"""
Shared FastAPI dependencies used across all routers.
"""
import os
import re
import json
from typing import Optional, List
from fastapi import Request, HTTPException
from backend.auth import get_current_user

UPLOAD_ROOT = "uploads"
os.makedirs(UPLOAD_ROOT, exist_ok=True)


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


def get_chats_metadata_file(slug: str) -> str:
    return os.path.join(get_workspace_path(slug), "chats.json")


def get_chat_history_file(slug: str, chat_id: str) -> str:
    return os.path.join(get_workspace_path(slug), f"chat_{chat_id}.json")


def ensure_chats_metadata_exists(slug: str):
    path = get_chats_metadata_file(slug)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump([], f)


def load_chats_metadata(slug: str) -> List[dict]:
    ensure_chats_metadata_exists(slug)
    with open(get_chats_metadata_file(slug), "r") as f:
        return json.load(f)


def save_chats_metadata(slug: str, chats: List[dict]):
    with open(get_chats_metadata_file(slug), "w") as f:
        json.dump(chats, f, indent=4)


def load_history(slug: str, chat_id: str = None) -> List[dict]:
    if chat_id:
        path = get_chat_history_file(slug, chat_id)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return []
    legacy = os.path.join(get_workspace_path(slug), "history.json")
    if os.path.exists(legacy):
        with open(legacy, "r") as f:
            return json.load(f)
    return []


def save_history(slug: str, history: List[dict], chat_id: str = None):
    if not chat_id:
        with open(os.path.join(get_workspace_path(slug), "history.json"), "w") as f:
            json.dump(history, f, indent=4)
    else:
        with open(get_chat_history_file(slug, chat_id), "w") as f:
            json.dump(history, f, indent=4)


def check_workspace_owner(slug: str, username: str):
    """Raise 403 if username doesn't own the workspace."""
    owner_file = os.path.join(get_workspace_path(slug), ".owner")
    if os.path.exists(owner_file):
        with open(owner_file, "r") as f:
            owner = f.read().strip()
        if owner != username:
            raise HTTPException(status_code=403, detail="Not authorized")
