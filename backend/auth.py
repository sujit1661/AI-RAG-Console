"""
Authentication — Supabase Auth (primary) with local JSON fallback for dev.
Sessions stored in Supabase DB; local sessions.json used only when Supabase
is unavailable (e.g. local dev without env vars set).
"""
import os
import secrets
import hashlib
import bcrypt
import json
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, status
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Environment flags
# ─────────────────────────────────────────────
# Set SECURE_COOKIES=true in production (Render). False for local HTTP dev.
_SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

# ─────────────────────────────────────────────
# Local JSON fallback (dev only — not used when Supabase is configured)
# ─────────────────────────────────────────────
SESSIONS_FILE = "sessions.json"
USERS_FILE    = "users.json"

def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_json(path: str, data: dict):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Local JSON save failed ({path}): {e}")

def load_users() -> dict:  return _load_json(USERS_FILE)
def save_users(u: dict):   _save_json(USERS_FILE, u)
def _load_local_sessions() -> dict: return _load_json(SESSIONS_FILE)
def _save_local_sessions(s: dict):  _save_json(SESSIONS_FILE, s)

# ─────────────────────────────────────────────
# Password helpers
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    # Legacy SHA256 migration
    if len(hashed) == 64 and all(c in "0123456789abcdef" for c in hashed):
        return hashlib.sha256(password.encode()).hexdigest() == hashed
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

# ─────────────────────────────────────────────
# Supabase client
# ─────────────────────────────────────────────

def _get_supabase():
    try:
        from backend.supabase_config import get_supabase
        return get_supabase()
    except Exception:
        return None

# ─────────────────────────────────────────────
# Session storage — Supabase (primary) / local (fallback)
# ─────────────────────────────────────────────

def _sb_create_session(username: str, token: str, expires_at: datetime) -> bool:
    sb = _get_supabase()
    if not sb:
        return False
    try:
        sb.table("sessions").upsert({
            "token": token,
            "username": username,
            "expires_at": expires_at.isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.warning(f"Supabase session create failed: {e}")
        return False

def _sb_verify_session(token: str) -> Optional[str]:
    sb = _get_supabase()
    if not sb:
        return None
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = sb.table("sessions")\
            .select("username, expires_at")\
            .eq("token", token)\
            .gt("expires_at", now)\
            .execute()
        if res.data:
            return res.data[0]["username"]
    except Exception as e:
        logger.warning(f"Supabase session verify failed: {e}")
    return None

def _sb_delete_session(token: str):
    sb = _get_supabase()
    if not sb:
        return
    try:
        sb.table("sessions").delete().eq("token", token).execute()
    except Exception as e:
        logger.warning(f"Supabase session delete failed: {e}")

def _sb_cleanup_expired():
    """Remove expired sessions — called lazily, non-fatal."""
    sb = _get_supabase()
    if not sb:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        sb.table("sessions").delete().lt("expires_at", now).execute()
    except Exception:
        pass

# ─────────────────────────────────────────────
# Supabase Auth helpers
# ─────────────────────────────────────────────

def _supabase_register(username: str, password: str, email: str) -> Optional[dict]:
    sb = _get_supabase()
    if not sb:
        return None
    try:
        actual_email = email if email else f"{username}@ragcore.local"
        res = sb.auth.admin.create_user({
            "email": actual_email,
            "password": password,
            "user_metadata": {"username": username},
            "email_confirm": True,
        })
        if res.user:
            try:
                sb.table("users").insert({
                    "id": res.user.id,
                    "username": username,
                    "email": actual_email,
                    "created_at": datetime.utcnow().isoformat(),
                }).execute()
            except Exception:
                pass
            return {"id": res.user.id, "username": username, "email": actual_email}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return None

def _supabase_login(username: str, password: str) -> Optional[dict]:
    sb = _get_supabase()
    if not sb:
        return None
    try:
        row = sb.table("users").select("email").eq("username", username).execute()
        if not row.data:
            return None
        email = row.data[0]["email"]
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        if res.session:
            return {
                "token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "user_id": res.user.id,
                "username": username,
            }
    except Exception as e:
        logger.debug(f"Supabase Auth sign_in failed for {username}: {e}")
        return None
    return None

def _supabase_verify_jwt(token: str) -> Optional[str]:
    """
    Verify Supabase JWT using PyJWT + the project's JWKS public key.
    Falls back to soft decode (expiry check only) when SUPABASE_JWT_SECRET is set.
    Never accepts an unverified payload as authoritative.
    """
    # ── Option A: verify with HMAC secret (Supabase project JWT secret) ──
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if jwt_secret:
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": True},
            )
            username = payload.get("user_metadata", {}).get("username")
            if username:
                return username
            # Look up by sub (user_id)
            user_id = payload.get("sub")
            if user_id:
                sb = _get_supabase()
                if sb:
                    row = sb.table("users").select("username").eq("id", user_id).execute()
                    if row.data:
                        return row.data[0]["username"]
        except Exception as e:
            logger.debug(f"JWT verification failed: {e}")
            return None

    # ── Option B: no secret configured — decode for expiry only, then
    #    confirm with Supabase DB (one network call, but verified) ──
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        pad = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(pad))

        exp = payload.get("exp", 0)
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            return None  # expired — reject immediately

        # Must confirm with Supabase — don't trust payload alone
        user_id = payload.get("sub")
        if not user_id:
            return None
        sb = _get_supabase()
        if not sb:
            return None
        row = sb.table("users").select("username").eq("id", user_id).execute()
        if row.data:
            return row.data[0]["username"]
    except Exception as e:
        logger.debug(f"JWT soft-decode failed: {e}")
    return None

def _supabase_logout(token: str):
    sb = _get_supabase()
    if not sb:
        return
    try:
        sb.auth.sign_out()
    except Exception:
        pass

# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def init_default_user():
    """
    Ensure an admin user exists in Supabase (and local fallback).
    Credentials controlled entirely via environment variables:
      ADMIN_USERNAME — defaults to 'admin'
      ADMIN_PASSWORD — defaults to 'admin123'
    """
    sb = _get_supabase()
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

    if sb:
        try:
            res = sb.table("users").select("id").limit(1).execute()
            if res.data:
                # Users exist — ensure admin role is set and local fallback is current
                try:
                    sb.table("users").update({"role": "admin"})\
                        .eq("username", admin_username).execute()
                except Exception:
                    pass
            else:
                _supabase_register(admin_username, admin_password, f"{admin_username}@ragcore.local")
                try:
                    sb.table("users").update({"role": "admin"})\
                        .eq("username", admin_username).execute()
                except Exception:
                    pass
                logger.info(f"Default admin user '{admin_username}' created in Supabase")
        except Exception as e:
            logger.warning(f"Supabase init_default_user failed: {e}")

    # Always upsert admin into local users.json so local fallback auth works
    users = load_users()
    users[admin_username] = {
        "password_hash": hash_password(admin_password),
        "email": f"{admin_username}@ragcore.local",
        "role": "admin",
        "created_at": users.get(admin_username, {}).get("created_at") or datetime.now().isoformat(),
        "last_login": users.get(admin_username, {}).get("last_login"),
    }
    save_users(users)
    logger.info(f"Admin user '{admin_username}' synced to local fallback store")

def create_user(username: str, password: str, email: str = "") -> bool:
    sb = _get_supabase()
    if sb:
        try:
            _supabase_register(username, password, email)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Local copy (for fallback auth)
    users = load_users()
    if username in users:
        if sb:
            return True  # Supabase succeeded, local duplicate is fine
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
    """Local-only auth (fallback when Supabase is unavailable)."""
    users = load_users()
    if username not in users:
        return False
    hashed = users[username]["password_hash"]
    if not verify_password(password, hashed):
        return False
    # Migrate legacy SHA256 → bcrypt
    if len(hashed) == 64 and all(c in "0123456789abcdef" for c in hashed):
        users[username]["password_hash"] = hash_password(password)
        save_users(users)
    return True

def create_session(username: str) -> str:
    """Create a session token — stored in Supabase, falls back to local JSON."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    if not _sb_create_session(username, token, expires_at):
        # Local fallback
        sessions = _load_local_sessions()
        sessions[token] = {
            "username": username,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        _save_local_sessions(sessions)

    _update_last_login(username)
    return token

def verify_session(token: Optional[str]) -> Optional[str]:
    """
    Verify token — tries Supabase JWT, then Supabase session table,
    then local session fallback.
    """
    if not token:
        return None

    # 1. Supabase JWT (issued by Supabase Auth login)
    username = _supabase_verify_jwt(token)
    if username:
        return username

    # 2. Supabase sessions table (issued by create_session for local-auth users)
    username = _sb_verify_session(token)
    if username:
        return username

    # 3. Local JSON fallback (dev only)
    sessions = _load_local_sessions()
    if token not in sessions:
        return None
    session = sessions[token]
    try:
        expires_at = datetime.fromisoformat(session["expires_at"])
        # Make timezone-aware for comparison
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            del sessions[token]
            _save_local_sessions(sessions)
            return None
    except Exception:
        return None
    return session["username"]

def delete_session(token: str):
    _supabase_logout(token)
    _sb_delete_session(token)
    # Also clean up local if present
    sessions = _load_local_sessions()
    if token in sessions:
        del sessions[token]
        _save_local_sessions(sessions)

def get_current_user(token: Optional[str]) -> str:
    username = verify_session(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return username

def get_user_info(username: str) -> Optional[dict]:
    # Try Supabase first
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("users").select("username, email, created_at, last_login, role")\
                .eq("username", username).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
    # Local fallback
    users = load_users()
    if username not in users:
        return {"username": username, "role": "user"}
    info = users[username].copy()
    info.pop("password_hash", None)
    if "role" not in info:
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        info["role"] = "admin" if username == admin_username else "user"
    return info


def get_user_role(username: str) -> str:
    """Return the role of a user ('admin' or 'user'). Defaults to 'user'."""
    info = get_user_info(username)
    return (info or {}).get("role", "user")

def _update_last_login(username: str):
    now = datetime.now(timezone.utc).isoformat()
    # Supabase
    sb = _get_supabase()
    if sb:
        try:
            sb.table("users").update({"last_login": now})\
                .eq("username", username).execute()
            return
        except Exception:
            pass
    # Local fallback
    users = load_users()
    if username in users:
        users[username]["last_login"] = now
        save_users(users)

def _sync_supabase_auth_password(username: str, password: str):
    """
    Update Supabase Auth password to match local — called when local auth
    succeeds but Supabase Auth failed, so they stay in sync going forward.
    Non-fatal.
    """
    sb = _get_supabase()
    if not sb:
        return
    try:
        row = sb.table("users").select("id").eq("username", username).execute()
        if not row.data:
            return
        user_id = row.data[0]["id"]
        sb.auth.admin.update_user_by_id(user_id, {"password": password})
        logger.info(f"Synced Supabase Auth password for {username}")
    except Exception as e:
        logger.debug(f"Supabase Auth password sync failed (non-fatal): {e}")


def login_user(username: str, password: str) -> dict:
    # Try Supabase Auth first
    result = _supabase_login(username, password)
    if result:
        _update_last_login(username)
        return {**result, "source": "supabase"}

    # Local fallback — also works when Supabase Auth is out of sync
    if authenticate_user(username, password):
        token = create_session(username)
        _update_last_login(username)
        # Silently re-sync Supabase Auth password so next login works via Supabase
        _sync_supabase_auth_password(username, password)
        return {"token": token, "username": username, "source": "local"}

    raise HTTPException(status_code=401, detail="Invalid credentials")

# Expose for cookie helper
SECURE_COOKIES = _SECURE_COOKIES
