<<<<<<< HEAD
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import shutil
=======
"""
RAGCORE — FastAPI entry point.
All routes are in routers/. Business logic is in backend/.
"""
>>>>>>> 0f84573 (feat: production RAG improvements)
import os
import sys
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

<<<<<<< HEAD
# Custom modules
from backend.ingestion import (
    extract_pdf_text, extract_excel_text, extract_docx_text, extract_image_text
)
from backend.chunking import chunk_text
from backend.retriever import (
    add_documents, retrieve, delete_from_collection, delete_workspace
)
from backend.llm import generate_answer, generate_answer_stream
from backend.auth import (
    authenticate_user, create_session, verify_session, delete_session,
    get_current_user, init_default_user, create_user, get_user_info,
    login_user
)
from backend.supabase_storage import upload_file_to_supabase
from backend.supabase_db import add_document_metadata
from backend.persistence import (
    sync_workspace_create, sync_workspace_delete,
    sync_chat_create, sync_chat_update, sync_chat_delete,
    sync_message_add, load_messages_from_supabase
)
from backend.analytics import QueryTrace, save_feedback, get_analytics
from backend.bm25_index import rebuild_from_chromadb

# Setup logging — force UTF-8 on Windows console
import sys
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.stream.reconfigure(encoding='utf-8') if hasattr(_stdout_handler.stream, 'reconfigure') else None
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        _stdout_handler,
    ]
)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Initialize default admin user
init_default_user()

# Rebuild BM25 indexes from ChromaDB on startup (non-blocking)
try:
    rebuild_from_chromadb()
except Exception as _e:
    logger.warning(f"BM25 startup rebuild skipped: {_e}")

# CORS — restrict to localhost in dev; set ALLOWED_ORIGINS in .env for production
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
=======
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
>>>>>>> 0f84573 (feat: production RAG improvements)
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

# Apply rate limits to auth router endpoints
from slowapi import Limiter
from routers.auth import router as _ar
for route in _ar.routes:
    if route.path == "/auth/login":
        route.endpoint = limiter.limit("10/minute")(route.endpoint)
    elif route.path == "/auth/register":
        route.endpoint = limiter.limit("5/minute")(route.endpoint)

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(files_router)
app.include_router(chat_router)

# ── Analytics ─────────────────────────────────────────────────
from fastapi import Depends
from typing import Optional
from backend.deps import get_token
from backend.auth import get_current_user
from backend.analytics import save_feedback, get_analytics
from backend.deps import get_safe_name
from pydantic import BaseModel

class FeedbackRequest(BaseModel):
    trace_id: str
    feedback: str

<<<<<<< HEAD
def get_chat_history_file(slug: str, chat_id: str) -> str:
    """Get path to a specific chat's history file."""
    return os.path.join(get_workspace_path(slug), f"chat_{chat_id}.json")

def ensure_chats_metadata_exists(slug: str):
    """Ensure chats metadata file exists."""
    path = get_chats_metadata_file(slug)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump([], f)

def load_chats_metadata(slug: str) -> List[dict]:
    """Load all chats metadata for a workspace."""
    ensure_chats_metadata_exists(slug)
    path = get_chats_metadata_file(slug)
    with open(path, "r") as f:
        return json.load(f)

def save_chats_metadata(slug: str, chats: List[dict]):
    """Save chats metadata."""
    path = get_chats_metadata_file(slug)
    with open(path, "w") as f:
        json.dump(chats, f, indent=4)

def load_history(slug: str, chat_id: str = None) -> List[dict]:
    """Load history for a specific chat or default chat."""
    if chat_id:
        path = get_chat_history_file(slug, chat_id)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return []
    else:
        # Legacy support - load from old history.json if exists
        legacy_path = os.path.join(get_workspace_path(slug), "history.json")
        if os.path.exists(legacy_path):
            with open(legacy_path, "r") as f:
                return json.load(f)
        return []

def save_history(slug: str, history: List[dict], chat_id: str = None):
    """Save history for a specific chat."""
    if not chat_id:
        legacy_path = os.path.join(get_workspace_path(slug), "history.json")
        with open(legacy_path, "w") as f:
            json.dump(history, f, indent=4)
    else:
        path = get_chat_history_file(slug, chat_id)
        with open(path, "w") as f:
            json.dump(history, f, indent=4)

# -----------------------------
# MODELS
# -----------------------------
class ChatRequest(BaseModel):
    workspace_name: str
    question: str
    chat_id: Optional[str] = None

class ChatCreateRequest(BaseModel):
    workspace_name: str
    chat_title: Optional[str] = None

class WorkspaceRequest(BaseModel):
    workspace_name: str

class WorkspaceRenameRequest(BaseModel):
    workspace_name: str
    new_name: str

class DeleteFileRequest(BaseModel):
    workspace_name: str
    filename: str

class ChatDeleteRequest(BaseModel):
    workspace_name: str
    chat_id: str

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class FeedbackRequest(BaseModel):
    trace_id: str
    feedback: str  # "up" or "down"

# -----------------------------
# AUTH ENDPOINTS
# -----------------------------
@app.get("/auth/check")
async def check_auth(token: Optional[str] = Depends(get_token)):
    """Check if user is authenticated."""
    username = verify_session(token)
    if username:
        return {"authenticated": True, "username": username}
    return {"authenticated": False}

@app.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, response: Response):
    """Login endpoint — tries Supabase Auth first, falls back to local."""
    try:
        result = login_user(data.username, data.password)
        token = result["token"]
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=7 * 24 * 60 * 60
        )
        user_info = get_user_info(data.username) or {}
        logger.info(f"User {data.username} logged in via {result.get('source', 'unknown')}")
        return {
            "success": True,
            "token": token,
            "refresh_token": result.get("refresh_token"),
            "username": data.username,
            "user_info": user_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest, response: Response):
    """Register a new user account."""
    try:
        # Validate username
        if not data.username or len(data.username) < 3:
            raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', data.username):
            raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, and underscores")
        
        # Validate password
        if not data.password or len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Create user
        if create_user(data.username, data.password, data.email):
            # Auto-login after registration
            token = create_session(data.username)
            response.set_cookie(
                key="session_token",
                value=token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=7 * 24 * 60 * 60
            )
            user_info = get_user_info(data.username)
            logger.info(f"New user {data.username} registered successfully")
            return {"success": True, "token": token, "username": data.username, "user_info": user_info}
        else:
            raise HTTPException(status_code=400, detail="Username already exists")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/user")
async def get_user(token: Optional[str] = Depends(get_token)):
    """Get current user information."""
    username = verify_session(token)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_info = get_user_info(username)
    return {"username": username, "user_info": user_info}

@app.post("/auth/change-password")
async def change_password(data: ChangePasswordRequest, username: str = Depends(require_auth)):
    """Change user password."""
    from backend.auth import load_users, save_users, hash_password, verify_password
    
    users = load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not verify_password(data.old_password, users[username]["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    users[username]["password_hash"] = hash_password(data.new_password)
    save_users(users)
    logger.info(f"User {username} changed password")
    return {"success": True, "message": "Password changed successfully"}

@app.post("/auth/logout")
async def logout(response: Response, token: Optional[str] = Depends(get_token)):
    """Logout endpoint."""
    if token:
        delete_session(token)
    response.delete_cookie(key="session_token")
    logger.info("User logged out")
    return {"success": True}

@app.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    """Refresh Supabase JWT using refresh token."""
    try:
        body = await request.json()
        refresh_tok = body.get("refresh_token", "")
        if not refresh_tok:
            raise HTTPException(status_code=400, detail="refresh_token required")

        from backend.supabase_config import get_supabase
        supabase = get_supabase()
        res = supabase.auth.refresh_session(refresh_tok)
        if not res.session:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        new_token = res.session.access_token
        new_refresh = res.session.refresh_token
        response.set_cookie(
            key="session_token",
            value=new_token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=7 * 24 * 60 * 60
        )
        return {"success": True, "token": new_token, "refresh_token": new_refresh}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token refresh failed")

# -----------------------------
# STATIC FILES
# -----------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    return FileResponse("frontend/landing.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/app", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("frontend/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    return FileResponse("frontend/login.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/register", response_class=HTMLResponse)
async def serve_register():
    return FileResponse("frontend/register.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# -----------------------------
# WORKSPACE ENDPOINTS
# -----------------------------
@app.get("/workspace/list")
async def list_all_workspaces(username: str = Depends(require_auth)):
    """List workspaces owned by the current user."""
    try:
        if not os.path.exists(UPLOAD_ROOT):
            return {"workspaces": []}

        # Only show workspaces that belong to this user (stored in owner file)
        all_dirs = [d for d in os.listdir(UPLOAD_ROOT)
                    if os.path.isdir(os.path.join(UPLOAD_ROOT, d)) and d != "__pycache__"]

        workspace_list = []
        for ws in sorted(all_dirs):
            slug = ws
            # Check ownership
            owner_file = os.path.join(get_workspace_path(slug), ".owner")
            if os.path.exists(owner_file):
                with open(owner_file, "r") as f:
                    owner = f.read().strip()
                if owner != username:
                    continue  # skip workspaces owned by other users
            # If no .owner file (legacy), show to all (migration path)

            # Read display name if set, otherwise use slug
            display_name_file = os.path.join(get_workspace_path(slug), ".display_name")
            display_name = ws
            if os.path.exists(display_name_file):
                with open(display_name_file, "r") as f:
                    display_name = f.read().strip() or ws

            metadata = {
                "name": display_name,
                "slug": slug,
                "last_message": None,
                "last_updated": None,
                "message_count": 0
            }
            try:
                chats = load_chats_metadata(slug)
                if chats:
                    def _ts(c: dict) -> str:
                        return c.get("updated_at") or c.get("created_at") or ""
                    chats_sorted = sorted(chats, key=_ts, reverse=True)
                    latest = chats_sorted[0]
                    chat_id = latest.get("id")
                    metadata["last_updated"] = latest.get("updated_at") or latest.get("created_at")
                    if chat_id:
                        history = load_history(slug, chat_id)
                        if history:
                            for msg in reversed(history):
                                if msg.get("role") == "assistant":
                                    metadata["last_message"] = msg.get("content", "")[:100]
                                    break
                            metadata["message_count"] = len([m for m in history if m.get("role") == "user"])
                else:
                    history = load_history(slug)
                    if history:
                        for msg in reversed(history):
                            if msg.get("role") == "assistant":
                                metadata["last_message"] = msg.get("content", "")[:100]
                                break
                        metadata["message_count"] = len([m for m in history if m.get("role") == "user"])
                        hist_file = os.path.join(get_workspace_path(slug), "history.json")
                        if os.path.exists(hist_file):
                            metadata["last_updated"] = os.path.getmtime(hist_file)
            except:
                pass
            workspace_list.append(metadata)

        workspace_list.sort(key=lambda x: x["last_updated"] or 0, reverse=True)
        return {"workspaces": workspace_list}
    except Exception as e:
        logger.error(f"Error listing workspaces: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workspace/create")
async def create_workspace(data: WorkspaceRequest, username: str = Depends(require_auth)):
    """Create a new workspace owned by the current user."""
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")

    try:
        # Prefix slug with username to avoid collisions across users
        base_slug = get_safe_name(data.workspace_name)
        if not base_slug:
            raise HTTPException(status_code=400, detail="Invalid workspace name")

        # Use username-prefixed slug on disk to guarantee uniqueness
        slug = get_safe_name(f"{username}-{base_slug}")
        path = get_workspace_path(slug)
        if os.path.exists(path):
            raise HTTPException(status_code=400, detail="Workspace already exists")

        os.makedirs(path, exist_ok=True)

        # Write owner file
        with open(os.path.join(path, ".owner"), "w") as f:
            f.write(username)

        # Legacy history file
        legacy_hist_file = os.path.join(path, "history.json")
        if not os.path.exists(legacy_hist_file):
            with open(legacy_hist_file, "w") as f:
                json.dump([], f)

        # Register in Supabase DB (non-fatal)
        try:
            sync_workspace_create(slug, data.workspace_name, username)
        except Exception as e:
            logger.warning(f"Supabase workspace create failed (non-fatal): {e}")

        logger.info(f"Workspace {slug} created by {username}")
        return {"message": "Created", "slug": slug}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workspace: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workspace/delete")
async def delete_entire_workspace(data: WorkspaceRequest, username: str = Depends(require_auth)):
    slug = get_safe_name(data.workspace_name)
    path = get_workspace_path(slug)

    # Verify ownership
    owner_file = os.path.join(path, ".owner")
    if os.path.exists(owner_file):
        with open(owner_file, "r") as f:
            owner = f.read().strip()
        if owner != username:
            raise HTTPException(status_code=403, detail="Not authorized to delete this workspace")

    # Clear user-scoped ChromaDB collection
    try:
        delete_workspace(slug, username)
    except:
        pass

    if os.path.exists(path):
        shutil.rmtree(path)

    # Sync deletion to Supabase
    sync_workspace_delete(slug, username)

    return {"message": f"Workspace {slug} deleted"}

@app.post("/workspace/rename")
async def rename_workspace(data: WorkspaceRenameRequest, username: str = Depends(require_auth)):
    """Rename a workspace (updates display name, keeps slug for stability)."""
    if not data.new_name or not data.new_name.strip():
        raise HTTPException(status_code=400, detail="New name cannot be empty")

    slug = get_safe_name(data.workspace_name)
    path = get_workspace_path(slug)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Verify ownership
    owner_file = os.path.join(path, ".owner")
    if os.path.exists(owner_file):
        with open(owner_file, "r") as f:
            owner = f.read().strip()
        if owner != username:
            raise HTTPException(status_code=403, detail="Not authorized to rename this workspace")

    # Store display name separately (slug stays the same to avoid breaking ChromaDB/file paths)
    display_name_file = os.path.join(path, ".display_name")
    with open(display_name_file, "w") as f:
        f.write(data.new_name.strip())

    logger.info(f"Workspace {slug} renamed to '{data.new_name}' by {username}")
    return {"message": "Renamed", "slug": slug, "name": data.new_name.strip()}

@app.get("/workspace/{workspace_name}/history")
async def get_history(workspace_name: str, chat_id: Optional[str] = None, username: str = Depends(require_auth)):
    slug = get_safe_name(workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"history": load_history(slug, chat_id)}


@app.get("/workspace/{workspace_name}/chats")
async def list_workspace_chats(workspace_name: str, username: str = Depends(require_auth)):
    """List chats for a workspace (most recently updated first)."""
    slug = get_safe_name(workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    chats = load_chats_metadata(slug)
    # Sort by updated_at desc (fallback to created_at)
    def _ts(c: dict) -> str:
        return c.get("updated_at") or c.get("created_at") or ""
    chats.sort(key=_ts, reverse=True)
    return {"chats": chats}

@app.post("/chat/create")
async def create_chat(data: ChatCreateRequest, username: str = Depends(require_auth)):
    """Create a new chat within a workspace."""
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")

    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    chat_id = str(uuid.uuid4())
    title = (data.chat_title or "").strip() or "New Chat"
    now = datetime.now().isoformat()

    chats = load_chats_metadata(slug)
    chats.append({"id": chat_id, "title": title, "created_at": now, "updated_at": now})
    save_chats_metadata(slug, chats)
    save_history(slug, [], chat_id)

    # Sync to Supabase
    sync_chat_create(slug, chat_id, title, username)

    return {"chat": {"id": chat_id, "title": title, "created_at": now, "updated_at": now}}

@app.post("/chat/delete")
async def delete_chat(data: ChatDeleteRequest, username: str = Depends(require_auth)):
    """Delete a chat and its history file within a workspace."""
    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not data.chat_id or not data.chat_id.strip():
        raise HTTPException(status_code=400, detail="chat_id cannot be empty")

    chats = load_chats_metadata(slug)
    chats = [c for c in chats if c.get("id") != data.chat_id]
    save_chats_metadata(slug, chats)

    hist_path = get_chat_history_file(slug, data.chat_id)
    if os.path.exists(hist_path):
        os.remove(hist_path)

    # Sync deletion to Supabase
    sync_chat_delete(data.chat_id, username)

    return {"message": "Chat deleted"}

@app.get("/workspace/{workspace_name}/files")
async def get_files(workspace_name: str, username: str = Depends(require_auth)):
    slug = get_safe_name(workspace_name)
    path = get_workspace_path(slug)
    if not os.path.exists(path):
        return {"files": []}
    
    # Exclude system files (history, chats metadata, etc.)
    excluded_files = {"history.json", "chats.json"}
    excluded_prefixes = {"chat_"}
    
    files = []
    for f in os.listdir(path):
        # Skip system files
        if f in excluded_files:
            continue
        # Skip chat history files
        if any(f.startswith(prefix) for prefix in excluded_prefixes):
            continue
        # Only include actual document files
        if os.path.isfile(os.path.join(path, f)):
            files.append(f)
    
    return {"files": sorted(files)}

# -----------------------------
# CORE RAG ENDPOINTS
# -----------------------------

MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

@app.post("/upload")
async def upload(workspace_name: str, file: UploadFile = File(...),
                 background_tasks: BackgroundTasks = BackgroundTasks(),
                 username: str = Depends(require_auth)):
    slug = get_safe_name(workspace_name)
    path = get_workspace_path(slug)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    safe_filename = os.path.basename(file.filename)
    if not safe_filename or safe_filename in [".", ".."]:
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_filename = safe_filename.replace("/", "_").replace("\\", "_")
    file_path = os.path.join(path, safe_filename)

    if os.path.exists(file_path):
        raise HTTPException(
            status_code=409,
            detail=f'"{safe_filename}" already exists in this workspace. Delete it first if you want to re-upload.'
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_UPLOAD_SIZE_MB}MB "
                   f"(got {len(file_bytes) / 1024 / 1024:.1f}MB)."
        )

    # Write to disk immediately — respond fast
    with open(file_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Heavy work runs in background — user gets instant response
    background_tasks.add_task(_upload_to_supabase, slug, safe_filename, file_bytes, username)
    background_tasks.add_task(_process_and_index, slug, safe_filename, file_path, username)

    logger.info(f"File {safe_filename} saved, processing in background [{username}/{slug}]")
    return {"status": "processing", "message": f'"{safe_filename}" uploaded. Indexing in background...'}


def _upload_to_supabase(slug: str, filename: str, file_bytes: bytes, username: str):
    try:
        storage_path = upload_file_to_supabase(slug, filename, file_bytes)
        if storage_path:
            add_document_metadata(slug, filename, storage_path, len(file_bytes), username)
            logger.info(f"Supabase Storage upload complete: {filename}")
    except Exception as e:
        logger.warning(f"Supabase upload error (non-fatal): {e}")


def _process_and_index(slug: str, filename: str, file_path: str, username: str):
    """Background: extract → semantic chunk → embed → index."""
    try:
        ext = filename.lower()
        logger.info(f"Background processing: {filename} [{username}/{slug}]")

        page_info = None
        if ext.endswith(".pdf"):
            text, page_info = extract_pdf_text(file_path)
        elif ext.endswith((".xlsx", ".xls")):
            text = extract_excel_text(file_path)
        elif ext.endswith(".docx"):
            text = extract_docx_text(file_path)
        elif ext.endswith((".png", ".jpg", ".jpeg")):
            text = extract_image_text(file_path)
        else:
            logger.error(f"Unsupported format: {filename}")
            return

        if not text or not text.strip():
            logger.warning(f"No text extracted from {filename}")
            return

        if page_info:
            from backend.chunking import chunk_text_with_pages
            chunks = chunk_text_with_pages(text, page_info)
        elif ext.endswith((".xlsx", ".xls")):
            from backend.chunking import chunk_excel_text
            chunks = chunk_excel_text(text)
        else:
            from backend.chunking import chunk_text
            chunks = chunk_text(text)

        add_documents(slug, chunks, filename, username=username)
        logger.info(f"Background indexing complete: {filename} → {len(chunks)} chunks")
    except Exception as e:
        logger.error(f"Background processing failed for {filename}: {e}")

@app.post("/chat")
async def chat(data: ChatRequest, username: str = Depends(require_auth)):
    """Process chat query with RAG."""
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(data.question) > 2000:
        raise HTTPException(status_code=400, detail="Question too long. Please keep it under 2000 characters.")
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")

    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    try:
        logger.info(f"Processing chat query in workspace {slug} by {username}")
        context_chunks, metadatas = retrieve(slug, data.question, username=username, k=15)
        if not context_chunks:
            answer = "No context found in documents. Please upload some documents first."
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            page_numbers = []
        else:
            context = "\n\n".join(context_chunks)
            prior_history = load_history(slug, (data.chat_id or "").strip() or None)
            answer, token_usage = generate_answer(context, data.question, history=prior_history)
            page_numbers = []
            for meta in metadatas:
                if meta and "page" in meta and meta["page"] is not None:
                    page_num = meta["page"]
                    if page_num not in page_numbers:
                        page_numbers.append(page_num)
            page_numbers.sort()
            logger.info(f"Generated answer with {len(context_chunks)} context chunks, pages: {page_numbers}")
    except Exception as e:
        logger.error(f"Error generating answer: {str(e)}")
        answer = f"Error generating answer: {str(e)}"
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        page_numbers = []

    # Get or create chat_id
    chat_id = (data.chat_id or "").strip() or None
    if not chat_id:
        chats = load_chats_metadata(slug)
        if not chats:
            chat_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            chats.append({"id": chat_id, "title": "Chat 1", "created_at": now, "updated_at": now})
            save_chats_metadata(slug, chats)
        else:
            # Use most recently updated chat
            def _ts(c: dict) -> str:
                return c.get("updated_at") or c.get("created_at") or ""
            chat_id = sorted(chats, key=_ts, reverse=True)[0]["id"]
    
    try:
        history = load_history(slug, chat_id)
        history.append({"role": "user", "content": data.question})
        history.append({"role": "assistant", "content": answer})
        save_history(slug, history, chat_id)

        # Sync messages to Supabase
        sync_message_add(chat_id, "user", data.question)
        sync_message_add(chat_id, "assistant", answer)

        # Update chat's updated_at timestamp
        chats = load_chats_metadata(slug)
        new_title = None
        for chat in chats:
            if chat["id"] == chat_id:
                chat["updated_at"] = datetime.now().isoformat()
                if len(history) == 2:
                    new_title = data.question[:50] + ("..." if len(data.question) > 50 else "")
                    chat["title"] = new_title
                break
        save_chats_metadata(slug, chats)
        sync_chat_update(chat_id, new_title)
    except Exception as e:
        logger.warning(f"Error saving history: {str(e)}")

    return {
        "answer": answer,
        "chat_id": chat_id,
        "page_numbers": page_numbers,
        "token_usage": token_usage
    }

@app.post("/chat/stream")
async def chat_stream(data: ChatRequest, username: str = Depends(require_auth)):
    """Process chat query with RAG using streaming response."""
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(data.question) > 2000:
        raise HTTPException(status_code=400, detail="Question too long. Please keep it under 2000 characters.")
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    
    slug = get_safe_name(data.workspace_name)

    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    async def generate():
        trace = QueryTrace(username, slug, data.question)
        trace.__enter__()
        try:
            q_lower = data.question.lower()
            if any(w in q_lower for w in ["list", "all", "who", "names", "people", "everyone", "each", "every", "show all", "find all"]):
                k = 20
            elif any(w in q_lower for w in ["summary", "summarize", "overview", "explain", "what is", "describe", "tell me about"]):
                k = 8
            else:
                k = 4
            context_chunks, metadatas = retrieve(slug, data.question, username=username, k=k)
            trace.set(chunks_retrieved=len(context_chunks), chunks_after_rerank=len(context_chunks))
            full_answer = ""
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            page_numbers = []

            if not context_chunks:
                answer = "No context found in documents. Please upload some documents first."
                yield f"data: {json.dumps({'type': 'chunk', 'content': answer})}\n\n"
                full_answer = answer
            else:
                context = "\n\n".join(context_chunks)

                # Extract unique page numbers from metadata
                for meta in metadatas:
                    if meta and "page" in meta and meta["page"] is not None:
                        page_num = meta["page"]
                        if page_num not in page_numbers:
                            page_numbers.append(page_num)
                page_numbers.sort()

                # Load prior history for conversation context
                prior_history = load_history(slug, (data.chat_id or "").strip() or None)

                # Stream the answer with history
                for item_type, item_data in generate_answer_stream(context, data.question, history=prior_history):
                    if item_type == "chunk":
                        full_answer += item_data
                        yield f"data: {json.dumps({'type': 'chunk', 'content': item_data})}\n\n"
                    elif item_type == "usage":
                        token_usage = item_data
                
                logger.info(f"Generated streaming answer with {len(context_chunks)} context chunks, pages: {page_numbers}")
            
            # Send metadata (page numbers, token usage, trace_id) before completion
            trace.set(total_tokens=token_usage.get("total_tokens", 0), query_variants=1)
            yield f"data: {json.dumps({'type': 'metadata', 'page_numbers': page_numbers, 'token_usage': token_usage, 'trace_id': trace.trace_id})}\n\n"

            # Get or create chat_id for history saving
            chat_id = (data.chat_id or "").strip() or None
            if not chat_id:
                chats = load_chats_metadata(slug)
                if not chats:
                    chat_id = str(uuid.uuid4())
                    now = datetime.now().isoformat()
                    chats.append({"id": chat_id, "title": "Chat 1", "created_at": now, "updated_at": now})
                    save_chats_metadata(slug, chats)
                else:
                    def _ts(c: dict) -> str:
                        return c.get("updated_at") or c.get("created_at") or ""
                    chat_id = sorted(chats, key=_ts, reverse=True)[0]["id"]
            
            # Save to history after streaming completes
            try:
                history = load_history(slug, chat_id)
                history.append({"role": "user", "content": data.question})
                history.append({"role": "assistant", "content": full_answer})
                save_history(slug, history, chat_id)

                # Sync messages to Supabase
                sync_message_add(chat_id, "user", data.question)
                sync_message_add(chat_id, "assistant", full_answer)

                # Update chat's updated_at timestamp
                chats = load_chats_metadata(slug)
                new_title = None
                for chat in chats:
                    if chat["id"] == chat_id:
                        chat["updated_at"] = datetime.now().isoformat()
                        if len(history) == 2:
                            new_title = data.question[:50] + ("..." if len(data.question) > 50 else "")
                            chat["title"] = new_title
                        break
                save_chats_metadata(slug, chats)
                sync_chat_update(chat_id, new_title)
            except Exception as e:
                logger.warning(f"Error saving history: {str(e)}")
            
            # Send completion signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"Error generating streaming answer: {str(e)}")
            trace.__exit__(type(e), e, None)
            error_msg = f"Error generating answer: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            return
        trace.__exit__(None, None, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/delete-file")
async def delete_one_file(data: DeleteFileRequest, username: str = Depends(require_auth)):
    slug = get_safe_name(data.workspace_name)
    workspace_path = get_workspace_path(slug)

    if not os.path.exists(workspace_path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    file_path = os.path.join(workspace_path, data.filename)

    # Remove from ChromaDB
    delete_from_collection(slug, data.filename, username)

    # Remove from local disk
    if os.path.exists(file_path):
        os.remove(file_path)

    # Remove from Supabase Storage
    try:
        from backend.supabase_storage import delete_file_from_supabase
        delete_file_from_supabase(slug, data.filename)
        logger.info(f"Deleted {data.filename} from Supabase Storage")
    except Exception as e:
        logger.warning(f"Supabase Storage delete failed (non-fatal): {e}")

    return {"message": "File deleted"}


# -----------------------------
# FEEDBACK & ANALYTICS ENDPOINTS
# -----------------------------

@app.post("/feedback")
async def submit_feedback(data: FeedbackRequest, username: str = Depends(require_auth)):
    """Submit thumbs up/down feedback for a query."""
    if data.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback must be 'up' or 'down'")
    save_feedback(data.trace_id, data.feedback)
    return {"success": True}

@app.get("/analytics")
async def analytics(workspace_name: Optional[str] = None, username: str = Depends(require_auth)):
    """Get query analytics for the current user."""
    slug = get_safe_name(workspace_name) if workspace_name else None
    data = get_analytics(username, slug)
    return data
=======
@app.post("/feedback")
async def submit_feedback(data: FeedbackRequest, token: Optional[str] = Depends(get_token)):
    username = get_current_user(token)
    if data.feedback not in ("up", "down"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="feedback must be 'up' or 'down'")
    save_feedback(data.trace_id, data.feedback)
    return {"success": True}

@app.get("/analytics")
async def analytics(workspace_name: Optional[str] = None, token: Optional[str] = Depends(get_token)):
    username = get_current_user(token)
    slug = get_safe_name(workspace_name) if workspace_name else None
    return get_analytics(username, slug)

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
>>>>>>> 0f84573 (feat: production RAG improvements)
