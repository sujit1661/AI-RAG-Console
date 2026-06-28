"""
BM25 keyword search index — persisted to Supabase Storage (primary) or disk (fallback).
Combined with vector search for hybrid retrieval (RRF fusion).

Performance optimisations (backward-compatible):
  - Per-document TF maps stored at index time (no re-tokenisation on search).
  - Inverted index: search only visits documents that contain at least one
    query term instead of scanning every document.
  - Both structures are pickled alongside the existing fields so old pickles
    (missing the new attrs) are transparently upgraded on first load.
"""
import logging
import math
import os
import pickle
import re
from collections import defaultdict
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

BM25_PERSIST_DIR = "./bm25_index"
os.makedirs(BM25_PERSIST_DIR, exist_ok=True)

# Supabase Storage bucket for BM25 indexes
BM25_STORAGE_BUCKET = "bm25-indexes"

# In-memory cache: {username__workspace_slug: BM25Index}
_indexes: Dict[str, "BM25Index"] = {}


def _tokenize(text: str) -> List[str]:
    return re.findall(r'\b\w+\b', text.lower())


class BM25Index:
    """
    BM25 with two performance improvements over the baseline:

    1. Cached TF maps  — ``self.tf_maps[i]`` holds the pre-computed
       {term: count} dict for document i so ``search()`` never re-tokenises.

    2. Inverted index  — ``self.inverted[term]`` is a set of document indices
       that contain that term.  ``search()`` unions the candidate sets for all
       query terms and only scores those documents (~O(df) instead of O(N)).

    Backward compatibility: ``__setstate__`` rebuilds the new structures from
    ``self.tokenized`` when loading a pickle that pre-dates this version, so
    existing saved indexes continue to work without re-indexing.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: List[str] = []
        self.metadatas: List[dict] = []
        self.tokenized: List[List[str]] = []          # kept for rebuild compat
        self.df: Dict[str, int] = defaultdict(int)
        self.avgdl: float = 0.0
        # ── new ──────────────────────────────────────────
        self.tf_maps: List[Dict[str, int]] = []       # per-doc term frequencies
        self.inverted: Dict[str, set] = defaultdict(set)  # term → {doc indices}

    # ------------------------------------------------------------------
    # Backward-compat deserialisation
    # ------------------------------------------------------------------
    def __setstate__(self, state: dict):
        self.__dict__.update(state)
        # Rebuild missing structures from tokenized list (old pickle)
        if not hasattr(self, "tf_maps") or len(self.tf_maps) != len(self.docs):
            self.tf_maps = []
            for tokens in self.tokenized:
                tf: Dict[str, int] = defaultdict(int)
                for t in tokens:
                    tf[t] += 1
                self.tf_maps.append(tf)
        if not hasattr(self, "inverted") or not self.inverted:
            self.inverted = defaultdict(set)
            for i, tokens in enumerate(self.tokenized):
                for term in set(tokens):
                    self.inverted[term].add(i)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def add(self, texts: List[str], metadatas: List[dict]):
        for text, meta in zip(texts, metadatas):
            tokens = _tokenize(text)
            idx = len(self.docs)

            # Build TF map for this document
            tf: Dict[str, int] = defaultdict(int)
            for t in tokens:
                tf[t] += 1

            self.docs.append(text)
            self.metadatas.append(meta)
            self.tokenized.append(tokens)
            self.tf_maps.append(tf)

            # Update DF and inverted index
            for term in set(tokens):
                self.df[term] += 1
                self.inverted[term].add(idx)

        total = sum(len(t) for t in self.tokenized)
        self.avgdl = total / len(self.tokenized) if self.tokenized else 1.0

    # ------------------------------------------------------------------
    # Search  (inverted-index candidate selection + cached TF scoring)
    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 20) -> List[Tuple[float, str, dict]]:
        if not self.docs:
            return []

        query_terms = _tokenize(query)
        if not query_terms:
            return []

        N = len(self.docs)

        # Candidate set: only docs that share at least one token with the query
        candidates: set = set()
        for term in query_terms:
            candidates |= self.inverted.get(term, set())

        if not candidates:
            return []

        scores: List[Tuple[float, int]] = []
        for i in candidates:
            tf_map = self.tf_maps[i]
            dl = len(self.tokenized[i])
            score = 0.0
            for term in query_terms:
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                df = self.df.get(term, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
                score += idf * tf_norm
            if score > 0:
                scores.append((score, i))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [(s, self.docs[i], self.metadatas[i]) for s, i in scores[:k]]

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def delete_by_source(self, filename: str):
        keep_idx = [i for i, m in enumerate(self.metadatas) if m.get("source") != filename]

        if not keep_idx:
            self.docs, self.metadatas, self.tokenized = [], [], []
            self.tf_maps = []
            self.df = defaultdict(int)
            self.inverted = defaultdict(set)
            self.avgdl = 0.0
            return

        self.docs      = [self.docs[i]      for i in keep_idx]
        self.metadatas = [self.metadatas[i] for i in keep_idx]
        self.tokenized = [self.tokenized[i] for i in keep_idx]
        self.tf_maps   = [self.tf_maps[i]   for i in keep_idx]

        # Rebuild DF and inverted from scratch (deletion is infrequent)
        self.df = defaultdict(int)
        self.inverted = defaultdict(set)
        for new_i, tokens in enumerate(self.tokenized):
            for term in set(tokens):
                self.df[term] += 1
                self.inverted[term].add(new_i)

        total = sum(len(t) for t in self.tokenized)
        self.avgdl = total / len(self.tokenized) if self.tokenized else 1.0


# ─────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────

def _persist_path(key: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', key)
    return os.path.join(BM25_PERSIST_DIR, f"{safe}.pkl")

def _storage_path(key: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', key)
    return f"indexes/{safe}.pkl"

def _save_to_supabase(key: str, data: bytes) -> bool:
    """Upload pickled BM25 index to Supabase Storage."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        path = _storage_path(key)
        sb.storage.from_(BM25_STORAGE_BUCKET).upload(
            path=path,
            file=data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"}
        )
        return True
    except Exception as e:
        logger.warning(f"BM25 Supabase save failed for {key}: {e}")
        return False

def _load_from_supabase(key: str) -> "BM25Index | None":
    """Download and unpickle BM25 index from Supabase Storage."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        path = _storage_path(key)
        data = sb.storage.from_(BM25_STORAGE_BUCKET).download(path)
        if data:
            return pickle.loads(data)
    except Exception as e:
        err = str(e).lower()
        # 400/404 = bucket doesn't exist or object not found — not an error worth warning about
        if any(x in err for x in ("400", "404", "not found", "does not exist", "no such")):
            logger.debug(f"BM25 not in Supabase Storage for {key} (will use local/rebuild)")
        else:
            logger.warning(f"BM25 Supabase load failed for {key}: {e}")
    return None

def _delete_from_supabase(key: str):
    """Remove BM25 index from Supabase Storage."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()
        path = _storage_path(key)
        sb.storage.from_(BM25_STORAGE_BUCKET).remove([path])
    except Exception as e:
        logger.debug(f"BM25 Supabase delete failed for {key}: {e}")

def _save(key: str, index: BM25Index):
    """Save to Supabase Storage (primary) with local disk as fallback."""
    data = pickle.dumps(index, protocol=pickle.HIGHEST_PROTOCOL)
    if not _save_to_supabase(key, data):
        # fallback: local disk
        try:
            with open(_persist_path(key), "wb") as f:
                f.write(data)
        except Exception as e:
            logger.warning(f"BM25 local save also failed for {key}: {e}")

def _load(key: str) -> "BM25Index | None":
    """Load from Supabase Storage first, then fall back to local disk."""
    idx = _load_from_supabase(key)
    if idx is not None:
        return idx
    # fallback: local disk
    path = _persist_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"BM25 local load failed for {key}: {e}")
        return None

def _key(username: str, workspace_slug: str) -> str:
    return f"{username}__{workspace_slug}"

def _get_or_load(key: str) -> BM25Index:
    """Get from memory cache, or load from Supabase/disk, or create new."""
    if key not in _indexes:
        loaded = _load(key)
        _indexes[key] = loaded if loaded is not None else BM25Index()
        if loaded:
            logger.info(f"BM25 loaded: {key} ({len(loaded.docs)} docs)")
    return _indexes[key]

# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def index_chunks(workspace_slug: str, username: str,
                 texts: List[str], metadatas: List[dict]):
    """Add chunks to the BM25 index and persist to disk."""
    key = _key(username, workspace_slug)
    idx = _get_or_load(key)
    idx.add(texts, metadatas)
    _save(key, idx)
    logger.debug(f"BM25 indexed {len(texts)} chunks [{username}/{workspace_slug}]")


def bm25_search(workspace_slug: str, username: str,
                query: str, k: int = 20) -> List[Tuple[float, str, dict]]:
    """Search BM25 index (loads from disk if not in memory)."""
    key = _key(username, workspace_slug)
    return _get_or_load(key).search(query, k)


def delete_file_from_index(workspace_slug: str, username: str, filename: str):
    key = _key(username, workspace_slug)
    idx = _get_or_load(key)
    idx.delete_by_source(filename)
    _save(key, idx)


def delete_workspace_index(workspace_slug: str, username: str):
    key = _key(username, workspace_slug)
    _indexes.pop(key, None)
    _delete_from_supabase(key)
    # also clean up local disk if present
    path = _persist_path(key)
    if os.path.exists(path):
        os.remove(path)


# ─────────────────────────────────────────────
# Startup rebuild from Supabase embeddings table
# ─────────────────────────────────────────────

def rebuild_from_chromadb():
    """
    On startup, rebuild BM25 indexes that aren't already in Supabase Storage
    or local disk. Reads chunk text from the Supabase embeddings table.
    Falls back to ChromaDB if Supabase is unavailable.
    """
    _rebuild_from_supabase()


def _rebuild_from_supabase():
    """Rebuild missing BM25 indexes from the Supabase embeddings table."""
    try:
        from backend.supabase_config import get_supabase
        sb = get_supabase()

        # Fetch distinct (username, workspace_slug) pairs in pages to avoid row limits
        pairs = set()
        page_size = 1000
        offset = 0
        while True:
            res = sb.table("embeddings")\
                .select("username, workspace_slug")\
                .range(offset, offset + page_size - 1)\
                .execute()
            batch = res.data or []
            for r in batch:
                if r.get("username") and r.get("workspace_slug"):
                    pairs.add((r["username"], r["workspace_slug"]))
            if len(batch) < page_size:
                break
            offset += page_size

        if not pairs:
            logger.info("BM25 startup: no embeddings found in Supabase")
            return

        # Check which keys actually exist in Supabase Storage in one batch
        # by listing the bucket — avoids 400 per missing file
        existing_in_storage = set()
        try:
            files = sb.storage.from_(BM25_STORAGE_BUCKET).list("indexes")
            for f in (files or []):
                name = f.get("name", "")
                if name.endswith(".pkl"):
                    existing_in_storage.add(name[:-4])  # strip .pkl → key safe name
        except Exception as e:
            logger.debug(f"BM25 bucket list failed (non-fatal): {e}")

        rebuilt = 0
        for username, workspace_slug in pairs:
            key = _key(username, workspace_slug)
            safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', key)

            # Already in memory cache — skip
            if key in _indexes:
                continue

            # Check if pickle exists in Supabase Storage (no HTTP request needed)
            if safe_key in existing_in_storage:
                # Lazy-load on first search rather than at startup
                logger.debug(f"BM25 exists in Storage for {key} — will load on demand")
                continue

            # Check local disk fallback
            local_path = _persist_path(key)
            if os.path.exists(local_path):
                try:
                    with open(local_path, "rb") as f:
                        idx = pickle.load(f)
                    _indexes[key] = idx
                    logger.info(f"BM25 loaded from local disk: {key} ({len(idx.docs)} docs)")
                    continue
                except Exception:
                    pass

            # Not in storage or disk — rebuild from embeddings table
            try:
                texts, metas = [], []
                chunk_offset = 0
                while True:
                    chunks_res = sb.table("embeddings")\
                        .select("chunk_text, filename, page_num")\
                        .eq("username", username)\
                        .eq("workspace_slug", workspace_slug)\
                        .range(chunk_offset, chunk_offset + page_size - 1)\
                        .execute()
                    rows = chunks_res.data or []
                    for r in rows:
                        if r.get("chunk_text"):
                            texts.append(r["chunk_text"])
                            metas.append({
                                "source": r.get("filename", ""),
                                **({"page": r["page_num"]} if r.get("page_num") is not None else {})
                            })
                    if len(rows) < page_size:
                        break
                    chunk_offset += page_size

                if not texts:
                    continue

                idx = BM25Index()
                idx.add(texts, metas)
                _indexes[key] = idx
                _save(key, idx)
                rebuilt += 1
                logger.info(f"BM25 rebuilt from Supabase embeddings: {key} ({len(texts)} chunks)")
            except Exception as e:
                logger.warning(f"BM25 rebuild failed for {key}: {e}")

        if rebuilt:
            logger.info(f"BM25 startup rebuild complete: {rebuilt} indexes rebuilt")
        else:
            logger.info("BM25 startup: all indexes up to date")

    except Exception as e:
        logger.warning(f"BM25 Supabase rebuild failed, trying ChromaDB fallback: {e}")
        _rebuild_from_chromadb_fallback()


def _rebuild_from_chromadb_fallback():
    """Fallback: rebuild BM25 from local ChromaDB if Supabase is unavailable."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path="./chroma_db")
        collections = client.list_collections()

        rebuilt = 0
        for col in collections:
            key = col.name
            if key in _indexes:
                continue
            existing = _load(key)
            if existing is not None:
                _indexes[key] = existing
                continue
            try:
                collection = client.get_collection(col.name)
                result = collection.get(include=["documents", "metadatas"])
                docs = result.get("documents") or []
                metas = result.get("metadatas") or [{}] * len(docs)
                if not docs:
                    continue
                idx = BM25Index()
                idx.add(docs, metas)
                _indexes[key] = idx
                _save(key, idx)
                rebuilt += 1
                logger.info(f"BM25 rebuilt from ChromaDB: {key} ({len(docs)} docs)")
            except Exception as e:
                logger.warning(f"BM25 ChromaDB rebuild failed for {col.name}: {e}")

        if rebuilt:
            logger.info(f"BM25 ChromaDB fallback rebuild: {rebuilt} indexes")
    except Exception as e:
        logger.warning(f"BM25 ChromaDB fallback also failed (non-fatal): {e}")
