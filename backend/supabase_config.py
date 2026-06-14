"""
Supabase configuration and client setup.
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "documents")

_client: Client = None


def get_supabase() -> Client:
    """Get (or lazily initialise) the Supabase client."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client
