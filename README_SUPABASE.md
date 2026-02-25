# Supabase Integration - Quick Start

## ✅ What Has Been Added to Your Project

All required Supabase components have been added:

1. **`requirements.txt`** - Supabase Python packages added
2. **`backend/supabase_config.py`** - Configuration and client setup
3. **`backend/supabase_db.py`** - Database operations (workspaces, chats, messages, documents)
4. **`backend/supabase_storage.py`** - File storage operations
5. **`supabase_schema.sql`** - Database schema to run in Supabase
6. **`migrate_to_supabase.py`** - Script to migrate existing data
7. **`SUPABASE_SETUP.md`** - Step-by-step setup instructions
8. **`MIGRATION_GUIDE.md`** - Detailed code replacement guide

## 🚀 Next Steps

### Step 1: Set Up Supabase (5 minutes)

1. **Create Account**: Go to https://supabase.com and sign up
2. **Create Project**: Click "New Project", fill in details, wait 2-3 minutes
3. **Get API Keys**: 
   - Go to Settings → API
   - Copy: Project URL, service_role key, anon key
4. **Create Storage Bucket**:
   - Go to Storage → New bucket
   - Name: `documents`, make it Private
5. **Run Database Schema**:
   - Go to SQL Editor
   - Copy/paste contents of `supabase_schema.sql`
   - Click Run

### Step 2: Configure Environment

Create `.env` file in project root:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key
STORAGE_BUCKET=documents
ADMIN_PASSWORD=admin123
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Replace Code in Your App

**See `MIGRATION_GUIDE.md` for detailed instructions.**

Main files to update:
- `backend/auth.py` - Replace file-based auth with Supabase Auth
- `app.py` - Replace file operations with Supabase DB/Storage calls

**Key replacements:**
- `load_chats_metadata()` → `get_workspace_chats()`
- `save_history()` → `add_message()`
- Local file upload → `upload_file_to_supabase()`
- File-based sessions → Supabase Auth JWT tokens

### Step 5: Test

1. Start your app: `uvicorn app:app --reload`
2. Register a new user
3. Create a workspace
4. Upload a document
5. Create a chat and send messages
6. Verify data in Supabase dashboard

## 📋 Files You Need to Modify

1. **`backend/auth.py`** - Replace all file operations with Supabase Auth
2. **`app.py`** - Replace workspace/chat/file operations with Supabase functions
3. **Update endpoints** - Change from username to user_id (UUID)

## 📚 Documentation Files

- **`SUPABASE_SETUP.md`** - Complete setup walkthrough
- **`MIGRATION_GUIDE.md`** - Detailed code replacement instructions
- **`supabase_schema.sql`** - Database schema (run in Supabase)

## ⚠️ Important Notes

- **User IDs are UUIDs**: Supabase uses UUIDs, not usernames
- **RLS Enabled**: Users automatically only see their own data
- **Storage is Private**: Use signed URLs for file access
- **Keep ChromaDB**: Vector DB can stay local for now

## 🆘 Need Help?

1. Check `SUPABASE_SETUP.md` for setup issues
2. Check `MIGRATION_GUIDE.md` for code replacement details
3. Verify `.env` file has correct Supabase credentials
4. Ensure database schema was run successfully

