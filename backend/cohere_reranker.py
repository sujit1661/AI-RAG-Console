"""
Cohere Rerank API — cloud-based reranker, no local model download.
Free tier: 1000 calls/month.
Set COHERE_API_KEY in .env to enable. Falls back to RRF order if not set.
"""
import os
import logging
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            logger.debug("COHERE_API_KEY not set — reranking disabled")
            return None
        try:
            import cohere
            _client = cohere.ClientV2(api_key)  # V2 is the current SDK
            logger.info("Cohere reranker initialized")
        except ImportError:
            logger.warning("cohere package not installed. Run: pip install cohere")
            return None
    return _client


def rerank(query: str, chunks: List[str], metadatas: List[dict],
           top_k: int = 5) -> Tuple[List[str], List[dict]]:
    """
    Rerank chunks using Cohere Rerank API.
    Falls back to original order if API key not set or call fails.
    """
    if not chunks:
        return chunks, metadatas

    client = _get_client()
    if client is None:
        logger.debug("Cohere reranker not configured, using RRF order")
        return chunks[:top_k], metadatas[:top_k]

    try:
        response = client.rerank(
            model="rerank-english-v3.0",
            query=query,
            documents=chunks,
            top_n=top_k,
        )
        ranked_chunks = [chunks[r.index] for r in response.results]
        ranked_metas  = [metadatas[r.index] for r in response.results]
        logger.info(f"Cohere reranked {len(chunks)} → {top_k} chunks, "
                    f"top score: {response.results[0].relevance_score:.3f}")
        return ranked_chunks, ranked_metas
    except Exception as e:
        logger.warning(f"Cohere rerank failed (using RRF order): {e}")
        return chunks[:top_k], metadatas[:top_k]
