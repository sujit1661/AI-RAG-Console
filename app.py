"""
RAGCORE — FastAPI entry point.
All routes are in routers/. Business logic is in backend/.
"""
import os
import sys
import logging
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Optional
from pydantic import BaseModel

# ── Logging ───────────────────────────────────────────────────
_stdout = logging.StreamHandler(sys.stdout)
if hasattr(_stdout.stream, "reconfigure"):
    _stdout.stream.reconfigure(encoding="utf-8")

# Use file logging in local dev, stdout-only in production (Render)
_handlers = [_stdout]
if os.getenv("ENVIRONMENT", "development") == "development":
    try:
        _handlers.append(logging.FileHandler("app.log", encoding="utf-8"))
    except Exception:
        pass  # skip if not writable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="RAGCORE", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────
_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000,http://0.0.0.0:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────
from backend.auth import init_default_user
from backend.bm25_index import rebuild_from_chromadb

init_default_user()
try:
    rebuild_from_chromadb()
except Exception as e:
    logger.warning(f"BM25 startup rebuild skipped: {e}")

# ── Routers ───────────────────────────────────────────────────
from routers.auth import router as auth_router
from routers.workspace import router as workspace_router
from routers.files import router as files_router
from routers.chat import router as chat_router
from routers.general_chat import router as general_chat_router
from routers.playground import router as playground_router

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(files_router)
app.include_router(chat_router)
app.include_router(general_chat_router)
app.include_router(playground_router)

from routers.pipeline_explorer import router as pipeline_explorer_router
app.include_router(pipeline_explorer_router)

from routers.dashboard import router as dashboard_router
app.include_router(dashboard_router)

from routers.admin import router as admin_router
app.include_router(admin_router)

# ── Analytics ─────────────────────────────────────────────────
from backend.deps import get_token, get_safe_name, require_admin
from backend.auth import get_current_user, get_user_role
from backend.analytics import save_feedback, get_analytics


class FeedbackRequest(BaseModel):
    trace_id: str
    feedback: str


@app.post("/feedback")
async def submit_feedback(data: FeedbackRequest, token: Optional[str] = Depends(get_token)):
    username = get_current_user(token)
    if data.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback must be 'up' or 'down'")
    save_feedback(data.trace_id, data.feedback)
    return {"success": True}


@app.get("/analytics")
async def analytics(workspace_name: Optional[str] = None, token: Optional[str] = Depends(get_token)):
    username = get_current_user(token)
    slug = get_safe_name(workspace_name) if workspace_name else None
    return get_analytics(username, slug)


# ── Health check ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/workspace-image/{slug}/{filename}")
async def serve_workspace_image(slug: str, filename: str,
                                token: Optional[str] = Depends(get_token)):
    """Serve an uploaded image file from a workspace (auth required)."""
    get_current_user(token)   # raises 401 if not logged in
    from backend.deps import get_workspace_path, get_safe_name
    safe_slug = get_safe_name(slug)
    workspace_path = get_workspace_path(safe_slug)
    # Prevent path traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(workspace_path, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    ext = safe_filename.rsplit(".", 1)[-1].lower()
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/octet-stream")
    return FileResponse(file_path, media_type=media, headers=_NC)


# ── Static pages ──────────────────────────────────────────────
_NC = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    return FileResponse("frontend/landing.html", headers=_NC)


@app.get("/app", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("frontend/index.html", headers=_NC)


@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    return FileResponse("frontend/login.html", headers=_NC)


@app.get("/register", response_class=HTMLResponse)
async def serve_register():
    return FileResponse("frontend/register.html", headers=_NC)


@app.get("/ai-chat", response_class=HTMLResponse)
async def serve_general_chat():
    return FileResponse("frontend/chat.html", headers=_NC)


@app.get("/playground", response_class=HTMLResponse)
async def serve_playground():
    return FileResponse("frontend/playground.html", headers=_NC)


@app.get("/pipeline", response_class=HTMLResponse)
async def serve_pipeline():
    return FileResponse("frontend/pipeline.html", headers=_NC)


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    return FileResponse("frontend/dashboard.html", headers=_NC)


@app.get("/monitoring", response_class=HTMLResponse)
async def serve_monitoring():
    return FileResponse("frontend/monitoring.html", headers=_NC)


@app.get("/profile", response_class=HTMLResponse)
async def serve_profile():
    return FileResponse("frontend/profile.html", headers=_NC)


@app.get("/settings", response_class=HTMLResponse)
async def serve_settings(token: Optional[str] = Depends(get_token)):
    """Settings page — admin only at the HTTP level."""
    try:
        username = get_current_user(token)
        if get_user_role(username) != "admin":
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/dashboard", status_code=303)
    except Exception:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse("frontend/settings.html", headers=_NC)


@app.get("/admin-panel", response_class=HTMLResponse)
async def serve_admin_panel(token: Optional[str] = Depends(get_token)):
    """Admin dashboard — admin only at the HTTP level."""
    try:
        username = get_current_user(token)
        if get_user_role(username) != "admin":
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/dashboard", status_code=303)
    except Exception:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse("frontend/admin.html", headers=_NC)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
