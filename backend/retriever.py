import chromadb
from chromadb.utils import embedding_functions

client = chromadb.PersistentClient(path="./chroma_db")

embedding_model = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-small-en-v1.5"
)

collection = client.get_or_create_collection(
    name="documents",
    embedding_function=embedding_model
)


def add_documents(chunks, filename):
    collection.add(
        documents=chunks,
        metadatas=[{"source": filename}] * len(chunks),
        ids=[f"{filename}_{i}" for i in range(len(chunks))]
    )


def retrieve(query, k=4):
    # Fix for the NoneType error: Ensure query is a string
    if query is None:
        return []

    query_str = "Represent this sentence for searching relevant passages: " + str(query)

    results = collection.query(
        query_texts=[query_str],
        n_results=k
    )

    return results["documents"][0] if results["documents"] else []


# NEW: Add this function to delete documents from ChromaDB
def delete_from_collection(filename):
    collection.delete(
        where={"source": filename}
    )