"""
Supabase sync layer — fire-and-forget writes that mirror local state to Supabase.
All functions swallow exceptions so a Supabase outage never breaks the main flow.
"""
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_user_id(username: str) -> Optional[str]:
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        res = sb.table("users").select("id").eq("username", username).execute()
        if res.data:
            return res.data[0]["id"]
    except Exception:
        pass
    return None


# ==================== WORKSPACES ====================

def sync_workspace_create(slug: str, name: str, username: str):
    try:
        user_id = _get_user_id(username)
        if not user_id:
            return
        from backend.supabase_db import create_workspace
        create_workspace(user_id, name, slug)
        logger.info(f"Synced workspace {slug} to Supabase")
    except Exception as e:
        logger.warning(f"Supabase workspace sync failed (non-fatal): {e}")


def sync_workspace_delete(slug: str, username: str):
    try:
        user_id = _get_user_id(username)
        if not user_id:
            return
        from backend.supabase_db import delete_workspace
        delete_workspace(slug, user_id)
        logger.info(f"Deleted workspace {slug} from Supabase")
    except Exception as e:
        logger.warning(f"Supabase workspace delete failed (non-fatal): {e}")


# ==================== CHATS ====================

def sync_chat_create(workspace_slug: str, chat_id: str, title: str, username: str):
    """Upsert chat — safe even if workspace row doesn't exist yet in Supabase."""
    try:
        user_id = _get_user_id(username)
        if not user_id:
            return
        from backend.supabase_db import upsert_chat
        upsert_chat(chat_id, workspace_slug, title, user_id)
        logger.info(f"Synced chat {chat_id} to Supabase")
    except Exception as e:
        logger.warning(f"Supabase chat sync failed (non-fatal): {e}")


def sync_chat_update(chat_id: str, title: Optional[str] = None):
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        update_data = {"updated_at": datetime.utcnow().isoformat()}
        if title:
            update_data["title"] = title
        sb.table("chats").update(update_data).eq("id", chat_id).execute()
    except Exception as e:
        logger.warning(f"Supabase chat update failed (non-fatal): {e}")


def sync_chat_delete(chat_id: str, username: str):
    try:
        user_id = _get_user_id(username)
        if not user_id:
            return
        from backend.supabase_db import delete_chat
        delete_chat(chat_id, user_id)
        logger.info(f"Deleted chat {chat_id} from Supabase")
    except Exception as e:
        logger.warning(f"Supabase chat delete failed (non-fatal): {e}")


# ==================== RAG MESSAGES ====================

def sync_message_add(chat_id: str, role: str, content: str):
    try:
        from backend.supabase_db import add_message
        add_message(chat_id, role, content)
    except Exception as e:
        logger.warning(f"Supabase message sync failed (non-fatal): {e}")
