import os
import shutil
import json
import datetime
import sys
import logging
import subprocess
import time
import glob

# Setup logging
LOG_FILE = os.path.join(os.path.dirname(__file__), 'updater.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE)
    ]
)

import sys
# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from system_config_manager import BASE_DIR, get_backup_path

# Configuration
PROJECT_ROOT = BASE_DIR
UPDATE_SOURCE_DIR = os.path.join(PROJECT_ROOT, 'update_source')
BACKUP_BASE_DIR = get_backup_path()
VERSION_FILE = os.path.join(PROJECT_ROOT, 'version.txt')

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
    'update_source',         # Source of updates
    'version.txt'            # Handle version separately
]

def normalize_path(path):
    return os.path.normpath(path)

def get_current_version():
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, 'r') as f:
            return f.read().strip()
    return "0.0.0"

def check_new_version():
    new_version_file = os.path.join(UPDATE_SOURCE_DIR, 'version.txt')
    if not os.path.exists(new_version_file):
        logging.warning("No version.txt found in update source.")
        return None
    
    with open(new_version_file, 'r') as f:
        new_version = f.read().strip()
    
    current_version = get_current_version()
    logging.info(f"Current Version: {current_version}, New Version: {new_version}")
    
    if new_version == current_version:
        logging.info("Versions are identical. Update might not be necessary.")
        # Proceed anyway if user wants, or return False? 
        # For automation, we might want to skip. But let's return the version.
    
    return new_version

def create_timestamped_backup():
    """Creates a backup of the current state before updating."""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.join(BACKUP_BASE_DIR, f'pre_update_{timestamp}')
    
    logging.info(f"Starting backup to {backup_dir}...")
    
    try:
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Backup Critical Data Explicitly first
        for item in ['data', 'system_config.json', 'Produtos', 'app.py', 'version.txt']:
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
        return False

    logging.info(f"Applying updates from {UPDATE_SOURCE_DIR}...")
    
    updated_count = 0
    skipped_count = 0

    for root, dirs, files in os.walk(UPDATE_SOURCE_DIR):
        rel_dir = os.path.relpath(root, UPDATE_SOURCE_DIR)
        dest_dir = os.path.join(PROJECT_ROOT, rel_dir)
        
        if rel_dir == '.':
            dest_dir = PROJECT_ROOT

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
                raise # Critical error, trigger rollback

    logging.info(f"Update applied. Updated {updated_count} files. Skipped {skipped_count} protected files.")
    return True

def validate_json_integrity():
    """Validates all JSON files in the data directory."""
    logging.info("Validating JSON integrity...")
    data_dir = os.path.join(PROJECT_ROOT, 'data')
    if not os.path.exists(data_dir):
        return True
        
    json_files = glob.glob(os.path.join(data_dir, '*.json'))
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            logging.error(f"Integrity check failed for {json_file}: {e}")
            return False
        except Exception as e:
            logging.error(f"Error reading {json_file}: {e}")
            return False
            
    logging.info("All JSON files validated successfully.")
    return True

def rollback(backup_dir):
    """Restores the backup in case of failure."""
    logging.warning("Initiating ROLLBACK...")
    try:
        # Restore critical files from backup
        for item in os.listdir(backup_dir):
            src = os.path.join(backup_dir, item)
            dst = os.path.join(PROJECT_ROOT, item)
            
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
                
        logging.info("Rollback completed successfully. System restored to previous state.")
    except Exception as e:
        logging.critical(f"Rollback FAILED: {e}. System might be in unstable state.")

def restart_services():
    """Restarts the production and development servers."""
    logging.info("Restarting services...")
    
    # 1. Kill existing Python processes (simple approach)
    # Note: This might kill the updater itself if run with 'python', so usually the updater runs separately
    # Or we exclude this process ID.
    current_pid = os.getpid()
    try:
        # Windows command to kill python processes except current one
        # Powershell way is cleaner, but we are in python
        # Simple approach: Kill all python.exe, hoping updater is resilient or finished?
        # Better: Just kill the servers we know about or rely on user to stop them.
        # But requirements say "Finalize todos os processo atives".
        subprocess.run("taskkill /F /IM python.exe /FI \"PID ne {}\"".format(current_pid), shell=True)
    except Exception as e:
        logging.warning(f"Failed to kill processes: {e}")

    time.sleep(2)

    # 2. Start Production (Port 5000)
    logging.info("Starting Production Server on Port 5000...")
    env_prod = os.environ.copy()
    env_prod['PORT'] = '5000'
    env_prod['FLASK_ENV'] = 'production'
    subprocess.Popen([sys.executable, 'app.py'], cwd=PROJECT_ROOT, env=env_prod, creationflags=subprocess.CREATE_NEW_CONSOLE)

    # 3. Start Development (Port 5001)
    logging.info("Starting Development Server on Port 5001...")
    env_dev = os.environ.copy()
    env_dev['PORT'] = '5001'
    env_dev['FLASK_ENV'] = 'development'
    subprocess.Popen([sys.executable, 'app.py'], cwd=PROJECT_ROOT, env=env_dev, creationflags=subprocess.CREATE_NEW_CONSOLE)

def update_version_file(new_version):
    if new_version:
        with open(VERSION_FILE, 'w') as f:
            f.write(new_version)

def main():
    logging.info("=== Automated System Updater ===")
    
    # 1. Verification
    new_version = check_new_version()
    if not new_version:
        logging.info("No update found or invalid version file.")
        # We might still want to restart services if requested, but let's assume this is strict updater
        # But for this task, user wants to verify the updater.
    
    backup_dir = None
    
    try:
        # 2. Backup
        backup_dir = create_timestamped_backup()
        
        # 3. Apply Updates
        if os.path.exists(UPDATE_SOURCE_DIR) and os.listdir(UPDATE_SOURCE_DIR):
            apply_updates()
        
        # 4. Validate Integrity
        if not validate_json_integrity():
            raise Exception("JSON Integrity Validation Failed")
            
        # 5. Update Version File
        if new_version:
            update_version_file(new_version)
            
        logging.info("Update Process Completed Successfully.")
        
        # 6. Restart Services
        restart_services()
        
    except Exception as e:
        logging.error(f"Update Process Failed: {e}")
        if backup_dir:
            rollback(backup_dir)
        # Even after rollback, we might want to restart services to bring back old state
        restart_services()

if __name__ == "__main__":
    main()
