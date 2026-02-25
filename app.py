from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
import shutil
import os
import re
import json
import logging
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

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
    get_current_user, init_default_user, create_user, get_user_info
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize default admin user
init_default_user()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get auth token from cookie or header
async def get_token(request: Request) -> Optional[str]:
    """Extract token from cookie or Authorization header."""
    # Try cookie first
    token = request.cookies.get("session_token")
    if token:
        return token
    # Try Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    return None

# Dependency to verify authentication
async def require_auth(token: Optional[str] = Depends(get_token)) -> str:
    """Dependency to require authentication."""
    return get_current_user(token)

UPLOAD_ROOT = "uploads"
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# -----------------------------
# HELPERS
# -----------------------------

def get_safe_name(name: str) -> str:
    """Slugifies workspace name: 'My Project' -> 'my-project'"""
    slug = re.sub(r'[^\w\s-]', '', name).strip().lower()
    return re.sub(r'[-\s]+', '-', slug)

def get_workspace_path(slug: str) -> str:
    return os.path.join(UPLOAD_ROOT, slug)

def get_chats_metadata_file(slug: str) -> str:
    """Get path to chats metadata file."""
    return os.path.join(get_workspace_path(slug), "chats.json")

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
async def login(data: LoginRequest, response: Response):
    """Login endpoint."""
    try:
        if authenticate_user(data.username, data.password):
            token = create_session(data.username)
            response.set_cookie(
                key="session_token",
                value=token,
                httponly=True,
                secure=False,  # Set to True in production with HTTPS
                samesite="lax",
                max_age=7 * 24 * 60 * 60  # 7 days
            )
            user_info = get_user_info(data.username)
            if user_info is None:
                user_info = {}  # Fallback if user info not found
            logger.info(f"User {data.username} logged in successfully")
            return {"success": True, "token": token, "username": data.username, "user_info": user_info}
        else:
            logger.warning(f"Failed login attempt for user {data.username}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/register")
async def register(data: RegisterRequest, response: Response):
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

# -----------------------------
# STATIC FILES
# -----------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    """Serve landing page."""
    return FileResponse("landing.html")

@app.get("/app", response_class=HTMLResponse)
async def serve_index():
    """Serve main application."""
    return FileResponse("index.html")

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """Serve login page."""
    return FileResponse("login.html")

@app.get("/register", response_class=HTMLResponse)
async def serve_register():
    """Serve registration page."""
    return FileResponse("register.html")

# -----------------------------
# WORKSPACE ENDPOINTS
# -----------------------------
@app.get("/workspace/list")
async def list_all_workspaces(username: str = Depends(require_auth)):
    """List all workspaces with metadata."""
    try:
        if not os.path.exists(UPLOAD_ROOT):
            return {"workspaces": []}
        workspaces = [d for d in os.listdir(UPLOAD_ROOT) if os.path.isdir(os.path.join(UPLOAD_ROOT, d)) and d != "__pycache__"]
        
        # Get metadata for each workspace
        workspace_list = []
        for ws in sorted(workspaces):
            slug = ws
            metadata = {
                "name": ws,
                "slug": slug,
                "last_message": None,
                "last_updated": None,
                "message_count": 0
            }
            
            # Get last message from most recently updated chat (fallback to legacy history)
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
        
        # Sort by last updated (most recent first)
        workspace_list.sort(key=lambda x: x["last_updated"] or 0, reverse=True)
        
        return {"workspaces": workspace_list}
    except Exception as e:
        logger.error(f"Error listing workspaces: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workspace/create")
async def create_workspace(data: WorkspaceRequest, username: str = Depends(require_auth)):
    """Create a new workspace."""
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    
    try:
        slug = get_safe_name(data.workspace_name)
        if not slug:
            raise HTTPException(status_code=400, detail="Invalid workspace name")
        
        path = get_workspace_path(slug)
        if os.path.exists(path):
            raise HTTPException(status_code=400, detail="Workspace already exists")
        
        os.makedirs(path, exist_ok=True)
        # Ensure history file exists (legacy support)
        legacy_hist_file = os.path.join(path, "history.json")
        if not os.path.exists(legacy_hist_file):
            with open(legacy_hist_file, "w") as f:
                json.dump([], f)
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

    # Clear Vector DB
    try:
        delete_workspace(slug)
    except:
        pass  # Ignore if collection doesn't exist

    # Delete files
    if os.path.exists(path):
        shutil.rmtree(path)

    return {"message": f"Workspace {slug} deleted from disk and DB"}

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
@app.post("/upload")
async def upload(workspace_name: str, file: UploadFile = File(...), username: str = Depends(require_auth)):
    slug = get_safe_name(workspace_name)
    path = get_workspace_path(slug)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Safe filename - prevent path traversal
    safe_filename = os.path.basename(file.filename)
    if not safe_filename or safe_filename in [".", ".."]:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Additional security: remove any path components
    safe_filename = safe_filename.replace("/", "_").replace("\\", "_")
    file_path = os.path.join(path, safe_filename)

    if os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="File already exists")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        ext = safe_filename.lower()
        logger.info(f"Processing file {safe_filename} in workspace {slug}")
        
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
            if os.path.exists(file_path): os.remove(file_path)
            raise HTTPException(status_code=400, detail="Format not supported")

        if not text.strip():
            if os.path.exists(file_path): os.remove(file_path)
            raise HTTPException(status_code=400, detail="No readable content found in file")

        # Use page-aware chunking for PDFs, regular chunking for others
        chunks_count = 0
        if page_info:
            from backend.chunking import chunk_text_with_pages
            chunks_with_pages = chunk_text_with_pages(text, page_info)
            add_documents(slug, chunks_with_pages, safe_filename)
            chunks_count = len(chunks_with_pages)
        else:
            chunks = chunk_text(text)
            add_documents(slug, chunks, safe_filename)
            chunks_count = len(chunks)
        logger.info(f"Successfully indexed {chunks_count} chunks from {safe_filename}")
        return {"status": "success", "chunks": chunks_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file {safe_filename}: {str(e)}")
        if os.path.exists(file_path): os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@app.post("/chat")
async def chat(data: ChatRequest, username: str = Depends(require_auth)):
    """Process chat query with RAG."""
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    
    slug = get_safe_name(data.workspace_name)

    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    try:
        logger.info(f"Processing chat query in workspace {slug} by {username}")
        context_chunks, metadatas = retrieve(slug, data.question)

        if not context_chunks:
            answer = "No context found in documents. Please upload some documents first."
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            page_numbers = []
        else:
            context = "\n\n".join(context_chunks)
            answer, token_usage = generate_answer(context, data.question)
            
            # Extract unique page numbers from metadata
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
        
        # Update chat's updated_at timestamp
        chats = load_chats_metadata(slug)
        for chat in chats:
            if chat["id"] == chat_id:
                chat["updated_at"] = datetime.now().isoformat()
                # Update title if it's the first message
                if len(history) == 2:
                    # Use first 50 chars of question as title
                    chat["title"] = data.question[:50] + ("..." if len(data.question) > 50 else "")
                break
        save_chats_metadata(slug, chats)
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
    
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")
    
    slug = get_safe_name(data.workspace_name)

    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    async def generate():
        try:
            logger.info(f"Processing streaming chat query in workspace {slug} by {username}")
            context_chunks, metadatas = retrieve(slug, data.question)
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
                
                # Stream the answer
                for item_type, item_data in generate_answer_stream(context, data.question):
                    if item_type == "chunk":
                        full_answer += item_data
                        yield f"data: {json.dumps({'type': 'chunk', 'content': item_data})}\n\n"
                    elif item_type == "usage":
                        token_usage = item_data
                
                logger.info(f"Generated streaming answer with {len(context_chunks)} context chunks, pages: {page_numbers}")
            
            # Send metadata (page numbers and token usage) before completion
            yield f"data: {json.dumps({'type': 'metadata', 'page_numbers': page_numbers, 'token_usage': token_usage})}\n\n"

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
                
                # Update chat's updated_at timestamp
                chats = load_chats_metadata(slug)
                for chat in chats:
                    if chat["id"] == chat_id:
                        chat["updated_at"] = datetime.now().isoformat()
                        # Update title if it's the first message
                        if len(history) == 2:
                            chat["title"] = data.question[:50] + ("..." if len(data.question) > 50 else "")
                        break
                save_chats_metadata(slug, chats)
            except Exception as e:
                logger.warning(f"Error saving history: {str(e)}")
            
            # Send completion signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"Error generating streaming answer: {str(e)}")
            error_msg = f"Error generating answer: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"

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

    delete_from_collection(slug, data.filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    return {"message": "File deleted"}