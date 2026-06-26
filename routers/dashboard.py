"""
Dashboard, monitoring, profile, and settings API endpoints.
"""
import os
import time
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.deps import get_token, get_safe_name, list_workspaces_for_user
from backend.auth import get_current_user, get_user_info, hash_password, verify_password, load_users, save_users

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_APP_START = time.time()


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


# ── Dashboard stats ───────────────────────────────────────────

@router.get("/dashboard/stats")
async def dashboard_stats(username: str = Depends(_require_auth)):
    """Aggregate stats for the current user."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()

        # Get user's workspaces
        workspaces = list_workspaces_for_user(username)
        ws_slugs = [w["slug"] for w in workspaces]

        total_docs = 0
        total_chunks = 0
        total_chats = 0
        total_queries = 0
        avg_latency = 0.0
        thumbs_up = 0
        thumbs_down = 0
        storage_bytes = 0

        if ws_slugs:
            # Documents count
            try:
                doc_res = sb.table("documents").select("id", count="exact")\
                    .in_("workspace_slug", ws_slugs).execute()
                total_docs = doc_res.count or 0
            except Exception:
                pass

            # Embeddings (chunks) count
            try:
                emb_res = sb.table("embeddings").select("id", count="exact")\
                    .in_("workspace_slug", ws_slugs).execute()
                total_chunks = emb_res.count or 0
            except Exception:
                pass

            # Chats count
            try:
                chat_res = sb.table("chats").select("id", count="exact")\
                    .in_("workspace_slug", ws_slugs).execute()
                total_chats = chat_res.count or 0
            except Exception:
                pass

            # Document storage size
            try:
                size_res = sb.table("documents").select("file_size")\
                    .in_("workspace_slug", ws_slugs).execute()
                storage_bytes = sum((r.get("file_size") or 0) for r in (size_res.data or []))
            except Exception:
                pass

        # Query logs
        try:
            logs_res = sb.table("query_logs").select("latency_ms, feedback, status")\
                .eq("username", username).limit(1000).execute()
            rows = logs_res.data or []
            total_queries = len(rows)
            latencies = [r["latency_ms"] for r in rows if r.get("latency_ms")]
            avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
            thumbs_up = sum(1 for r in rows if r.get("feedback") == "up")
            thumbs_down = sum(1 for r in rows if r.get("feedback") == "down")
        except Exception:
            pass

        def fmt_bytes(b):
            if b < 1024: return f"{b} B"
            if b < 1024**2: return f"{b/1024:.1f} KB"
            if b < 1024**3: return f"{b/1024**2:.1f} MB"
            return f"{b/1024**3:.1f} GB"

        return {
            "workspaces": len(workspaces),
            "documents": total_docs,
            "chunks": total_chunks,
            "chats": total_chats,
            "queries": total_queries,
            "avg_latency_ms": avg_latency,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "storage_bytes": storage_bytes,
            "storage_fmt": fmt_bytes(storage_bytes),
        }
    except Exception as e:
        logger.warning(f"dashboard_stats failed: {e}")
        return {"workspaces": 0, "documents": 0, "chunks": 0, "chats": 0,
                "queries": 0, "avg_latency_ms": 0, "thumbs_up": 0, "thumbs_down": 0,
                "storage_bytes": 0, "storage_fmt": "0 B"}


@router.get("/dashboard/queries")
async def dashboard_queries(limit: int = 50, username: str = Depends(_require_auth)):
    """Recent query logs for the current user."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        res = sb.table("query_logs").select(
            "trace_id, workspace_slug, question, latency_ms, chunks_retrieved, "
            "total_tokens, status, feedback, created_at"
        ).eq("username", username).order("created_at", desc=True).limit(min(limit, 200)).execute()
        return {"queries": res.data or []}
    except Exception as e:
        logger.warning(f"dashboard_queries failed: {e}")
        return {"queries": []}


@router.get("/dashboard/workspace-detail/{slug}")
async def workspace_detail(slug: str, username: str = Depends(_require_auth)):
    """Detail stats for a single workspace."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        safe = get_safe_name(slug)

        docs_res = sb.table("documents").select("filename, file_size, uploaded_at")\
            .eq("workspace_slug", safe).order("uploaded_at", desc=True).execute()
        chats_res = sb.table("chats").select("id, title, updated_at")\
            .eq("workspace_slug", safe).order("updated_at", desc=True).limit(20).execute()
        chunks_res = sb.table("embeddings").select("id", count="exact")\
            .eq("workspace_slug", safe).execute()

        return {
            "slug": safe,
            "documents": docs_res.data or [],
            "chats": chats_res.data or [],
            "chunks": chunks_res.count or 0,
        }
    except Exception as e:
        logger.warning(f"workspace_detail failed: {e}")
        return {"slug": slug, "documents": [], "chats": [], "chunks": 0}


# ── Monitoring ────────────────────────────────────────────────

@router.get("/monitoring/status")
async def monitoring_status(username: str = Depends(_require_auth)):
    """System health check — Supabase, BM25, embedding model."""
    status = {}

    # Uptime
    status["uptime_seconds"] = int(time.time() - _APP_START)
    uptime = timedelta(seconds=status["uptime_seconds"])
    h, rem = divmod(uptime.seconds, 3600)
    m, s = divmod(rem, 60)
    status["uptime_fmt"] = f"{uptime.days}d {h}h {m}m {s}s"

    # Supabase
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        t0 = time.perf_counter()
        sb.table("users").select("id").limit(1).execute()
        status["supabase"] = {"ok": True, "latency_ms": round((time.perf_counter()-t0)*1000, 1)}
    except Exception as e:
        status["supabase"] = {"ok": False, "error": str(e)[:120]}

    # BM25 indexes in memory
    try:
        from backend.bm25_index import _indexes
        status["bm25"] = {
            "ok": True,
            "indexes_in_memory": len(_indexes),
            "keys": list(_indexes.keys())[:10],
        }
    except Exception as e:
        status["bm25"] = {"ok": False, "error": str(e)[:120]}

    # Embedding model
    try:
        from backend.embeddings import get_embedding_model
        model = get_embedding_model()
        status["embedding_model"] = {
            "ok": True,
            "name": "BAAI/bge-small-en-v1.5",
            "dims": 384,
            "loaded": model is not None,
        }
    except Exception as e:
        status["embedding_model"] = {"ok": False, "error": str(e)[:120]}

    # ChromaDB
    try:
        from backend.retriever import _chroma_available
        status["chromadb"] = {"ok": True, "available": _chroma_available}
    except Exception:
        status["chromadb"] = {"ok": False, "available": False}

    # Groq API key present
    status["groq"] = {"ok": bool(os.getenv("GROQ_API_KEY")), "key_set": bool(os.getenv("GROQ_API_KEY"))}
    status["cohere"] = {"ok": True, "key_set": bool(os.getenv("COHERE_API_KEY")), "optional": True}

    # Environment
    status["environment"] = os.getenv("ENVIRONMENT", "development")
    status["version"] = "1.0.0"

    return status


@router.get("/monitoring/logs")
async def monitoring_logs(limit: int = 50, username: str = Depends(_require_auth)):
    """Recent error/warning logs from query_logs table."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        res = sb.table("query_logs").select(
            "trace_id, workspace_slug, question, latency_ms, status, created_at"
        ).eq("username", username).eq("status", "ERROR")\
         .order("created_at", desc=True).limit(min(limit, 100)).execute()
        return {"errors": res.data or []}
    except Exception as e:
        return {"errors": []}


# ── Profile ───────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class UpdateProfileRequest(BaseModel):
    email: Optional[str] = None


@router.get("/profile/me")
async def get_profile(username: str = Depends(_require_auth)):
    info = get_user_info(username) or {}
    # Try Supabase for richer info
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        res = sb.table("users").select("username, email, created_at, last_login")\
            .eq("username", username).execute()
        if res.data:
            info = {**info, **res.data[0]}
    except Exception:
        pass
    info.pop("password_hash", None)
    return {"user": info}


@router.post("/profile/change-password")
async def change_password(data: ChangePasswordRequest, username: str = Depends(_require_auth)):
    users = load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(data.old_password, users[username].get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    users[username]["password_hash"] = hash_password(data.new_password)
    save_users(users)
    return {"success": True}


@router.get("/profile/sessions")
async def list_sessions(username: str = Depends(_require_auth)):
    """List active sessions for the user."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        now = datetime.now(timezone.utc).isoformat()
        res = sb.table("sessions").select("token, created_at, expires_at")\
            .eq("username", username).gt("expires_at", now)\
            .order("created_at", desc=True).limit(10).execute()
        # Mask token
        sessions = []
        for s in (res.data or []):
            tok = s.get("token", "")
            sessions.append({
                "token_hint": tok[:6] + "…" + tok[-4:] if len(tok) > 10 else "••••",
                "created_at": s.get("created_at"),
                "expires_at": s.get("expires_at"),
            })
        return {"sessions": sessions}
    except Exception:
        return {"sessions": []}


@router.delete("/profile/sessions")
async def revoke_all_sessions(username: str = Depends(_require_auth)):
    """Revoke all sessions (force logout everywhere)."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        sb.table("sessions").delete().eq("username", username).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Settings ──────────────────────────────────────────────────

@router.get("/settings/info")
async def settings_info(username: str = Depends(_require_auth)):
    """Return read-only settings / system info the user can see."""
    return {
        "model": {
            "llm": "openai/gpt-oss-120b (Groq)",
            "embedding": "BAAI/bge-small-en-v1.5 (384 dims)",
            "vision": "meta-llama/llama-4-scout-17b-16e-instruct (Groq)",
            "reranker": "cohere-rerank-v3.5" if os.getenv("COHERE_API_KEY") else "disabled (no COHERE_API_KEY)",
        },
        "retrieval": {
            "chunk_size": 1000,
            "chunk_overlap": 300,
            "candidate_k": 30,
            "rrf_k": 60,
        },
        "storage": {
            "vector_store": "Supabase pgvector (primary)",
            "keyword_index": "BM25 → Supabase Storage",
            "file_storage": "Supabase Storage (documents bucket)",
            "fallback": "ChromaDB + local disk",
        },
        "keys": {
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "supabase": bool(os.getenv("SUPABASE_URL")),
            "cohere": bool(os.getenv("COHERE_API_KEY")),
            "jwt_secret": bool(os.getenv("SUPABASE_JWT_SECRET")),
        },
        "environment": os.getenv("ENVIRONMENT", "development"),
    }
