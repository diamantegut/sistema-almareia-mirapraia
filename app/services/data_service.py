import os
import json
import uuid
import unicodedata
import logging
from datetime import datetime
from flask import session

from app.services.system_config_manager import (
    SETTINGS_FILE, SALES_PRODUCTS_FILE, SALES_HISTORY_FILE,
    MAINTENANCE_FILE, STOCK_FILE, STOCK_LOGS_FILE, PRODUCTS_FILE,
    SUPPLIERS_FILE, PAYABLES_FILE, STOCK_ENTRIES_FILE,
    CONFERENCES_FILE, CONFERENCE_PRESETS_FILE, CONFERENCE_SKIPPED_FILE,
    STOCK_TRANSFERS_FILE, TABLE_ORDERS_FILE,
    ROOM_CHARGES_FILE, MENU_ITEMS_FILE, PAYMENT_METHODS_FILE, CASHIER_SESSIONS_FILE,
    ROOM_OCCUPANCY_FILE, QUALITY_AUDITS_FILE, PRINTERS_FILE, FISCAL_SETTINGS_FILE,
    COMPLEMENTS_FILE, OBSERVATIONS_FILE, PRODUCT_PHOTOS_DIR,
    BREAKFAST_HISTORY_FILE, FLAVOR_GROUPS_FILE,
    RESTAURANT_TABLE_SETTINGS_FILE, RESTAURANT_SETTINGS_FILE,
    CHECKLIST_ITEMS_FILE, INSPECTION_LOGS_FILE, CLEANING_STATUS_FILE,
    ARCHIVED_ORDERS_FILE, AUDIT_LOGS_FILE, USERS_FILE, EX_EMPLOYEES_FILE,
    DEPARTMENTS
)

def format_room_number(room_num):
    """
    Formats room number to ensure at least 2 digits (e.g., '1' -> '01').
    Only applies to numeric strings/integers. Returns string.
    """
    if room_num is None:
        return ""
    try:
        # Check if it's a number
        num = int(room_num)
        return f"{num:02d}"
    except ValueError:
        return str(room_num)

def normalize_text(text):
    if not text:
        return ""
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()

def normalize_room_simple(r):
    """
    Normalizes room number string:
    - Strips whitespace
    - Converts '01' -> '1' (removes leading zeros if numeric)
    """
    s = str(r).strip()
    if s.isdigit():
        return str(int(s))
    return s

# --- Generic Load/Save Helper ---
def _load_json(filepath, default=None):
    if default is None: default = []
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default

def _save_json(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
        return False

def _save_json_atomic(filepath, data):
    temp_file = filepath + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        if os.path.exists(filepath):
            os.replace(temp_file, filepath)
        else:
            os.rename(temp_file, filepath)
        return True
    except Exception as e:
        print(f"Error saving {filepath} (atomic): {e}")
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except: pass
        return False

# --- Settings ---
def load_settings(): return _load_json(SETTINGS_FILE, {})
def save_settings(settings): return _save_json(SETTINGS_FILE, settings)

# --- Users ---
def load_users(): return _load_json(USERS_FILE, [])
def save_users(users): return _save_json(USERS_FILE, users)

def load_ex_employees(): return _load_json(EX_EMPLOYEES_FILE, [])
def save_ex_employees(employees): return _save_json(EX_EMPLOYEES_FILE, employees)

# --- Breakfast History ---
def load_breakfast_history(): return _load_json(BREAKFAST_HISTORY_FILE, [])
def save_breakfast_history(history): return _save_json(BREAKFAST_HISTORY_FILE, history)

# --- Flavor Groups ---
def load_flavor_groups(): return _load_json(FLAVOR_GROUPS_FILE, [])
def save_flavor_groups(groups): return _save_json(FLAVOR_GROUPS_FILE, groups)

# --- Room Charges ---
def load_room_charges(): return _load_json(ROOM_CHARGES_FILE, [])
def save_room_charges(charges): return _save_json_atomic(ROOM_CHARGES_FILE, charges)

# --- Room Occupancy ---
def load_room_occupancy():
    data = _load_json(ROOM_OCCUPANCY_FILE, {})
    normalized_data = {}
    for k, v in data.items():
        normalized_data[format_room_number(k)] = v
    return normalized_data

def save_room_occupancy(occupancy): return _save_json_atomic(ROOM_OCCUPANCY_FILE, occupancy)

# --- Quality Audits ---
# Note: There were duplicate definitions for load/save_quality_audits in original file. Consolidating.
def load_quality_audits(): return _load_json(QUALITY_AUDITS_FILE, [])
def save_quality_audits(audits): return _save_json(QUALITY_AUDITS_FILE, audits)

# --- Printers ---
def load_printers(): return _load_json(PRINTERS_FILE, [])
def save_printers(printers): return _save_json(PRINTERS_FILE, printers)

# --- Fiscal Settings ---
def load_fiscal_settings(): return _load_json(FISCAL_SETTINGS_FILE, {})
def save_fiscal_settings(settings): return _save_json(FISCAL_SETTINGS_FILE, settings)

# --- Menu Items ---
def load_menu_items(): return _load_json(MENU_ITEMS_FILE, [])
def save_menu_items(items): return _save_json(MENU_ITEMS_FILE, items)

# --- Complements ---
def load_complements(): return _load_json(COMPLEMENTS_FILE, [])
def save_complements(items): return _save_json(COMPLEMENTS_FILE, items)

# --- Observations ---
def load_observations(): return _load_json(OBSERVATIONS_FILE, [])
def save_observations(observations): return _save_json(OBSERVATIONS_FILE, observations)

# --- Payment Methods ---
def load_payment_methods():
    methods = _load_json(PAYMENT_METHODS_FILE, [])
    valid_methods = []
    
    # Valid categories
    VALID_CATEGORIES = {
        'restaurant', 'reception', 'reservations', 
        'caixa_restaurante', 'caixa_recepcao', 'caixa_reservas'
    }
    
    for method in methods:
        try:
            # Auto-fix legacy 'dinheiro' if missing fields
            if method.get('id') == 'dinheiro':
                if 'available_in' not in method:
                    method['available_in'] = ['restaurant', 'reception']
                if 'is_fiscal' not in method:
                    method['is_fiscal'] = False
            
            # 1. Mandatory Fields Validation
            if not method.get('id'):
                logging.error(f"Payment Method Validation Failed: Missing ID. Data: {method}")
                continue
                
            if not method.get('name'):
                logging.error(f"Payment Method Validation Failed: Missing Name. ID: {method.get('id')}")
                continue
                
            # 2. Category Validation
            available_in = method.get('available_in')
            if not isinstance(available_in, list) or not available_in:
                logging.error(f"Payment Method Validation Failed: Invalid 'available_in'. ID: {method.get('id')}, Value: {available_in}")
                continue

            # Check if categories are valid
            # We accept the ones in VALID_CATEGORIES. 
            # If a method has 'restaurant' and 'unknown', we log warning but might accept it?
            # User said: "corretamente categorizada para uso em restaurante, recepção ou reservas".
            # Strict check: all items must be in VALID_CATEGORIES.
            invalid_cats = [cat for cat in available_in if cat not in VALID_CATEGORIES]
            if invalid_cats:
                 logging.error(f"Payment Method Validation Failed: Invalid categories {invalid_cats}. ID: {method.get('id')}")
                 continue

            # 3. Fiscal Flag Validation
            if 'is_fiscal' not in method:
                 logging.error(f"Payment Method Validation Failed: Missing 'is_fiscal'. ID: {method.get('id')}")
                 continue
            
            if not isinstance(method['is_fiscal'], bool):
                 logging.error(f"Payment Method Validation Failed: 'is_fiscal' must be boolean. ID: {method.get('id')}")
                 continue

            # 4. Fiscal CNPJ Validation (if fiscal)
            if method['is_fiscal'] and 'fiscal_cnpj' not in method:
                 # Not explicitly requested to fail, but good practice.
                 # User said "marcada com o indicador fiscal (sim/não)".
                 # I'll just warn for now or ensure key exists.
                 method['fiscal_cnpj'] = method.get('fiscal_cnpj', '')

            valid_methods.append(method)
            
        except Exception as e:
            logging.error(f"Payment Method Validation Error: {e}. Data: {method}")
            continue
            
    return valid_methods

def save_payment_methods(methods): return _save_json(PAYMENT_METHODS_FILE, methods)

# --- Cashier Sessions ---
def load_cashier_sessions(): return _load_json(CASHIER_SESSIONS_FILE, [])
def save_cashier_sessions(sessions): return _save_json(CASHIER_SESSIONS_FILE, sessions)

def get_current_cashier(user=None, cashier_type=None):
    # Delegate to centralized CashierService to ensure consistent logic
    from app.services.cashier_service import CashierService
    if cashier_type:
        return CashierService.get_active_session(cashier_type)
        
    # Fallback for unspecified type (return first open)
    sessions = CashierService._load_sessions()
    for s in reversed(sessions):
        if str(s.get('status', '')).lower().strip() == 'open':
            return s
    return None

# --- Sales Products ---
def load_sales_products(): return _load_json(SALES_PRODUCTS_FILE, {})
def save_sales_products(data): return _save_json(SALES_PRODUCTS_FILE, data)

# --- Sales History ---
def load_sales_history(): return _load_json(SALES_HISTORY_FILE, [])
def save_sales_history(data): return _save_json(SALES_HISTORY_FILE, data)

# --- Maintenance ---
def load_maintenance_requests(): return _load_json(MAINTENANCE_FILE, [])
def save_maintenance_requests(data): return _save_json(MAINTENANCE_FILE, data)

# --- Stock ---
def load_stock_requests(): return _load_json(STOCK_FILE, [])
def save_stock_requests(data): return _save_json(STOCK_FILE, data)
def save_all_stock_requests(data): return save_stock_requests(data)

def save_stock_request(req):
    requests = load_stock_requests()
    requests.append(req)
    save_stock_requests(requests)

def load_stock_logs(): return _load_json(STOCK_LOGS_FILE, [])
def save_stock_logs(data): return _save_json(STOCK_LOGS_FILE, data)

def load_products(): return _load_json(PRODUCTS_FILE, [])
def save_products(data): return _save_json(PRODUCTS_FILE, data)

def load_suppliers(): return _load_json(SUPPLIERS_FILE, [])
def save_suppliers(data): return _save_json(SUPPLIERS_FILE, data)

def load_payables(): return _load_json(PAYABLES_FILE, [])
def save_payables(data): return _save_json(PAYABLES_FILE, data)

def load_stock_entries(): return _load_json(STOCK_ENTRIES_FILE, [])
def save_stock_entries(data): return _save_json(STOCK_ENTRIES_FILE, data)

def save_stock_entry(entry):
    entries = load_stock_entries()
    entries.append(entry)
    save_stock_entries(entries)

def load_conferences(): return _load_json(CONFERENCES_FILE, [])
def save_conferences(data): return _save_json(CONFERENCES_FILE, data)

def load_conference_presets(): return _load_json(CONFERENCE_PRESETS_FILE, [])
def save_conference_presets(data): return _save_json(CONFERENCE_PRESETS_FILE, data)

def load_conference_skipped_items(): return _load_json(CONFERENCE_SKIPPED_FILE, [])
def save_conference_skipped_items(data): return _save_json(CONFERENCE_SKIPPED_FILE, data)

def load_stock_transfers(): return _load_json(STOCK_TRANSFERS_FILE, [])
def save_stock_transfers(data): return _save_json(STOCK_TRANSFERS_FILE, data)

import shutil
import logging
# --- Table Orders ---
def load_table_orders(): return _load_json(TABLE_ORDERS_FILE, {})

def save_table_orders(data):
    # 1. Logging Context
    try:
        user = session.get('user') if session else 'system'
    except:
        user = 'unknown'
        
    current_size = len(data) if data else 0
    logging.info(f"Attempting to save table_orders. User: {user}. Items count: {current_size}")

    # 2. Backup Logic
    if os.path.exists(TABLE_ORDERS_FILE):
        try:
            # Check existing data
            old_data = _load_json(TABLE_ORDERS_FILE, {})
            old_size = len(old_data)
            
            # Safety Check: Emptying a populated file?
            if old_size > 0 and current_size == 0:
                logging.warning(f"CRITICAL: Wipe detected on table_orders.json! User: {user}. Backing up before wipe.")
                
            backup_dir = os.path.join(os.path.dirname(TABLE_ORDERS_FILE), 'backups', 'table_orders')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f"table_orders_{timestamp}_{user}.json")
            shutil.copy2(TABLE_ORDERS_FILE, backup_path)
            
            # Retention: Keep last 50 backups
            backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir)], key=os.path.getmtime)
            while len(backups) > 50:
                os.remove(backups.pop(0))
                
        except Exception as e:
            logging.error(f"Failed to create backup for table_orders: {e}")

    # 3. Save (Atomic)
    return _save_json_atomic(TABLE_ORDERS_FILE, data)

# --- Restaurant Settings ---
def load_restaurant_table_settings(): return _load_json(RESTAURANT_TABLE_SETTINGS_FILE, {})
def save_restaurant_table_settings(data): return _save_json(RESTAURANT_TABLE_SETTINGS_FILE, data)

def load_restaurant_settings(): return _load_json(RESTAURANT_SETTINGS_FILE, {})
def save_restaurant_settings(data): return _save_json(RESTAURANT_SETTINGS_FILE, data)

# --- Checklist Items ---
def load_checklist_items(): return _load_json(CHECKLIST_ITEMS_FILE, [])
def save_checklist_items(items): return _save_json(CHECKLIST_ITEMS_FILE, items)

# --- Inspection Logs ---
def load_inspection_logs(): return _load_json(INSPECTION_LOGS_FILE, [])
def save_inspection_logs(logs): return _save_json(INSPECTION_LOGS_FILE, logs)

def add_inspection_log(log_entry):
    logs = load_inspection_logs()
    logs.append(log_entry)
    save_inspection_logs(logs)

# --- Cleaning Status ---
def load_cleaning_status(): return _load_json(CLEANING_STATUS_FILE, {})
def save_cleaning_status(status): return _save_json(CLEANING_STATUS_FILE, status)

def log_stock_action(user, action, product, qty, details, date_str=None, department=None):
    if not date_str:
        date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    if not department:
        try:
            from flask import session
            department = session.get('department', 'Geral')
        except:
            department = 'Geral'
    
    entry = {
        'id': str(uuid.uuid4()),
        'date': date_str,
        'user': user,
        'department': department,
        'action': action,
        'product': product,
        'qty': qty,
        'details': details
    }
    
    logs = _load_json(STOCK_LOGS_FILE, [])
    logs.append(entry)
    _save_json(STOCK_LOGS_FILE, logs)

def load_audit_logs():
    return _load_json(AUDIT_LOGS_FILE, [])

def save_audit_logs(logs):
    return _save_json(AUDIT_LOGS_FILE, logs)
