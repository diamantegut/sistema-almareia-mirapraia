import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'system_config.json')

DEFAULT_CONFIG = {
    'data_dir': 'data',
    'logs_dir': 'logs',
    'backups_dir': 'backups',
    'fiscal_dir': 'Fiscal',
    'uploads_dir': 'static/uploads/maintenance'
}


def load_system_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG


def save_system_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception:
        return False


def get_config_value(key, default=None):
    config = load_system_config()
    return config.get(key, default)


def get_data_path(filename):
    config = load_system_config()
    data_dir = config.get('data_dir', 'data')
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
    fiscal_dir = config.get('fiscal_dir', 'Fiscal')
    if not os.path.isabs(fiscal_dir):
        fiscal_dir = os.path.join(BASE_DIR, fiscal_dir)
    if not os.path.exists(fiscal_dir):
        os.makedirs(fiscal_dir, exist_ok=True)
    return os.path.join(fiscal_dir, subpath)

