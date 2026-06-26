"""
Structured logging, request tracing, and analytics.
Stores query logs in Supabase + optional Langfuse tracing.
"""
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Langfuse client (lazy, optional) ─────────────────────────
_langfuse = None

def _get_langfuse():
    """Return Langfuse client if keys are configured, else None."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        return None
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        logger.info("Langfuse tracing enabled")
    except Exception as e:
        logger.debug(f"Langfuse init failed (non-fatal): {e}")
    return _langfuse


class QueryTrace:
    """Context manager that times a query and logs structured metrics."""

    def __init__(self, username: str, workspace_slug: str, question: str):
        self.trace_id = str(uuid.uuid4())[:8]
        self.username = username
        self.workspace_slug = workspace_slug
        self.question = question
        self.start_time = None
        self.metrics = {}

    def __enter__(self):
        self.start_time = time.perf_counter()
        logger.info(
            f"[{self.trace_id}] QUERY START | user={self.username} "
            f"ws={self.workspace_slug} | q={self.question[:80]}"
        )
        # Playground event
        try:
            from backend.playground import new_trace
            self._pg_trace_id = new_trace(
                self.username, "rag_query", self.question,
                meta={"workspace": self.workspace_slug}
            )
        except Exception:
            self._pg_trace_id = None

        # Langfuse trace
        self._lf_trace = None
        try:
            lf = _get_langfuse()
            if lf:
                self._lf_trace = lf.trace(
                    id=self.trace_id,
                    name="rag-query",
                    user_id=self.username,
                    metadata={"workspace": self.workspace_slug},
                    input={"question": self.question},
                )
        except Exception:
            pass
        return self

    def set(self, **kwargs):
        """Record metrics during the query."""
        self.metrics.update(kwargs)

    def emit_stage(self, stage: str, status: str, message: str = "", meta: dict = None):
        """Emit a playground pipeline stage event (no-op if playground unavailable)."""
        try:
            pg_id = getattr(self, "_pg_trace_id", None)
            if pg_id:
                from backend.playground import emit
                emit(pg_id, stage, status, message, meta or {})
        except Exception:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = round((time.perf_counter() - self.start_time) * 1000, 1)
        self.metrics["latency_ms"] = elapsed
        status = "ERROR" if exc_type else "OK"

        logger.info(
            f"[{self.trace_id}] QUERY {status} | "
            f"latency={elapsed}ms | "
            f"chunks_retrieved={self.metrics.get('chunks_retrieved', 0)} | "
            f"chunks_after_rerank={self.metrics.get('chunks_after_rerank', 0)} | "
            f"query_variants={self.metrics.get('query_variants', 1)} | "
            f"tokens={self.metrics.get('total_tokens', 0)}"
        )

        # Async save to Supabase (non-blocking)
        try:
            _save_query_log(
                trace_id=self.trace_id,
                username=self.username,
                workspace_slug=self.workspace_slug,
                question=self.question,
                metrics=self.metrics,
                status=status,
            )
        except Exception:
            pass  # Never let analytics break the main flow

        # Langfuse — update trace with output + scores
        try:
            if getattr(self, "_lf_trace", None):
                self._lf_trace.update(
                    output={"answer": self.metrics.get("answer", "")[:500]},
                    metadata={
                        "latency_ms": elapsed,
                        "chunks_retrieved": self.metrics.get("chunks_retrieved", 0),
                        "total_tokens": self.metrics.get("total_tokens", 0),
                        "status": status,
                    },
                    level="ERROR" if exc_type else "DEFAULT",
                )
                lf = _get_langfuse()
                if lf:
                    lf.flush()
        except Exception:
            pass
        # Playground finish
        try:
            if getattr(self, "_pg_trace_id", None):
                from backend.playground import finish_trace
                finish_trace(self._pg_trace_id,
                             status="error" if exc_type else "done",
                             final_meta=self.metrics)
        except Exception:
            pass


def _save_query_log(trace_id: str, username: str, workspace_slug: str,
                    question: str, metrics: dict, status: str):
    """Save query log to Supabase query_logs table."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        sb.table("query_logs").insert({
            "trace_id": trace_id,
            "username": username,
            "workspace_slug": workspace_slug,
            "question": question[:500],
            "latency_ms": metrics.get("latency_ms"),
            "chunks_retrieved": metrics.get("chunks_retrieved", 0),
            "chunks_after_rerank": metrics.get("chunks_after_rerank", 0),
            "query_variants": metrics.get("query_variants", 1),
            "total_tokens": metrics.get("total_tokens", 0),
            "status": status,
            "feedback": None,
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        logger.debug(f"Analytics save failed (non-fatal): {e}")


def save_feedback(trace_id: str, feedback: str):
    """Save thumbs up/down feedback for a query."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        sb.table("query_logs").update({"feedback": feedback})\
            .eq("trace_id", trace_id).execute()
        logger.info(f"Feedback saved: {trace_id} → {feedback}")
    except Exception as e:
        logger.warning(f"Feedback save failed: {e}")

    # Mirror to Langfuse
    try:
        lf = _get_langfuse()
        if lf:
            lf.score(
                trace_id=trace_id,
                name="user-feedback",
                value=1 if feedback == "up" else 0,
                comment=feedback,
            )
            lf.flush()
    except Exception:
        pass


def get_analytics(username: str, workspace_slug: Optional[str] = None,
                  limit: int = 100) -> dict:
    """Get analytics summary for a user."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        query = sb.table("query_logs").select("*").eq("username", username)
        if workspace_slug:
            query = query.eq("workspace_slug", workspace_slug)
        result = query.order("created_at", desc=True).limit(limit).execute()
        rows = result.data or []

        if not rows:
            return {"total_queries": 0, "avg_latency_ms": 0, "logs": []}

        avg_latency = sum(r.get("latency_ms") or 0 for r in rows) / len(rows)
        thumbs_up = sum(1 for r in rows if r.get("feedback") == "up")
        thumbs_down = sum(1 for r in rows if r.get("feedback") == "down")
        errors = sum(1 for r in rows if r.get("status") == "ERROR")

        return {
            "total_queries": len(rows),
            "avg_latency_ms": round(avg_latency, 1),
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "errors": errors,
            "logs": rows,
        }
    except Exception as e:
        logger.warning(f"Analytics fetch failed: {e}")
        return {"total_queries": 0, "avg_latency_ms": 0, "logs": []}
