"""
Supabase database operations for RAG system.
Handles workspaces, chats, messages, documents, and general-chat sessions.
"""
import uuid
import logging
from typing import List, Optional, Dict
from datetime import datetime
from backend.supabase_config import get_supabase

logger = logging.getLogger(__name__)


# ==================== WORKSPACES ====================

def create_workspace(user_id: str, name: str, slug: str) -> Dict:
    supabase = get_supabase()
    try:
        response = supabase.table("workspaces").insert({
            "slug": slug,
            "name": name,
            "owner_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).execute()
        return {"success": True, "workspace": response.data[0] if response.data else None}
    except Exception as e:
        logger.warning(f"create_workspace failed: {e}")
        return {"success": False, "error": str(e)}


def delete_workspace(slug: str, user_id: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("workspaces").delete().eq("slug", slug).eq("owner_id", user_id).execute()
        return True
    except Exception as e:
        logger.warning(f"delete_workspace failed: {e}")
        return False


# ==================== RAG CHATS ====================

def upsert_chat(chat_id: str, workspace_slug: str, title: str, owner_id: str) -> bool:
    """Insert or update a chat row (no FK constraint on workspace_slug so always safe)."""
    supabase = get_supabase()
    try:
        now = datetime.utcnow().isoformat()
        supabase.table("chats").upsert({
            "id": chat_id,
            "workspace_slug": workspace_slug,
            "title": title,
            "owner_id": owner_id,
            "updated_at": now,
        }, on_conflict="id").execute()
        return True
    except Exception as e:
        logger.warning(f"upsert_chat failed: {e}")
        return False


def update_chat_title(chat_id: str, title: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("chats").update({
            "title": title,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", chat_id).execute()
        return True
    except Exception as e:
        logger.warning(f"update_chat_title failed: {e}")
        return False


def delete_chat(chat_id: str, user_id: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("chats").delete().eq("id", chat_id).eq("owner_id", user_id).execute()
        return True
    except Exception as e:
        logger.warning(f"delete_chat failed: {e}")
        return False


# ==================== RAG MESSAGES ====================

def add_message(chat_id: str, role: str, content: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("messages").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return True
    except Exception as e:
        logger.warning(f"add_message failed: {e}")
        return False


# ==================== DOCUMENTS ====================

def add_document_metadata(workspace_slug: str, filename: str, file_path: str,
                          file_size: int, owner_id: str) -> Dict:
    supabase = get_supabase()
    try:
        response = supabase.table("documents").upsert({
            "workspace_slug": workspace_slug,
            "filename": filename,
            "file_path": file_path,
            "file_size": file_size,
            "owner_id": owner_id,
            "uploaded_at": datetime.utcnow().isoformat()
        }, on_conflict="workspace_slug,filename,owner_id").execute()
        return {"success": True, "document": response.data[0] if response.data else None}
    except Exception as e:
        logger.warning(f"add_document_metadata failed: {e}")
        return {"success": False, "error": str(e)}


# ==================== GENERAL CHAT SESSIONS ====================

def create_general_session(username: str, title: str = "New Chat") -> Optional[str]:
    """Create a new general-chat session. Returns the session id."""
    supabase = get_supabase()
    try:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        supabase.table("general_chat_sessions").insert({
            "id": session_id,
            "username": username,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }).execute()
        return session_id
    except Exception as e:
        logger.warning(f"create_general_session failed: {e}")
        return None


def get_general_sessions(username: str) -> List[Dict]:
    """Return all sessions for a user, newest first."""
    supabase = get_supabase()
    try:
        res = supabase.table("general_chat_sessions")\
            .select("id, title, created_at, updated_at")\
            .eq("username", username)\
            .order("updated_at", desc=True)\
            .limit(50)\
            .execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"get_general_sessions failed: {e}")
        return []


def update_general_session_title(session_id: str, title: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("general_chat_sessions").update({
            "title": title,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", session_id).execute()
        return True
    except Exception as e:
        logger.warning(f"update_general_session_title failed: {e}")
        return False


def touch_general_session(session_id: str) -> bool:
    """Update updated_at so session floats to top of list."""
    supabase = get_supabase()
    try:
        supabase.table("general_chat_sessions").update({
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", session_id).execute()
        return True
    except Exception as e:
        logger.warning(f"touch_general_session failed: {e}")
        return False


def delete_general_session(session_id: str, username: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("general_chat_sessions").delete()\
            .eq("id", session_id)\
            .eq("username", username)\
            .execute()
        return True
    except Exception as e:
        logger.warning(f"delete_general_session failed: {e}")
        return False


# ==================== GENERAL CHAT MESSAGES ====================

def add_general_message(session_id: str, role: str, content: str) -> bool:
    supabase = get_supabase()
    try:
        supabase.table("general_chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return True
    except Exception as e:
        logger.warning(f"add_general_message failed: {e}")
        return False


def get_general_messages(session_id: str, username: str) -> List[Dict]:
    """Return all messages for a session (verifies ownership via session table)."""
    supabase = get_supabase()
    try:
        # Verify ownership
        sess = supabase.table("general_chat_sessions")\
            .select("id")\
            .eq("id", session_id)\
            .eq("username", username)\
            .execute()
        if not sess.data:
            return []
        res = supabase.table("general_chat_messages")\
            .select("role, content")\
            .eq("session_id", session_id)\
            .order("created_at")\
            .execute()
        return [{"role": r["role"], "content": r["content"]} for r in (res.data or [])]
    except Exception as e:
        logger.warning(f"get_general_messages failed: {e}")
        return []
