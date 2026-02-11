import os
import shutil
import tarfile
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    filename='backup_system.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def create_local_backup():
    """
    Creates a full backup of the 'data' directory.
    """
    source_dir = 'data'
    backup_root = 'backups/staging'
    
    if not os.path.exists(source_dir):
        logging.error("Data directory not found!")
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"backup_full_{timestamp}"
    backup_path = os.path.join(backup_root, backup_name)
    
    os.makedirs(backup_root, exist_ok=True)
    
    try:
        # Create tar.gz
        tar_path = f"{backup_path}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(source_dir, arcname=os.path.basename(source_dir))
            
        logging.info(f"Local backup created: {tar_path}")
        return tar_path
    except Exception as e:
        logging.error(f"Backup failed: {e}")
        return None

if __name__ == "__main__":
    print("--- Starting Manual Backup ---")
    path = create_local_backup()
    if path:
        print(f"Backup created successfully at: {path}")
    else:
        print("Backup failed. Check backup_system.log")
