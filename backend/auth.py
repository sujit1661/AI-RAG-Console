import os
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Session storage (in production, use Redis or database)
SESSIONS_FILE = "sessions.json"
USERS_FILE = "users.json"

# Security
security = HTTPBearer(auto_error=False)

def load_sessions() -> dict:
    """Load sessions from file."""
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sessions(sessions: dict):
    """Save sessions to file."""
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

def load_users() -> dict:
    """Load users from file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users: dict):
    """Save users to file."""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def hash_password(password: str) -> str:
    """Hash password using SHA256 (for basic auth, in production use bcrypt)."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    return hash_password(password) == hashed

def create_session(username: str) -> str:
    """Create a new session token for user."""
    token = secrets.token_urlsafe(32)
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=7)).isoformat()
    }
    save_sessions(sessions)
    update_user_last_login(username)
    return token

def verify_session(token: Optional[str]) -> Optional[str]:
    """Verify session token and return username if valid."""
    if not token:
        return None
    
    sessions = load_sessions()
    if token not in sessions:
        return None
    
    session = sessions[token]
    expires_at = datetime.fromisoformat(session["expires_at"])
    
    if datetime.now() > expires_at:
        # Session expired, remove it
        del sessions[token]
        save_sessions(sessions)
        return None
    
    return session["username"]

def delete_session(token: str):
    """Delete a session."""
    sessions = load_sessions()
    if token in sessions:
        del sessions[token]
        save_sessions(sessions)

def init_default_user():
    """Initialize default admin user if no users exist."""
    users = load_users()
    if not users:
        default_password = os.getenv("ADMIN_PASSWORD", "admin123")
        users["admin"] = {
            "password_hash": hash_password(default_password),
            "created_at": datetime.now().isoformat()
        }
        save_users(users)
        return True
    return False

def authenticate_user(username: str, password: str) -> bool:
    """Authenticate user credentials."""
    users = load_users()
    if username not in users:
        return False
    
    return verify_password(password, users[username]["password_hash"])

def get_current_user(token: Optional[str]) -> str:
    """Get current user from token, raise exception if invalid."""
    username = verify_session(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return username

def create_user(username: str, password: str, email: str = "") -> bool:
    """
    Create a new user account.
    Returns True if created, False if username already exists.
    """
    users = load_users()
    if username in users:
        return False
    
    users[username] = {
        "password_hash": hash_password(password),
        "email": email,
        "created_at": datetime.now().isoformat(),
        "last_login": None
    }
    save_users(users)
    return True

def get_user_info(username: str) -> Optional[dict]:
    """Get user information (without password)."""
    users = load_users()
    if username not in users:
        return None
    
    user_info = users[username].copy()
    user_info.pop("password_hash", None)
    return user_info

def update_user_last_login(username: str):
    """Update user's last login timestamp."""
    users = load_users()
    if username in users:
        users[username]["last_login"] = datetime.now().isoformat()
        save_users(users)

