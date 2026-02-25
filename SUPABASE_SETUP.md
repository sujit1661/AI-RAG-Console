# Supabase Setup Guide

## Step 1: Create Supabase Project

1. Go to https://supabase.com and sign up/login
2. Click "New Project"
3. Fill in:
   - **Name**: Your project name
   - **Database Password**: Choose a strong password (save it!)
   - **Region**: Choose closest to you
4. Wait for project to be created (2-3 minutes)

## Step 2: Get API Keys

1. Go to **Settings** → **API** in your Supabase project
2. Copy these values:
   - **Project URL** (e.g., `https://xxxxx.supabase.co`)
   - **service_role key** (secret key - keep it safe!)
   - **anon public key** (for frontend if needed)

## Step 3: Create Storage Bucket

1. Go to **Storage** in Supabase dashboard
2. Click **New bucket**
3. Name: `documents`
4. Make it **Private** (not public)
5. Click **Create bucket**

## Step 4: Set Up Database Schema

1. Go to **SQL Editor** in Supabase dashboard
2. Click **New query**
3. Copy and paste the entire contents of `supabase_schema.sql`
4. Click **Run** (or press Ctrl+Enter)
5. Verify tables were created in **Table Editor**

## Step 5: Configure Environment Variables

1. Create a `.env` file in your project root (copy from `.env.example` if it exists)
2. Add these variables:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key-here
SUPABASE_ANON_KEY=your-anon-key-here
STORAGE_BUCKET=documents
ADMIN_PASSWORD=admin123
```

3. **Never commit `.env` to git!** (It's already in `.gitignore`)

## Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 7: Create Your First User

You have two options:

### Option A: Use Supabase Auth UI
1. Go to **Authentication** → **Users** in Supabase dashboard
2. Click **Add user** → **Create new user**
3. Enter email and password
4. Copy the **User ID** (UUID) - you'll need it for migration

### Option B: Use Supabase Auth API
The app will handle user registration through Supabase Auth automatically.

## Step 8: Migrate Existing Data (Optional)

If you have existing data in `uploads/` and JSON files:

1. Open `migrate_to_supabase.py`
2. Uncomment the migration code
3. Set `user_id` to your Supabase user ID
4. Run: `python migrate_to_supabase.py`

## Step 9: Test Connection

Run your app and verify:
- Users can register/login
- Workspaces are created in Supabase
- Files upload to Supabase Storage
- Chats and messages save to database

## Troubleshooting

- **"SUPABASE_URL not set"**: Check your `.env` file exists and has correct values
- **"Permission denied"**: Make sure you're using `SUPABASE_SERVICE_KEY` (not anon key) for backend
- **"Table doesn't exist"**: Run the SQL schema in Supabase SQL Editor
- **"Bucket not found"**: Create the `documents` bucket in Storage

