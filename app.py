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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log", encoding="utf-8"), _stdout],
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="RAGCORE", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────
_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
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

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(files_router)
app.include_router(chat_router)

# ── Analytics ─────────────────────────────────────────────────
from backend.deps import get_token, get_safe_name
from backend.auth import get_current_user
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
