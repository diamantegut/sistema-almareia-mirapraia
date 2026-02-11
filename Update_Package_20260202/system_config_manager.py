import json
import os

# Base directory is the directory containing this script (project root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'system_config.json')

DEFAULT_CONFIG = {
    'data_dir': 'data',
    'logs_dir': 'logs',
    'backups_dir': 'backups',
    'fiscal_dir': 'fiscal_documents',
    'uploads_dir': 'static/uploads/maintenance'
}

def load_system_config():
    """Loads the system configuration from system_config.json."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading system config: {e}")
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_system_config(config):
    """Saves the system configuration to system_config.json."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving system config: {e}")
        return False

def get_config_value(key, default=None):
    config = load_system_config()
    return config.get(key, default)

def get_data_path(filename):
    """Returns the full path for a data file, ensuring the directory exists."""
    config = load_system_config()
    data_dir = config.get('data_dir', 'data')
    
    # Ensure relative paths are relative to the project root
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(BASE_DIR, data_dir)
        
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
        
    return os.path.join(data_dir, filename)

def get_log_path(filename):
    config = load_system_config()
    logs_dir = config.get('logs_dir', 'logs')
    
    if not os.path.isabs(logs_dir):
        logs_dir = os.path.join(BASE_DIR, logs_dir)
        
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)
        
    return os.path.join(logs_dir, filename)

def get_backup_path(filename=''):
    config = load_system_config()
    backups_dir = config.get('backups_dir', 'backups')
    
    if not os.path.isabs(backups_dir):
        backups_dir = os.path.join(BASE_DIR, backups_dir)
        
    if not os.path.exists(backups_dir):
        os.makedirs(backups_dir, exist_ok=True)
        
    return os.path.join(backups_dir, filename)

def get_fiscal_path(subpath=''):
    config = load_system_config()
    fiscal_dir = config.get('fiscal_dir', 'fiscal_documents')
    
    if not os.path.isabs(fiscal_dir):
        fiscal_dir = os.path.join(BASE_DIR, fiscal_dir)
        
    if not os.path.exists(fiscal_dir):
        os.makedirs(fiscal_dir, exist_ok=True)
        
    return os.path.join(fiscal_dir, subpath)
