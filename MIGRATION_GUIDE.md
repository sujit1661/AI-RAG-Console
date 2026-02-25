# Code Migration Guide: Local Storage → Supabase

## What Has Been Added

✅ **New Files Created:**
- `requirements.txt` - Added Supabase dependencies
- `backend/supabase_config.py` - Supabase client configuration
- `backend/supabase_db.py` - Database operations (users, workspaces, chats, messages, documents)
- `backend/supabase_storage.py` - File storage operations
- `supabase_schema.sql` - Database schema (run in Supabase SQL Editor)
- `migrate_to_supabase.py` - Script to migrate existing data
- `SUPABASE_SETUP.md` - Setup instructions

## What You Need to Replace

### 1. **Update `backend/auth.py`**

**REPLACE:**
- `load_sessions()` / `save_sessions()` functions
- `load_users()` / `save_users()` functions
- File-based session management

**WITH:**
- Supabase Auth API calls
- Use `supabase.auth.sign_in_with_password()` for login
- Use `supabase.auth.sign_up()` for registration
- Use `supabase.auth.get_user()` for session verification
- Store user metadata in `users` table

**Key Changes:**
```python
# OLD: File-based
sessions = load_sessions()
sessions[token] = {...}
save_sessions(sessions)

# NEW: Supabase Auth
from supabase import create_client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
response = supabase.auth.sign_in_with_password({"email": email, "password": password})
```

### 2. **Update `app.py` - Workspace Functions**

**REPLACE:**
- `load_chats_metadata()` / `save_chats_metadata()` - File JSON operations
- `load_history()` / `save_history()` - File JSON operations
- `get_files()` - Filesystem directory listing

**WITH:**
- `backend.supabase_db.get_workspace_chats()` - Get chats from database
- `backend.supabase_db.create_chat()` - Create chat in database
- `backend.supabase_db.get_chat_history()` - Get messages from database
- `backend.supabase_db.add_message()` - Add message to database
- `backend.supabase_db.get_workspace_documents()` - Get documents from database

**Key Changes:**
```python
# OLD: File-based
chats = load_chats_metadata(slug)
with open(path, "w") as f:
    json.dump(chats, f)

# NEW: Supabase
from backend.supabase_db import get_workspace_chats, create_chat
chats = get_workspace_chats(workspace_slug, user_id)
result = create_chat(workspace_slug, title, user_id)
```

### 3. **Update `app.py` - File Upload Endpoint**

**REPLACE:**
- Saving files to `uploads/{workspace}/` directory
- Local file path storage

**WITH:**
- Upload to Supabase Storage using `backend.supabase_storage.upload_file_to_supabase()`
- Store file metadata in `documents` table using `backend.supabase_db.add_document_metadata()`
- Return Supabase Storage path instead of local path

**Key Changes:**
```python
# OLD: Local storage
file_path = os.path.join(path, safe_filename)
with open(file_path, "wb") as buffer:
    shutil.copyfileobj(file.file, buffer)

# NEW: Supabase Storage
from backend.supabase_storage import upload_file_to_supabase
file_content = await file.read()
storage_path = upload_file_to_supabase(workspace_slug, filename, file_content)
add_document_metadata(workspace_slug, filename, storage_path, file_size, user_id)
```

### 4. **Update `app.py` - File Download/Delete**

**REPLACE:**
- `os.path.exists()` checks
- `os.remove()` for file deletion
- Direct file serving

**WITH:**
- `backend.supabase_storage.get_file_url()` - Get signed URL for download
- `backend.supabase_storage.delete_file_from_supabase()` - Delete from storage
- `backend.supabase_db.delete_document()` - Remove metadata

### 5. **Update Authentication Flow**

**REPLACE:**
- Custom session token generation
- Cookie-based session management
- `get_current_user()` dependency

**WITH:**
- Supabase JWT token handling
- Extract user from Supabase JWT: `supabase.auth.get_user(token)`
- Use Supabase user ID instead of username for ownership checks

**Key Changes:**
```python
# OLD: Custom token
token = create_session(username)
verify_session(token)

# NEW: Supabase Auth
response = supabase.auth.sign_in_with_password({"email": email, "password": password})
user = response.user
token = response.session.access_token
```

### 6. **Update All Endpoints to Use User ID**

**REPLACE:**
- `username: str = Depends(require_auth)` - Returns username
- Workspace ownership checks using username

**WITH:**
- Get user ID from Supabase token
- Use `user_id` (UUID) for all ownership checks
- Update RLS policies ensure users only see their own data

**Key Changes:**
```python
# OLD: Username-based
username = get_current_user(token)
workspace = get_workspace(slug, username)

# NEW: User ID-based
user_id = get_user_id_from_token(token)  # Returns UUID
workspace = get_workspace(slug, user_id)
```

## Migration Checklist

- [ ] Install Supabase dependencies: `pip install -r requirements.txt`
- [ ] Create Supabase project and get API keys
- [ ] Run `supabase_schema.sql` in Supabase SQL Editor
- [ ] Create storage bucket named `documents`
- [ ] Create `.env` file with Supabase credentials
- [ ] Update `backend/auth.py` to use Supabase Auth
- [ ] Update `app.py` workspace endpoints to use Supabase DB
- [ ] Update `app.py` file upload to use Supabase Storage
- [ ] Update `app.py` chat endpoints to use Supabase DB
- [ ] Update authentication to return user_id instead of username
- [ ] Test user registration/login
- [ ] Test workspace creation
- [ ] Test file upload/download
- [ ] Test chat creation/messaging
- [ ] Run migration script if you have existing data
- [ ] Remove old file-based code (optional cleanup)

## Important Notes

1. **User IDs are UUIDs**: Supabase uses UUIDs for user IDs, not usernames. Update all ownership checks.

2. **RLS is Enabled**: Row Level Security ensures users can only access their own data. The SQL schema includes policies.

3. **Storage is Private**: Files in Supabase Storage are private by default. Use signed URLs for temporary access.

4. **Keep ChromaDB Local**: Vector database (ChromaDB) can stay local for now, or migrate to pgvector later.

5. **Backward Compatibility**: You can keep both systems running during migration, then switch over.

## Testing After Migration

1. Create a new user account
2. Create a workspace
3. Upload a document
4. Create a chat
5. Send messages
6. Verify data appears in Supabase dashboard
7. Verify files appear in Supabase Storage

