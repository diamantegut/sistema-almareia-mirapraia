import os
import shutil
import time
import subprocess
import datetime
import logging
import sys
import json
import requests

import sys
# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from system_config_manager import BASE_DIR

# Configuration
SOURCE_DIR = BASE_DIR
# DEST_DIR = r"G:\Almareia Mirapraia Sistema Producao"
# ISOLATION: Use local path for dev/test environment or F: drive
DEST_DIR = r"F:\Sistema Almareia Mirapraia"
if os.path.exists(r"G:\Almareia Mirapraia Sistema Producao"):
    DEST_DIR = r"G:\Almareia Mirapraia Sistema Producao"
BACKUP_BASE_DIR = os.path.join(DEST_DIR, "backups")
LOG_FILE = os.path.join(SOURCE_DIR, "scripts", "deploy.log")
PYTHON_EXE = os.path.join(DEST_DIR, ".venv", "Scripts", "python.exe")

if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable  # Fallback

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE)
    ]
)

# Paths to preserve in Destination (Do not overwrite if exist)
PROTECTED_PATHS = [
    'data',
    'system_config.json',
    'Produtos', # Contains Fotos, careful
    'instance',
    'static/uploads',
    'backups',
    '.venv',
    '.git',
    '__pycache__',
    'deploy.log',
    'version.txt' # Maybe we want to update this? Let's say we update it.
]

# Paths to IGNORE from Source (Do not copy)
IGNORE_SOURCE = [
    '.venv',
    '.git',
    '__pycache__',
    'backups',
    'update_source',
    'scripts/deploy.log',
    'tests', # Maybe don't deploy tests to prod?
    '.pytest_cache'
]

def kill_python_processes():
    """Kills all python processes except the current one."""
    current_pid = os.getpid()
    logging.info(f"Stopping other Python processes (Current PID: {current_pid})...")
    try:
        subprocess.run(f'taskkill /F /IM python.exe /FI "PID ne {current_pid}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    except Exception as e:
        logging.warning(f"Error killing processes: {e}")

def create_backup():
    """Creates a timestamped backup of the destination directory."""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.join(BACKUP_BASE_DIR, f"backup_{timestamp}")
    
    logging.info(f"Creating backup at {backup_dir}...")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    for item in os.listdir(DEST_DIR):
        if item == 'backups': continue
        
        src = os.path.join(DEST_DIR, item)
        dst = os.path.join(backup_dir, item)
        
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except PermissionError:
            logging.warning(f"Could not backup {item} (Permission Error)")
        except Exception as e:
            logging.warning(f"Could not backup {item}: {e}")
            
    return backup_dir

def is_protected(path, relative_to):
    rel = os.path.relpath(path, relative_to)
    for p in PROTECTED_PATHS:
        if rel == p or rel.startswith(p + os.sep):
            return True
    return False

def should_ignore_source(path, relative_to):
    rel = os.path.relpath(path, relative_to)
    for i in IGNORE_SOURCE:
        if rel == i or rel.startswith(i + os.sep):
            return True
    return False

def copy_updates():
    """Copies files from Source to Destination."""
    logging.info("Copying updates...")
    count = 0
    for root, dirs, files in os.walk(SOURCE_DIR):
        # Filter dirs in place to prevent walking into ignored ones
        dirs[:] = [d for d in dirs if not should_ignore_source(os.path.join(root, d), SOURCE_DIR)]
        
        rel_dir = os.path.relpath(root, SOURCE_DIR)
        dest_dir = os.path.join(DEST_DIR, rel_dir)
        
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
            
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(dest_dir, file)
            
            # Check ignore
            if should_ignore_source(src_file, SOURCE_DIR):
                continue
                
            # Check protected (Preserve Dest)
            # Logic: If protected and exists in dest, SKIP.
            # Exception: If it's code in a protected folder? No, protected means "User Data".
            if is_protected(dest_file, DEST_DIR) and os.path.exists(dest_file):
                # Special case: Products/Fotos - we might want to add NEW photos but not overwrite?
                # For now, strict preservation.
                continue
                
            try:
                shutil.copy2(src_file, dest_file)
                count += 1
            except Exception as e:
                logging.error(f"Failed to copy {src_file}: {e}")
                raise
    logging.info(f"Copied {count} files.")

def validate_integrity():
    """Checks JSON files in Destination data dir."""
    logging.info("Validating JSON integrity in Production...")
    data_dir = os.path.join(DEST_DIR, 'data')
    if not os.path.exists(data_dir):
        return True
    
    valid = True
    for f_name in os.listdir(data_dir):
        if f_name.endswith('.json'):
            path = os.path.join(data_dir, f_name)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    json.load(f)
            except Exception as e:
                logging.error(f"Corrupt JSON detected: {f_name} - {e}")
                valid = False
    return valid

def restore_backup(backup_dir):
    logging.warning("Restoring from backup...")
    # Logic to restore...
    # For now, simplistic restore
    for item in os.listdir(backup_dir):
        src = os.path.join(backup_dir, item)
        dst = os.path.join(DEST_DIR, item)
        if os.path.isdir(src):
            if os.path.exists(dst): shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            if os.path.exists(dst): os.remove(dst)
            shutil.copy2(src, dst)

def start_production_server():
    logging.info(f"Starting Production Server using {PYTHON_EXE}...")
    env = os.environ.copy()
    env['PORT'] = '5000'
    env['FLASK_ENV'] = 'production'
    
    # Redirect output to file for debugging
    log_path = os.path.join(DEST_DIR, "server_startup.log")
    with open(log_path, "w") as out:
        # Detach process but keep valid file handles
        subprocess.Popen([PYTHON_EXE, 'app.py'], cwd=DEST_DIR, env=env, stdout=out, stderr=out)

def test_functionality():
    logging.info("Testing functionality (Health Check)...")
    url = "http://localhost:5000"
    for i in range(30): # Increased to 30 attempts (~2 mins)
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                logging.info("Server responded with 200 OK.")
                return True
        except:
            pass
        time.sleep(2)
    
    # If failed, read log
    log_path = os.path.join(DEST_DIR, "server_startup.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                content = f.read()[-1000:] # Last 1000 chars
                logging.error(f"Server Startup Log (Last 1000 chars):\n{content}")
        except:
            pass
    return False

def main():
    logging.info("Starting Deployment to Production...")
    
    backup_dir = None
    try:
        # 1. Kill Processes (Handled by wrapper script)
        # kill_python_processes()
        
        # 2. Backup
        backup_dir = create_backup()
        
        # 3. Copy Updates
        copy_updates()
        
        # 4. Validate
        if not validate_integrity():
            raise Exception("Integrity Validation Failed")
            
        # 5. Start Server
        start_production_server()
        
        # 6. Test
        if not test_functionality():
            raise Exception("Functional Test Failed")
            
        logging.info("DEPLOYMENT SUCCESSFUL!")
        
    except Exception as e:
        logging.error(f"DEPLOYMENT FAILED: {e}")
        if backup_dir:
            restore_backup(backup_dir)
            logging.info("Rolled back to previous version.")
            # Try to restart anyway?
            start_production_server()

if __name__ == "__main__":
    main()
