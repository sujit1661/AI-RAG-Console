# How to Run the Migration

## Quick Start

1. **Make sure Supabase is set up:**
   - ✅ Supabase project created
   - ✅ Database schema run (`supabase_schema.sql`)
   - ✅ Storage bucket `documents` created
   - ✅ `.env` file configured with Supabase credentials

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the migration script:**
   ```bash
   python migrate_to_supabase.py
   ```

## What the Script Does

The migration script will:

1. **Ask you to set up a user:**
   - Option 1: Use existing Supabase user (enter email)
   - Option 2: Create new user from `users.json` 
   - Option 3: Enter user ID directly

2. **Migrate all workspaces** from `uploads/` folder

3. **Migrate all chats** from each workspace (including messages)

4. **Migrate all documents** from each workspace to Supabase Storage

## Example Output

```
============================================================
Supabase Migration Script
============================================================

✓ Supabase connection initialized

============================================================
USER SETUP
============================================================

You need a Supabase user ID to migrate data.
Options:
1. Use existing Supabase user (enter email)
2. Create new user from users.json
3. Enter user ID directly (if you know it)

Enter choice (1/2/3): 2

Available users:
  1. admin (admin@example.com)
  2. sujit (gg@gmail.com)

Enter username to create in Supabase: sujit
Enter password for sujit (or press Enter to use 'password123'): 

Creating user sujit in Supabase...
✓ User created: abc123-def456-...
  Email: gg@gmail.com
  Password: password123

⚠️  IMPORTANT: Save these credentials!

============================================================
STARTING MIGRATION
============================================================

[1/3] Migrating workspaces...

Found 7 workspaces to migrate:
  - 1111
  - abcd
  - shreyas
  - sssss
  - sujit
  - ws-a
  - ws-b
✓ Migrated workspace: 1111
✓ Migrated workspace: abcd
...

[2/3] Migrating chats...

Workspace: ws-a
  Migrating 2 chats from ws-a...
    ✓ Migrated chat 'hello alpha?' with 2 messages
    ✓ Migrated chat 'hello beta?' with 2 messages

[3/3] Migrating documents...

Workspace: sujit
  Migrating 1 documents from sujit...
    ✓ Migrated document: week3_4 submission.pdf (123456 bytes)

============================================================
MIGRATION COMPLETE
============================================================
Workspaces migrated: 7
Chats migrated: 2
Documents migrated: 1

✓ All data has been migrated to Supabase!
```

## Troubleshooting

**"Error initializing Supabase"**
- Check your `.env` file has correct `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
- Make sure you're using the **service_role** key (not anon key)

**"User not found" or "Permission denied"**
- Make sure you've run the database schema in Supabase SQL Editor
- Check that RLS policies are enabled (they're in the schema)

**"Bucket not found"**
- Create the `documents` bucket in Supabase Storage
- Make sure it's set to Private

**"Workspace already exists"**
- The script will skip workspaces that already exist
- This is safe - it won't duplicate data

## After Migration

1. **Verify in Supabase Dashboard:**
   - Check Tables → workspaces, chats, messages, documents
   - Check Storage → documents bucket

2. **Update your app code:**
   - Follow `MIGRATION_GUIDE.md` to replace file operations with Supabase functions

3. **Test your app:**
   - Register/login should work with Supabase Auth
   - Workspaces should load from Supabase
   - Files should download from Supabase Storage

