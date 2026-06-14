-- Supabase Database Schema for RAG System
-- Run this SQL in your Supabase SQL Editor to create all tables
-- Re-running is safe — all statements use IF NOT EXISTS / OR REPLACE

-- ============================================================
-- Extensions
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- Users table (mirrors Supabase auth.users)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.users (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username    TEXT UNIQUE NOT NULL,
    email       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_login  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Workspaces
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workspaces (
    slug        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    owner_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RAG Chats  (workspace_slug FK is DEFERRABLE so async inserts work)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.chats (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_slug  TEXT NOT NULL,          -- soft FK — no hard constraint to avoid timing issues
    title           TEXT NOT NULL DEFAULT 'New Chat',
    owner_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RAG Messages
-- ============================================================
CREATE TABLE IF NOT EXISTS public.messages (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     UUID NOT NULL REFERENCES public.chats(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Documents metadata
-- ============================================================
CREATE TABLE IF NOT EXISTS public.documents (
    id              BIGSERIAL PRIMARY KEY,
    workspace_slug  TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    file_size       INTEGER,
    owner_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (workspace_slug, filename, owner_id)
);

-- ============================================================
-- Embeddings  (pgvector RAG chunks)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.embeddings (
    id              TEXT PRIMARY KEY,       -- "{filename}_{i}_{hash}"
    workspace_slug  TEXT NOT NULL,
    username        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    chunk_text      TEXT NOT NULL,
    embedding       vector(384),            -- BAAI/bge-small-en-v1.5 = 384 dims
    page_num        INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- General AI chatbot sessions & messages
-- ============================================================
CREATE TABLE IF NOT EXISTS public.general_chat_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username    TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT 'New Chat',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.general_chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES public.general_chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Query analytics
-- ============================================================
CREATE TABLE IF NOT EXISTS public.query_logs (
    id                  BIGSERIAL PRIMARY KEY,
    trace_id            TEXT,
    username            TEXT,
    workspace_slug      TEXT,
    question            TEXT,
    latency_ms          FLOAT,
    chunks_retrieved    INTEGER DEFAULT 0,
    chunks_after_rerank INTEGER DEFAULT 0,
    query_variants      INTEGER DEFAULT 1,
    total_tokens        INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'OK',
    feedback            TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_workspaces_owner         ON public.workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_chats_workspace          ON public.chats(workspace_slug);
CREATE INDEX IF NOT EXISTS idx_chats_owner              ON public.chats(owner_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat            ON public.messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_created         ON public.messages(created_at);
CREATE INDEX IF NOT EXISTS idx_documents_workspace      ON public.documents(workspace_slug);
CREATE INDEX IF NOT EXISTS idx_documents_owner          ON public.documents(owner_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_workspace     ON public.embeddings(username, workspace_slug);
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON public.embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gen_sessions_username    ON public.general_chat_sessions(username);
CREATE INDEX IF NOT EXISTS idx_gen_messages_session     ON public.general_chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_username      ON public.query_logs(username);

-- ============================================================
-- updated_at trigger
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_workspaces_updated_at ON public.workspaces;
CREATE TRIGGER update_workspaces_updated_at
    BEFORE UPDATE ON public.workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_chats_updated_at ON public.chats;
CREATE TRIGGER update_chats_updated_at
    BEFORE UPDATE ON public.chats
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_gen_sessions_updated_at ON public.general_chat_sessions;
CREATE TRIGGER update_gen_sessions_updated_at
    BEFORE UPDATE ON public.general_chat_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- RLS — enable on all tables
-- The backend uses the SERVICE ROLE KEY which bypasses RLS.
-- These policies are for any future direct-client access.
-- ============================================================
ALTER TABLE public.users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chats                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.embeddings           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.general_chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.general_chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.query_logs           ENABLE ROW LEVEL SECURITY;

-- Drop old policies before recreating (idempotent)
DO $$ BEGIN
  DROP POLICY IF EXISTS "Users can view own profile"         ON public.users;
  DROP POLICY IF EXISTS "Users can update own profile"       ON public.users;
  DROP POLICY IF EXISTS "Users can view own workspaces"      ON public.workspaces;
  DROP POLICY IF EXISTS "Users can create own workspaces"    ON public.workspaces;
  DROP POLICY IF EXISTS "Users can update own workspaces"    ON public.workspaces;
  DROP POLICY IF EXISTS "Users can delete own workspaces"    ON public.workspaces;
  DROP POLICY IF EXISTS "Users can view own chats"           ON public.chats;
  DROP POLICY IF EXISTS "Users can create own chats"         ON public.chats;
  DROP POLICY IF EXISTS "Users can update own chats"         ON public.chats;
  DROP POLICY IF EXISTS "Users can delete own chats"         ON public.chats;
  DROP POLICY IF EXISTS "Users can view own messages"        ON public.messages;
  DROP POLICY IF EXISTS "Users can create own messages"      ON public.messages;
  DROP POLICY IF EXISTS "Users can view own documents"       ON public.documents;
  DROP POLICY IF EXISTS "Users can create own documents"     ON public.documents;
  DROP POLICY IF EXISTS "Users can delete own documents"     ON public.documents;
  DROP POLICY IF EXISTS "Users can insert own embeddings"    ON public.embeddings;
  DROP POLICY IF EXISTS "Users can select own embeddings"    ON public.embeddings;
  DROP POLICY IF EXISTS "Users can delete own embeddings"    ON public.embeddings;
END $$;

-- Service role (used by backend) bypasses RLS entirely.
-- Grant full access so the service key never hits policy blocks.
CREATE POLICY "service_all" ON public.users                 FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.workspaces            FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.chats                 FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.messages              FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.documents             FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.embeddings            FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.general_chat_sessions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.general_chat_messages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON public.query_logs            FOR ALL USING (true) WITH CHECK (true);

-- ============================================================
-- pgvector similarity search RPC
-- ============================================================
CREATE OR REPLACE FUNCTION match_embeddings(
    query_embedding vector(384),
    match_workspace TEXT,
    match_username  TEXT,
    match_count     INT DEFAULT 4
)
RETURNS TABLE (
    id          TEXT,
    chunk_text  TEXT,
    filename    TEXT,
    page_num    INTEGER,
    similarity  FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        id,
        chunk_text,
        filename,
        page_num,
        1 - (embedding <=> query_embedding) AS similarity
    FROM public.embeddings
    WHERE workspace_slug = match_workspace
      AND username       = match_username
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
