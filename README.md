# RAGCORE

A production-grade **Retrieval-Augmented Generation (RAG)** system. Upload documents, index them into a vector database, and chat with them through a fast, context-aware AI interface.

Built with FastAPI, Supabase, ChromaDB, and Groq.

---

## Project Structure

```
ragcore/
├── app.py                    # FastAPI entry point
│
├── frontend/                 # All HTML pages
│   ├── index.html            # Main chat application
│   ├── landing.html          # Public landing page
│   ├── login.html            # Login page
│   └── register.html         # Registration page
│
├── backend/                  # Python modules
│   ├── auth.py               # Supabase Auth + local session fallback (bcrypt)
│   ├── ingestion.py          # PDF, DOCX, Excel, image text extraction
│   ├── chunking.py           # Fixed + Excel-aware chunking
│   ├── semantic_chunker.py   # Semantic chunking (meaning-based splits)
│   ├── embeddings.py         # Sentence-transformer embedding generation
│   ├── retriever.py          # Hybrid search: pgvector + BM25 + reranking
│   ├── bm25_index.py         # BM25 keyword index (disk-persisted, auto-rebuilt)
│   ├── reranker.py           # BGE cross-encoder reranker
│   ├── query_expansion.py    # LLM-based query rewriting (3 variants)
│   ├── llm.py                # Groq LLM calls with conversation history
│   ├── persistence.py        # Dual-write: local JSON + Supabase DB
│   ├── analytics.py          # Query tracing, latency logging, feedback
│   ├── supabase_config.py    # Supabase client setup
│   ├── supabase_db.py        # Supabase DB operations
│   └── supabase_storage.py   # Supabase Storage operations
│
├── database/
│   ├── schema.sql            # Full Supabase schema (run once)
│   └── pgvector_migration.sql # pgvector + query_logs tables
│
├── uploads/                  # Local file storage (runtime, gitignored)
├── chroma_db/                # Local ChromaDB (runtime, gitignored)
├── bm25_index/               # Persisted BM25 indexes (runtime, gitignored)
├── requirements.txt
├── .env
└── .gitignore
```

---

## Features

### Authentication
- **Supabase Auth** — JWT-based login/register with email + password
- **Local fallback** — bcrypt session auth if Supabase is unavailable
- **Automatic hash migration** — existing SHA256 passwords silently upgraded to bcrypt on next login
- **Token refresh** — Proactive JWT renewal 5 min before expiry (no silent logouts)
- **Rate limiting** — Login: 10/min, Register: 5/min per IP (via slowapi)
- **Per-user isolation** — Every workspace, file, and embedding is scoped to the owner
- **Locked CORS** — Configurable via `ALLOWED_ORIGINS` env var (no wildcard with credentials)

### Workspaces
- Create, rename, and delete workspaces
- Each workspace is isolated — users only see their own
- Ownership enforced via `.owner` file + Supabase RLS
- Workspace slugs prefixed with username to prevent collisions

### Document Ingestion
- Supported formats: **PDF**, **DOCX**, **XLSX/XLS**, **PNG/JPG/JPEG**
- PDF: page-aware extraction with page number tracking
- Excel: multi-sheet support, numeric summaries, row-level text conversion
- Images: OCR via Tesseract
- **50MB file size limit** with clear error messages
- **Duplicate detection** — 409 with descriptive message
- **Async processing** — upload responds instantly, indexing runs in background

### Chunking
- **Semantic chunking** — splits where sentence embedding similarity drops (meaning-based boundaries)
- **Excel-aware chunking** — groups rows in batches, preserves sheet headers per chunk
- Fallback to fixed-size chunking (1000 chars, 300 overlap) if needed

### Retrieval Pipeline (Production-Grade)
```
Query
  ↓
Query Expansion (3 LLM-generated variants)
  ↓
Hybrid Search per variant:
  ├── Vector search (Supabase pgvector / ChromaDB fallback)
  └── BM25 keyword search (disk-persisted, auto-rebuilt on startup)
  ↓
Reciprocal Rank Fusion (RRF merge)
  ↓
Cross-encoder Reranking (BGE-reranker-base)
  ↓
Top-k chunks + conversation history → LLM
```

### Vector Storage
- **Primary**: Supabase pgvector (`embeddings` table, HNSW index)
- **Fallback**: Local ChromaDB (always written as backup)
- **Model**: `BAAI/bge-small-en-v1.5` (384 dimensions)
- Per-user collection naming: `{username}__{workspace_slug}`

### Chat
- **Streaming responses** via Server-Sent Events (SSE)
- **Conversation history** — last 4 exchanges sent to LLM for follow-up question support
- **Question length limit** — 2000 characters max (enforced frontend + backend)
- **Markdown rendering** — bold, lists, headings, code blocks, tables
- **Multi-chat** — multiple named chat threads per workspace
- **Chat history** — dual-persisted: local JSON + Supabase `messages` table
- **Page citations** — shows which PDF pages the answer came from
- **Token usage** — displayed per response
- **Thinking animation** — animated dots while streaming

### Observability & Feedback
- **Query tracing** — every query gets a `trace_id`, logs latency + chunk counts
- **Structured logs** — `[trace_id] QUERY OK | latency=142ms | chunks=5 | tokens=820`
- **Supabase analytics** — all query logs saved to `query_logs` table
- **Thumbs up/down** — feedback buttons on every AI response
- **Analytics endpoint** — `GET /analytics` returns stats per user/workspace

### Data Persistence
| Data | Local | Supabase |
|---|:---:|:---:|
| Users | `users.json` | `auth.users` + `users` table |
| Sessions | `sessions.json` | JWT (stateless) |
| Workspaces | `uploads/{slug}/` | `workspaces` table |
| Chat list | `chats.json` | `chats` table |
| Messages | `chat_{id}.json` | `messages` table |
| Files | `uploads/{slug}/file` | Storage bucket |
| Embeddings | `chroma_db/` | `embeddings` table (pgvector) |
| Query logs | `app.log` | `query_logs` table |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.9+) |
| Frontend | HTML5, Tailwind CSS, Vanilla JS |
| LLM | Groq API (`openai/gpt-oss-120b`) |
| Embeddings | `BAAI/bge-small-en-v1.5` (sentence-transformers) |
| Reranker | `BAAI/bge-reranker-base` (cross-encoder) |
| Vector DB | Supabase pgvector + ChromaDB |
| Database | Supabase (PostgreSQL) |
| Storage | Supabase Storage |
| Auth | Supabase Auth + local fallback |
| PDF | PyMuPDF (fitz) |
| OCR | Tesseract + Pillow |
| Excel | pandas + openpyxl |

---

## Setup

### 1. Prerequisites

- Python 3.9+
- Tesseract OCR

**Install Tesseract:**

Windows: https://github.com/UB-Mannheim/tesseract/wiki

Linux:
```bash
sudo apt install tesseract-ocr
```

### 2. Clone & Install

```bash
git clone https://github.com/sujit1661/RAG-System.git
cd RAG-System

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables

Create `.env` in the root:

```env
GROQ_API_KEY=your_groq_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key
STORAGE_BUCKET=documents
ADMIN_PASSWORD=your_admin_password
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

### 4. Supabase Setup

1. Create a Supabase project at https://supabase.com
2. Go to **Database → Extensions** → enable `vector`
3. Go to **SQL Editor** → run `database/schema.sql`
4. Then run `database/pgvector_migration.sql`
5. Go to **Storage** → create a bucket named `documents` (private)

### 5. Run

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000

Default login: `admin` / `admin123` (change immediately)

---

## API Endpoints

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Login |
| POST | `/auth/register` | Register |
| POST | `/auth/logout` | Logout |
| POST | `/auth/refresh` | Refresh JWT |
| GET | `/auth/check` | Check auth status |
| GET | `/auth/user` | Get current user |
| POST | `/auth/change-password` | Change password |

### Workspaces
| Method | Endpoint | Description |
|---|---|---|
| GET | `/workspace/list` | List user's workspaces |
| POST | `/workspace/create` | Create workspace |
| POST | `/workspace/delete` | Delete workspace |
| POST | `/workspace/rename` | Rename workspace |
| GET | `/workspace/{name}/files` | List files |
| GET | `/workspace/{name}/chats` | List chats |
| GET | `/workspace/{name}/history` | Get chat history |

### Documents
| Method | Endpoint | Description |
|---|---|---|
| POST | `/upload` | Upload + index document (async) |
| POST | `/delete-file` | Delete file + embeddings |

### Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | `/chat` | Non-streaming query |
| POST | `/chat/stream` | Streaming query (SSE) |
| POST | `/chat/create` | Create new chat |
| POST | `/chat/delete` | Delete chat |

### Analytics
| Method | Endpoint | Description |
|---|---|---|
| POST | `/feedback` | Submit thumbs up/down |
| GET | `/analytics` | Query stats for current user |

---

## Author

Sujit Sadalage
