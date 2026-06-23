# RAGCORE

A production-ready, full-stack Retrieval-Augmented Generation (RAG) system. Upload documents, ask questions, and get AI answers grounded exclusively in your content — with hybrid search, a visual pipeline explorer, a general AI chatbot, and a real-time monitoring dashboard.

---

## What's New (Latest)

### Production & Deployment
- **Render-ready** — `render.yaml` added for one-command deploy to Render (recommended host)
- **Supabase-first storage** — ChromaDB and local disk are now fallbacks only; all critical data lives in Supabase
- **BM25 indexes in Supabase Storage** — pickle files stored in `bm25-indexes` bucket; rebuilt from `embeddings` table on startup if missing
- **Ephemeral-disk-safe** — workspaces, chats, sessions, and embeddings all survive Render deploys/restarts
- **Secure cookies** — `SECURE_COOKIES=true` env var enables `HttpOnly; Secure` on production HTTPS
- **JWT verification** — Supabase JWTs verified with `PyJWT` + `SUPABASE_JWT_SECRET`; no more unsigned decode
- **Stdout-only logging in production** — file handler only added when `ENVIRONMENT=development`

### Auth & Sessions
- Sessions stored in Supabase `sessions` table — survive server restarts
- Users stored in Supabase `users` table — local `users.json` / `sessions.json` are dev fallbacks only
- Default admin creation skipped if `ADMIN_PASSWORD` not set (safe in production)

### Workspace Management
- **Workspace persistence** — all workspaces, chats, and docs reload from Supabase on page refresh and new sessions
- **"Already exists" recovery** — creating a duplicate workspace shows an "Open it →" link instead of a dead-end error
- **Batch workspace list** — `/workspace/list` now uses 2 Supabase queries total (was N×2); shows last message and message count
- **Search by name or slug** — workspace search matches both display name and slug
- **`workspace_exists` vs `workspace_accessible`** — creation uses strict check; chat/file endpoints use broader check that also finds legacy workspaces without a `workspaces` table row
- **Auto-repair** — `chat/create` automatically inserts a missing `workspaces` row for legacy workspaces

### Document RAG
- **Send button and Enter key fixed** — replaced `disabled` attribute with `readonly` so keyboard events always fire
- **No infinite loading** — `loadChats` → `_createChatSilent` removes the recursive loop that caused infinite requests
- **`Promise.allSettled`** — `switchWorkspace` always hides the overlay even if `loadChats` or `refreshLibrary` throws
- **State persists across navigation** — `sessionStorage` saves active workspace + chat; restored on every page load

### Streaming & Typing
- **ChatGPT-style smooth typing** — all chat interfaces (RAG, AI Chat, Playground, Pipeline) use a `requestAnimationFrame` queue that drains 4 chars/frame; markdown rendered once on finalize
- **Pipeline answer displayed** — `populateStage("llm")` no longer overwrites the streamed content; `finalizeLLM` renders markdown and hides raw stream

### Pipeline & Playground
- **Ask again without re-uploading** — both Pipeline and Playground show a sticky "Ask another question" bar after a run completes
- **Back button on Playground** — overlay now has a `← Back` link to `/app`
- **Pipeline result rendered** — answer now shows as formatted markdown after streaming ends

### Sidebar
- Simplified flat layout — no collapsible sections
- Workspace list with inline chats + docs when a workspace is selected
- "Open" button visible on hover for each workspace row
- Slug shown as subtitle when no last message exists

---

## Features

| Feature | Description |
|---|---|
| **Document RAG** | Upload PDFs, DOCX, Excel, and images. Ask questions and get answers with page-number citations. |
| **Hybrid Retrieval** | Vector search (pgvector / ChromaDB) + BM25 keyword search, fused with Reciprocal Rank Fusion. |
| **Cohere Reranking** | Optional cross-encoder reranking for higher precision. Falls back to RRF order if key not set. |
| **General AI Chatbot** | Separate chat interface backed by Groq — no documents needed. Sessions persisted to Supabase. |
| **RAG Playground** | Visual animated flow graph. Upload a document, ask a question, watch every pipeline stage execute in real time. Ask again without re-uploading. |
| **Pipeline Explorer** | Step-by-step educational walkthrough with embedding bars, score bars, RRF tables, and streamed LLM output. Ask multiple questions on the same file. |
| **Monitoring Dashboard** | SSE-powered live trace viewer. See every RAG query and file upload as it happens. |
| **Multi-workspace** | Isolated workspaces per user. Each workspace has its own documents, chat history, and vector index. All data persists across restarts. |
| **Auth** | Supabase Auth (JWT verified with PyJWT) with local JSON fallback. bcrypt password hashing. |

---

## Tech Stack

**Backend**
- FastAPI + Uvicorn (async, production-ready)
- `BAAI/bge-small-en-v1.5` via SentenceTransformers — 384-dim dense embeddings
- ChromaDB — local vector store (fallback only in production)
- Supabase pgvector — cloud vector store (primary, HNSW index)
- BM25 — pure-Python keyword index, persisted to Supabase Storage
- Cohere Rerank API (optional)
- Groq API — LLM inference
- PyMuPDF, python-docx, pandas, Tesseract OCR — document extraction
- SlowAPI — rate limiting
- PyJWT — JWT verification

**Frontend**
- Vanilla HTML/CSS/JS — no build step
- Tailwind CSS (CDN), Space Grotesk font, Material Symbols icons
- Server-Sent Events (SSE) for streaming across all features
- marked.js — markdown rendering
- `requestAnimationFrame` smooth typing engine

---

## How RAG Works in This Project

### Phase 1 — Ingestion (on file upload)

```
Upload PDF / DOCX / Excel / Image
        │
        ▼
1. TEXT EXTRACTION
   PDF   → PyMuPDF   (page-by-page, char offset tracking)
   DOCX  → python-docx
   Excel → pandas    ("Col: value | Col: value" per row)
   Image → Tesseract OCR
        │
        ▼
2. CHUNKING  (1000 chars, 300 overlap)
   PDFs: page-aware chunks
   Excel: sheet-aware, 20 rows per chunk, headers repeated
        │
        ▼
3. EMBEDDING  (BAAI/bge-small-en-v1.5 → 384 floats per chunk)
        │
        ▼
4. STORING  (3 parallel destinations)
   ├── Supabase pgvector  ← primary (cloud, always persistent)
   ├── ChromaDB           ← local fallback (./chroma_db/)
   └── BM25 index         ← Supabase Storage (./bm25_index/ fallback)
```

### Phase 2 — Retrieval & Generation (on question)

```
Question
        │
        ▼
1. QUERY EMBEDDING  (same model + query prefix)
        │
        ▼
2. HYBRID SEARCH  (30 candidates each)
   ├── Vector: Supabase pgvector → ChromaDB fallback
   └── BM25: keyword scoring (exact matches)
        │
        ▼
3. RRF MERGE  score = Σ 1/(60 + rank)
        │
        ▼
4. RERANKING  (Cohere cross-encoder, optional)
        │
        ▼
5. ADAPTIVE-K
   Broad query  (list, all, summarize) → k = 15
   Factual      (what is, when, where) → k = 4
   Default                              → k = 8
        │
        ▼
6. LLM GENERATION  (Groq, streamed SSE)
   System: "answer only from context"
   Last 8 conversation messages included
   Context trimmed to 5000 chars
        │
        ▼
7. SAVE & SYNC
   ├── Local JSON  →  uploads/{workspace}/chat_{id}.json
   └── Supabase    →  messages + chats tables
```

---

## Project Structure

```
app.py                        ← FastAPI entry point, CORS, startup, routes
render.yaml                   ← Render deployment config
requirements.txt

routers/
  auth.py                     ← /auth/* (login, register, logout, refresh)
  workspace.py                ← /workspace/* CRUD + /chat/* endpoints
  files.py                    ← /upload (background indexing), /delete-file
  chat.py                     ← /chat/stream  (streaming RAG answer, SSE)
  general_chat.py             ← /general/*    (general AI chatbot)
  playground.py               ← /playground/stream, /traces, /stats
  pipeline_explorer.py        ← /pipeline/run  (isolated RAG walkthrough, SSE)

backend/
  auth.py                     ← Login/register, JWT verify (PyJWT), sessions → Supabase
  deps.py                     ← Shared deps, workspace_exists, workspace_accessible
  ingestion.py                ← PDF / DOCX / Excel / image extraction
  chunking.py                 ← RecursiveCharacterTextSplitter (page-aware + Excel)
  embeddings.py               ← SentenceTransformer lazy-loader
  retriever.py                ← Hybrid search, RRF, add_documents (Supabase + ChromaDB)
  bm25_index.py               ← Pure-Python BM25, Supabase Storage persistence
  cohere_reranker.py          ← Cohere Rerank wrapper
  llm.py                      ← Groq API (streaming + batch)
  persistence.py              ← Fire-and-forget Supabase sync
  analytics.py                ← QueryTrace, feedback, analytics
  playground.py               ← In-memory SSE event bus
  supabase_config.py          ← Supabase client
  supabase_db.py              ← CRUD helpers
  supabase_storage.py         ← File upload/delete in Supabase Storage

frontend/
  index.html                  ← Main RAG chat (flat sidebar, persistent state)
  chat.html                   ← General AI chatbot
  playground.html             ← Visual pipeline graph (ask-again bar)
  pipeline.html               ← Step-by-step pipeline explorer (ask-again bar)
  landing.html                ← Public marketing page
  login.html / register.html  ← Auth pages

database/
  schema.sql                        ← All Supabase tables (idempotent)
  pgvector_migration.sql            ← pgvector extension + match_embeddings RPC
  sessions_and_workspace_meta.sql   ← sessions table + workspaces.display_name column
  create_bm25_bucket.sql            ← bm25-indexes Storage bucket
  query_logs_only.sql               ← Analytics table only
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/ragcore.git
cd ragcore
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure environment

```env
# ── Required ──────────────────────────────────────
GROQ_API_KEY=gsk_...

# ── Supabase ──────────────────────────────────────
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_JWT_SECRET=your-jwt-secret      # Settings → API → JWT Secret
STORAGE_BUCKET=documents

# ── Production ────────────────────────────────────
ENVIRONMENT=production                   # or development
SECURE_COOKIES=true                      # true on HTTPS

# ── Optional ──────────────────────────────────────
COHERE_API_KEY=...
ADMIN_PASSWORD=changeme                  # leave unset in prod to skip default user
ALLOWED_ORIGINS=https://yourdomain.com
```

Without Supabase keys the app runs **fully locally** using ChromaDB + BM25 + JSON files. No features are lost.

### 3. Supabase setup

Run these SQL files in your Supabase SQL Editor **in order**:

1. `database/schema.sql` — all tables (pgvector must be enabled first)
2. `database/sessions_and_workspace_meta.sql` — sessions table + display_name column
3. `database/create_bm25_bucket.sql` — storage bucket for BM25 indexes

Enable pgvector: Dashboard → Database → Extensions → "vector" → Enable.

### 4. Tesseract OCR (image uploads only)

- Windows: [download installer](https://github.com/UB-Mannheim/tesseract/wiki)
- macOS: `brew install tesseract`
- Ubuntu: `sudo apt install tesseract-ocr`

### 5. Run locally

```bash
python app.py
# or
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000**

---

## Deploy to Render

1. Push to GitHub
2. Connect repo in Render dashboard
3. Render detects `render.yaml` automatically
4. Set all environment variables in Render dashboard (marked `sync: false` in `render.yaml`)
5. Deploy — `render.yaml` sets the build and start commands

Minimum plan: **Starter ($7/mo)** — the embedding model needs ~512MB RAM.

---

## Pages

| URL | Description |
|---|---|
| `/` | Landing page |
| `/app` | Main RAG chat — workspaces, documents, streaming answers |
| `/ai-chat` | General AI chatbot (no documents needed) |
| `/playground` | Visual pipeline animation — watch RAG run step by step |
| `/pipeline` | Educational pipeline explorer with full metadata per stage |
| `/login` | Login |
| `/register` | Create account |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Login |
| `POST` | `/auth/register` | — | Register |
| `POST` | `/auth/logout` | ✓ | Logout |
| `GET`  | `/auth/check` | — | Auth status |
| `POST` | `/auth/refresh` | — | Refresh JWT |
| `GET`  | `/workspace/list` | ✓ | List workspaces (batch-enriched) |
| `POST` | `/workspace/create` | ✓ | Create workspace (returns slug on 400 if exists) |
| `POST` | `/workspace/delete` | ✓ | Delete workspace + all data |
| `POST` | `/workspace/rename` | ✓ | Rename workspace |
| `GET`  | `/workspace/{slug}/files` | ✓ | List documents (Supabase → disk fallback) |
| `GET`  | `/workspace/{slug}/chats` | ✓ | List chats |
| `GET`  | `/workspace/{slug}/history` | ✓ | Chat message history |
| `POST` | `/chat/create` | ✓ | Create chat (auto-repairs missing workspace row) |
| `POST` | `/chat/delete` | ✓ | Delete chat |
| `POST` | `/chat/stream` | ✓ | **Streaming RAG answer (SSE)** |
| `POST` | `/upload` | ✓ | Upload + background index document |
| `POST` | `/delete-file` | ✓ | Delete document + embeddings |
| `GET`  | `/general/sessions` | ✓ | List AI chat sessions |
| `POST` | `/general/sessions` | ✓ | Create session |
| `DELETE` | `/general/sessions/{id}` | ✓ | Delete session |
| `POST` | `/general/chat/stream` | ✓ | **Streaming general AI answer (SSE)** |
| `GET`  | `/playground/stream` | ✓ | Live pipeline monitor (SSE) |
| `POST` | `/pipeline/run` | ✓ | **Run pipeline walkthrough (SSE)** |
| `POST` | `/feedback` | ✓ | Thumbs up/down on answer |
| `GET`  | `/analytics` | ✓ | Analytics summary |
| `GET`  | `/health` | — | Health check |

---

## What Gets Stored Where

### Supabase (primary — survives deploys)

| Table / Bucket | What's stored |
|---|---|
| `users` | username, email, last_login |
| `sessions` | session tokens with expiry |
| `workspaces` | slug, name, display_name, owner_id |
| `chats` | id, workspace_slug, title, owner_id |
| `messages` | chat_id, role, content |
| `embeddings` | chunk_text, vector (384 dims), filename, page_num |
| `documents` | workspace_slug, filename, file_path, file_size |
| `general_chat_sessions` | username, title |
| `general_chat_messages` | session_id, role, content |
| `query_logs` | trace_id, latency_ms, chunks_retrieved, feedback |
| Storage: `documents` | raw uploaded files |
| Storage: `bm25-indexes` | BM25 pickle indexes per workspace |

### Local filesystem (dev fallback / temp)

| Data | Path |
|---|---|
| Uploaded files (temp during indexing) | `uploads/{slug}/` |
| Chat history fallback | `uploads/{slug}/chat_{id}.json` |
| BM25 indexes fallback | `bm25_index/{user}__{workspace}.pkl` |
| ChromaDB vectors fallback | `chroma_db/` |
| Users fallback | `users.json` |
| Sessions fallback | `sessions.json` |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | **Yes** | Groq API key |
| `SUPABASE_URL` | No | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | No | Supabase service role key |
| `SUPABASE_JWT_SECRET` | No | JWT secret for token verification (Settings → API) |
| `STORAGE_BUCKET` | No | Storage bucket name (default: `documents`) |
| `ENVIRONMENT` | No | `production` or `development` (default: `development`) |
| `SECURE_COOKIES` | No | `true` to set Secure flag on cookies (required on HTTPS) |
| `COHERE_API_KEY` | No | Enables Cohere cross-encoder reranking |
| `ADMIN_PASSWORD` | No | Default admin password — leave unset in production |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `http://localhost:8000`) |

---

## Requirements

- Python 3.11+
- Tesseract OCR — only for image uploads
- No Node.js — frontend is pure HTML/JS served by FastAPI

---

## Author

**Sujit Sadalage**

---

## License

© 2025 Sujit Sadalage. All rights reserved.

This project is proprietary. No part of this codebase may be reproduced, distributed, or used without explicit written permission from the author.
