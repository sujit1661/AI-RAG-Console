"""
General AI chatbot router — pure LLM, no document context.
Sessions and messages are persisted to Supabase.
Falls back gracefully if Supabase is unavailable.
"""
import json
import logging
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.deps import get_token
from backend.auth import get_current_user
from backend.llm import generate_general_answer_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/general", tags=["general-chat"])


# ── Pydantic models ────────────────────────────────────────────

class GeneralChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # client sends this after first message


class SessionCreateRequest(BaseModel):
    title: Optional[str] = "New Chat"


class SessionDeleteRequest(BaseModel):
    session_id: str


# ── Auth ───────────────────────────────────────────────────────

def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


# ── Session endpoints ──────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(username: str = Depends(_require_auth)):
    """Return all general-chat sessions for the current user."""
    try:
        from backend.supabase_db import get_general_sessions
        return {"sessions": get_general_sessions(username)}
    except Exception as e:
        logger.warning(f"list_sessions failed: {e}")
        return {"sessions": []}


@router.post("/sessions")
async def create_session(data: SessionCreateRequest, username: str = Depends(_require_auth)):
    """Create a new general-chat session."""
    try:
        from backend.supabase_db import create_general_session
        session_id = create_general_session(username, data.title or "New Chat")
        if not session_id:
            raise HTTPException(status_code=500, detail="Could not create session")
        return {"session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, username: str = Depends(_require_auth)):
    """Delete a session and all its messages."""
    try:
        from backend.supabase_db import delete_general_session
        delete_general_session(session_id, username)
        return {"success": True}
    except Exception as e:
        logger.warning(f"delete_session error: {e}")
        return {"success": False}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, username: str = Depends(_require_auth)):
    """Return the full message history for a session."""
    try:
        from backend.supabase_db import get_general_messages
        messages = get_general_messages(session_id, username)
        return {"messages": messages}
    except Exception as e:
        logger.warning(f"get_session_messages error: {e}")
        return {"messages": []}


# ── Chat streaming endpoint ────────────────────────────────────

@router.post("/chat/stream")
async def general_chat_stream(data: GeneralChatRequest, username: str = Depends(_require_auth)):
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(data.question) > 4000:
        raise HTTPException(status_code=400, detail="Question too long (max 4000 chars)")

    # Resolve session — create one if the client didn't send an id
    session_id = (data.session_id or "").strip() or None

    # Load history from Supabase for context
    history: List[Dict] = []
    if session_id:
        try:
            from backend.supabase_db import get_general_messages
            history = get_general_messages(session_id, username)
        except Exception:
            pass

    async def generate():
        nonlocal session_id
        full_answer = ""
        token_usage = {}

        try:
            for item_type, item_data in generate_general_answer_stream(data.question, history):
                if item_type == "chunk":
                    full_answer += item_data
                    yield f"data: {json.dumps({'type': 'chunk', 'content': item_data})}\n\n"
                elif item_type == "usage":
                    token_usage = item_data or {}

        except Exception as e:
            logger.error(f"Stream error [{username}]: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        # Persist to Supabase (non-blocking — errors are logged, not raised)
        try:
            from backend.supabase_db import (
                create_general_session, update_general_session_title,
                touch_general_session, add_general_message
            )

            # Create session on first message
            if not session_id:
                title = data.question[:60] + ("…" if len(data.question) > 60 else "")
                session_id = create_general_session(username, title)
            else:
                touch_general_session(session_id)

            if session_id:
                # Auto-title: if this was the first exchange, title = first question
                history_len = len(history)
                if history_len == 0:
                    title = data.question[:60] + ("…" if len(data.question) > 60 else "")
                    update_general_session_title(session_id, title)

                add_general_message(session_id, "user", data.question)
                add_general_message(session_id, "assistant", full_answer)

        except Exception as e:
            logger.warning(f"Supabase general-chat persist failed (non-fatal): {e}")

        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'token_usage': token_usage})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
