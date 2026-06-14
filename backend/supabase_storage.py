"""
Supabase Storage operations for document files.
"""
import logging
from typing import Optional
from backend.supabase_config import get_supabase, STORAGE_BUCKET

logger = logging.getLogger(__name__)


def upload_file_to_supabase(workspace_slug: str, filename: str, file_content: bytes) -> Optional[str]:
    """Upload a file to Supabase Storage. Returns the storage path or None."""
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        response = supabase.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_content,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        if response:
            return storage_path
    except Exception as e:
        logger.warning(f"Supabase Storage upload failed (non-fatal): {e}")
    return None


def delete_file_from_supabase(workspace_slug: str, filename: str) -> bool:
    """Delete a file from Supabase Storage."""
    supabase = get_supabase()
    try:
        storage_path = f"workspaces/{workspace_slug}/{filename}"
        supabase.storage.from_(STORAGE_BUCKET).remove([storage_path])
        return True
    except Exception as e:
        logger.warning(f"Supabase Storage delete failed (non-fatal): {e}")
    return False
