# RAGCORE

A production-ready, full-stack Retrieval-Augmented Generation (RAG) system. Upload documents, ask questions, and get AI answers grounded exclusively in your content — with hybrid search, a visual pipeline explorer, a general AI chatbot, and a real-time monitoring dashboard.

---

## Features

| Feature | Description |
|---|---|
| **Document RAG** | Upload PDFs, DOCX, Excel, and images. Ask questions and get answers with page-number citations. |
| **Hybrid Retrieval** | Vector search (pgvector / ChromaDB) + BM25 keyword search, fused with Reciprocal Rank Fusion. |
| **Cohere Reranking** | Optional cross-encoder reranking for higher precision. Falls back to RRF order if key not set. |
| **General AI Chatbot** | Separate chat interface backed by Groq — no documents needed. Sessions persisted to Supabase. |
| **RAG Playground** | Visual animated flow graph. Upload a document, ask a question, watch every pipeline stage execute in real time with particle animations and expandable node details. |
| **Pipeline Explorer** | Step-by-step educational walkthrough of the RAG pipeline with embedding bar charts, score bars, RRF tables, and streamed LLM output. Completely isolated — no production data touched. |
| **Monitoring Dashboard** | SSE-powered live trace viewer. See every RAG query and file upload as it happens, with latency, chunk counts, and per-stage metadata. |
| **Multi-workspace** | Isolated workspaces per user. Each workspace has its own documents, chat history, and vector index. |
| **Auth** | Supabase Auth (JWT) with local JSON fallback. bcrypt password hashing with legacy SHA-256 migration. |

---

## Tech Stack

**Backend**
- FastAPI + Uvicorn (async, production-ready)
- `BAAI/bge-small-en-v1.5` via SentenceTransformers — 384-dim dense embeddings
- ChromaDB — local vector store (automatic fallback)
- Supabase pgvector — cloud vector store (primary, with HNSW index)
- BM25 — pure-Python keyword index, persisted as pickle files on disk
- Cohere Rerank API (optional, free tier: 1000 calls/month)
- Groq API — LLM inference (fast, free tier available)
- PyMuPDF, python-docx, pandas, Tesseract OCR — document extraction
- SlowAPI — rate limiting

**Frontend**
- Vanilla HTML/CSS/JS — no build step required
- Tailwind CSS (CDN), Space Grotesk font, Material Symbols icons
- Server-Sent Events (SSE) for real-time streaming across all features
- marked.js — markdown rendering for AI responses

---

## How RAG Works in This Project

### The two-phase architecture

RAG has two separate phases. Understanding the difference is key.

#### Phase 1 — Ingestion (happens when you upload a file)

```
You upload a PDF / DOCX / Excel / Image
        │
        ▼
1. TEXT EXTRACTION
   PDF   → PyMuPDF   — extracts text page-by-page, tracks char offsets per page
   DOCX  → python-docx
   Excel → pandas    — converts rows to readable text: "Name: John | Age: 25"
   Image → Tesseract OCR

        │
        ▼
2. CHUNKING  (split into overlapping windows)
   chunk_size = 1000 chars, overlap = 300 chars
   PDFs: page-aware — each chunk knows which page it came from
   Excel: sheet-aware — 20 data rows per chunk, header repeated each time

        │
        ▼
3. EMBEDDING  (each chunk → 384 numbers)
   Model: BAAI/bge-small-en-v1.5 (sentence-transformer)
   Similar meanings → similar vectors
   Asymmetric: documents use no prefix; queries use a prefix

        │
        ▼
4. STORING  (written to 3 places simultaneously)
   ├── Supabase pgvector  ← primary (cloud, persistent across deploys)
   ├── ChromaDB           ← local fallback (./chroma_db/)
   └── BM25 pickle        ← keyword index (./bm25_index/*.pkl)
```

#### Phase 2 — Retrieval & Generation (happens when you ask a question)

```
You type a question
        │
        ▼
1. QUERY EMBEDDING
   Same BAAI/bge-small-en-v1.5 model
   Query prefix: "Represent this sentence for searching relevant passages: "
   → 384-float vector

        │
        ▼
2. HYBRID SEARCH  (finds 30 candidates from each source)
   ├── Vector search  → cosine similarity between query vector and chunk vectors
   │     Primary:  Supabase pgvector  (SQL RPC call, HNSW index)
   │     Fallback: ChromaDB           (if Supabase unavailable)
   │
   └── BM25 search    → TF-IDF keyword scoring
         (catches exact term matches that vector search misses)

        │
        ▼
3. RRF MERGE  (Reciprocal Rank Fusion)
   score = Σ 1/(60 + rank)
   Chunks appearing in BOTH lists score higher.
   A chunk ranked #1 in both gets ≈ 0.033.

        │
        ▼
4. RERANKING  (optional, Cohere API)
   Cross-encoder reads full (query, chunk) pair together.
   More accurate than bi-encoders.
   Only runs on top-30 candidates to keep it fast.
   Falls back to RRF order if COHERE_API_KEY not set.

        │
        ▼
5. ADAPTIVE-K  (how many chunks to send to the LLM)
   Broad query (list, all, summarize, who) → k = 15
   Simple factual (what is, when, where)   → k = 4
   Default                                  → k = 8

        │
        ▼
6. LLM GENERATION  (Groq, streamed SSE)
   System prompt enforces "answer only from context"
   Includes last 8 conversation messages for follow-ups
   Context trimmed to 5000 chars to stay within token budget
   Model: openai/gpt-oss-120b

        │
        ▼
7. SAVE & SYNC
   ├── Local JSON  →  uploads/{workspace}/chat_{id}.json  (always)
   └── Supabase    →  messages + chats tables              (if configured)
```

### Why 3 storage layers for embeddings?

```
Supabase pgvector   ← source of truth
      │
      │ fails? (no key, offline, rate limited)
      ▼
ChromaDB (local)    ← automatic silent fallback
      │
      │ both always run in parallel
      ▼
BM25 keyword index  ← complementary retrieval, never replaced
```

On every server startup, BM25 indexes are rebuilt from ChromaDB if pickle files are missing.

### About the Playground trimming (does it affect accuracy?)

**No.** The Playground (`/playground`) is a completely isolated educational tool. It runs its own in-memory pipeline in a temp directory. The trimming (shorter previews, fewer displayed results) only affects what is **shown in the UI**. The actual RAG chatbot (`/app`) is entirely unaffected — it uses the full pipeline with no data limits.

---

## Project Structure

```
app.py                        ← FastAPI entry point, CORS, startup, routes
requirements.txt

routers/
  auth.py                     ← /auth/login, /register, /logout, /refresh
  workspace.py                ← /workspace/* CRUD + /chat/* endpoints
  files.py                    ← /upload (background indexing), /delete-file
  chat.py                     ← /chat/stream  (streaming RAG answer, SSE)
  general_chat.py             ← /general/*    (general AI chatbot + sessions)
  playground.py               ← /playground/stream, /traces, /stats  (monitor SSE)
  pipeline_explorer.py        ← /pipeline/run  (isolated RAG walkthrough, SSE)

backend/
  auth.py                     ← Login/register, JWT verify, bcrypt, session tokens
  deps.py                     ← Shared FastAPI deps, path helpers, JSON file I/O
  ingestion.py                ← PDF / DOCX / Excel / image text extraction
  chunking.py                 ← RecursiveCharacterTextSplitter (fixed + page-aware + Excel)
  embeddings.py               ← SentenceTransformer lazy-loader, embed_text / embed_texts
  retriever.py                ← Hybrid search, RRF merge, add_documents, delete
  bm25_index.py               ← Pure-Python BM25, in-memory cache, disk persistence
  cohere_reranker.py          ← Cohere Rerank API wrapper with graceful fallback
  llm.py                      ← Groq API: RAG answers + General AI (streaming + batch)
  persistence.py              ← Fire-and-forget Supabase sync (workspaces, chats, messages)
  analytics.py                ← QueryTrace context manager, feedback, analytics endpoint
  playground.py               ← In-memory SSE event bus (ring buffer, 200 traces)
  supabase_config.py          ← Supabase client (lazy init, service key)
  supabase_db.py              ← CRUD: workspaces, chats, messages, documents, general sessions
  supabase_storage.py         ← File upload/delete in Supabase Storage bucket

frontend/
  index.html                  ← Main RAG chat app (sidebar: workspaces/chats/docs)
  chat.html                   ← General AI chatbot (Supabase-persisted sessions)
  playground.html             ← Visual animated flow graph (Playground)
  pipeline.html               ← Step-by-step pipeline explorer
  landing.html                ← Public marketing page
  login.html                  ← Login with loading + success animation
  register.html               ← Registration with validation

database/
  schema.sql                  ← All Supabase table definitions (idempotent, run once)
  pgvector_migration.sql      ← pgvector extension + match_embeddings RPC
  query_logs_only.sql         ← Just the analytics table

uploads/                      ← User files (git-ignored)
bm25_index/                   ← BM25 pickle files (git-ignored)
chroma_db/                    ← ChromaDB local store (git-ignored)
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/ragcore.git
cd ragcore

python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
# ── Required ──────────────────────────────────────
GROQ_API_KEY=gsk_...

# ── Supabase (optional — app works fully locally) ─
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
STORAGE_BUCKET=documents

# ── Reranking (optional) ──────────────────────────
COHERE_API_KEY=...

# ── Auth / CORS ───────────────────────────────────
ADMIN_PASSWORD=admin123
ALLOWED_ORIGINS=http://localhost:8000
```

Without Supabase keys the app runs **fully locally**: ChromaDB + BM25 + JSON flat files. No features are lost — Supabase is a sync/backup layer.

### 3. Supabase setup (optional)

Run `database/schema.sql` in your Supabase SQL Editor.  
All statements use `IF NOT EXISTS` / `OR REPLACE` — safe to re-run on an existing database.

You need to enable the **pgvector** extension first:  
Supabase Dashboard → Database → Extensions → search "vector" → Enable.

### 4. Tesseract OCR (for image uploads)

Only needed if you want to upload image files (PNG/JPG).

- Windows: [download installer](https://github.com/UB-Mannheim/tesseract/wiki)
- macOS: `brew install tesseract`
- Ubuntu: `sudo apt install tesseract-ocr`

### 5. Run

```bash
python app.py
```

Or with auto-reload:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000**

Default credentials: `admin` / `admin123` (override with `ADMIN_PASSWORD` env var)

---

## Pages

| URL | Description |
|---|---|
| `/` | Landing page |
| `/app` | Main RAG chat (workspaces + documents + streaming answers) |
| `/ai-chat` | General AI chatbot (no documents needed) |
| `/playground` | Visual pipeline flow graph — watch RAG animate in real time |
| `/pipeline` | Step-by-step pipeline explorer with metadata at every stage |
| `/login` | Login |
| `/register` | Create account |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Login (Supabase JWT or local fallback) |
| `POST` | `/auth/register` | — | Create account |
| `POST` | `/auth/logout` | ✓ | Logout + clear session |
| `GET`  | `/auth/check` | — | Check if authenticated |
| `POST` | `/auth/refresh` | — | Refresh Supabase JWT |
| `GET`  | `/workspace/list` | ✓ | List owned workspaces |
| `POST` | `/workspace/create` | ✓ | Create workspace |
| `POST` | `/workspace/delete` | ✓ | Delete workspace + all data |
| `POST` | `/workspace/rename` | ✓ | Rename workspace |
| `GET`  | `/workspace/{slug}/files` | ✓ | List documents |
| `GET`  | `/workspace/{slug}/chats` | ✓ | List chats |
| `GET`  | `/workspace/{slug}/history` | ✓ | Chat message history |
| `POST` | `/chat/create` | ✓ | Create new chat |
| `POST` | `/chat/delete` | ✓ | Delete chat |
| `POST` | `/chat/stream` | ✓ | **Streaming RAG answer (SSE)** |
| `POST` | `/upload` | ✓ | Upload + background index document |
| `POST` | `/delete-file` | ✓ | Delete document + embeddings |
| `GET`  | `/general/sessions` | ✓ | List AI chat sessions |
| `POST` | `/general/sessions` | ✓ | Create AI chat session |
| `DELETE` | `/general/sessions/{id}` | ✓ | Delete session |
| `GET`  | `/general/sessions/{id}/messages` | ✓ | Session message history |
| `POST` | `/general/chat/stream` | ✓ | **Streaming general AI answer (SSE)** |
| `GET`  | `/playground/stream` | ✓ | Live pipeline monitor (SSE) |
| `GET`  | `/playground/traces` | ✓ | Recent traces snapshot |
| `POST` | `/pipeline/run` | ✓ | **Run isolated pipeline walkthrough (SSE)** |
| `POST` | `/feedback` | ✓ | Thumbs up/down on an answer |
| `GET`  | `/analytics` | ✓ | Query analytics summary |
| `GET`  | `/health` | — | Health check |

---

## What Gets Stored Where

### Local filesystem (always, no config needed)

| Data | Path |
|---|---|
| Uploaded files | `uploads/{workspace_slug}/` |
| Chat history | `uploads/{workspace_slug}/chat_{id}.json` |
| Chat metadata | `uploads/{workspace_slug}/chats.json` |
| Workspace owner | `uploads/{workspace_slug}/.owner` |
| BM25 indexes | `bm25_index/{user}__{workspace}.pkl` |
| ChromaDB vectors | `chroma_db/` |
| Users (fallback) | `users.json` |
| Sessions (fallback) | `sessions.json` |

### Supabase (when configured)

| Table | What's stored |
|---|---|
| `users` | username, email, created_at |
| `workspaces` | slug, name, owner_id |
| `chats` | id, workspace_slug, title, owner_id |
| `messages` | chat_id, role, content |
| `embeddings` | chunk_text, embedding vector (384 dims), filename, page_num |
| `documents` | workspace_slug, filename, file_path, file_size |
| `general_chat_sessions` | username, title |
| `general_chat_messages` | session_id, role, content |
| `query_logs` | trace_id, latency_ms, chunks_retrieved, feedback |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | **Yes** | Groq API key for LLM inference |
| `SUPABASE_URL` | No | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | No | Supabase service role key (bypasses RLS) |
| `STORAGE_BUCKET` | No | Supabase Storage bucket name (default: `documents`) |
| `COHERE_API_KEY` | No | Enables Cohere cross-encoder reranking |
| `ADMIN_PASSWORD` | No | Default admin password (default: `admin123`) |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `http://localhost:8000`) |

---

## Requirements

- Python 3.11+
- Tesseract OCR — only for image file uploads ([install](https://github.com/tesseract-ocr/tesseract))
- No Node.js — frontend is pure HTML/JS served by FastAPI

---

## Author

**Sujit Sadalage**

---

## License

© 2025 Sujit Sadalage. All rights reserved.

This project is proprietary. No part of this codebase may be reproduced, distributed, or used without explicit written permission from the author.
