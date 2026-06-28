-- RBAC Migration — run once in Supabase SQL Editor
-- Adds role column to users, creates admin_logs table for audit trail

-- 1. Add role column to users
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'
  CHECK (role IN ('admin', 'user'));

-- 2. Make the first/admin user an admin (if ADMIN_PASSWORD was set during init)
UPDATE public.users SET role = 'admin' WHERE username = 'admin';

-- 3. Admin audit log table
CREATE TABLE IF NOT EXISTS public.admin_logs (
    id          BIGSERIAL PRIMARY KEY,
    admin_user  TEXT NOT NULL,
    action      TEXT NOT NULL,        -- e.g. 'delete_user', 'change_role'
    target_user TEXT,
    detail      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON public.admin_logs(admin_user);
CREATE INDEX IF NOT EXISTS idx_admin_logs_created ON public.admin_logs(created_at DESC);

-- RLS for admin_logs (service role bypasses, same as other tables)
ALTER TABLE public.admin_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_all" ON public.admin_logs FOR ALL USING (true) WITH CHECK (true);
