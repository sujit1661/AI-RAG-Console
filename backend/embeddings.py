"""
Embedding generation using sentence-transformers.
Independent of ChromaDB so we can use it with Supabase pgvector.
"""
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

# Load model once at module import
_model = None

def get_embedding_model():
    """Lazy-load the embedding model."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: BAAI/bge-small-en-v1.5")
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _model

def embed_text(text: str) -> list:
    """
    Generate embedding for a single text string.
    Returns a list of 384 floats.
    """
    model = get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()

def embed_texts(texts: list) -> list:
    """
    Generate embeddings for multiple texts (batch).
    Returns list of embeddings (each is a list of 384 floats).
    """
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [emb.tolist() for emb in embeddings]
