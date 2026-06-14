"""
Playground event bus — in-memory SSE pipeline trace store.
Instruments the RAG pipeline without touching core logic.

Traces flow:
  new_trace() → emit() × N → finish_trace()
  SSE clients subscribe to /playground/stream and receive all events in real time.
"""
import time
import uuid
import asyncio
import logging
from collections import deque
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── In-memory ring buffer (last 200 traces, 1000 events) ──────
_MAX_TRACES = 200
_MAX_EVENTS = 1000

# trace_id → trace dict
_traces: Dict[str, dict] = {}
# ordered list of trace_ids (newest last)
_trace_order: deque = deque(maxlen=_MAX_TRACES)
# global event stream (all events from all traces)
_event_log: deque = deque(maxlen=_MAX_EVENTS)

# SSE subscriber queues
_subscribers: List[asyncio.Queue] = []

# Stage display config
STAGE_META = {
    "file_upload":      {"icon": "upload_file",    "label": "File Upload",       "color": "#3b82f6"},
    "text_extraction":  {"icon": "text_snippet",   "label": "Text Extraction",   "color": "#8b5cf6"},
    "chunking":         {"icon": "call_split",      "label": "Chunking",          "color": "#f59e0b"},
    "embedding":        {"icon": "hub",             "label": "Embedding",         "color": "#06b6d4"},
    "vector_store":     {"icon": "database",        "label": "Vector Store",      "color": "#10b981"},
    "query_received":   {"icon": "search",          "label": "Query Received",    "color": "#6366f1"},
    "hybrid_search":    {"icon": "manage_search",   "label": "Hybrid Search",     "color": "#f59e0b"},
    "rrf_merge":        {"icon": "merge",           "label": "RRF Merge",         "color": "#ec4899"},
    "rerank":           {"icon": "sort",            "label": "Rerank",            "color": "#f97316"},
    "llm_generation":   {"icon": "smart_toy",       "label": "LLM Generation",    "color": "#ff2e62"},
    "response":         {"icon": "check_circle",    "label": "Response",          "color": "#10b981"},
    "storage":          {"icon": "save",            "label": "Storage",           "color": "#64748b"},
}

STATUS_COLORS = {
    "running": "#f59e0b",
    "done":    "#10b981",
    "error":   "#ef4444",
    "skip":    "#64748b",
    "pending": "#334155",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _broadcast(event: dict):
    """Push event to all connected SSE subscribers."""
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def new_trace(username: str, trace_type: str, label: str,
              meta: Optional[dict] = None) -> str:
    """
    Create a new pipeline trace. Returns trace_id.
    trace_type: 'rag_query' | 'file_upload'
    """
    trace_id = str(uuid.uuid4())[:12]
    trace = {
        "id": trace_id,
        "username": username,
        "type": trace_type,
        "label": label[:120],
        "meta": meta or {},
        "status": "running",
        "started_at": _now_ms(),
        "finished_at": None,
        "stages": [],          # ordered list of stage dicts
        "final_meta": {},
    }
    _traces[trace_id] = trace
    _trace_order.append(trace_id)

    # Evict oldest if over limit
    while len(_traces) > _MAX_TRACES:
        oldest = _trace_order[0]
        _traces.pop(oldest, None)

    event = {"type": "trace_start", "trace": _serialise_trace(trace)}
    _event_log.append(event)
    _broadcast(event)
    return trace_id


def emit(trace_id: str, stage: str, status: str,
         message: str = "", meta: Optional[dict] = None):
    """
    Emit a pipeline stage event for an active trace.
    status: 'running' | 'done' | 'error' | 'skip'
    """
    trace = _traces.get(trace_id)
    if not trace:
        return

    stage_event = {
        "stage": stage,
        "status": status,
        "message": message,
        "meta": meta or {},
        "ts": _now_ms(),
        **STAGE_META.get(stage, {"icon": "circle", "label": stage, "color": "#64748b"}),
    }

    # Update existing stage entry or append new one
    existing = next((s for s in trace["stages"] if s["stage"] == stage), None)
    if existing:
        existing.update(stage_event)
    else:
        trace["stages"].append(stage_event)

    event = {"type": "stage", "trace_id": trace_id, "stage_event": stage_event}
    _event_log.append(event)
    _broadcast(event)


def finish_trace(trace_id: str, status: str = "done",
                 final_meta: Optional[dict] = None):
    """Mark a trace as finished."""
    trace = _traces.get(trace_id)
    if not trace:
        return
    trace["status"] = status
    trace["finished_at"] = _now_ms()
    trace["final_meta"] = final_meta or {}

    event = {
        "type": "trace_end",
        "trace_id": trace_id,
        "status": status,
        "latency_ms": trace["finished_at"] - trace["started_at"],
        "final_meta": trace["final_meta"],
    }
    _event_log.append(event)
    _broadcast(event)


def get_recent_traces(limit: int = 50) -> List[dict]:
    """Return the N most recent traces (newest first)."""
    ids = list(_trace_order)[-limit:]
    ids.reverse()
    return [_serialise_trace(_traces[tid]) for tid in ids if tid in _traces]


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber. Returns its queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def _serialise_trace(t: dict) -> dict:
    return {
        "id": t["id"],
        "username": t["username"],
        "type": t["type"],
        "label": t["label"],
        "meta": t["meta"],
        "status": t["status"],
        "started_at": t["started_at"],
        "finished_at": t["finished_at"],
        "latency_ms": (t["finished_at"] - t["started_at"]) if t["finished_at"] else None,
        "stages": t["stages"],
        "final_meta": t["final_meta"],
    }
