import os
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Request
from pydantic import BaseModel

from backend.deps import get_token, get_safe_name, get_workspace_path
from backend.auth import get_current_user
from backend.ingestion import extract_pdf_text, extract_excel_text, extract_docx_text, extract_image_text
from backend.retriever import add_documents, delete_from_collection
from backend.supabase_storage import upload_file_to_supabase, delete_file_from_supabase
from backend.supabase_db import add_document_metadata

logger = logging.getLogger(__name__)
router = APIRouter(tags=["files"])

MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _require_auth(token: Optional[str] = Depends(get_token)) -> str:
    return get_current_user(token)


class DeleteFileRequest(BaseModel):
    workspace_name: str
    filename: str


@router.post("/upload")
async def upload(workspace_name: str, file: UploadFile = File(...),
                 background_tasks: BackgroundTasks = BackgroundTasks(),
                 username: str = Depends(_require_auth)):
    slug = get_safe_name(workspace_name)
    path = get_workspace_path(slug)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    safe_filename = os.path.basename(file.filename).replace("/", "_").replace("\\", "_")
    if not safe_filename or safe_filename in [".", ".."]:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(path, safe_filename)
    if os.path.exists(file_path):
        raise HTTPException(status_code=409,
            detail=f'"{safe_filename}" already exists. Delete it first to re-upload.')

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File too large. Max {MAX_UPLOAD_SIZE_MB}MB (got {len(file_bytes)/1024/1024:.1f}MB).")

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Start playground trace for this upload
    pg_trace_id = None
    try:
        from backend.playground import new_trace, emit
        pg_trace_id = new_trace(username, "file_upload", safe_filename,
                                meta={"workspace": slug, "size_bytes": len(file_bytes),
                                      "filename": safe_filename})
        emit(pg_trace_id, "file_upload", "done",
             f"{safe_filename} ({len(file_bytes)/1024:.1f} KB)",
             {"filename": safe_filename, "size_bytes": len(file_bytes), "workspace": slug})
    except Exception:
        pass

    background_tasks.add_task(_upload_to_supabase, slug, safe_filename, file_bytes, username)
    background_tasks.add_task(_process_and_index, slug, safe_filename, file_path, username, pg_trace_id)

    logger.info(f"File {safe_filename} saved, indexing in background [{username}/{slug}]")
    return {"status": "processing", "message": f'"{safe_filename}" uploaded. Indexing in background...'}


@router.post("/delete-file")
async def delete_file(data: DeleteFileRequest, username: str = Depends(_require_auth)):
    slug = get_safe_name(data.workspace_name)
    workspace_path = get_workspace_path(slug)
    if not os.path.exists(workspace_path):
        raise HTTPException(status_code=404, detail="Workspace not found")

    delete_from_collection(slug, data.filename, username)

    file_path = os.path.join(workspace_path, data.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    try:
        delete_file_from_supabase(slug, data.filename)
    except Exception as e:
        logger.warning(f"Supabase Storage delete failed (non-fatal): {e}")

    return {"message": "File deleted"}


def _upload_to_supabase(slug: str, filename: str, file_bytes: bytes, username: str):
    try:
        path = upload_file_to_supabase(slug, filename, file_bytes)
        if path:
            add_document_metadata(slug, filename, path, len(file_bytes), username)
    except Exception as e:
        logger.warning(f"Supabase upload error (non-fatal): {e}")


def _process_and_index(slug: str, filename: str, file_path: str, username: str,
                       pg_trace_id: str = None):
    def _pg(stage, status, msg="", meta=None):
        if not pg_trace_id:
            return
        try:
            from backend.playground import emit, finish_trace
            emit(pg_trace_id, stage, status, msg, meta or {})
            if status in ("done", "error") and stage in ("vector_store", "embedding"):
                pass  # finish called explicitly below
        except Exception:
            pass

    try:
        ext = filename.lower()
        page_info = None
        _pg("text_extraction", "running", f"Extracting text from {filename}")
        if ext.endswith(".pdf"):
            text, page_info = extract_pdf_text(file_path)
        elif ext.endswith((".xlsx", ".xls")):
            text = extract_excel_text(file_path)
        elif ext.endswith(".docx"):
            text = extract_docx_text(file_path)
        elif ext.endswith((".png", ".jpg", ".jpeg")):
            text = extract_image_text(file_path)
        else:
            logger.error(f"Unsupported format: {filename}")
            _pg("text_extraction", "error", f"Unsupported format: {filename}")
            return

        if not text or not text.strip():
            logger.warning(f"No text extracted from {filename}")
            _pg("text_extraction", "error", "No text extracted")
            return

        _pg("text_extraction", "done", f"{len(text):,} characters extracted",
            {"chars": len(text), "has_pages": page_info is not None})
        _pg("chunking", "running", "Splitting into chunks")

        if page_info:
            from backend.chunking import chunk_text_with_pages
            chunks = chunk_text_with_pages(text, page_info)
        elif ext.endswith((".xlsx", ".xls")):
            from backend.chunking import chunk_excel_text
            chunks = chunk_excel_text(text)
        else:
            from backend.chunking import chunk_text
            chunks = chunk_text(text)

        _pg("chunking", "done", f"{len(chunks)} chunks created",
            {"chunk_count": len(chunks), "strategy": "page-aware" if page_info else "recursive"})
        _pg("embedding", "running", "Generating vector embeddings")
        _pg("vector_store", "running", "Writing to Supabase pgvector + ChromaDB + BM25")

        add_documents(slug, chunks, filename, username=username)

        _pg("embedding", "done", f"BAAI/bge-small-en-v1.5 (384 dims)",
            {"model": "BAAI/bge-small-en-v1.5", "dims": 384, "chunks": len(chunks)})
        _pg("vector_store", "done",
            f"{len(chunks)} chunks → Supabase + ChromaDB + BM25",
            {"supabase": True, "chromadb": True, "bm25": True, "chunks": len(chunks)})

        try:
            from backend.playground import finish_trace
            finish_trace(pg_trace_id, "done",
                         {"chunk_count": len(chunks), "filename": filename})
        except Exception:
            pass

        logger.info(f"Indexed {filename}: {len(chunks)} chunks [{username}/{slug}]")
    except Exception as e:
        _pg("vector_store", "error", str(e))
        try:
            from backend.playground import finish_trace
            finish_trace(pg_trace_id, "error")
        except Exception:
            pass
        logger.error(f"Background processing failed for {filename}: {e}")
