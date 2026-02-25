"""
Supabase configuration and client setup.
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase credentials (set these in .env file)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # Use service key for backend operations
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")  # For frontend if needed

# Storage bucket name for documents
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "documents")

# Initialize Supabase client
supabase: Client = None

def init_supabase():
    """Initialize Supabase client."""
    global supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env file. "
            "Get these from your Supabase project settings."
        )
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return supabase

def get_supabase() -> Client:
    """Get Supabase client instance."""
    global supabase
    if supabase is None:
        supabase = init_supabase()
    return supabase

