-- Run in Supabase SQL Editor.
-- Adds sessions table and workspace-meta tables needed for ephemeral-disk-free operation.

-- ============================================================
-- Sessions  (replaces sessions.json)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.sessions (
    token       TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_username   ON public.sessions(username);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON public.sessions(expires_at);

-- Auto-delete expired sessions (run as a cron or just let the app clean up)
-- Optional: pg_cron extension can run this periodically
-- SELECT cron.schedule('cleanup-sessions', '0 * * * *', $$DELETE FROM public.sessions WHERE expires_at < NOW()$$);

-- ============================================================
-- Workspace meta  (replaces .owner / .display_name files)
-- Already exists as public.workspaces — just need display_name column
-- ============================================================
ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS display_name TEXT;

-- ============================================================
-- Chats metadata  (replaces chats.json — already public.chats, add missing cols)
-- ============================================================
-- chats table already exists, nothing new needed.

-- ============================================================
-- Chat messages / history  (replaces chat_{id}.json)
-- Already public.messages — verify it has what we need.
-- ============================================================
-- messages table already exists, nothing new needed.

-- ============================================================
-- RLS policies for new tables
-- ============================================================
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_all" ON public.sessions;
CREATE POLICY "service_all" ON public.sessions FOR ALL USING (true) WITH CHECK (true);
