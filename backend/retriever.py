"""
Retriever: Supabase pgvector (primary) + ChromaDB (local fallback).
Hybrid search: vector + BM25 with Reciprocal Rank Fusion.
Reranking: cross-encoder after retrieval.
"""
import re
import logging
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ChromaDB (local fallback)
# ─────────────────────────────────────────────
_chroma_client = chromadb.PersistentClient(path="./chroma_db")
_chroma_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-small-en-v1.5"
)

def _normalize(name: str) -> str:
    n = re.sub(r'[^a-zA-Z0-9._-]', '', name)
    if n and not n[0].isalnum(): n = 'w' + n
    if n and not n[-1].isalnum(): n = n + '1'
    if len(n) < 3: n = n.ljust(3, '0')
    return n[:512]

def _col_name(username: str, workspace_slug: str) -> str:
    return _normalize(f"{username}__{workspace_slug}")

def _get_chroma_collection(workspace_slug: str, username: str):
    return _chroma_client.get_or_create_collection(
        name=_col_name(username, workspace_slug),
        embedding_function=_chroma_ef
    )

# ─────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────

def _get_supabase():
    try:
        from backend.supabase_config import get_supabase
        return get_supabase()
    except Exception:
        return None

def _supabase_add(workspace_slug: str, username: str, chunk_texts: list,
                  ids: list, metadatas: list, embeddings: list) -> bool:
    sb = _get_supabase()
    if not sb:
        return False
    try:
        rows = [{
            "id": cid,
            "workspace_slug": workspace_slug,
            "username": username,
            "filename": meta.get("source", ""),
            "chunk_text": text,
            "embedding": emb,
            "page_num": meta.get("page"),
        } for cid, text, meta, emb in zip(ids, chunk_texts, metadatas, embeddings)]
        for i in range(0, len(rows), 100):
            sb.table("embeddings").upsert(rows[i:i + 100]).execute()
        return True
    except Exception as e:
        logger.warning(f"Supabase embedding insert failed (non-fatal): {e}")
        return False

def _supabase_vector_search(workspace_slug: str, username: str,
                             query_embedding: list, k: int = 20):
    sb = _get_supabase()
    if not sb:
        return None
    try:
        result = sb.rpc("match_embeddings", {
            "query_embedding": query_embedding,
            "match_workspace": workspace_slug,
            "match_username": username,
            "match_count": k
        }).execute()
        if result.data:
            return (
                [r["chunk_text"] for r in result.data],
                [{"source": r["filename"], "page": r.get("page_num")} for r in result.data]
            )
        return [], []
    except Exception as e:
        logger.warning(f"Supabase vector search failed, falling back to ChromaDB: {e}")
        return None

def _supabase_delete_file(workspace_slug: str, username: str, filename: str):
    sb = _get_supabase()
    if not sb:
        return
    try:
        sb.table("embeddings").delete()\
            .eq("workspace_slug", workspace_slug)\
            .eq("username", username)\
            .eq("filename", filename).execute()
    except Exception as e:
        logger.warning(f"Supabase embedding delete failed (non-fatal): {e}")

def _supabase_delete_workspace(workspace_slug: str, username: str):
    sb = _get_supabase()
    if not sb:
        return
    try:
        sb.table("embeddings").delete()\
            .eq("workspace_slug", workspace_slug)\
            .eq("username", username).execute()
    except Exception as e:
        logger.warning(f"Supabase workspace embedding delete failed (non-fatal): {e}")

# ─────────────────────────────────────────────
# RRF merge
# ─────────────────────────────────────────────

def _rrf_merge(vector_results: List[Tuple[str, dict]],
               bm25_results: List[Tuple[str, dict]],
               k: int = 60) -> List[Tuple[str, dict]]:
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Tuple[str, dict]] = {}
    for rank, (doc, meta) in enumerate(vector_results):
        key = doc[:100]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        doc_map[key] = (doc, meta)
    for rank, (doc, meta) in enumerate(bm25_results):
        key = doc[:100]
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        doc_map[key] = (doc, meta)
    return [doc_map[key] for key in sorted(scores, key=lambda x: scores[x], reverse=True)]

# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def add_documents(workspace_slug: str, chunks, filename: str,
                  username: str = "", page_numbers=None):
    """Add chunks to Supabase pgvector + ChromaDB + BM25."""
    if not chunks:
        return

    if isinstance(chunks[0], tuple):
        chunk_texts = [c[0] for c in chunks]
        page_nums   = [c[1] for c in chunks]
    else:
        chunk_texts = list(chunks)
        page_nums   = page_numbers if page_numbers else [None] * len(chunks)

    ids = [f"{filename}_{i}_{hash(t) % 1000000}" for i, t in enumerate(chunk_texts)]
    metadatas = [{"source": filename, **({"page": p} if p is not None else {})} for p in page_nums]

    # Supabase pgvector
    try:
        from backend.embeddings import embed_texts
        embeddings = embed_texts(chunk_texts)
        if _supabase_add(workspace_slug, username, chunk_texts, ids, metadatas, embeddings):
            logger.info(f"Stored {len(chunk_texts)} chunks in Supabase [{username}/{workspace_slug}]")
    except Exception as e:
        logger.warning(f"Supabase write failed (non-fatal): {e}")

    # ChromaDB (local backup)
    try:
        col = _get_chroma_collection(workspace_slug, username)
        col.add(documents=chunk_texts, metadatas=metadatas, ids=ids)
        logger.info(f"Stored {len(chunk_texts)} chunks in ChromaDB [{username}/{workspace_slug}]")
    except Exception as e:
        logger.error(f"ChromaDB write failed [{username}/{workspace_slug}]: {e}")
        raise

    # BM25
    try:
        from backend.bm25_index import index_chunks
        index_chunks(workspace_slug, username, chunk_texts, metadatas)
    except Exception as e:
        logger.warning(f"BM25 indexing failed (non-fatal): {e}")


def retrieve(workspace_slug: str, query: str, username: str = "",
             k: int = 4, expand_queries: bool = False) -> Tuple[List[str], List[dict]]:
    """
    Hybrid retrieval: vector search + BM25 → RRF merge → rerank → top k.
    """
    if not query or not query.strip():
        return [], []

    CANDIDATE_K = 30  # Fetch more candidates for better coverage on filter queries
    query_prefix = "Represent this sentence for searching relevant passages: "
    q_str = query_prefix + query.strip()

    # ── Vector search ─────────────────────────────────────────
    all_vector: List[Tuple[str, dict]] = []
    try:
        from backend.embeddings import embed_text
        q_emb = embed_text(q_str)
        result = _supabase_vector_search(workspace_slug, username, q_emb, CANDIDATE_K)
        if result is not None:
            all_vector = list(zip(*result)) if result[0] else []
        else:
            raise Exception("Supabase unavailable")
    except Exception:
        # ChromaDB fallback
        try:
            col = _get_chroma_collection(workspace_slug, username)
            results = col.query(query_texts=[q_str], n_results=CANDIDATE_K)
            if results and results.get("documents") and results["documents"]:
                docs  = results["documents"][0]
                metas = results.get("metadatas", [[]])[0] or [{}] * len(docs)
                all_vector = list(zip(docs, metas))
        except Exception as e:
            logger.warning(f"ChromaDB search error: {e}")

    # ── BM25 search ───────────────────────────────────────────
    all_bm25: List[Tuple[str, dict]] = []
    try:
        from backend.bm25_index import bm25_search
        all_bm25 = [(doc, meta) for _, doc, meta in bm25_search(workspace_slug, username, query, CANDIDATE_K)]
    except Exception as e:
        logger.warning(f"BM25 search failed (non-fatal): {e}")

    if not all_vector and not all_bm25:
        return [], []

    # ── RRF merge ─────────────────────────────────────────────
    def dedup(items):
        seen, out = set(), []
        for doc, meta in items:
            key = doc[:100]
            if key not in seen:
                seen.add(key)
                out.append((doc, meta))
        return out

    merged = _rrf_merge(dedup(all_vector), dedup(all_bm25))[:CANDIDATE_K]
    docs  = [d for d, _ in merged]
    metas = [m for _, m in merged]
<<<<<<< HEAD

    # ── Rerank (disabled — BGE reranker is 1.1GB, too heavy for local use) ──
    # Hybrid search + RRF already gives good ranking without a cross-encoder
    docs, metas = docs[:k], metas[:k]

    logger.info(f"Retrieved {len(docs)} chunks [{username}/{workspace_slug}]")
    return docs, metas


def delete_from_collection(workspace_slug: str, filename: str, username: str = ""):
    _supabase_delete_file(workspace_slug, username, filename)
    try:
        _get_chroma_collection(workspace_slug, username).delete(where={"source": filename})
    except Exception as e:
=======

    # ── Rerank (Cohere if configured, else RRF order) ─────────
    try:
        from backend.cohere_reranker import rerank
        docs, metas = rerank(query, docs, metas, top_k=k)
    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
        docs, metas = docs[:k], metas[:k]

    logger.info(f"Retrieved {len(docs)} chunks [{username}/{workspace_slug}]")
    return docs, metas


def delete_from_collection(workspace_slug: str, filename: str, username: str = ""):
    _supabase_delete_file(workspace_slug, username, filename)
    try:
        _get_chroma_collection(workspace_slug, username).delete(where={"source": filename})
    except Exception as e:
>>>>>>> 0f84573 (feat: production RAG improvements)
        logger.warning(f"ChromaDB file delete failed: {e}")
    try:
        from backend.bm25_index import delete_file_from_index
        delete_file_from_index(workspace_slug, username, filename)
    except Exception:
        pass


def delete_workspace(workspace_slug: str, username: str = ""):
    _supabase_delete_workspace(workspace_slug, username)
    try:
        _chroma_client.delete_collection(_col_name(username, workspace_slug))
    except Exception as e:
        logger.warning(f"ChromaDB workspace delete failed: {e}")
    try:
        from backend.bm25_index import delete_workspace_index
        delete_workspace_index(workspace_slug, username)
    except Exception:
        pass


def list_workspaces():
    return [c.name for c in _chroma_client.list_collections()]
