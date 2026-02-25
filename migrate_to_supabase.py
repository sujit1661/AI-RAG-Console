"""
Migration script to move existing local data to Supabase.
Run this once after setting up Supabase to migrate existing data.
"""
import os
import json
from datetime import datetime
from backend.supabase_config import init_supabase, get_supabase
from backend.supabase_db import (
    create_workspace, create_chat, add_message, add_document_metadata,
    create_user_supabase, get_user_by_username, get_workspace
)
from backend.supabase_storage import upload_file_to_supabase

def get_user_id_interactive():
    """Interactive function to get or create user ID."""
    supabase = get_supabase()
    
    print("\n" + "=" * 60)
    print("USER SETUP")
    print("=" * 60)
    print("\nYou need a Supabase user ID to migrate data.")
    print("Options:")
    print("1. Use existing Supabase user (enter email)")
    print("2. Create new user from users.json")
    print("3. Enter user ID directly (if you know it)")
    
    choice = input("\nEnter choice (1/2/3): ").strip()
    
    if choice == "1":
        email = input("Enter Supabase user email: ").strip()
        try:
            # Try to get user by email
            response = supabase.auth.admin.list_users()
            for user in response.users:
                if user.email == email:
                    print(f"✓ Found user: {user.id}")
                    return user.id
            print(f"✗ User with email {email} not found")
            return None
        except Exception as e:
            print(f"✗ Error: {e}")
            return None
    
    elif choice == "2":
        if not os.path.exists("users.json"):
            print("✗ users.json not found")
            return None
        
        with open("users.json", "r") as f:
            users = json.load(f)
        
        print("\nAvailable users:")
        for i, (username, data) in enumerate(users.items(), 1):
            email = data.get("email", f"{username}@example.com")
            print(f"  {i}. {username} ({email})")
        
        username = input("\nEnter username to create in Supabase: ").strip()
        if username not in users:
            print(f"✗ Username {username} not found in users.json")
            return None
        
        user_data = users[username]
        email = user_data.get("email", f"{username}@example.com")
        password = input(f"Enter password for {username} (or press Enter to use 'password123'): ").strip() or "password123"
        
        print(f"\nCreating user {username} in Supabase...")
        result = create_user_supabase(username, email, password)
        if result["success"]:
            user_id = result["user"].id
            print(f"✓ User created: {user_id}")
            print(f"  Email: {email}")
            print(f"  Password: {password}")
            print("\n⚠️  IMPORTANT: Save these credentials!")
            return user_id
        else:
            print(f"✗ Error creating user: {result.get('error')}")
            return None
    
    elif choice == "3":
        user_id = input("Enter user ID (UUID): ").strip()
        if user_id:
            print(f"✓ Using user ID: {user_id}")
            return user_id
        return None
    
    else:
        print("✗ Invalid choice")
        return None

def migrate_workspaces(user_id: str):
    """Migrate workspaces from uploads/ folders to Supabase."""
    upload_root = "uploads"
    if not os.path.exists(upload_root):
        print("No uploads folder found, skipping workspace migration.")
        return []
    
    workspaces = [d for d in os.listdir(upload_root) 
                  if os.path.isdir(os.path.join(upload_root, d))]
    
    if not workspaces:
        print("No workspaces found to migrate.")
        return []
    
    print(f"\nFound {len(workspaces)} workspaces to migrate:")
    for ws in workspaces:
        print(f"  - {ws}")
    
    migrated = []
    for ws_slug in workspaces:
        # Check if workspace already exists
        existing = get_workspace(ws_slug, user_id)
        if existing:
            print(f"⚠️  Workspace '{ws_slug}' already exists, skipping...")
            migrated.append(ws_slug)
            continue
        
        result = create_workspace(user_id, ws_slug, ws_slug)
        if result["success"]:
            print(f"✓ Migrated workspace: {ws_slug}")
            migrated.append(ws_slug)
        else:
            print(f"✗ Error migrating {ws_slug}: {result.get('error')}")
    
    return migrated

def migrate_chats(workspace_slug: str, user_id: str):
    """Migrate chats from workspace folder to Supabase."""
    chats_file = os.path.join("uploads", workspace_slug, "chats.json")
    if not os.path.exists(chats_file):
        print(f"  No chats.json found for {workspace_slug}")
        return 0
    
    with open(chats_file, "r") as f:
        chats = json.load(f)
    
    if not chats:
        print(f"  No chats to migrate for {workspace_slug}")
        return 0
    
    print(f"  Migrating {len(chats)} chats from {workspace_slug}...")
    migrated_count = 0
    
    for chat_data in chats:
        old_chat_id = chat_data.get("id")
        title = chat_data.get("title", "Migrated Chat")
        
        # Create chat in Supabase
        result = create_chat(workspace_slug, title, user_id)
        if not result["success"]:
            print(f"    ✗ Error creating chat '{title}': {result.get('error')}")
            continue
        
        new_chat_id = result["chat"]["id"]
        migrated_count += 1
        
        # Migrate messages
        chat_history_file = os.path.join("uploads", workspace_slug, f"chat_{old_chat_id}.json")
        legacy_history_file = os.path.join("uploads", workspace_slug, "history.json")
        
        messages = []
        if os.path.exists(chat_history_file):
            with open(chat_history_file, "r") as f:
                messages = json.load(f)
        elif os.path.exists(legacy_history_file):
            with open(legacy_history_file, "r") as f:
                messages = json.load(f)
        
        if messages:
            msg_count = 0
            for msg in messages:
                if msg.get("role") in ["user", "assistant"]:
                    add_message(new_chat_id, msg.get("role"), msg.get("content", ""))
                    msg_count += 1
            print(f"    ✓ Migrated chat '{title}' with {msg_count} messages")
        else:
            print(f"    ✓ Migrated chat '{title}' (no messages)")
    
    return migrated_count

def migrate_documents(workspace_slug: str, user_id: str):
    """Migrate documents from workspace folder to Supabase Storage."""
    workspace_path = os.path.join("uploads", workspace_slug)
    if not os.path.exists(workspace_path):
        return 0
    
    # Get list of files (exclude system files)
    excluded = {"chats.json", "history.json"}
    excluded_prefixes = {"chat_"}
    
    files = [f for f in os.listdir(workspace_path)
             if os.path.isfile(os.path.join(workspace_path, f))
             and f not in excluded
             and not any(f.startswith(p) for p in excluded_prefixes)]
    
    if not files:
        print(f"  No documents to migrate for {workspace_slug}")
        return 0
    
    print(f"  Migrating {len(files)} documents from {workspace_slug}...")
    migrated_count = 0
    
    for filename in files:
        file_path = os.path.join(workspace_path, filename)
        file_size = os.path.getsize(file_path)
        
        try:
            # Read file
            with open(file_path, "rb") as f:
                file_content = f.read()
            
            # Upload to Supabase Storage
            storage_path = upload_file_to_supabase(workspace_slug, filename, file_content)
            if storage_path:
                # Add metadata to database
                result = add_document_metadata(workspace_slug, filename, storage_path, file_size, user_id)
                if result["success"]:
                    print(f"    ✓ Migrated document: {filename} ({file_size} bytes)")
                    migrated_count += 1
                else:
                    print(f"    ✗ Error adding metadata for {filename}: {result.get('error')}")
            else:
                print(f"    ✗ Error uploading {filename} to Supabase Storage")
        except Exception as e:
            print(f"    ✗ Error migrating {filename}: {e}")
    
    return migrated_count

def main():
    """Main migration function."""
    print("=" * 60)
    print("Supabase Migration Script")
    print("=" * 60)
    print()
    
    # Initialize Supabase
    try:
        init_supabase()
        print("✓ Supabase connection initialized")
    except Exception as e:
        print(f"✗ Error initializing Supabase: {e}")
        print("\nMake sure SUPABASE_URL and SUPABASE_SERVICE_KEY are set in .env")
        print("Check SUPABASE_SETUP.md for setup instructions.")
        return
    
    # Get user ID
    user_id = get_user_id_interactive()
    if not user_id:
        print("\n✗ Cannot proceed without user ID. Exiting.")
        return
    
    print("\n" + "=" * 60)
    print("STARTING MIGRATION")
    print("=" * 60)
    
    # Migrate workspaces
    print("\n[1/3] Migrating workspaces...")
    migrated_workspaces = migrate_workspaces(user_id)
    
    if not migrated_workspaces:
        print("\n⚠️  No workspaces to migrate. Exiting.")
        return
    
    # Migrate chats and documents for each workspace
    total_chats = 0
    total_docs = 0
    
    print("\n[2/3] Migrating chats...")
    for ws_slug in migrated_workspaces:
        print(f"\nWorkspace: {ws_slug}")
        chat_count = migrate_chats(ws_slug, user_id)
        total_chats += chat_count
    
    print("\n[3/3] Migrating documents...")
    for ws_slug in migrated_workspaces:
        print(f"\nWorkspace: {ws_slug}")
        doc_count = migrate_documents(ws_slug, user_id)
        total_docs += doc_count
    
    # Summary
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Workspaces migrated: {len(migrated_workspaces)}")
    print(f"Chats migrated: {total_chats}")
    print(f"Documents migrated: {total_docs}")
    print("\n✓ All data has been migrated to Supabase!")
    print("\nNext steps:")
    print("1. Verify data in Supabase dashboard")
    print("2. Update your app.py to use Supabase functions")
    print("3. Test the application")

if __name__ == "__main__":
    main()

