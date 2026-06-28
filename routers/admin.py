"""
Admin-only API endpoints.
Every route here uses `require_admin` — server-side 403 if not admin.
"""
import os
import time
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.deps import get_token, require_admin
from backend.auth import (
    get_current_user, get_user_info, get_user_role,
    load_users, save_users, hash_password, verify_password
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Helpers ───────────────────────────────────────────────────

def _get_supabase():
    try:
        from backend.supabase_config import get_supabase
        return get_supabase()
    except Exception:
        return None


def _audit(admin: str, action: str, target: str = None, detail: str = None):
    """Write to admin_logs table (non-fatal)."""
    sb = _get_supabase()
    if sb:
        try:
            sb.table("admin_logs").insert({
                "admin_user": admin,
                "action": action,
                "target_user": target,
                "detail": detail,
            }).execute()
        except Exception as e:
            logger.warning(f"Admin audit log failed: {e}")


# ── Auth check ────────────────────────────────────────────────

@router.get("/me")
async def admin_me(admin: str = Depends(require_admin)):
    """Confirms the caller is an admin and returns their info."""
    return {"username": admin, "role": "admin"}


# ── User management ───────────────────────────────────────────

@router.get("/users")
async def list_all_users(
    search: str = "",
    limit: int = 100,
    admin: str = Depends(require_admin)
):
    """List all users with their role and activity stats."""
    sb = _get_supabase()
    users_out = []

    if sb:
        try:
            query = sb.table("users").select(
                "username, email, role, created_at, last_login"
            ).order("created_at", desc=True).limit(min(limit, 500))
            if search:
                query = query.ilike("username", f"%{search}%")
            res = query.execute()
            rows = res.data or []

            # Enrich with query counts
            for u in rows:
                try:
                    qres = sb.table("query_logs").select("id", count="exact")\
                        .eq("username", u["username"]).execute()
                    u["query_count"] = qres.count or 0
                except Exception:
                    u["query_count"] = 0
                try:
                    wsres = sb.table("workspaces").select("slug", count="exact")\
                        .eq("owner_id", u.get("id", "")).execute()
                    # fallback count by username via documents
                    u["workspace_count"] = wsres.count or 0
                except Exception:
                    u["workspace_count"] = 0
                u.pop("id", None)
            users_out = rows
        except Exception as e:
            logger.warning(f"admin list_users Supabase failed: {e}")

    # Local fallback
    if not users_out:
        local = load_users()
        for uname, data in local.items():
            if search and search.lower() not in uname.lower():
                continue
            entry = {k: v for k, v in data.items() if k != "password_hash"}
            entry["username"] = uname
            entry.setdefault("role", "admin" if uname == "admin" else "user")
            entry["query_count"] = 0
            entry["workspace_count"] = 0
            users_out.append(entry)

    return {"users": users_out, "total": len(users_out)}


@router.get("/users/{username}")
async def get_user_detail(username: str, admin: str = Depends(require_admin)):
    """Full profile + activity for one user."""
    sb = _get_supabase()
    info = {}

    if sb:
        try:
            res = sb.table("users").select(
                "username, email, role, created_at, last_login"
            ).eq("username", username).execute()
            if not res.data:
                raise HTTPException(status_code=404, detail="User not found")
            info = res.data[0]

            # Workspaces
            ws = sb.table("workspaces").select("slug, name, created_at")\
                .order("created_at", desc=True).execute()
            info["workspaces"] = [
                w for w in (ws.data or [])
            ]

            # Recent queries
            ql = sb.table("query_logs").select(
                "question, workspace_slug, latency_ms, status, feedback, created_at"
            ).eq("username", username).order("created_at", desc=True).limit(20).execute()
            info["recent_queries"] = ql.data or []

            # Sessions
            now = datetime.now(timezone.utc).isoformat()
            sess = sb.table("sessions").select("token, created_at, expires_at")\
                .eq("username", username).gt("expires_at", now).execute()
            info["active_sessions"] = len(sess.data or [])
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"admin get_user_detail failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        users = load_users()
        if username not in users:
            raise HTTPException(status_code=404, detail="User not found")
        info = {k: v for k, v in users[username].items() if k != "password_hash"}
        info["username"] = username
        info.setdefault("role", "admin" if username == "admin" else "user")

    info.pop("password_hash", None)
    return info


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    email: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/users/{username}")
async def update_user(
    username: str,
    data: UpdateUserRequest,
    admin: str = Depends(require_admin)
):
    """Update a user's role or email. Admins cannot demote themselves."""
    if username == admin and data.role and data.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    if data.role and data.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")

    sb = _get_supabase()
    updates: dict = {}
    if data.role:
        updates["role"] = data.role
    if data.email is not None:
        updates["email"] = data.email

    if sb and updates:
        try:
            sb.table("users").update(updates).eq("username", username).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Local fallback
    users = load_users()
    if username in users:
        if data.role:
            users[username]["role"] = data.role
        if data.email is not None:
            users[username]["email"] = data.email
        save_users(users)

    _audit(admin, "update_user", username, str(updates))
    return {"success": True, "updated": updates}


@router.post("/users/{username}/reset-password")
async def admin_reset_password(
    username: str,
    body: dict,
    admin: str = Depends(require_admin)
):
    """Force-set a user's password (admin only)."""
    new_password = body.get("new_password", "")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    users = load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found in local store")
    users[username]["password_hash"] = hash_password(new_password)
    save_users(users)
    _audit(admin, "reset_password", username)
    return {"success": True}


@router.delete("/users/{username}")
async def delete_user(username: str, admin: str = Depends(require_admin)):
    """Delete a user account. Cannot delete yourself."""
    if username == admin:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    sb = _get_supabase()
    if sb:
        try:
            # Revoke sessions first
            sb.table("sessions").delete().eq("username", username).execute()
            # Delete from users table (cascades to workspaces, chats, etc.)
            sb.table("users").delete().eq("username", username).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Local fallback
    users = load_users()
    users.pop(username, None)
    save_users(users)

    _audit(admin, "delete_user", username)
    return {"success": True}


@router.post("/users/{username}/revoke-sessions")
async def revoke_user_sessions(username: str, admin: str = Depends(require_admin)):
    """Force-logout a user by revoking all their sessions."""
    sb = _get_supabase()
    if sb:
        try:
            sb.table("sessions").delete().eq("username", username).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    _audit(admin, "revoke_sessions", username)
    return {"success": True}


# ── System observability ──────────────────────────────────────

@router.get("/observability/queries")
async def all_queries(
    limit: int = 100,
    workspace: str = "",
    status_filter: str = "",
    username_filter: str = "",
    admin: str = Depends(require_admin)
):
    """All query logs across all users — for global monitoring."""
    sb = _get_supabase()
    if not sb:
        return {"queries": []}
    try:
        q = sb.table("query_logs").select(
            "trace_id, username, workspace_slug, question, latency_ms, "
            "chunks_retrieved, chunks_after_rerank, total_tokens, status, feedback, created_at"
        ).order("created_at", desc=True).limit(min(limit, 500))
        if workspace:
            q = q.eq("workspace_slug", workspace)
        if status_filter:
            q = q.eq("status", status_filter)
        if username_filter:
            q = q.ilike("username", f"%{username_filter}%")
        res = q.execute()
        return {"queries": res.data or [], "total": len(res.data or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observability/errors")
async def all_errors(
    limit: int = 100,
    admin: str = Depends(require_admin)
):
    """All ERROR-status query logs across all users."""
    sb = _get_supabase()
    if not sb:
        return {"errors": []}
    try:
        res = sb.table("query_logs").select(
            "trace_id, username, workspace_slug, question, latency_ms, status, created_at"
        ).eq("status", "ERROR").order("created_at", desc=True).limit(min(limit, 500)).execute()
        return {"errors": res.data or [], "total": len(res.data or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observability/stats")
async def system_stats(admin: str = Depends(require_admin)):
    """Aggregate system-wide stats across ALL users."""
    sb = _get_supabase()
    if not sb:
        return {}
    try:
        users_res     = sb.table("users").select("id", count="exact").execute()
        ws_res        = sb.table("workspaces").select("slug", count="exact").execute()
        docs_res      = sb.table("documents").select("id", count="exact").execute()
        chunks_res    = sb.table("embeddings").select("id", count="exact").execute()
        queries_res   = sb.table("query_logs").select("id", count="exact").execute()
        errors_res    = sb.table("query_logs").select("id", count="exact").eq("status", "ERROR").execute()

        # Storage
        size_res = sb.table("documents").select("file_size").execute()
        storage  = sum((r.get("file_size") or 0) for r in (size_res.data or []))

        def fmt(b):
            if b < 1024: return f"{b} B"
            if b < 1024**2: return f"{b/1024:.1f} KB"
            if b < 1024**3: return f"{b/1024**2:.1f} MB"
            return f"{b/1024**3:.1f} GB"

        # Avg latency
        lat_res = sb.table("query_logs").select("latency_ms").limit(1000).execute()
        lats = [r["latency_ms"] for r in (lat_res.data or []) if r.get("latency_ms")]
        avg_lat = round(sum(lats)/len(lats), 1) if lats else 0

        # Feedback
        fb_res = sb.table("query_logs").select("feedback").execute()
        up   = sum(1 for r in (fb_res.data or []) if r.get("feedback") == "up")
        down = sum(1 for r in (fb_res.data or []) if r.get("feedback") == "down")

        return {
            "total_users":      users_res.count  or 0,
            "total_workspaces": ws_res.count     or 0,
            "total_documents":  docs_res.count   or 0,
            "total_chunks":     chunks_res.count or 0,
            "total_queries":    queries_res.count or 0,
            "total_errors":     errors_res.count or 0,
            "storage_bytes":    storage,
            "storage_fmt":      fmt(storage),
            "avg_latency_ms":   avg_lat,
            "thumbs_up":        up,
            "thumbs_down":      down,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observability/audit-log")
async def audit_log(limit: int = 100, admin: str = Depends(require_admin)):
    """Admin action audit trail."""
    sb = _get_supabase()
    if not sb:
        return {"logs": []}
    try:
        res = sb.table("admin_logs").select("*")\
            .order("created_at", desc=True).limit(min(limit, 500)).execute()
        return {"logs": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
