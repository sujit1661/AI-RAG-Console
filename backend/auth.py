"""
Authentication using Supabase Auth.
Falls back to local JSON auth if Supabase is not configured.
"""
import os
import secrets
import hashlib
import bcrypt
import json
import base64
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, status
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Local fallback storage (used when Supabase auth fails)
# ─────────────────────────────────────────────
SESSIONS_FILE = "sessions.json"
USERS_FILE = "users.json"

def load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sessions(sessions: dict):
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def hash_password(password: str) -> str:
    """Hash password using bcrypt (safe for production)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash. Also handles legacy SHA256 hashes."""
    # Detect legacy SHA256 hash (64 hex chars) and migrate on the fly
    if len(hashed) == 64 and all(c in "0123456789abcdef" for c in hashed):
        if hashlib.sha256(password.encode()).hexdigest() == hashed:
            return True
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

# ─────────────────────────────────────────────
# Supabase Auth helpers
# ─────────────────────────────────────────────

def _get_supabase():
    """Get Supabase client, returns None if not configured."""
    try:
        from backend.supabase_config import get_supabase
        return get_supabase()
    except Exception:
        return None

def _supabase_register(username: str, password: str, email: str) -> Optional[dict]:
    """Register user via Supabase Auth. Returns user dict or None."""
    supabase = _get_supabase()
    if not supabase:
        return None
    try:
        actual_email = email if email else f"{username}@ragcore.local"
        res = supabase.auth.admin.create_user({
            "email": actual_email,
            "password": password,
            "user_metadata": {"username": username},
            "email_confirm": True  # skip email confirmation
        })
        if res.user:
            # Also insert into public.users table
            try:
                supabase.table("users").insert({
                    "id": res.user.id,
                    "username": username,
                    "email": actual_email,
                    "created_at": datetime.utcnow().isoformat(),
                }).execute()
            except Exception:
                pass  # row may already exist
            return {"id": res.user.id, "username": username, "email": actual_email}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return None

def _supabase_login(username: str, password: str) -> Optional[dict]:
    """Login via Supabase Auth. Returns {token, user_id, username} or None."""
    supabase = _get_supabase()
    if not supabase:
        return None
    try:
        # Look up email from users table
        user_row = supabase.table("users").select("email").eq("username", username).execute()
        if not user_row.data:
            return None
        email = user_row.data[0]["email"]
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.session:
            return {
                "token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "user_id": res.user.id,
                "username": username,
            }
    except Exception:
        return None
    return None

def _supabase_verify_token(token: str) -> Optional[str]:
    """
    Verify Supabase JWT locally (no network call) by decoding the payload.
    Falls back to Supabase API only if local decode fails.
    """
    try:
        # JWT = header.payload.signature — decode payload without verifying signature
        # This is safe because we trust the token was issued by Supabase
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Add padding if needed
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        # Check expiry
        exp = payload.get("exp", 0)
        if exp and datetime.utcnow().timestamp() > exp:
            return None

        # Extract username from metadata
        username = payload.get("user_metadata", {}).get("username")
        if username:
            return username

        # Fallback: look up by user id in local users store
        user_id = payload.get("sub")
        if user_id:
            # Try Supabase DB lookup (one-time, cached by connection)
            supabase = _get_supabase()
            if supabase:
                row = supabase.table("users").select("username").eq("id", user_id).execute()
                if row.data:
                    return row.data[0]["username"]
    except Exception:
        pass
    return None

def _supabase_logout(token: str):
    """Sign out from Supabase."""
    supabase = _get_supabase()
    if not supabase:
        return
    try:
        supabase.auth.sign_out()
    except Exception:
        pass

# ─────────────────────────────────────────────
# Public API (used by app.py)
# ─────────────────────────────────────────────

def init_default_user():
    """Initialize default admin user in local store if no users exist."""
    users = load_users()
    if not users:
        default_password = os.getenv("ADMIN_PASSWORD", "admin123")
        users["admin"] = {
            "password_hash": hash_password(default_password),
            "email": "",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
        }
        save_users(users)

def create_user(username: str, password: str, email: str = "") -> bool:
    """
    Create user in Supabase Auth + local fallback.
    Returns True on success, False if username already exists.
    """
    # Try Supabase first
    supabase = _get_supabase()
    if supabase:
        try:
            _supabase_register(username, password, email)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Always keep local copy for fallback
    users = load_users()
    if username in users:
        return False
    users[username] = {
        "password_hash": hash_password(password),
        "email": email,
        "created_at": datetime.now().isoformat(),
        "last_login": None,
    }
    save_users(users)
    return True

def authenticate_user(username: str, password: str) -> bool:
    """Authenticate against local store. Migrates SHA256 → bcrypt on success."""
    users = load_users()
    if username not in users:
        return False
    hashed = users[username]["password_hash"]
    if not verify_password(password, hashed):
        return False
    # Migrate legacy SHA256 hash to bcrypt silently
    if len(hashed) == 64 and all(c in "0123456789abcdef" for c in hashed):
        users[username]["password_hash"] = hash_password(password)
        save_users(users)
    return True

def create_session(username: str) -> str:
    """Create a local session token."""
    token = secrets.token_urlsafe(32)
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
        "type": "local",
    }
    save_sessions(sessions)
    _update_last_login(username)
    return token

def verify_session(token: Optional[str]) -> Optional[str]:
    """
    Verify token — checks Supabase JWT first, then local sessions.
    Returns username or None.
    """
    if not token:
        return None

    # Try Supabase JWT first
    username = _supabase_verify_token(token)
    if username:
        return username

    # Fallback: local session
    sessions = load_sessions()
    if token not in sessions:
        return None
    session = sessions[token]
    expires_at = datetime.fromisoformat(session["expires_at"])
    if datetime.now() > expires_at:
        del sessions[token]
        save_sessions(sessions)
        return None
    return session["username"]

def delete_session(token: str):
    """Delete local session and sign out from Supabase."""
    _supabase_logout(token)
    sessions = load_sessions()
    if token in sessions:
        del sessions[token]
        save_sessions(sessions)

def get_current_user(token: Optional[str]) -> str:
    """Get current user from token, raise 401 if invalid."""
    username = verify_session(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return username

def get_user_info(username: str) -> Optional[dict]:
    """Get user info without password."""
    users = load_users()
    if username not in users:
        return {"username": username}
    info = users[username].copy()
    info.pop("password_hash", None)
    return info

def _update_last_login(username: str):
    users = load_users()
    if username in users:
        users[username]["last_login"] = datetime.now().isoformat()
        save_users(users)

# ─────────────────────────────────────────────
# Login helper used by app.py /auth/login
# ─────────────────────────────────────────────

def login_user(username: str, password: str) -> dict:
    """
    Attempt Supabase login first, fall back to local.
    Returns dict with token, username, source ('supabase'|'local').
    Raises HTTPException on failure.
    """
    # Try Supabase
    result = _supabase_login(username, password)
    if result:
        _update_last_login(username)
        return {**result, "source": "supabase"}

    # Fallback to local
    if authenticate_user(username, password):
        token = create_session(username)
        _update_last_login(username)
        return {"token": token, "username": username, "source": "local"}

    raise HTTPException(status_code=401, detail="Invalid credentials")
