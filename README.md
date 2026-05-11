# RAGCORE

A production-grade **Retrieval-Augmented Generation (RAG)** system. Upload documents, index them into a vector database, and chat with them through a fast, context-aware AI interface.

---

## How It Works — The Full Pipeline

```
User uploads document
        ↓
Text extraction (PDF / DOCX / Excel / Image)
        ↓
Chunking (page-aware / Excel-row-aware / fixed-size)
        ↓
Embedding (BAAI/bge-small-en-v1.5, 384 dims)
        ↓
Dual-write → Supabase pgvector + ChromaDB (local backup)
             + BM25 index (disk-persisted)

User asks a question
        ↓
Hybrid Search
  ├── Vector search  (pgvector cosine similarity, HNSW index)
  └── BM25 keyword search (exact term matching)
        ↓
Reciprocal Rank Fusion (RRF) — merges both result lists
        ↓
Cohere Rerank API — cross-encoder rescoring
        ↓
Adaptive top-k chunks (4 / 8 / 15 based on query type)
        ↓
LLM (Groq, openai/gpt-oss-120b) with conversation history
        ↓
Streamed answer via SSE
```

---

## Algorithms & Search Patterns

### 1. Hybrid Search

Pure vector search misses exact keyword matches. Pure keyword search misses semantic meaning. Hybrid search runs both in parallel and combines results.

**Vector search** — embeds the query and finds chunks with the closest embedding vectors using cosine similarity. Good for: "what does the contract say about termination?" (semantic intent).

**BM25 (Best Match 25)** — scores documents based on term frequency and inverse document frequency. Good for: "Tess Warren age 22" (exact names, numbers, codes).

```
BM25 score = Σ IDF(term) × TF_normalized(term, doc)

IDF = log((N - df + 0.5) / (df + 0.5) + 1)   ← rare words score higher
TF_norm = tf × (k1+1) / (tf + k1×(1 - b + b×dl/avgdl))  ← diminishing returns on repetition

k1 = 1.5  (TF saturation)
b  = 0.75 (document length normalization)
```

### 2. Reciprocal Rank Fusion (RRF)

Merges the vector and BM25 result lists without needing to normalize their scores (which use different scales).

```
RRF score(doc) = Σ 1 / (k + rank_in_list)    k = 60 (standard constant)
```

A document ranked #1 in vector search and #3 in BM25 scores higher than one ranked #2 in only one list. This naturally rewards documents that appear in both result sets.

### 3. Cohere Rerank (Cross-Encoder)

Vector search and BM25 are **bi-encoders** — they encode query and document separately, then compare. This is fast but less accurate.

Cohere Rerank is a **cross-encoder** — it reads the query and each candidate chunk together in a single pass, giving a much more accurate relevance score.

```
Bi-encoder:    embed(query) · embed(chunk)  → similarity score
Cross-encoder: model(query + chunk)         → relevance score  ← more accurate
```

The pipeline retrieves 30 candidates via hybrid search, then Cohere rescores all 30 and returns the top k. This gives the accuracy of a cross-encoder without the latency of running it on the full corpus.

### 4. Adaptive k

Different query types need different amounts of context:

| Query type | k | Example |
|---|---|---|
| List / filter | 15 | "list all people aged 22" |
| General | 8 | "explain the refund policy" |
| Factual | 4 | "what is the contract start date?" |

### 5. Semantic Chunking

Documents are split where meaning changes, not at fixed character counts. Sentence embeddings are compared between adjacent sentences — when cosine similarity drops below 0.75, a new chunk starts. This keeps semantically related content together.

For Excel files, rows are grouped in batches of 20 with the sheet header repeated in every chunk, so the LLM always knows column names and context.

### 6. Conversation History

The last 8 messages are injected into the LLM prompt before the current question. This enables follow-up questions like "what about the second point?" without re-explaining context.

---

## Key Technologies

| Technology | Role | Why |
|---|---|---|
| **FastAPI** | Backend framework | Async, fast, automatic OpenAPI docs |
| **Supabase** | Auth + DB + Storage | One service for users, data, files, and pgvector |
| **pgvector** | Cloud vector store | HNSW index, cosine similarity, lives in Postgres |
| **ChromaDB** | Local vector fallback | Works offline, no network dependency |
| **BAAI/bge-small-en-v1.5** | Embedding model | 384 dims, fast, runs locally, strong retrieval performance |
| **BM25** | Keyword search | Catches exact matches vector search misses |
| **Cohere Rerank** | Cross-encoder reranking | Dramatically improves result ordering, free tier available |
| **Groq API** | LLM inference | Ultra-low latency (~10x faster than standard OpenAI) |
| **bcrypt** | Password hashing | Industry standard, resistant to brute force |
| **slowapi** | Rate limiting | Prevents brute force on auth endpoints |
| **marked.js** | Markdown rendering | Renders LLM responses with proper formatting |
| **Tailwind CSS** | Frontend styling | Utility-first, consistent dark theme |

---

## Project Structure

```
ragcore/
├── app.py                      # FastAPI entry point (~80 lines)
│
├── routers/                    # Route handlers (split by domain)
│   ├── auth.py                 # /auth/* endpoints
│   ├── workspace.py            # /workspace/*, /chat/create, /chat/delete
│   ├── files.py                # /upload, /delete-file
│   └── chat.py                 # /chat, /chat/stream (adaptive k + streaming)
│
├── frontend/
│   ├── index.html              # Main chat application
│   ├── landing.html            # Public landing page
│   ├── login.html              # Login page
│   └── register.html           # Registration page
│
├── backend/
│   ├── auth.py                 # Supabase Auth + local bcrypt fallback
│   ├── deps.py                 # Shared FastAPI dependencies + file helpers
│   ├── ingestion.py            # PDF, DOCX, Excel, image text extraction
│   ├── chunking.py             # Fixed-size + Excel-aware chunking
│   ├── semantic_chunker.py     # Meaning-based chunking (sentence embeddings)
│   ├── embeddings.py           # BAAI/bge-small-en-v1.5 embedding generation
│   ├── retriever.py            # Hybrid search: pgvector + BM25 + RRF + rerank
│   ├── bm25_index.py           # BM25 implementation (disk-persisted, auto-rebuilt)
│   ├── cohere_reranker.py      # Cohere Rerank API integration
│   ├── llm.py                  # Groq LLM with conversation history + streaming
│   ├── persistence.py          # Dual-write: local JSON + Supabase DB
│   ├── analytics.py            # Query tracing, latency logging, feedback
│   ├── supabase_config.py      # Supabase client setup
│   ├── supabase_db.py          # Supabase DB operations
│   └── supabase_storage.py     # Supabase Storage operations
│
├── tests/
│   ├── test_auth.py            # bcrypt, SHA256 migration, password verification
│   ├── test_bm25.py            # BM25 search, scoring, delete, edge cases
│   ├── test_chunking.py        # Text, page-aware, Excel chunking
│   └── test_deps.py            # Slug generation utilities
│
├── database/
│   ├── schema.sql              # Full Supabase schema (run once on setup)
│   ├── pgvector_migration.sql  # pgvector embeddings table + RPC function
│   └── query_logs_only.sql     # query_logs table only
│
├── uploads/                    # Local file storage (runtime, gitignored)
├── chroma_db/                  # Local ChromaDB (runtime, gitignored)
├── bm25_index/                 # Persisted BM25 indexes (runtime, gitignored)
├── requirements.txt
├── .env
└── .gitignore
```

---

## Features

### Authentication & Security
- Supabase Auth (JWT) with local bcrypt fallback
- JWT decoded locally — no network call on every request
- Automatic SHA256 → bcrypt password migration on login
- Proactive token refresh 5 min before expiry
- Rate limiting: login 10/min, register 5/min per IP
- Locked CORS via `ALLOWED_ORIGINS` env var
- Per-user data isolation at every layer

### Document Ingestion
- PDF — page-aware extraction, page numbers tracked per chunk
- Excel — multi-sheet, numeric summaries, 20 rows/chunk with headers
- DOCX — full paragraph extraction
- Images — OCR via Tesseract
- 50MB limit, duplicate detection (409), async background indexing

### Retrieval
- Hybrid search: pgvector + BM25 → RRF → Cohere Rerank
- Adaptive k: 4 / 8 / 15 chunks based on query complexity
- Candidate pool of 30 before reranking
- BM25 disk-persisted, auto-rebuilt from ChromaDB on startup
- Per-user ChromaDB collections: `{username}__{workspace_slug}`

### Chat
- SSE streaming with thinking animation
- Conversation history (last 8 messages) in LLM context
- Markdown rendering (bold, lists, tables, code blocks)
- Multi-chat threads per workspace
- Page citations, token usage display
- Thumbs up/down feedback per answer
- 2000 character question limit

### Observability
- Query tracing with trace_id, latency, chunk counts
- Structured logs (UTF-8 safe on Windows)
- Supabase `query_logs` table for analytics
- `GET /analytics` endpoint per user/workspace

### Data Persistence
| Data | Local | Supabase |
|---|:---:|:---:|
| Users | `users.json` | `auth.users` + `users` table |
| Workspaces | `uploads/{slug}/` | `workspaces` table |
| Chats | `chats.json` | `chats` table |
| Messages | `chat_{id}.json` | `messages` table |
| Files | `uploads/{slug}/` | Storage bucket |
| Embeddings | `chroma_db/` | `embeddings` (pgvector) |
| BM25 indexes | `bm25_index/` | — |
| Query logs | `app.log` | `query_logs` table |

---

## Setup

### 1. Prerequisites
- Python 3.9+
- Tesseract OCR — Windows: https://github.com/UB-Mannheim/tesseract/wiki | Linux: `sudo apt install tesseract-ocr`

### 2. Install

```bash
git clone https://github.com/sujit1661/AI-RAG-Console.git
cd AI-RAG-Console
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
```

### 3. Environment Variables

```env
GROQ_API_KEY=your_groq_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key
STORAGE_BUCKET=documents
ADMIN_PASSWORD=your_secure_password
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
COHERE_API_KEY=your_cohere_api_key   # optional — enables reranking (free: 1000/month)
```

### 4. Supabase Setup

1. Create project at https://supabase.com
2. Database → Extensions → enable `vector`
3. SQL Editor → run `database/schema.sql`
4. SQL Editor → run `database/pgvector_migration.sql`
5. Storage → create bucket `documents` (private)

### 5. Run

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 — default login: `admin` / value of `ADMIN_PASSWORD`

### 6. Run Tests

```bash
pytest tests/ -v
```

---

## API Reference

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Login (10 req/min) |
| POST | `/auth/register` | Register (5 req/min) |
| POST | `/auth/logout` | Logout |
| POST | `/auth/refresh` | Refresh JWT |
| GET | `/auth/check` | Auth status |
| GET | `/auth/user` | Current user info |
| POST | `/auth/change-password` | Change password |

### Workspaces
| Method | Endpoint | Description |
|---|---|---|
| GET | `/workspace/list` | List user's workspaces |
| POST | `/workspace/create` | Create workspace |
| POST | `/workspace/delete` | Delete workspace + all data |
| POST | `/workspace/rename` | Rename (slug unchanged) |
| GET | `/workspace/{name}/files` | List files |
| GET | `/workspace/{name}/chats` | List chats |
| GET | `/workspace/{name}/history` | Chat history |

### Documents
| Method | Endpoint | Description |
|---|---|---|
| POST | `/upload` | Upload + async index |
| POST | `/delete-file` | Delete file + embeddings |

### Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | `/chat` | Non-streaming query |
| POST | `/chat/stream` | Streaming query (SSE) |
| POST | `/chat/create` | New chat thread |
| POST | `/chat/delete` | Delete chat thread |

### Analytics
| Method | Endpoint | Description |
|---|---|---|
| POST | `/feedback` | Thumbs up/down |
| GET | `/analytics` | Query stats |

---

## Author

Sujit Sadalage
