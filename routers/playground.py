"""
Playground router — SSE stream + REST endpoints for the pipeline dashboard.
Read-only monitoring layer; does not modify any RAG functionality.
"""
import json
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.deps import get_token
from backend.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/playground", tags=["playground"])


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


@router.get("/stream")
async def playground_stream(username: str = Depends(_require_auth)):
    """SSE endpoint — streams live pipeline events to the dashboard."""
    from backend.playground import subscribe, unsubscribe, get_recent_traces

    q = subscribe()

    async def event_generator():
        # Send a snapshot of recent traces on connect
        try:
            snapshot = get_recent_traces(30)
            yield f"data: {json.dumps({'type': 'snapshot', 'traces': snapshot})}\n\n"
        except Exception as e:
            logger.warning(f"Snapshot error: {e}")

        # Stream live events
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield "data: {\"type\":\"ping\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/traces")
async def get_traces(limit: int = 50, username: str = Depends(_require_auth)):
    """REST endpoint — returns recent traces (used for initial page load)."""
    from backend.playground import get_recent_traces
    traces = get_recent_traces(min(limit, 100))
    return {"traces": traces}


@router.get("/stats")
async def get_stats(username: str = Depends(_require_auth)):
    """Aggregate stats across in-memory traces."""
    from backend.playground import _traces
    traces = list(_traces.values())
    total = len(traces)
    done = sum(1 for t in traces if t["status"] == "done")
    errors = sum(1 for t in traces if t["status"] == "error")
    running = sum(1 for t in traces if t["status"] == "running")
    latencies = [
        t["finished_at"] - t["started_at"]
        for t in traces
        if t["finished_at"] and t["status"] == "done"
    ]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0
    rag_count = sum(1 for t in traces if t["type"] == "rag_query")
    upload_count = sum(1 for t in traces if t["type"] == "file_upload")
    return {
        "total": total, "done": done, "errors": errors, "running": running,
        "avg_latency_ms": avg_latency, "rag_queries": rag_count,
        "file_uploads": upload_count,
    }
