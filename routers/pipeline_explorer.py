"""
Pipeline Explorer — isolated educational RAG walkthrough.
Accepts a temp file upload + question, runs the full pipeline
in a sandboxed temp directory, and streams SSE events with
rich metadata at every stage.

COMPLETELY ISOLATED: uses no workspaces, no persistent storage,
no ChromaDB collections, no BM25 disk files, no Supabase writes.
All state lives in memory and a temp directory per request.
"""
import os
import json
import math
import time
import uuid
import shutil
import asyncio
import logging
import tempfile
import re
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Generator

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.deps import get_token
from backend.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline-explorer"])

MAX_FILE_MB = 20
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


# ── SSE helper ────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    data["event"] = event_type
    data["ts"] = int(time.time() * 1000)
    return f"data: {json.dumps(data, default=str)}\n\n"


# ── Isolated BM25 (in-memory only, no disk) ──────────────────

class _BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: List[str] = []
        self.tokenized: List[List[str]] = []
        self.df: Dict[str, int] = defaultdict(int)
        self.avgdl: float = 1.0

    def _tok(self, text: str) -> List[str]:
        return re.findall(r'\b\w+\b', text.lower())

    def index(self, texts: List[str]):
        for t in texts:
            toks = self._tok(t)
            self.docs.append(t)
            self.tokenized.append(toks)
            for term in set(toks):
                self.df[term] += 1
        total = sum(len(t) for t in self.tokenized)
        self.avgdl = total / len(self.tokenized) if self.tokenized else 1.0

    def search(self, query: str, k: int = 20) -> List[Tuple[float, str, int]]:
        """Returns (score, text, original_index) sorted by score desc."""
        if not self.docs:
            return []
        qtoks = self._tok(query)
        N = len(self.docs)
        scored = []
        for i, toks in enumerate(self.tokenized):
            tf_map: Dict[str, int] = defaultdict(int)
            for t in toks:
                tf_map[t] += 1
            score = 0.0
            dl = len(toks)
            for term in qtoks:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                df = self.df.get(term, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf_n = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                score += idf * tf_n
            if score > 0:
                scored.append((score, self.docs[i], i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


# ── RRF ──────────────────────────────────────────────────────

def _rrf(vector_ranked: List[int], bm25_ranked: List[int],
         n: int, k: int = 60) -> List[Tuple[float, int]]:
    """Reciprocal Rank Fusion over chunk indices. Returns [(score, idx)]."""
    scores: Dict[int, float] = {}
    for rank, idx in enumerate(vector_ranked):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)
    for rank, idx in enumerate(bm25_ranked):
        scores[idx] = scores.get(idx, 0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── Cosine similarity ─────────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ── Main pipeline SSE endpoint ────────────────────────────────

@router.post("/run")
async def run_pipeline(
    file: UploadFile = File(...),
    question: str = Form(...),
    username: str = Depends(_require_auth),
):
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 1000:
        raise HTTPException(status_code=400, detail="question too long (max 1000 chars)")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File too large (max {MAX_FILE_MB}MB)")

    filename = os.path.basename(file.filename or "upload.txt")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    allowed = {"pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "txt"}
    if ext not in allowed:
        raise HTTPException(status_code=400,
            detail=f"Unsupported format. Allowed: {', '.join(sorted(allowed))}")

    async def generate():
        tmp_dir = tempfile.mkdtemp(prefix="pg_explorer_")
        try:
            yield _sse("start", {"question": question, "filename": filename,
                                  "file_size": len(file_bytes)})
            for chunk in _run_pipeline_stages(
                tmp_dir, file_bytes, filename, ext, question, username
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Pipeline explorer error: {e}", exc_info=True)
            yield _sse("error", {"message": str(e)})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_pipeline_stages(
    tmp_dir: str,
    file_bytes: bytes,
    filename: str,
    ext: str,
    question: str,
    username: str,
) -> Generator[str, None, None]:

    file_path = os.path.join(tmp_dir, filename)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # ── Stage 1: Text Extraction ──────────────────────────────
    yield _sse("stage_start", {"stage": "extraction", "label": "Text Extraction",
                                "description": "Parsing document into raw text using PyMuPDF / python-docx / pandas / Tesseract OCR"})
    t0 = time.perf_counter()
    try:
        from backend.ingestion import (extract_pdf_text, extract_excel_text,
                                        extract_docx_text, extract_image_text)
        page_info = None
        if ext == "pdf":
            text, page_info = extract_pdf_text(file_path)
        elif ext in ("xlsx", "xls"):
            text = extract_excel_text(file_path)
        elif ext == "docx":
            text = extract_docx_text(file_path)
        elif ext in ("png", "jpg", "jpeg"):
            text = extract_image_text(file_path)
        else:  # txt
            text = file_bytes.decode("utf-8", errors="replace")

        if not text or not text.strip():
            yield _sse("stage_done", {"stage": "extraction", "status": "error",
                                       "message": "No text extracted from document"})
            yield _sse("done", {"status": "error"})
            return

        words = len(text.split())
        pages = len(page_info) if page_info else None
        yield _sse("stage_done", {
            "stage": "extraction", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "chars": len(text), "words": words, "pages": pages,
                "extractor": {"pdf":"PyMuPDF","docx":"python-docx",
                              "xlsx":"pandas","xls":"pandas",
                              "png":"Tesseract","jpg":"Tesseract",
                              "jpeg":"Tesseract"}.get(ext, "plaintext"),
            },
            "preview": text[:400].strip(),
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "extraction", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 2: Chunking ─────────────────────────────────────
    yield _sse("stage_start", {"stage": "chunking", "label": "Chunking",
                                "description": "Splitting text into overlapping chunks (chunk_size=1000 chars, overlap=300) using RecursiveCharacterTextSplitter"})
    t0 = time.perf_counter()
    try:
        from backend.chunking import chunk_text, chunk_text_with_pages, chunk_excel_text
        if page_info:
            raw_chunks = chunk_text_with_pages(text, page_info)
            chunk_texts = [c[0] for c in raw_chunks]
            chunk_pages = [c[1] for c in raw_chunks]
        elif ext in ("xlsx", "xls"):
            chunk_texts = chunk_excel_text(text)
            chunk_pages = [None] * len(chunk_texts)
        else:
            chunk_texts = chunk_text(text)
            chunk_pages = [None] * len(chunk_texts)

        chunk_preview = [
            {"index": i, "text": c[:120], "length": len(c), "page": chunk_pages[i]}
            for i, c in enumerate(chunk_texts[:5])
        ]
        yield _sse("stage_done", {
            "stage": "chunking", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "total_chunks": len(chunk_texts),
                "avg_chunk_chars": round(sum(len(c) for c in chunk_texts) / max(len(chunk_texts),1)),
                "strategy": "page-aware" if page_info else ("excel-row-batch" if ext in ("xlsx","xls") else "recursive"),
            },
            "chunks": chunk_preview,
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "chunking", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 3: Embedding (doc chunks) ───────────────────────
    yield _sse("stage_start", {
        "stage": "embedding",
        "label": "Document Embedding",
        "description": "Converting each chunk to a 384-dim dense vector using BAAI/bge-small-en-v1.5 sentence-transformer",
    })
    t0 = time.perf_counter()
    try:
        from backend.embeddings import embed_texts, embed_text
        chunk_embeddings = embed_texts(chunk_texts)
        # Show first 16 dims of first 5 chunks as preview
        emb_preview = [
            {"index": i, "dims_preview": chunk_embeddings[i][:12],
             "magnitude": round(math.sqrt(sum(x*x for x in chunk_embeddings[i])), 3)}
            for i in range(min(3, len(chunk_embeddings)))
        ]
        yield _sse("stage_done", {
            "stage": "embedding", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "model": "BAAI/bge-small-en-v1.5",
                "dimensions": 384,
                "chunks_embedded": len(chunk_embeddings),
            },
            "embedding_preview": emb_preview,
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "embedding", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 4: Query Embedding ──────────────────────────────
    yield _sse("stage_start", {
        "stage": "query_embedding",
        "label": "Query Embedding",
        "description": "Embedding the user question with the same model + query prefix for asymmetric retrieval",
    })
    t0 = time.perf_counter()
    try:
        query_prefix = "Represent this sentence for searching relevant passages: "
        q_embedded = embed_text(query_prefix + question.strip())
        yield _sse("stage_done", {
            "stage": "query_embedding", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "dimensions": len(q_embedded),
                "magnitude": round(math.sqrt(sum(x*x for x in q_embedded)), 3),
            },
            "dims_preview": q_embedded[:12],
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "query_embedding", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 5: Vector Search ────────────────────────────────
    yield _sse("stage_start", {
        "stage": "vector_search",
        "label": "Vector Search",
        "description": "Computing cosine similarity between query vector and all chunk vectors (in-memory, isolated from production ChromaDB)",
    })
    t0 = time.perf_counter()
    CANDIDATE_K = min(len(chunk_texts), 30)
    try:
        # In-memory cosine similarity (isolated — does not touch ChromaDB)
        sims = [(i, _cosine(q_embedded, chunk_embeddings[i])) for i in range(len(chunk_texts))]
        sims.sort(key=lambda x: x[1], reverse=True)
        vector_ranked_idx = [i for i, _ in sims[:CANDIDATE_K]]
        vector_results = [
            {"rank": r+1, "chunk_index": i,
             "score": round(sims[r][1], 4),
             "text_preview": chunk_texts[i][:200],
             "page": chunk_pages[i]}
            for r, (i, _) in enumerate(sims[:CANDIDATE_K])
        ]
        yield _sse("stage_done", {
            "stage": "vector_search", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "candidates": CANDIDATE_K,
                "top_score": round(sims[0][1], 3) if sims else 0,
            },
            "results": vector_results[:5],
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "vector_search", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 6: BM25 Search ──────────────────────────────────
    yield _sse("stage_start", {
        "stage": "bm25_search",
        "label": "BM25 Keyword Search",
        "description": "Keyword-based retrieval using BM25 (k1=1.5, b=0.75) — catches exact term matches that vector search may miss",
    })
    t0 = time.perf_counter()
    try:
        bm25 = _BM25()
        bm25.index(chunk_texts)
        bm25_hits = bm25.search(question, k=CANDIDATE_K)
        bm25_ranked_idx = [idx for _, _, idx in bm25_hits]
        bm25_results = [
            {"rank": r+1, "chunk_index": idx,
             "score": round(score, 4),
             "text_preview": chunk_texts[idx][:200],
             "page": chunk_pages[idx]}
            for r, (score, _, idx) in enumerate(bm25_hits[:15])
        ]
        yield _sse("stage_done", {
            "stage": "bm25_search", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "hits": len(bm25_hits),
                "vocab_size": len(bm25.df),
            },
            "results": bm25_results[:5],
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "bm25_search", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 7: RRF Fusion ───────────────────────────────────
    yield _sse("stage_start", {
        "stage": "rrf",
        "label": "RRF Fusion",
        "description": "Reciprocal Rank Fusion — merges vector and BM25 ranked lists. Score = Σ 1/(k+rank). k=60 by convention.",
    })
    t0 = time.perf_counter()
    try:
        rrf_scores = _rrf(vector_ranked_idx, bm25_ranked_idx, len(chunk_texts))
        rrf_results = []
        for rank, (idx, score) in enumerate(rrf_scores[:CANDIDATE_K]):
            vec_rank = next((r+1 for r, i in enumerate(vector_ranked_idx) if i==idx), None)
            bm_rank  = next((r+1 for r, i in enumerate(bm25_ranked_idx) if i==idx), None)
            rrf_results.append({
                "rank": rank+1, "chunk_index": idx,
                "rrf_score": round(score, 6),
                "vector_rank": vec_rank,
                "bm25_rank": bm_rank,
                "in_both": vec_rank is not None and bm_rank is not None,
                "text_preview": chunk_texts[idx][:200],
                "page": chunk_pages[idx],
            })
        merged_idx = [idx for idx, _ in rrf_scores[:CANDIDATE_K]]
        yield _sse("stage_done", {
            "stage": "rrf", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "merged": len(rrf_scores),
                "in_both": sum(1 for r in rrf_results if r["in_both"]),
            },
            "results": rrf_results[:5],
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "rrf", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Stage 8: Reranking ────────────────────────────────────
    yield _sse("stage_start", {
        "stage": "rerank",
        "label": "Reranking",
        "description": "Cross-encoder reranking via Cohere Rerank API (falls back to RRF order if COHERE_API_KEY not set)",
    })
    t0 = time.perf_counter()
    FINAL_K = min(8, len(merged_idx))
    rerank_used = False
    rerank_scores = None
    try:
        from backend.cohere_reranker import rerank, _get_client
        candidate_texts = [chunk_texts[i] for i in merged_idx[:CANDIDATE_K]]
        candidate_pages = [chunk_pages[i] for i in merged_idx[:CANDIDATE_K]]
        candidate_orig_idx = list(merged_idx[:CANDIDATE_K])
        dummy_metas = [{"source": "pg_explorer", "idx": i} for i in candidate_orig_idx]

        client = _get_client()
        if client:
            reranked_texts, reranked_metas = rerank(question, candidate_texts, dummy_metas, top_k=FINAL_K)
            rerank_used = True
            final_chunks = reranked_texts
            final_pages  = [m.get("idx") for m in reranked_metas]
            rerank_results = [
                {"rank": r+1, "text_preview": t[:200],
                 "cohere_reranked": True}
                for r, t in enumerate(reranked_texts)
            ]
        else:
            final_chunks = [chunk_texts[i] for i in merged_idx[:FINAL_K]]
            final_pages  = [chunk_pages[i] for i in merged_idx[:FINAL_K]]
            rerank_results = [
                {"rank": r+1, "text_preview": chunk_texts[merged_idx[r]][:200],
                 "cohere_reranked": False}
                for r in range(FINAL_K)
            ]

        yield _sse("stage_done", {
            "stage": "rerank", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "method": "Cohere" if rerank_used else "RRF order",
                "top_k": FINAL_K,
            },
            "results": rerank_results,
        })
    except Exception as e:
        # Graceful fallback
        final_chunks = [chunk_texts[i] for i in merged_idx[:FINAL_K]]
        final_pages  = [chunk_pages[i] for i in merged_idx[:FINAL_K]]
        yield _sse("stage_done", {"stage": "rerank", "status": "done",
                                   "meta": {"method": "RRF fallback", "cohere_enabled": False},
                                   "results": [{"rank": r+1, "text_preview": t[:200]}
                                               for r, t in enumerate(final_chunks)]})

    # ── Stage 9: Context Assembly ─────────────────────────────
    yield _sse("stage_start", {
        "stage": "context",
        "label": "Context Assembly",
        "description": "Joining selected chunks into the context window sent to the LLM. Trimmed to 5000 chars.",
    })
    context_raw = "\n\n".join(final_chunks)
    MAX_CTX = 5000
    context = context_raw[:MAX_CTX]
    trimmed = len(context_raw) > MAX_CTX
    yield _sse("stage_done", {
        "stage": "context", "status": "done",
        "meta": {
            "chunks_used": len(final_chunks),
            "chars_sent": len(context),
            "trimmed": trimmed,
        },
        "context": context[:800],
    })

    # ── Stage 10: LLM Prompt ──────────────────────────────────
    from backend.llm import SYSTEM_PROMPT
    yield _sse("stage_start", {
        "stage": "llm_prompt",
        "label": "LLM Prompt",
        "description": "Building the messages array: system prompt + context + question",
    })
    yield _sse("stage_done", {
        "stage": "llm_prompt", "status": "done",
        "meta": {
            "model": "openai/gpt-oss-120b (Groq)",
            "temperature": 0.2,
            "context_chars": len(context),
        },
    })

    # ── Stage 11: LLM Generation ──────────────────────────────
    yield _sse("stage_start", {
        "stage": "llm",
        "label": "LLM Generation",
        "description": "Streaming answer from Groq (openai/gpt-oss-120b). Tokens arrive one-by-one.",
    })
    t0 = time.perf_counter()
    full_answer = ""
    token_usage = {}
    try:
        from backend.llm import generate_answer_stream
        for item_type, item_data in generate_answer_stream(context, question):
            if item_type == "chunk":
                full_answer += item_data
                yield _sse("llm_chunk", {"delta": item_data, "full": full_answer})
            elif item_type == "usage":
                token_usage = item_data or {}

        yield _sse("stage_done", {
            "stage": "llm", "status": "done",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "meta": {
                "tokens": token_usage.get("total_tokens", 0),
                "answer_words": len(full_answer.split()),
            },
            "answer": full_answer,
        })
    except Exception as e:
        yield _sse("stage_done", {"stage": "llm", "status": "error", "message": str(e)})
        yield _sse("done", {"status": "error"})
        return

    # ── Done ──────────────────────────────────────────────────
    yield _sse("done", {
        "status": "success",
        "total_chunks": len(chunk_texts),
        "final_chunks_used": len(final_chunks),
        "answer": full_answer,
        "token_usage": token_usage,
    })
