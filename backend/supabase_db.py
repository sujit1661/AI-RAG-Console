"""
Supabase database operations for RAG system.
Handles users, workspaces, chats, messages, and documents.
"""
from typing import List, Optional, Dict
from datetime import datetime
from supabase import Client
from backend.supabase_config import get_supabase

def get_user_id_from_token(token: str) -> Optional[str]:
    """Get user ID from Supabase JWT token."""
    try:
        supabase = get_supabase()
        # Verify token and get user
        response = supabase.auth.get_user(token)
        if response.user:
            return response.user.id
    except Exception as e:
        print(f"Error getting user from token: {e}")
    return None

# ==================== USERS ====================

def create_user_supabase(username: str, email: str, password: str) -> Dict:
    """Create a new user in Supabase Auth."""
    supabase = get_supabase()
    try:
        response = supabase.auth.admin.create_user({
            "email": email or f"{username}@example.com",
            "password": password,
            "user_metadata": {"username": username}
        })
        return {"success": True, "user": response.user}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_user_by_username(username: str) -> Optional[Dict]:
    """Get user by username from metadata."""
    supabase = get_supabase()
    try:
        # Query users table (you'll need to create this)
        response = supabase.table("users").select("*").eq("username", username).execute()
        if response.data:
            return response.data[0]
    except Exception:
        pass
    return None

# ==================== WORKSPACES ====================

def create_workspace(user_id: str, name: str, slug: str) -> Dict:
    """Create a new workspace."""
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
        return {"success": False, "error": str(e)}

def get_user_workspaces(user_id: str) -> List[Dict]:
    """Get all workspaces for a user."""
    supabase = get_supabase()
    try:
        response = supabase.table("workspaces").select("*").eq("owner_id", user_id).order("updated_at", desc=True).execute()
        return response.data or []
    except Exception:
        return []

def get_workspace(slug: str, user_id: str) -> Optional[Dict]:
    """Get a specific workspace (only if user owns it)."""
    supabase = get_supabase()
    try:
        response = supabase.table("workspaces").select("*").eq("slug", slug).eq("owner_id", user_id).execute()
        if response.data:
            return response.data[0]
    except Exception:
        pass
    return None

def delete_workspace(slug: str, user_id: str) -> bool:
    """Delete a workspace and all its data."""
    supabase = get_supabase()
    try:
        # Delete workspace (cascade will delete chats, messages, documents)
        supabase.table("workspaces").delete().eq("slug", slug).eq("owner_id", user_id).execute()
        return True
    except Exception:
        return False

# ==================== CHATS ====================

def create_chat(workspace_slug: str, title: str, user_id: str) -> Dict:
    """Create a new chat in a workspace."""
    supabase = get_supabase()
    import uuid
    chat_id = str(uuid.uuid4())
    try:
        response = supabase.table("chats").insert({
            "id": chat_id,
            "workspace_slug": workspace_slug,
            "title": title or "New Chat",
            "owner_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).execute()
        return {"success": True, "chat": response.data[0] if response.data else None}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_workspace_chats(workspace_slug: str, user_id: str) -> List[Dict]:
    """Get all chats for a workspace."""
    supabase = get_supabase()
    try:
        response = supabase.table("chats").select("*").eq("workspace_slug", workspace_slug).eq("owner_id", user_id).order("updated_at", desc=True).execute()
        return response.data or []
    except Exception:
        return []

def delete_chat(chat_id: str, user_id: str) -> bool:
    """Delete a chat and all its messages."""
    supabase = get_supabase()
    try:
        supabase.table("chats").delete().eq("id", chat_id).eq("owner_id", user_id).execute()
        return True
    except Exception:
        return False

# ==================== MESSAGES ====================

def add_message(chat_id: str, role: str, content: str) -> Dict:
    """Add a message to a chat."""
    supabase = get_supabase()
    try:
        response = supabase.table("messages").insert({
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return {"success": True, "message": response.data[0] if response.data else None}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_chat_history(chat_id: str, user_id: str) -> List[Dict]:
    """Get all messages for a chat."""
    supabase = get_supabase()
    try:
        # First verify user owns the chat
        chat_response = supabase.table("chats").select("id").eq("id", chat_id).eq("owner_id", user_id).execute()
        if not chat_response.data:
            return []
        
        # Get messages
        response = supabase.table("messages").select("*").eq("chat_id", chat_id).order("created_at").execute()
        return response.data or []
    except Exception:
        return []

# ==================== DOCUMENTS ====================

def add_document_metadata(workspace_slug: str, filename: str, file_path: str, file_size: int, user_id: str) -> Dict:
    """Add document metadata to database."""
    supabase = get_supabase()
    try:
        response = supabase.table("documents").insert({
            "workspace_slug": workspace_slug,
            "filename": filename,
            "file_path": file_path,
            "file_size": file_size,
            "owner_id": user_id,
            "uploaded_at": datetime.utcnow().isoformat()
        }).execute()
        return {"success": True, "document": response.data[0] if response.data else None}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_workspace_documents(workspace_slug: str, user_id: str) -> List[Dict]:
    """Get all documents for a workspace."""
    supabase = get_supabase()
    try:
        response = supabase.table("documents").select("*").eq("workspace_slug", workspace_slug).eq("owner_id", user_id).order("uploaded_at", desc=True).execute()
        return response.data or []
    except Exception:
        return []

def delete_document(document_id: int, user_id: str) -> bool:
    """Delete document metadata from database."""
    supabase = get_supabase()
    try:
        supabase.table("documents").delete().eq("id", document_id).eq("owner_id", user_id).execute()
        return True
    except Exception:
        return False

