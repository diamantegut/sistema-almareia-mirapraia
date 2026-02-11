import os
import shutil
import json
import datetime
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'updater.log'))
    ]
)

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPDATE_SOURCE_DIR = os.path.join(PROJECT_ROOT, 'update_source')
BACKUP_BASE_DIR = os.path.join(PROJECT_ROOT, 'backups')

# Files and directories that MUST NOT be overwritten by the update
PROTECTED_PATHS = [
    'data',                  # Main data directory
    'system_config.json',    # System configuration
    'Produtos/Fotos',        # Product images
    'instance',              # Flask instance folder (secrets)
    'static/uploads',        # User uploads
    'scripts',               # Scripts (including this one)
    'backups',               # Backups themselves
    'venv',                  # Virtual environment
    '.git',                  # Git history
    'update_source'          # Source of updates
]

def normalize_path(path):
    return os.path.normpath(path)

def create_timestamped_backup():
    """Creates a backup of the current state before updating."""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.join(BACKUP_BASE_DIR, f'pre_update_{timestamp}')
    
    logging.info(f"Starting backup to {backup_dir}...")
    
    try:
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Backup Critical Data Explicitly first
        for item in ['data', 'system_config.json', 'Produtos']:
            src = os.path.join(PROJECT_ROOT, item)
            dst = os.path.join(backup_dir, item)
            
            if os.path.exists(src):
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        
        logging.info("Backup completed successfully.")
        return backup_dir
    except Exception as e:
        logging.error(f"Backup failed: {e}")
        raise

def should_skip(path):
    """Check if the path should be skipped during update copy."""
    rel_path = os.path.relpath(path, UPDATE_SOURCE_DIR)
    
    # Check if this file/dir corresponds to a protected path in the destination
    for protected in PROTECTED_PATHS:
        # Check exact match or subdirectory
        if rel_path == protected or rel_path.startswith(protected + os.sep):
            return True
    return False

def apply_updates():
    """Copies files from update_source to project root, respecting protected paths."""
    if not os.path.exists(UPDATE_SOURCE_DIR):
        logging.warning(f"Update source directory '{UPDATE_SOURCE_DIR}' not found.")
        logging.info("Please create 'update_source' folder and place the new version files there.")
        return False

    logging.info(f"Applying updates from {UPDATE_SOURCE_DIR}...")
    
    updated_count = 0
    skipped_count = 0

    for root, dirs, files in os.walk(UPDATE_SOURCE_DIR):
        # Calculate relative path to project root
        rel_dir = os.path.relpath(root, UPDATE_SOURCE_DIR)
        dest_dir = os.path.join(PROJECT_ROOT, rel_dir)
        
        if rel_dir == '.':
            dest_dir = PROJECT_ROOT

        # Filter directories to skip traversing into protected ones
        # We modify 'dirs' in-place to prevent os.walk from entering them
        dirs[:] = [d for d in dirs if not should_skip(os.path.join(root, d))]

        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        for file in files:
            src_file = os.path.join(root, file)
            
            if should_skip(src_file):
                logging.info(f"Skipping protected file: {src_file}")
                skipped_count += 1
                continue
                
            dest_file = os.path.join(dest_dir, file)
            
            try:
                shutil.copy2(src_file, dest_file)
                updated_count += 1
            except Exception as e:
                logging.error(f"Failed to copy {src_file} to {dest_file}: {e}")

    logging.info(f"Update applied. Updated {updated_count} files. Skipped {skipped_count} protected files.")
    return True

def migrate_menu_items():
    """Ensures menu_items.json has all required fields (e.g., 'paused')."""
    menu_file = os.path.join(PROJECT_ROOT, 'data', 'menu_items.json')
    if not os.path.exists(menu_file):
        return

    logging.info("Checking menu_items.json for migrations...")
    try:
        with open(menu_file, 'r', encoding='utf-8') as f:
            items = json.load(f)
        
        changed = False
        for item in items:
            # Migration 1: Add 'paused' field
            if 'paused' not in item:
                item['paused'] = False
                changed = True
            
            # Migration 2: Add 'active' field
            if 'active' not in item:
                item['active'] = True
                changed = True

        if changed:
            # Create a safety backup of just this file before writing
            shutil.copy2(menu_file, menu_file + '.migrated_bak')
            
            with open(menu_file, 'w', encoding='utf-8') as f:
                json.dump(items, f, indent=4, ensure_ascii=False)
            logging.info("Migrated menu_items.json: Added missing fields.")
        else:
            logging.info("menu_items.json is up to date.")

    except Exception as e:
        logging.error(f"Error migrating menu_items.json: {e}")

def main():
    print("=== System Safe Updater ===")
    print(f"Project Root: {PROJECT_ROOT}")
    print("This script will:")
    print("1. Backup critical data (data/, config, photos)")
    print("2. Apply updates from 'update_source/' folder (if it exists)")
    print("3. Migrate data schemas (add missing fields)")
    print("---------------------------")
    
    confirm = input("Do you want to proceed? (y/n): ")
    if confirm.lower() != 'y':
        print("Update cancelled.")
        return

    # Step 1: Backup
    try:
        print("Creating backup...")
        backup_path = create_timestamped_backup()
        print(f"Backup created at: {backup_path}")
    except Exception as e:
        print(f"CRITICAL: Backup failed. Aborting update. Error: {e}")
        return

    # Step 2: Update Code
    if os.path.exists(UPDATE_SOURCE_DIR) and os.listdir(UPDATE_SOURCE_DIR):
        print("Applying code updates...")
        apply_updates()
    else:
        print("No update files found in 'update_source/'. Skipping code update.")
        print("Tip: Place new version files in 'update_source' folder to update code next time.")

    # Step 3: Migrate Data
    print("Running data migrations...")
    migrate_menu_items()
    
    print("=== Update Process Completed Successfully ===")

if __name__ == "__main__":
    main()
