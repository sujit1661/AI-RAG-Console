import os
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.deps import (
    get_token, get_safe_name, get_workspace_path,
    load_chats_metadata, save_chats_metadata,
    load_history, save_history,
)
from backend.auth import get_current_user
from backend.retriever import retrieve
from backend.llm import generate_answer, generate_answer_stream
from backend.persistence import sync_message_add, sync_chat_update
from backend.analytics import QueryTrace

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    workspace_name: str
    question: str
    chat_id: Optional[str] = None


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


def _adaptive_k(question: str) -> int:
    """Return how many final chunks to return based on query type."""
    q = question.lower()
    if any(w in q for w in ["list", "all", "every", "each", "who", "names",
                             "people", "everyone", "summary", "summarize",
                             "overview", "describe", "explain"]):
        return 15
    if any(w in q for w in ["what is", "when", "where", "how many", "how much",
                             "define", "what does", "who is"]):
        return 4
    return 8


def _save_and_sync(slug: str, chat_id: str, question: str, answer: str):
    """Save message to local JSON and sync to Supabase."""
    try:
        history = load_history(slug, chat_id)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        save_history(slug, history, chat_id)
        sync_message_add(chat_id, "user", question)
        sync_message_add(chat_id, "assistant", answer)

        chats = load_chats_metadata(slug)
        new_title = None
        for chat in chats:
            if chat["id"] == chat_id:
                chat["updated_at"] = datetime.now().isoformat()
                if len(history) == 2:
                    new_title = question[:50] + ("..." if len(question) > 50 else "")
                    chat["title"] = new_title
                break
        save_chats_metadata(slug, chats)
        sync_chat_update(chat_id, new_title)
    except Exception as e:
        logger.warning(f"Error saving history: {e}")


def _resolve_chat_id(slug: str, requested_id: Optional[str]) -> str:
    """Return existing chat_id, or create a new one."""
    chat_id = (requested_id or "").strip() or None
    if chat_id:
        return chat_id
    chats = load_chats_metadata(slug)
    if not chats:
        chat_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        chats.append({"id": chat_id, "title": "Chat 1", "created_at": now, "updated_at": now})
        save_chats_metadata(slug, chats)
        return chat_id
    return sorted(chats, key=lambda c: c.get("updated_at") or c.get("created_at") or "", reverse=True)[0]["id"]


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/chat")
async def chat(data: ChatRequest, username: str = Depends(_require_auth)):
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(data.question) > 2000:
        raise HTTPException(status_code=400, detail="Question too long (max 2000 chars)")
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")

    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    k = _adaptive_k(data.question)
    try:
        context_chunks, metadatas = retrieve(slug, data.question, username=username, k=k)
        if not context_chunks:
            answer = "No context found. Please upload documents first."
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            page_numbers = []
        else:
            context = "\n\n".join(context_chunks)
            prior = load_history(slug, (data.chat_id or "").strip() or None)
            answer, token_usage = generate_answer(context, data.question, history=prior)
            page_numbers = sorted({m["page"] for m in metadatas if m and m.get("page") is not None})
    except Exception as e:
        logger.error(f"Chat error: {e}")
        answer = f"Error: {e}"
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        page_numbers = []

    chat_id = _resolve_chat_id(slug, data.chat_id)
    _save_and_sync(slug, chat_id, data.question, answer)
    return {"answer": answer, "chat_id": chat_id, "page_numbers": page_numbers, "token_usage": token_usage}


@router.post("/chat/stream")
async def chat_stream(data: ChatRequest, username: str = Depends(_require_auth)):
    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(data.question) > 2000:
        raise HTTPException(status_code=400, detail="Question too long (max 2000 chars)")
    if not data.workspace_name or not data.workspace_name.strip():
        raise HTTPException(status_code=400, detail="Workspace name cannot be empty")

    slug = get_safe_name(data.workspace_name)
    if not os.path.exists(get_workspace_path(slug)):
        raise HTTPException(status_code=404, detail="Workspace not found")

    async def generate():
        trace = QueryTrace(username, slug, data.question)
        trace.__enter__()
        try:
            k = _adaptive_k(data.question)
            trace.emit_stage("query_received", "done",
                             f"k={k}, workspace={slug}",
                             {"question": data.question, "k": k, "workspace": slug})

            trace.emit_stage("hybrid_search", "running", "Searching vector + BM25 indexes")
            context_chunks, metadatas = retrieve(slug, data.question, username=username, k=k)
            trace.set(chunks_retrieved=len(context_chunks), chunks_after_rerank=len(context_chunks))

            sources = list({m.get("source", "") for m in metadatas if m})
            trace.emit_stage("hybrid_search", "done",
                             f"{len(context_chunks)} chunks retrieved",
                             {"chunks": len(context_chunks), "sources": sources})
            trace.emit_stage("rrf_merge", "done",
                             "Reciprocal Rank Fusion applied",
                             {"candidates": len(context_chunks)})
            trace.emit_stage("rerank", "done" if context_chunks else "skip",
                             f"Reranked to top {len(context_chunks)}",
                             {"chunks_after_rerank": len(context_chunks)})

            full_answer = ""
            token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            page_numbers = []

            if not context_chunks:
                msg = "No context found. Please upload documents first."
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                full_answer = msg
                trace.emit_stage("llm_generation", "skip", "No context — skipped")
            else:
                context = "\n\n".join(context_chunks)
                page_numbers = sorted({m["page"] for m in metadatas if m and m.get("page") is not None})
                prior = load_history(slug, (data.chat_id or "").strip() or None)
                trace.emit_stage("llm_generation", "running",
                                 "Streaming from LLM",
                                 {"context_chars": len(context), "pages": page_numbers})
                for item_type, item_data in generate_answer_stream(context, data.question, history=prior):
                    if item_type == "chunk":
                        full_answer += item_data
                        yield f"data: {json.dumps({'type': 'chunk', 'content': item_data})}\n\n"
                    elif item_type == "usage":
                        token_usage = item_data

            trace.set(total_tokens=token_usage.get("total_tokens", 0))
            trace.emit_stage("llm_generation", "done",
                             f"{token_usage.get('total_tokens', 0)} tokens",
                             token_usage)
            yield f"data: {json.dumps({'type': 'metadata', 'page_numbers': page_numbers, 'token_usage': token_usage, 'trace_id': trace.trace_id})}\n\n"

            chat_id = _resolve_chat_id(slug, data.chat_id)
            trace.emit_stage("storage", "running", "Persisting to local JSON + Supabase")
            _save_and_sync(slug, chat_id, data.question, full_answer)
            trace.emit_stage("storage", "done", "Saved",
                             {"chat_id": chat_id})
            trace.emit_stage("response", "done",
                             f"{len(full_answer)} chars",
                             {"answer_length": len(full_answer), "pages": page_numbers})
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            trace.__exit__(type(e), e, None)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return
        trace.__exit__(None, None, None)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
