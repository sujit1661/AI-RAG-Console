-- Run ONLY this in Supabase SQL Editor
-- (embeddings table already exists from previous run)

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
    feedback      TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_logs_user ON public.query_logs (username);
CREATE INDEX IF NOT EXISTS idx_query_logs_workspace ON public.query_logs (workspace_slug);

ALTER TABLE public.query_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on query_logs" ON public.query_logs
    USING (true) WITH CHECK (true);
