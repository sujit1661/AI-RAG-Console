-- Create the Supabase Storage bucket for BM25 pickle indexes.
-- Run this once in your Supabase SQL Editor.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'bm25-indexes',
    'bm25-indexes',
    false,                          -- private bucket, service key only
    52428800,                       -- 50 MB per file
    ARRAY['application/octet-stream']
)
ON CONFLICT (id) DO NOTHING;

-- Allow service role full access (service key bypasses RLS anyway,
-- but explicit policy avoids any future surprises)
CREATE POLICY "service_all_bm25" ON storage.objects
    FOR ALL
    USING (bucket_id = 'bm25-indexes')
    WITH CHECK (bucket_id = 'bm25-indexes');
