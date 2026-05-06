-- Run this in Supabase SQL Editor (pgvector additions only)
-- Skip if you already ran the full supabase_schema.sql before

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Embeddings table
CREATE TABLE IF NOT EXISTS public.embeddings (
    id             TEXT PRIMARY KEY,
    workspace_slug TEXT NOT NULL,
    username       TEXT NOT NULL,
    filename       TEXT NOT NULL,
    chunk_text     TEXT NOT NULL,
    embedding      vector(384),
    page_num       INTEGER,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Indexes
CREATE INDEX IF NOT EXISTS idx_embeddings_workspace
    ON public.embeddings (username, workspace_slug);

CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON public.embeddings
    USING hnsw (embedding vector_cosine_ops);

-- 4. RLS
ALTER TABLE public.embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can insert own embeddings" ON public.embeddings
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Users can select own embeddings" ON public.embeddings
    FOR SELECT USING (true);

CREATE POLICY "Users can delete own embeddings" ON public.embeddings
    FOR DELETE USING (true);

-- 5. match_embeddings RPC function
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

-- ============================================================
-- Query logs table for analytics and feedback
-- ============================================================

CREATE TABLE IF NOT EXISTS public.query_logs (
    id            SERIAL PRIMARY KEY,
    trace_id      TEXT NOT NULL,
    username      TEXT NOT NULL,
    workspace_slug TEXT NOT NULL,
    question      TEXT,
    latency_ms    FLOAT,
    chunks_retrieved  INT DEFAULT 0,
    chunks_after_rerank INT DEFAULT 0,
    query_variants INT DEFAULT 1,
    total_tokens  INT DEFAULT 0,
    status        TEXT DEFAULT 'OK',
    feedback      TEXT,  -- 'up' | 'down' | NULL
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_logs_user ON public.query_logs (username);
CREATE INDEX IF NOT EXISTS idx_query_logs_workspace ON public.query_logs (workspace_slug);

ALTER TABLE public.query_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on query_logs" ON public.query_logs
    USING (true) WITH CHECK (true);
