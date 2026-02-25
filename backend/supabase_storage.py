"""
Supabase Storage operations for document files.
"""
import os
from typing import Optional
from backend.supabase_config import get_supabase, STORAGE_BUCKET

def upload_file_to_supabase(workspace_slug: str, filename: str, file_content: bytes) -> Optional[str]:
    """
    Upload a file to Supabase Storage.
    Returns the file path in storage if successful, None otherwise.
    """
    supabase = get_supabase()
    try:
        # Storage path: workspaces/{workspace_slug}/{filename}
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        
        # Upload file
        response = supabase.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_content,
            file_options={"content-type": "application/octet-stream", "upsert": "false"}
        )
        
        if response:
            return storage_path
    except Exception as e:
        print(f"Error uploading file to Supabase: {e}")
    return None

def get_file_url(workspace_slug: str, filename: str, expires_in: int = 3600) -> Optional[str]:
    """
    Get a signed URL for downloading a file.
    expires_in: URL expiration time in seconds (default 1 hour)
    """
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        response = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
            path=storage_path,
            expires_in=expires_in
        )
        return response.get("signedURL") if response else None
    except Exception as e:
        print(f"Error getting file URL: {e}")
    return None

def download_file_from_supabase(workspace_slug: str, filename: str) -> Optional[bytes]:
    """Download a file from Supabase Storage."""
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        response = supabase.storage.from_(STORAGE_BUCKET).download(path=storage_path)
        return response
    except Exception as e:
        print(f"Error downloading file from Supabase: {e}")
    return None

def delete_file_from_supabase(workspace_slug: str, filename: str) -> bool:
    """Delete a file from Supabase Storage."""
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        supabase.storage.from_(STORAGE_BUCKET).remove([storage_path])
        return True
    except Exception as e:
        print(f"Error deleting file from Supabase: {e}")
    return False

def file_exists_in_supabase(workspace_slug: str, filename: str) -> bool:
    """Check if a file exists in Supabase Storage."""
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        files = supabase.storage.from_(STORAGE_BUCKET).list(path=f"workspaces/{workspace_slug}/")
        if files:
            return any(f.get("name") == filename for f in files)
    except Exception:
        pass
    return False

