"""
BM25 keyword search index — persisted to disk, rebuilt from ChromaDB on startup.
Combined with vector search for hybrid retrieval (RRF fusion).
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

# In-memory cache: {username__workspace_slug: BM25Index}
_indexes: Dict[str, "BM25Index"] = {}


def _tokenize(text: str) -> List[str]:
    return re.findall(r'\b\w+\b', text.lower())


class BM25Index:
    """Minimal BM25 — no external dependencies, pickle-serializable."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: List[str] = []
        self.metadatas: List[dict] = []
        self.tokenized: List[List[str]] = []
        self.df: Dict[str, int] = defaultdict(int)
        self.avgdl: float = 0.0

    def add(self, texts: List[str], metadatas: List[dict]):
        for text, meta in zip(texts, metadatas):
            tokens = _tokenize(text)
            self.docs.append(text)
            self.metadatas.append(meta)
            self.tokenized.append(tokens)
            for term in set(tokens):
                self.df[term] += 1
        total = sum(len(t) for t in self.tokenized)
        self.avgdl = total / len(self.tokenized) if self.tokenized else 1.0

    def search(self, query: str, k: int = 20) -> List[Tuple[float, str, dict]]:
        if not self.docs:
            return []
        query_terms = _tokenize(query)
        N = len(self.docs)
        scores = []
        for i, tokens in enumerate(self.tokenized):
            tf_map: Dict[str, int] = defaultdict(int)
            for t in tokens:
                tf_map[t] += 1
            score = 0.0
            dl = len(tokens)
            for term in query_terms:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                df = self.df.get(term, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
                score += idf * tf_norm
            if score > 0:
                scores.append((score, self.docs[i], self.metadatas[i]))
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[:k]

    def delete_by_source(self, filename: str):
        keep = [(d, m, t) for d, m, t in zip(self.docs, self.metadatas, self.tokenized)
                if m.get("source") != filename]
        if keep:
            self.docs, self.metadatas, self.tokenized = map(list, zip(*keep))
        else:
            self.docs, self.metadatas, self.tokenized = [], [], []
        self.df = defaultdict(int)
        for tokens in self.tokenized:
            for term in set(tokens):
                self.df[term] += 1
        total = sum(len(t) for t in self.tokenized)
        self.avgdl = total / len(self.tokenized) if self.tokenized else 1.0


# ─────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────

def _persist_path(key: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', key)
    return os.path.join(BM25_PERSIST_DIR, f"{safe}.pkl")

def _save(key: str, index: BM25Index):
    try:
        with open(_persist_path(key), "wb") as f:
            pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.warning(f"BM25 save failed for {key}: {e}")

def _load(key: str) -> "BM25Index | None":
    path = _persist_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"BM25 load failed for {key}: {e}")
        return None

def _key(username: str, workspace_slug: str) -> str:
    return f"{username}__{workspace_slug}"

def _get_or_load(key: str) -> BM25Index:
    """Get from memory cache, or load from disk, or create new."""
    if key not in _indexes:
        loaded = _load(key)
        _indexes[key] = loaded if loaded is not None else BM25Index()
        if loaded:
            logger.info(f"BM25 loaded from disk: {key} ({len(loaded.docs)} docs)")
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
    path = _persist_path(key)
    if os.path.exists(path):
        os.remove(path)


# ─────────────────────────────────────────────
# Startup rebuild from ChromaDB
# ─────────────────────────────────────────────

def rebuild_from_chromadb():
    """
    On server startup, rebuild any BM25 indexes that don't have a persisted file.
    Reads from ChromaDB so hybrid search works immediately after restart
    even if the pickle files were lost.
    """
    try:
        import chromadb
        client = chromadb.PersistentClient(path="./chroma_db")
        collections = client.list_collections()

        rebuilt = 0
        for col in collections:
            key = col.name  # format: username__workspace_slug
            persist_file = _persist_path(key)

            # Skip if already persisted
            if os.path.exists(persist_file):
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
                logger.warning(f"BM25 rebuild failed for {col.name}: {e}")

        if rebuilt:
            logger.info(f"BM25 startup rebuild complete: {rebuilt} indexes rebuilt")
        else:
            logger.info("BM25 startup: all indexes already persisted")

    except Exception as e:
        logger.warning(f"BM25 startup rebuild failed (non-fatal): {e}")
