# AI RAG Console

A high-performance, full-stack **Retrieval-Augmented Generation (RAG)** system that enables intelligent document interaction. Users can upload documents (PDF, Word, Excel, Images), index them into a vector database, and query them through a fast, context-aware AI chat interface powered by Groq.

The platform also supports secure user authentication and multi-workspace document management using Supabase.

---

## 📸 Preview

![AI-RAG-Console](image_rag.jpg)

---

## 🚀 Overview

AI RAG Console allows users to:

- Upload and index multiple document formats  
- Perform semantic search over embedded content  
- Receive context-grounded AI responses  
- Manage indexed documents dynamically  
- Organize knowledge across multiple workspaces  

The system integrates **FastAPI**, **Supabase (Database & Authentication)**, **ChromaDB**, **HuggingFace embeddings**, and **Groq LLM inference** to deliver secure, accurate, and low-latency results.

---

## ✨ Features

- **Multimodal Ingestion**
  - Supports `.pdf`, `.docx`, `.xlsx`, `.xls`, `.png`, `.jpg`

- **OCR Integration**
  - Extracts text from images and scanned documents using Tesseract

- **Semantic Search**
  - Powered by `BGE-small-en-v1.5` embeddings

- **Persistent Vector Storage**
  - ChromaDB-based indexing and retrieval

- **Authentication & Workspace Management**
  - Secure login and user management via Supabase
  - Multi-workspace document organization

- **Ultra-Fast Inference**
  - Groq API integration for rapid LLM responses

- **Response Transparency**
  - Token usage visibility
  - Page-level source reference display

- **Modern UI**
  - Responsive dark-themed dashboard built with Tailwind CSS
  - Interactive chat interface with Markdown support
  - File upload and deletion management

---

## 🛠️ Tech Stack

**Frontend**
- HTML5
- Tailwind CSS
- JavaScript (Vanilla)

**Backend**
- FastAPI (Python)

**AI & Data**
- Supabase (Database & Authentication)
- ChromaDB (Vector Database)
- HuggingFace Sentence Transformers (BGE)
- Groq API (LLM Inference)
- Pytesseract & Pillow (OCR)

---

## 📋 Prerequisites

- Python 3.9+
- Tesseract OCR installed on your system

### Install Tesseract

**Windows:**  
Download from: https://github.com/UB-Mannheim/tesseract/wiki  
Ensure it is added to your system PATH.

**Linux:**
```bash
sudo apt install tesseract-ocr
```

---

## ⚙️ Setup Instructions

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/sujit1661/RAG-System.git
cd RAG-System
```

### 2️⃣ Create Virtual Environment

```bash
python -m venv venv
```

Activate:

Windows:
```bash
venv\Scripts\activate
```

Linux / Mac:
```bash
source venv/bin/activate
```

### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

### 4️⃣ Configure Environment Variables

Create a `.env` file in the root directory:

```
GROQ_API_KEY=your_api_key_here
```

---

## 🏃 Running the Application

### Start Backend

```bash
uvicorn app:app --reload
```

Backend will run at:
```
http://127.0.0.1:8000
```

### Launch Frontend

Open `index.html` in any modern web browser.

---

## 📂 Project Structure

```
├── backend/
│   ├── ingestion.py
│   ├── chunking.py
│   ├── retriever.py
│   └── llm.py
├── uploads/
├── chroma_db/
├── app.py
├── index.html
├── requirements.txt
└── .env
```

---

## 🔐 Environment Notes

If Tesseract is not added to your system PATH (Windows), specify its location manually in `ingestion.py`:

```python
# Only required if Tesseract is not in PATH
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

---

## 🤝 Contributing

Contributions are welcome. Feel free to fork the repository, open issues, or submit pull requests.

---

## 👨‍💻 Author

Sujit Sadalage
