"""
Semantic chunking: splits text where meaning changes significantly,
rather than at fixed character counts.
Uses sentence embeddings to detect topic boundaries.
"""
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Similarity threshold — lower = more splits (more chunks)
SPLIT_THRESHOLD = 0.75
# Min / max chars per chunk
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 1500


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_chunk(text: str) -> List[str]:
    """
    Split text into semantically coherent chunks.
    Falls back to regular splitting if embedding model unavailable.
    """
    try:
        from backend.embeddings import embed_texts
    except Exception:
        # Fallback to regular chunking
        from backend.chunking import chunk_text
        return chunk_text(text)

    sentences = _split_sentences(text)
    if len(sentences) <= 3:
        return [text] if text.strip() else []

    try:
        embeddings = embed_texts(sentences)
    except Exception as e:
        logger.warning(f"Semantic chunking embedding failed, using regular: {e}")
        from backend.chunking import chunk_text
        return chunk_text(text)

    # Find split points where similarity between adjacent sentences drops
    split_points = set()
    for i in range(len(sentences) - 1):
        sim = _cosine_sim(embeddings[i], embeddings[i + 1])
        if sim < SPLIT_THRESHOLD:
            split_points.add(i + 1)

    # Build chunks from split points
    chunks = []
    current_sentences = []
    current_len = 0

    for i, sentence in enumerate(sentences):
        if i in split_points and current_len >= MIN_CHUNK_CHARS:
            chunk = " ".join(current_sentences).strip()
            if chunk:
                chunks.append(chunk)
            current_sentences = [sentence]
            current_len = len(sentence)
        else:
            current_sentences.append(sentence)
            current_len += len(sentence)

            # Force split if chunk is getting too long
            if current_len >= MAX_CHUNK_CHARS:
                chunk = " ".join(current_sentences).strip()
                if chunk:
                    chunks.append(chunk)
                current_sentences = []
                current_len = 0

    # Add remaining sentences
    if current_sentences:
        chunk = " ".join(current_sentences).strip()
        if chunk:
            chunks.append(chunk)

    logger.info(f"Semantic chunking: {len(sentences)} sentences → {len(chunks)} chunks")
    return chunks if chunks else [text]


def semantic_chunk_with_pages(text: str, page_info: List[Tuple]) -> List[Tuple[str, int]]:
    """
    Semantic chunking with page number tracking.
    Returns list of (chunk_text, page_num) tuples.
    """
    chunks = semantic_chunk(text)
    result = []

    for chunk in chunks:
        chunk_start = text.find(chunk[:50])  # Find by first 50 chars
        chunk_mid = chunk_start + len(chunk) // 2 if chunk_start != -1 else 0

        page_num = None
        for start_pos, end_pos, pg_num in page_info:
            if start_pos <= chunk_mid < end_pos:
                page_num = pg_num
                break

        if page_num is None and page_info:
            page_num = page_info[0][2]

        result.append((chunk, page_num))

    return result
