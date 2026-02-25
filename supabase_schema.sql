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

