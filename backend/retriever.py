import chromadb
import re
from chromadb.utils import embedding_functions

# Persistent DB
client = chromadb.PersistentClient(path="./chroma_db")

# Embedding model
embedding_model = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-small-en-v1.5"
)

# Workspace Collection Manager
def normalize_collection_name(workspace_name: str) -> str:
    """
    Normalize workspace name to meet ChromaDB requirements.
    ChromaDB requires: 3-512 chars, [a-zA-Z0-9._-], start/end with [a-zA-Z0-9]
    """
    # Remove invalid characters and ensure it starts/ends with alphanumeric
    normalized = re.sub(r'[^a-zA-Z0-9._-]', '', workspace_name)
    
    # Ensure it starts with alphanumeric
    if normalized and not normalized[0].isalnum():
        normalized = 'w' + normalized
    
    # Ensure it ends with alphanumeric
    if normalized and not normalized[-1].isalnum():
        normalized = normalized + '1'
    
    # Ensure minimum length of 3
    if len(normalized) < 3:
        normalized = normalized.ljust(3, '0')
    
    # Ensure maximum length
    if len(normalized) > 512:
        normalized = normalized[:512]
    
    return normalized

def get_collection(workspace_name: str):
    """
    Get or create collection dynamically per workspace.
    ChromaDB collection names must be 3-512 characters.
    """
    collection_name = normalize_collection_name(workspace_name)
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_model
    )

# Add Documents
def add_documents(workspace_name, chunks, filename, page_numbers=None):
    """
    Add document chunks to the collection.
    Args:
        workspace_name: Name of the workspace/collection
        chunks: List of text chunks to add, or list of (chunk_text, page_num) tuples
        filename: Source filename for metadata
        page_numbers: Optional list of page numbers (if chunks is list of tuples, this is ignored)
    """
    if not chunks or len(chunks) == 0:
        return
    
    try:
        collection = get_collection(workspace_name)
        
        # Handle both formats: list of strings or list of (text, page_num) tuples
        if isinstance(chunks[0], tuple):
            chunk_texts = [chunk[0] for chunk in chunks]
            page_nums = [chunk[1] for chunk in chunks]
        else:
            chunk_texts = chunks
            page_nums = page_numbers if page_numbers else [None] * len(chunks)
        
        # Generate unique IDs
        ids = [f"{filename}_{i}_{hash(chunk) % 1000000}" for i, chunk in enumerate(chunk_texts)]
        
        # Create metadata with page numbers
        metadatas = []
        for i, page_num in enumerate(page_nums):
            meta = {"source": filename}
            if page_num is not None:
                meta["page"] = page_num
            metadatas.append(meta)
        
        collection.add(
            documents=chunk_texts,
            metadatas=metadatas,
            ids=ids
        )
    except Exception as e:
        import logging
        logging.error(f"Error adding documents to workspace {workspace_name}: {str(e)}")
        raise

# Retrieve
def retrieve(workspace_name, query, k=4):
    """
    Retrieve relevant documents from the collection.
    Args:
        workspace_name: Name of the workspace/collection
        query: Search query string
        k: Number of results to return (default: 4)
    Returns:
        Tuple of (list of document chunks, list of metadata dicts)
    """
    if not query or not query.strip():
        return [], []
    
    try:
        collection = get_collection(workspace_name)
        # BGE models work better with this prefix for retrieval
        query_str = "Represent this sentence for searching relevant passages: " + str(query).strip()

        results = collection.query(
            query_texts=[query_str],
            n_results=k
        )
        
        if not results or not results.get("documents") or not results["documents"]:
            return [], []

        documents = results["documents"][0]
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{}] * len(documents)
        
        return documents, metadatas
    except Exception as e:
        # Log error but return empty list to prevent crashes
        import logging
        logging.error(f"Error retrieving from workspace {workspace_name}: {str(e)}")
        return [], []

# Delete File from Workspace
def delete_from_collection(workspace_name, filename):
    collection = get_collection(workspace_name)

    collection.delete(
        where={"source": filename}
    )


# Workspace Utilities
def list_workspaces():
    return [c.name for c in client.list_collections()]

def delete_workspace(workspace_name):
    """Delete a workspace collection from ChromaDB."""
    try:
        collection_name = normalize_collection_name(workspace_name)
        client.delete_collection(collection_name)
    except Exception as e:
        import logging
        logging.error(f"Error deleting workspace collection {workspace_name}: {str(e)}")
        # Don't raise - workspace might not exist in DB