-- Create the Supabase Storage bucket for BM25 pickle indexes.
-- Run this once in your Supabase SQL Editor.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'bm25-indexes',
    'bm25-indexes',
    false,
    52428800,
    ARRAY['application/octet-stream']
)
ON CONFLICT (id) DO NOTHING;

-- Allow service role full access (idempotent)
DROP POLICY IF EXISTS "service_all_bm25" ON storage.objects;
CREATE POLICY "service_all_bm25" ON storage.objects
    FOR ALL
    USING (bucket_id = 'bm25-indexes')
    WITH CHECK (bucket_id = 'bm25-indexes');
