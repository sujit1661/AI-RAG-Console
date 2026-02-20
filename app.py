from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
from pydantic import BaseModel

from backend.ingestion import (
    extract_pdf_text,
    extract_excel_text,
    extract_docx_text,
    extract_image_text
)
from backend.chunking import chunk_text
from backend.retriever import add_documents, retrieve, delete_from_collection # Added delete import
from backend.llm import generate_answer

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Data models to handle incoming JSON
class ChatRequest(BaseModel):
    question: str

class DeleteRequest(BaseModel):
    filename: str

@app.get("/")
def root():
    return {"message": "API is online"}

# ---------- Upload Endpoint ----------
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        if file.filename.endswith(".pdf"):
            text = extract_pdf_text(file_path)
        elif file.filename.endswith((".xlsx", ".xls")):
            text = extract_excel_text(file_path)
        elif file.filename.endswith(".docx"):
            text = extract_docx_text(file_path)
        elif file.filename.endswith((".png", ".jpg", ".jpeg")):
            text = extract_image_text(file_path)
        else:
            return {"error": "Unsupported file format"}

        chunks = chunk_text(text)
        add_documents(chunks, file.filename)

        # "message" key matches frontend alert(data.message)
        return {"message": f"{file.filename} Indexed Successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Chat Endpoint (FIXED) ----------
@app.post("/chat")
async def chat(data: ChatRequest):
    # data.question matches frontend { question }
    question = data.question

    context = retrieve(question)
    answer = generate_answer(question, context)

    # return "answer" key matches frontend data.answer
    return {"answer": answer}


# ---------- Delete Endpoint (NEW) ----------
@app.post("/delete")
async def delete_file(data: DeleteRequest):
    filename = data.filename
    file_path = os.path.join(UPLOAD_DIR, filename)

    try:
        # 1. Delete from Vector DB
        delete_from_collection(filename)

        # 2. Delete local file if it exists
        if os.path.exists(file_path):
            os.remove(file_path)

        return {"message": f"Deleted {filename} successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))