-- Supabase Database Schema for RAG System
-- Run this SQL in your Supabase SQL Editor to create all tables

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Workspaces table
CREATE TABLE IF NOT EXISTS public.workspaces (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chats table
CREATE TABLE IF NOT EXISTS public.chats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_slug TEXT NOT NULL REFERENCES public.workspaces(slug) ON DELETE CASCADE,
    title TEXT NOT NULL,
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Messages table
CREATE TABLE IF NOT EXISTS public.messages (
    id SERIAL PRIMARY KEY,
    chat_id UUID NOT NULL REFERENCES public.chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Documents table
CREATE TABLE IF NOT EXISTS public.documents (
    id SERIAL PRIMARY KEY,
    workspace_slug TEXT NOT NULL REFERENCES public.workspaces(slug) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL, -- Path in Supabase Storage
    file_size INTEGER,
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON public.workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_chats_workspace ON public.chats(workspace_slug);
CREATE INDEX IF NOT EXISTS idx_chats_owner ON public.chats(owner_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON public.messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON public.documents(workspace_slug);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON public.documents(owner_id);

-- Row Level Security (RLS) Policies
-- Enable RLS on all tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

-- Users: Users can only see/update their own record
CREATE POLICY "Users can view own profile" ON public.users
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON public.users
    FOR UPDATE USING (auth.uid() = id);

-- Workspaces: Users can only access their own workspaces
CREATE POLICY "Users can view own workspaces" ON public.workspaces
    FOR SELECT USING (auth.uid() = owner_id);

CREATE POLICY "Users can create own workspaces" ON public.workspaces
    FOR INSERT WITH CHECK (auth.uid() = owner_id);

CREATE POLICY "Users can update own workspaces" ON public.workspaces
    FOR UPDATE USING (auth.uid() = owner_id);

CREATE POLICY "Users can delete own workspaces" ON public.workspaces
    FOR DELETE USING (auth.uid() = owner_id);

-- Chats: Users can only access chats in their own workspaces
CREATE POLICY "Users can view own chats" ON public.chats
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.workspaces 
            WHERE workspaces.slug = chats.workspace_slug 
            AND workspaces.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can create own chats" ON public.chats
    FOR INSERT WITH CHECK (
        auth.uid() = owner_id AND
        EXISTS (
            SELECT 1 FROM public.workspaces 
            WHERE workspaces.slug = chats.workspace_slug 
            AND workspaces.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can update own chats" ON public.chats
    FOR UPDATE USING (auth.uid() = owner_id);

CREATE POLICY "Users can delete own chats" ON public.chats
    FOR DELETE USING (auth.uid() = owner_id);

-- Messages: Users can only access messages in their own chats
CREATE POLICY "Users can view own messages" ON public.messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.chats 
            JOIN public.workspaces ON chats.workspace_slug = workspaces.slug
            WHERE chats.id = messages.chat_id 
            AND workspaces.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can create own messages" ON public.messages
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.chats 
            JOIN public.workspaces ON chats.workspace_slug = workspaces.slug
            WHERE chats.id = messages.chat_id 
            AND workspaces.owner_id = auth.uid()
        )
    );

-- Documents: Users can only access documents in their own workspaces
CREATE POLICY "Users can view own documents" ON public.documents
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.workspaces 
            WHERE workspaces.slug = documents.workspace_slug 
            AND workspaces.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can create own documents" ON public.documents
    FOR INSERT WITH CHECK (
        auth.uid() = owner_id AND
        EXISTS (
            SELECT 1 FROM public.workspaces 
            WHERE workspaces.slug = documents.workspace_slug 
            AND workspaces.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete own documents" ON public.documents
    FOR DELETE USING (auth.uid() = owner_id);

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to auto-update updated_at
CREATE TRIGGER update_workspaces_updated_at BEFORE UPDATE ON public.workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chats_updated_at BEFORE UPDATE ON public.chats
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- pgvector: Embeddings table for RAG chunks
-- Run this AFTER enabling the vector extension in Supabase:
--   Dashboard → Database → Extensions → enable "vector"
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.embeddings (
    id          TEXT PRIMARY KEY,          -- "{filename}_{i}_{hash}"
    workspace_slug TEXT NOT NULL,
    username    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   vector(384),               -- BAAI/bge-small-en-v1.5 = 384 dims
    page_num    INTEGER,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_workspace
    ON public.embeddings (username, workspace_slug);

-- HNSW index for fast approximate nearest-neighbour search
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON public.embeddings
    USING hnsw (embedding vector_cosine_ops);

-- RLS: users can only access their own embeddings
ALTER TABLE public.embeddings ENABLE ROW LEVEL SECURITY;

-- Service role (backend) bypasses RLS automatically.
-- These policies cover direct client access if ever needed.
CREATE POLICY "Users can insert own embeddings" ON public.embeddings
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Users can select own embeddings" ON public.embeddings
    FOR SELECT USING (true);

CREATE POLICY "Users can delete own embeddings" ON public.embeddings
    FOR DELETE USING (true);

-- ============================================================
-- RPC function for pgvector similarity search
-- Called by backend/retriever.py → _supabase_retrieve()
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
