import json
import os

# Base directory is the directory containing this script (project root)
# Refactored: Now inside app/services, so root is two levels up
current_dir = os.path.dirname(os.path.abspath(__file__))
# app/services -> app -> root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))) if os.path.basename(os.path.dirname(current_dir)) == 'services' else os.path.dirname(current_dir)

# Fix for when we are running from root but importing from app.services
# If current_dir ends with 'services', go up 2 levels.
if current_dir.endswith('services'):
    BASE_DIR = os.path.dirname(os.path.dirname(current_dir))

CONFIG_FILE = os.path.join(BASE_DIR, 'system_config.json')

DEFAULT_CONFIG = {
    'data_dir': 'data',
    'logs_dir': 'logs',
    'backups_dir': 'backups',
    'fiscal_dir': 'fiscal_documents',
    'uploads_dir': 'static/uploads/maintenance', # Updated path
    'sales_excel_path': '' # Deprecated or handled via upload
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
        try:
            os.makedirs(data_dir)
        except Exception as e:
            print(f"Error creating data directory: {e}")
            
    return os.path.join(data_dir, filename)

def get_log_path(filename):
    """Returns the full path for a log file, ensuring the directory exists."""
    config = load_system_config()
    logs_dir = config.get('logs_dir', 'logs')
    
    if not os.path.isabs(logs_dir):
        logs_dir = os.path.join(BASE_DIR, logs_dir)
        
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)
        
    return os.path.join(logs_dir, filename)

def get_backup_path(subpath=''):
    """Returns the full path for backups, ensuring the directory exists."""
    config = load_system_config()
    backups_dir = config.get('backups_dir', 'backups')
    
    if not os.path.isabs(backups_dir):
        backups_dir = os.path.join(BASE_DIR, backups_dir)
        
    if not os.path.exists(backups_dir):
        os.makedirs(backups_dir, exist_ok=True)
        
    return os.path.join(backups_dir, subpath)

def get_fiscal_path(subpath=''):
    """Returns the full path for fiscal documents, ensuring the directory exists."""
    config = load_system_config()
    fiscal_dir = config.get('fiscal_dir', 'fiscal_documents')
    
    if not os.path.isabs(fiscal_dir):
        fiscal_dir = os.path.join(BASE_DIR, fiscal_dir)
        
    if not os.path.exists(fiscal_dir):
        os.makedirs(fiscal_dir, exist_ok=True)
        
    return os.path.join(fiscal_dir, subpath)

def validate_paths():
    """Ensures all configured directories exist."""
    config = load_system_config()
    results = []
    for key in ['data_dir', 'logs_dir', 'backups_dir', 'fiscal_dir']:
        path = config.get(key)
        if path:
            if not os.path.isabs(path):
                path = os.path.join(BASE_DIR, path)
            status = 'OK'
            try:
                if not os.path.exists(path):
                    os.makedirs(path)
                    print(f"Created directory: {path}")
                # Check writability
                test_file = os.path.join(path, '.test_write')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
            except Exception as e:
                status = f'ERROR: {e}'
                print(f"Error creating/checking directory {path}: {e}")
            results.append((path, status))
    return results

# --- CENTRALIZED FILE PATH CONSTANTS ---
# These constants define the canonical location of all system files.
# All modules should import these constants instead of calling get_data_path directly where possible.

# Core Data
USERS_FILE = get_data_path('users.json')
EX_EMPLOYEES_FILE = get_data_path('ex_employees.json')
SETTINGS_FILE = get_data_path('settings.json')
PRINTERS_FILE = get_data_path('printers.json')
DB_PATH = get_data_path('department_logs.db')

# Financial & POS
CASHIER_SESSIONS_FILE = get_data_path('cashier_sessions.json')
PAYABLES_FILE = get_data_path('payables.json')
PAYMENT_METHODS_FILE = get_data_path('payment_methods.json')
ROOM_CHARGES_FILE = get_data_path('room_charges.json')
TABLE_ORDERS_FILE = get_data_path('table_orders.json')
ARCHIVED_ORDERS_FILE = get_data_path('archived_orders.json')
SALES_HISTORY_FILE = get_data_path('sales_history.json')
CLOSED_ACCOUNTS_FILE = get_data_path('closed_accounts.json')
COMMISSION_CYCLES_FILE = get_data_path('commission_cycles.json')

# Inventory & Products
PRODUCTS_FILE = get_data_path('products.json')
MENU_ITEMS_FILE = get_data_path('menu_items.json')
COMPLEMENTS_FILE = get_data_path('complements.json')
STOCK_FILE = get_data_path('stock_requests.json')
STOCK_ENTRIES_FILE = get_data_path('stock_entries.json')
STOCK_LOGS_FILE = get_data_path('stock_logs.json')
STOCK_TRANSFERS_FILE = get_data_path('stock_transfers.json')
SALES_PRODUCTS_FILE = get_data_path('sales_products.json')
SUPPLIERS_FILE = get_data_path('suppliers.json')
CONFERENCES_FILE = get_data_path('conferences.json')
CONFERENCE_PRESETS_FILE = get_data_path('conference_presets.json')
CONFERENCE_SKIPPED_FILE = get_data_path('conference_skipped_items.json')

# Hotel Operations
ROOM_OCCUPANCY_FILE = get_data_path('room_occupancy.json')
BREAKFAST_HISTORY_FILE = get_data_path('breakfast_history.json')
CLEANING_STATUS_FILE = get_data_path('cleaning_status.json')
CLEANING_LOGS_FILE = get_data_path('cleaning_logs.json')
MAINTENANCE_FILE = get_data_path('maintenance.json')
GUEST_NOTIFICATIONS_FILE = get_data_path('guest_notifications.json')
WAITING_LIST_FILE = get_data_path('waiting_list.json')
CHECKLIST_ITEMS_FILE = get_data_path('checklist_items.json')
CHECKLIST_SETTINGS_FILE = get_data_path('checklist_settings.json')
DAILY_CHECKLISTS_FILE = get_data_path('daily_checklists.json')

# Logs & Tracking
TIME_TRACKING_FILE = get_data_path('time_tracking.json')
TIME_TRACKING_DIR = get_data_path('time_tracking')
ACTION_LOGS_DIR = get_log_path('actions')
WHATSAPP_MESSAGES_FILE = get_data_path('whatsapp_messages.json')
WHATSAPP_TAGS_FILE = get_data_path('whatsapp_tags.json')
WHATSAPP_QUICK_REPLIES_FILE = get_data_path('whatsapp_quick_replies.json')
WHATSAPP_TEMPLATES_FILE = get_data_path('whatsapp_templates.json')
DELETED_MESSAGES_LOG = get_data_path('deleted_messages_log.json')
AUDIT_LOGS_FILE = get_data_path('audit_logs.json')
PASSWORD_RESET_REQUESTS_FILE = get_data_path('password_reset_requests.json')

SYSTEM_STATUS_FILE = get_data_path('system_status.json')
FISCAL_POOL_FILE = get_data_path('fiscal_pool.json')
LAST_SYNC_FILE = get_data_path('last_sync.json')
BACKUP_CONFIG_FILE = get_data_path('backup_config.json')
PENDING_FISCAL_EMISSIONS_FILE = get_data_path('pending_fiscal_emissions.json')
FISCAL_NSU_FILE = get_data_path('fiscal_nsu.json')

# Miscellaneous
OBSERVATIONS_FILE = get_data_path('observations.json')
FISCAL_SETTINGS_FILE = get_data_path('fiscal_settings.json')
LAUNDRY_DATA_DIR = get_data_path('laundry_data')
INSPECTION_LOGS_FILE = get_data_path('inspection_logs.json')
RESTAURANT_TABLE_SETTINGS_FILE = get_data_path('restaurant_table_settings.json')
RESTAURANT_SETTINGS_FILE = get_data_path('restaurant_settings.json')
FLAVOR_GROUPS_FILE = get_data_path('flavor_groups.json')
QUALITY_AUDITS_FILE = get_data_path('quality_audits.json')

# Static Assets
PRODUCT_PHOTOS_DIR = os.path.join(BASE_DIR, 'Produtos', 'Fotos')
SAEPEARL_TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates', 'saepearl_external')
SAEPEARL_ASSETS_DIR = os.path.join(SAEPEARL_TEMPLATE_DIR, "assets")
SALES_DIR = os.path.join(BASE_DIR, 'Vendas')
SALES_EXCEL_PATH = os.path.join(SALES_DIR, 'Produtos.xlsx')

DEPARTMENTS = [
    'Recepção', 'Restaurante', 'Cozinha', 'Governança', 
    'Lavanderia', 'Manutencao', 'Admin', 'RH'
]

# Constants
BREAKFAST_TABLE_ID = 36

if __name__ == '__main__':
    # Simple self-test
    print("System Paths Configuration:")
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"DATA_DIR: {get_data_path('')}")
    print(f"LOGS_DIR: {get_log_path('')}")
    print("\nValidation:")
    for path, status in validate_paths():
        print(f"{path}: {status}")
