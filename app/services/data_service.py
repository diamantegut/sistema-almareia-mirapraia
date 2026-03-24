import os
import json
import uuid
import unicodedata
import logging
import hashlib
import threading
import copy
from datetime import datetime
from flask import session
from app.services.data_cleanup_monitor_service import record_data_cleanup_event

from app.services.system_config_manager import (
    SETTINGS_FILE, SALES_PRODUCTS_FILE, SALES_HISTORY_FILE,
    MAINTENANCE_FILE, STOCK_FILE, STOCK_LOGS_FILE, PRODUCTS_FILE,
    SUPPLIERS_FILE, PAYABLES_FILE, STOCK_ENTRIES_FILE,
    CONFERENCES_FILE, CONFERENCE_PRESETS_FILE, CONFERENCE_SKIPPED_FILE,
    STOCK_TRANSFERS_FILE, TABLE_ORDERS_FILE, FIXED_ASSETS_FILE, ASSET_CONFERENCES_FILE,
    ROOM_CHARGES_FILE, MENU_ITEMS_FILE, PAYMENT_METHODS_FILE, CASHIER_SESSIONS_FILE,
    ROOM_OCCUPANCY_FILE, QUALITY_AUDITS_FILE, PRINTERS_FILE, FISCAL_SETTINGS_FILE,
    COMPLEMENTS_FILE, OBSERVATIONS_FILE, PRODUCT_PHOTOS_DIR,
    BREAKFAST_HISTORY_FILE, FLAVOR_GROUPS_FILE,
    RESTAURANT_TABLE_SETTINGS_FILE, RESTAURANT_SETTINGS_FILE,
    CHECKLIST_ITEMS_FILE, INSPECTION_LOGS_FILE, CLEANING_STATUS_FILE,
    ARCHIVED_ORDERS_FILE, AUDIT_LOGS_FILE, USERS_FILE, EX_EMPLOYEES_FILE,
    BAR_DATA_FILE,
    DEPARTMENT_PERMISSIONS_FILE,
    DEPARTMENTS, # for load/save helpers
    get_backup_path, get_data_path, get_legacy_root_json_path
)

_CRITICAL_JSON_PATHS = {
    os.path.abspath(TABLE_ORDERS_FILE),
    os.path.abspath(SALES_HISTORY_FILE),
    os.path.abspath(STOCK_ENTRIES_FILE),
    os.path.abspath(CASHIER_SESSIONS_FILE),
}

_CRITICAL_JSON_FILENAMES = {
    'cashier_sessions.json',
    'room_charges.json',
    'table_orders.json',
    'sales_history.json',
    'closed_accounts.json',
    'guest_details.json',
    'manual_allocations.json',
    'waiting_list.json',
    'products.json',
    'stock_entries.json',
    'stock_logs.json',
}
_LEGACY_DIVERGENCE_ALERTED = set()

def _critical_filename(filepath):
    return os.path.basename(str(filepath or '')).lower()

def _legacy_read_candidate(filepath):
    filename = _critical_filename(filepath)
    if filename not in _CRITICAL_JSON_FILENAMES:
        return None
    legacy = get_legacy_root_json_path(filename)
    if os.path.abspath(str(legacy)) == os.path.abspath(str(filepath)):
        return None
    return legacy

def _canonical_write_path(filepath):
    filename = _critical_filename(filepath)
    if filename not in _CRITICAL_JSON_FILENAMES:
        return filepath
    canonical = get_data_path(filename)
    if os.path.abspath(str(canonical)) != os.path.abspath(str(filepath)):
        logging.warning(f"json_write_canonicalized file={filename} from={filepath} to={canonical}")
    return canonical

def _alert_legacy_divergence_once(filepath):
    filename = _critical_filename(filepath)
    if filename not in _CRITICAL_JSON_FILENAMES or filename in _LEGACY_DIVERGENCE_ALERTED:
        return
    canonical = get_data_path(filename)
    legacy = get_legacy_root_json_path(filename)
    if os.path.abspath(canonical) == os.path.abspath(legacy):
        return
    if not os.path.exists(canonical) or not os.path.exists(legacy):
        return
    try:
        with open(canonical, 'rb') as stream:
            canonical_hash = hashlib.sha256(stream.read()).hexdigest()
        with open(legacy, 'rb') as stream:
            legacy_hash = hashlib.sha256(stream.read()).hexdigest()
    except Exception:
        return
    if canonical_hash != legacy_hash:
        logging.warning(f"json_legacy_divergence_detected file={filename} canonical={canonical} legacy={legacy}")
        _LEGACY_DIVERGENCE_ALERTED.add(filename)

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
def _load_json(filepath, default=None, strict=False):
    import time
    if default is None: default = []
    _alert_legacy_divergence_once(filepath)
    target_path = filepath
    if not os.path.exists(target_path):
        legacy_candidate = _legacy_read_candidate(target_path)
        if legacy_candidate and os.path.exists(legacy_candidate):
            logging.warning(f"json_read_fallback_legacy file={_critical_filename(filepath)} canonical={filepath} legacy={legacy_candidate}")
            target_path = legacy_candidate
    if not os.path.exists(target_path):
        record_data_cleanup_event(
            event_type='file_not_found',
            requested_file=filepath,
            error_message='Arquivo JSON inexistente durante leitura'
        )
        return default
    
    max_retries = 20
    for i in range(max_retries):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (PermissionError, OSError):
            if i == max_retries - 1:
                logging.error(f"Could not acquire lock for {target_path} after {max_retries} attempts.")
                record_data_cleanup_event(
                    event_type='config_read_failure',
                    requested_file=target_path,
                    error_message=f'Falha de leitura/lock após {max_retries} tentativas'
                )
                if strict:
                    raise RuntimeError(f"JSON read lock timeout: {target_path}")
                return default
            time.sleep(0.1)
        except json.JSONDecodeError as exc:
            backup_path = f"{target_path}.corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            try:
                with open(target_path, 'r', encoding='utf-8', errors='replace') as src, open(backup_path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            except Exception:
                pass
            logging.error(f"Invalid JSON detected in {target_path}: {exc}")
            record_data_cleanup_event(
                event_type='json_decode_error',
                requested_file=target_path,
                error_message=str(exc)
            )
            if strict:
                raise RuntimeError(f"JSON corrupt: {target_path}") from exc
            return default
            
    return default

def _save_json(filepath, data):
    filepath = _canonical_write_path(filepath)
    if os.path.abspath(filepath) in _CRITICAL_JSON_PATHS:
        return _save_json_atomic(filepath, data)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
        return False

def _save_json_atomic(filepath, data):
    filepath = _canonical_write_path(filepath)
    import time
    temp_file = filepath + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        
        # Retry logic for Windows file locking
        max_retries = 30
        for i in range(max_retries):
            try:
                if os.path.exists(filepath):
                    os.replace(temp_file, filepath)
                else:
                    os.rename(temp_file, filepath)
                return True
            except (PermissionError, OSError): # WinError 32 or 5
                if i == max_retries - 1:
                    raise
                time.sleep(0.1)
                
        return True
    except Exception as e:
        print(f"Error saving {filepath} (atomic): {e}")
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except: pass
        return False

def _backup_before_write(filepath, max_backups=30):
    filepath = _canonical_write_path(filepath)
    try:
        if not os.path.exists(filepath):
            return
        backup_root = get_backup_path('')
        os.makedirs(backup_root, exist_ok=True)
        base = os.path.basename(filepath)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_root, f"{base}.{timestamp}.bak")
        with open(filepath, 'r', encoding='utf-8') as src, open(backup_path, 'w', encoding='utf-8') as dst:
            dst.write(src.read())
        files = [f for f in os.listdir(backup_root) if f.startswith(base + '.')]
        if len(files) > max_backups:
            files.sort()
            to_remove = files[0:len(files) - max_backups]
            for name in to_remove:
                try:
                    os.remove(os.path.join(backup_root, name))
                except OSError:
                    pass
    except Exception as e:
        print(f"Error creating backup for {filepath}: {e}")

# --- Settings ---
def load_settings(): return _load_json(SETTINGS_FILE, {})
def save_settings(settings): return _save_json(SETTINGS_FILE, settings)

# --- Users ---
def load_users(): return _load_json(USERS_FILE, {})
def save_users(users):
    _backup_before_write(USERS_FILE)
    return _save_json_atomic(USERS_FILE, users)

def load_department_permissions():
    return _load_json(DEPARTMENT_PERMISSIONS_FILE, {})

def save_department_permissions(data):
    _backup_before_write(DEPARTMENT_PERMISSIONS_FILE)
    return _save_json_atomic(DEPARTMENT_PERMISSIONS_FILE, data)

def load_bar_data():
    default = {
        "storage_units": [],
        "checklists": [],
        "audits": [],
        "settings": {
            "thursday_saturday_multiplier": 1.4
        }
    }
    return _load_json(BAR_DATA_FILE, default=default)

def save_bar_data(data):
    return _save_json(BAR_DATA_FILE, data)

def load_ex_employees(): return _load_json(EX_EMPLOYEES_FILE, [])
def save_ex_employees(employees): return _save_json(EX_EMPLOYEES_FILE, employees)

# --- Breakfast History ---
def load_breakfast_history(): return _load_json(BREAKFAST_HISTORY_FILE, [])
def save_breakfast_history(history): return _save_json(BREAKFAST_HISTORY_FILE, history)

# --- Flavor Groups ---
def load_flavor_groups(): return _load_json(FLAVOR_GROUPS_FILE, [])
def save_flavor_groups(groups): return _save_json(FLAVOR_GROUPS_FILE, groups)

# --- Room Charges ---
def _get_room_charges_path():
    try:
        import app as _app
        if hasattr(_app, 'ROOM_CHARGES_FILE') and _app.ROOM_CHARGES_FILE:
            return _app.ROOM_CHARGES_FILE
        if hasattr(_app, 'get_data_path'):
            return _app.get_data_path('room_charges.json')
    except Exception:
        return ROOM_CHARGES_FILE

def load_room_charges(): return _load_json(_get_room_charges_path(), [])
def save_room_charges(charges):
    path = _get_room_charges_path()
    _backup_before_write(path)
    return _save_json_atomic(path, charges)

# --- Room Occupancy ---
def _get_room_occupancy_path():
    try:
        import app as _app
        if hasattr(_app, 'ROOM_OCCUPANCY_FILE') and _app.ROOM_OCCUPANCY_FILE:
            return _app.ROOM_OCCUPANCY_FILE
        if hasattr(_app, 'get_data_path'):
            return _app.get_data_path('room_occupancy.json')
    except Exception:
        return ROOM_OCCUPANCY_FILE

def load_room_occupancy():
    data = _load_json(_get_room_occupancy_path(), {})
    normalized_data = {}
    for k, v in data.items():
        normalized_data[format_room_number(k)] = v
    return normalized_data

def save_room_occupancy(occupancy): return _save_json_atomic(_get_room_occupancy_path(), occupancy)

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

def save_menu_items(items):
    return secure_save_menu_items(items, user_id='Sistema')

def secure_save_menu_items(new_items, user_id='Sistema'):
    """
    Securely saves menu items with validation, auditing, and integrity checks.
    """
    try:
        # 1. Load current state
        old_items = load_menu_items()
        old_map = {str(i.get('id')): i for i in old_items}
        
        processed_items = []
        changes_detected = False
        
        # 2. Process changes
        for item in new_items:
            i_id = str(item.get('id'))
            
            # Validate
            try:
                MenuSecurityService.validate_menu_item(item)
            except ValueError as e:
                logging.error(f"Validation failed for menu item {item.get('name')}: {e}")
                raise
            
            if i_id in old_map:
                old_i = old_map[i_id]
                
                # Optimistic Locking
                if 'version' in item and 'version' in old_i:
                    if int(item['version']) != int(old_i['version']):
                        raise ValueError(f"Conflito de edição detectado para {item.get('name')}. Recarregue a página.")
                
                # Generate Diff
                diff = MenuSecurityService.generate_diff(old_i, item)
                if diff:
                    changes_detected = True
                    item['version'] = int(old_i.get('version', 1)) + 1
                    item['last_updated'] = datetime.now().isoformat()
                    item['hash'] = MenuSecurityService.calculate_hash(item)
                    
                    MenuSecurityService.log_audit('UPDATE', user_id, i_id, {'name': item['name']}, diff)
                else:
                    item['version'] = old_i.get('version', 1)
                    item['hash'] = old_i.get('hash', '')
                    item['last_updated'] = old_i.get('last_updated', '')
            else:
                # New Item
                changes_detected = True
                item['version'] = 1
                item['last_updated'] = datetime.now().isoformat()
                item['hash'] = MenuSecurityService.calculate_hash(item)
                MenuSecurityService.log_audit('CREATE', user_id, i_id, item)
            
            processed_items.append(item)
            
        # 3. Check for deletions
        new_ids = set(str(i.get('id')) for i in processed_items)
        for old_id, old_i in old_map.items():
            if old_id not in new_ids:
                changes_detected = True
                MenuSecurityService.log_audit('DELETE', user_id, old_id, old_i)
                
        # 3.1. Detect Bulk Changes (Anti-Overwrite)
        try:
            is_bulk, bulk_details = MenuSecurityService.detect_bulk_changes(old_items, processed_items)
            if is_bulk:
                msg = f"SECURITY ALERT (MENU): {bulk_details}"
                logging.warning(msg)
                MenuSecurityService.log_audit('BULK_CHANGE_ALERT', user_id, 'ALL', {'message': msg})
                MenuSecurityService.create_menu_sales_backup()
        except Exception as e:
            logging.error(f"Error detecting bulk menu changes: {e}")

        # 4. Save if changes
        if changes_detected:
            _backup_before_write(MENU_ITEMS_FILE)
            return _save_json_atomic(MENU_ITEMS_FILE, processed_items)
        
        return True
        
    except Exception as e:
        logging.error(f"Secure Save Menu Error: {e}")
        raise e

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
            if not isinstance(available_in, list):
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
            alias = method.get('pagseguro_alias')
            if alias is None:
                method['pagseguro_alias'] = ''
            else:
                method['pagseguro_alias'] = str(alias).strip()

            valid_methods.append(method)
            
        except Exception as e:
            logging.error(f"Payment Method Validation Error: {e}. Data: {method}")
            continue
            
    return valid_methods

def save_payment_methods(methods): return _save_json(PAYMENT_METHODS_FILE, methods)

# --- Cashier Sessions ---
def _get_cashier_sessions_path():
    try:
        import app as _app
        if hasattr(_app, 'CASHIER_SESSIONS_FILE') and _app.CASHIER_SESSIONS_FILE:
            return _app.CASHIER_SESSIONS_FILE
        if hasattr(_app, 'get_data_path'):
            return _app.get_data_path('cashier_sessions.json')
    except Exception:
        return CASHIER_SESSIONS_FILE

def load_cashier_sessions(): return _load_json(_get_cashier_sessions_path(), [], strict=True)
def save_cashier_sessions(sessions):
    from app.services.cashier_service import CashierService
    return CashierService.persist_sessions(sessions, trigger_backup=False)

def get_current_cashier(user=None, cashier_type=None):
    # Delegate to centralized CashierService to ensure consistent logic
    from app.services.cashier_service import CashierService
    if cashier_type:
        return CashierService.get_active_session(cashier_type)
        
    # Fallback for unspecified type (return first open)
    sessions = CashierService.list_sessions()
    for s in reversed(sessions):
        if str(s.get('status', '')).lower().strip() == 'open':
            return s
    return None

# --- Sales Products ---
def load_sales_products(): return _load_json(SALES_PRODUCTS_FILE, {})
def save_sales_products(data): return _save_json(SALES_PRODUCTS_FILE, data)

# --- Sales History ---
def load_sales_history(): return _load_json(SALES_HISTORY_FILE, [], strict=True)

def save_sales_history(data):
    return secure_save_sales_history(data, user_id='Sistema')

def secure_save_sales_history(new_data, user_id='Sistema'):
    """
    Securely saves sales history with backup and bulk deletion protection.
    """
    try:
        old_data = load_sales_history()
        
        # Check for bulk deletion (if new list is significantly smaller)
        if len(new_data) < len(old_data) * 0.8 and len(old_data) > 10:
            msg = f"SECURITY ALERT (SALES): Potential bulk deletion detected. Old: {len(old_data)}, New: {len(new_data)}"
            logging.warning(msg)
            # Create backup before allowing this
            MenuSecurityService.create_menu_sales_backup()
            MenuSecurityService.log_audit('BULK_DELETE_ALERT_SALES', user_id, 'ALL', {'message': msg})
            
        _backup_before_write(SALES_HISTORY_FILE)
        return _save_json_atomic(SALES_HISTORY_FILE, new_data)
    except Exception as e:
        logging.error(f"Secure Save Sales History Error: {e}")
        raise e

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

from app.services.stock_security_service import StockSecurityService
from app.services.menu_security_service import MenuSecurityService

def load_products():
    canonical_path = _canonical_write_path(PRODUCTS_FILE)
    products = _load_json(canonical_path, [])
    canonical_count = len(products) if isinstance(products, list) else 0
    fallback_used = False
    legacy_count = 0
    source = "canonical"
    if not isinstance(products, list):
        products = []
        canonical_count = 0
    legacy_path = get_legacy_root_json_path('products.json')
    try:
        if canonical_count == 0 and os.path.abspath(str(legacy_path)) != os.path.abspath(str(canonical_path)) and os.path.exists(legacy_path):
            legacy_products = _load_json(legacy_path, [])
            if isinstance(legacy_products, list):
                legacy_count = len(legacy_products)
                if legacy_count > 0:
                    products = legacy_products
                    fallback_used = True
                    source = "legacy_root"
                    logging.warning(
                        "products_load_fallback_using_legacy canonical_path=%s legacy_path=%s canonical_count=%s legacy_count=%s",
                        canonical_path,
                        legacy_path,
                        canonical_count,
                        legacy_count,
                    )
    except Exception as e:
        logging.error(f"products_load_fallback_error canonical_path={canonical_path} legacy_path={legacy_path} error={e}")
    logging.info(
        "products_load_source source=%s canonical_path=%s legacy_path=%s canonical_count=%s legacy_count=%s fallback_used=%s",
        source,
        canonical_path,
        legacy_path,
        canonical_count,
        legacy_count,
        fallback_used,
    )
    return products

from app.utils.lock import file_lock
from app.services.system_config_manager import PRODUCTS_FILE

def save_products(data):
    return secure_save_products(data, user_id='Sistema')

def secure_save_products(new_products, user_id='Sistema', allow_empty_overwrite=False):
    """
    Securely saves products with validation, auditing, and integrity checks.
    """
    try:
        # We don't lock HERE because the caller should have locked to ensure atomicity 
        # of the whole read-modify-write cycle.
        # But if the caller didn't lock, we are still vulnerable to race conditions 
        # between load_products() (step 1) and _save_json_atomic() (step 4).
        
        # However, locking here implies we might deadlock if the caller already locked?
        # file_lock is NOT reentrant if using simple os.open/fcntl?
        # Our implementation uses a .lock file. If the same process tries to lock again, it will block itself if it doesn't check owner.
        # Our file_lock implementation in app/utils/lock.py:
        # fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        # It is NOT reentrant.
        
        # So we MUST NOT lock here if the caller already locked.
        # But we can't easily know.
        
        # Strategy:
        # The caller MUST lock.
        # If we lock here, we break callers that correctly locked.
        
        # The issue the user is reporting is "Conflito de edição".
        # This happens at step 2 (Optimistic Locking check).
        
        # 1. Load current state for comparison
        old_products = load_products()
        old_map = {str(p.get('id')): p for p in old_products}
        
        # 2. Process changes
        processed_products = []
        changes_detected = False
        
        for p in new_products:
            p_id = str(p.get('id'))
            
            # Validate
            try:
                StockSecurityService.validate_product(p)
            except ValueError as e:
                logging.error(f"Validation failed for product {p.get('name')}: {e}")
                raise
            
            if p_id in old_map:
                old_p = old_map[p_id]
                
                # Optimistic Locking
                # If we are in a lock, old_p should be identical to what the caller loaded.
                # If they differ, it means the caller modified 'p' but didn't update 'version',
                # OR the caller loaded stale data (didn't lock before load).
                
                if 'version' in p and 'version' in old_p:
                    if int(p['version']) != int(old_p['version']):
                         # If we are here, it means mismatch.
                         # If the caller held the lock, this shouldn't happen unless:
                         # The caller loaded data, THEN acquired lock? (Bad pattern)
                         # My fix in stock.py does: with lock: load(); modify(); save(). Correct.
                         
                         raise ValueError(f"Conflito de edição detectado para {p.get('name')}. Recarregue a página.")
                
                # Generate Diff
                diff = StockSecurityService.generate_diff(old_p, p)
                if diff:
                    changes_detected = True
                    # Update Version and Hash
                    p['version'] = int(old_p.get('version', 1)) + 1
                    p['last_updated'] = datetime.now().isoformat()
                    p['hash'] = StockSecurityService.calculate_hash(p)
                    
                    # Audit Log
                    StockSecurityService.log_audit('UPDATE', user_id, p_id, {'name': p['name']}, diff)
                else:
                    # Keep existing metadata if no change
                    p['version'] = old_p.get('version', 1)
                    p['hash'] = old_p.get('hash', '')
                    p['last_updated'] = old_p.get('last_updated', '')
            else:
                # New Product
                changes_detected = True
                p['version'] = 1
                p['last_updated'] = datetime.now().isoformat()
                p['hash'] = StockSecurityService.calculate_hash(p)
                StockSecurityService.log_audit('CREATE', user_id, p_id, p)
            
            processed_products.append(p)
            
        # 3. Check for deletions
        new_ids = set(str(p.get('id')) for p in processed_products)
        for old_id, old_p in old_map.items():
            if old_id not in new_ids:
                changes_detected = True
                StockSecurityService.log_audit('DELETE', user_id, old_id, old_p)

        if len(processed_products) == 0 and len(old_products) > 0 and not bool(allow_empty_overwrite):
            msg = f"Bloqueio de integridade: tentativa de sobrescrever products.json com lista vazia (old_count={len(old_products)})."
            logging.error(msg)
            StockSecurityService.log_audit('EMPTY_OVERWRITE_BLOCKED', user_id, 'ALL', {'message': msg})
            raise ValueError(msg)

        # 3.1. Detect Bulk Changes (Anti-Overwrite)
        try:
            is_bulk, bulk_details = StockSecurityService.detect_bulk_changes(old_products, processed_products)
            if is_bulk:
                msg = f"SECURITY ALERT: {bulk_details}"
                logging.warning(msg)
                StockSecurityService.log_audit('BULK_CHANGE_ALERT', user_id, 'ALL', {'message': msg})
                # Trigger immediate backup for safety
                StockSecurityService.create_stock_backup()
        except Exception as e:
            logging.error(f"Error detecting bulk changes: {e}")

        # 4. Save if changes
        if changes_detected:
            # Create Checkpoint periodically or on critical changes? 
            # Let's do standard backup first
            canonical_products_path = _canonical_write_path(PRODUCTS_FILE)
            logging.info(
                "products_save_write target_path=%s old_count=%s new_count=%s changes_detected=%s user=%s",
                canonical_products_path,
                len(old_products),
                len(processed_products),
                changes_detected,
                user_id,
            )
            _backup_before_write(PRODUCTS_FILE)
            return _save_json_atomic(PRODUCTS_FILE, processed_products)
        
        return True
        
    except Exception as e:
        logging.error(f"Secure Save Error: {e}")
        raise e

def load_suppliers(): return _load_json(SUPPLIERS_FILE, [])
def save_suppliers(data): return _save_json(SUPPLIERS_FILE, data)


def _get_payables_path():
    try:
        import app as _app
        if hasattr(_app, 'PAYABLES_FILE') and _app.PAYABLES_FILE:
            return _app.PAYABLES_FILE
        if hasattr(_app, 'get_data_path'):
            return _app.get_data_path('payables.json')
    except Exception:
        return PAYABLES_FILE

def load_payables(): return _load_json(_get_payables_path(), [])
def save_payables(data): return _save_json(_get_payables_path(), data)

def load_stock_entries(): return _load_json(STOCK_ENTRIES_FILE, [], strict=True)
def save_stock_entries(data):
    _backup_before_write(STOCK_ENTRIES_FILE)
    return _save_json_atomic(STOCK_ENTRIES_FILE, data)

def save_stock_entry(entry):
    entries = load_stock_entries()
    entries.append(entry)
    save_stock_entries(entries)

def add_stock_entries_batch(new_entries):
    """
    Adds multiple stock entries with deduplication check based on 'id'.
    Does NOT handle locking; caller must ensure concurrency control if needed.
    """
    entries = load_stock_entries()
    existing_ids = set(e.get('id') for e in entries if e.get('id'))
    
    added_count = 0
    for entry in new_entries:
        if entry.get('id') and entry['id'] not in existing_ids:
            entries.append(entry)
            existing_ids.add(entry['id'])
            added_count += 1
        elif not entry.get('id'):
            # If no ID, append anyway (legacy support) but ideally all should have IDs
            entries.append(entry)
            added_count += 1
            
    if added_count > 0:
        save_stock_entries(entries)
    return added_count

def load_conferences(): return _load_json(CONFERENCES_FILE, [])
def save_conferences(data): return _save_json(CONFERENCES_FILE, data)

def load_conference_presets(): return _load_json(CONFERENCE_PRESETS_FILE, [])
def save_conference_presets(data): return _save_json(CONFERENCE_PRESETS_FILE, data)

def load_conference_skipped_items(): return _load_json(CONFERENCE_SKIPPED_FILE, [])
def save_conference_skipped_items(data): return _save_json(CONFERENCE_SKIPPED_FILE, data)

def load_stock_transfers(): return _load_json(STOCK_TRANSFERS_FILE, [])
def save_stock_transfers(data): return _save_json(STOCK_TRANSFERS_FILE, data)

# --- Fixed Assets ---
def load_fixed_assets(): return _load_json(FIXED_ASSETS_FILE, [])
def save_fixed_assets(data): return _save_json(FIXED_ASSETS_FILE, data)

def load_asset_conferences(): return _load_json(ASSET_CONFERENCES_FILE, [])
def save_asset_conferences(data): return _save_json(ASSET_CONFERENCES_FILE, data)

import shutil
import logging
_table_orders_context = threading.local()

def _table_orders_hash(data):
    try:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    except Exception:
        payload = json.dumps({}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def _merge_table_orders_data(current_data, incoming_data):
    if not isinstance(current_data, dict):
        current_data = {}
    if not isinstance(incoming_data, dict):
        return current_data
    merged = copy.deepcopy(current_data)
    for key, value in incoming_data.items():
        if value is None:
            merged.pop(key, None)
            continue
        merged[key] = value
    return merged

# --- Table Orders ---
def load_table_orders():
    data = _load_json(TABLE_ORDERS_FILE, {}, strict=True)
    _table_orders_context.last_loaded_hash = _table_orders_hash(data)
    return data

def save_table_orders(data):
    with file_lock(TABLE_ORDERS_FILE):
        try:
            user = session.get('user') if session else 'system'
        except:
            user = 'unknown'

        incoming_data = data if isinstance(data, dict) else {}
        current_data = _load_json(TABLE_ORDERS_FILE, {}) if os.path.exists(TABLE_ORDERS_FILE) else {}
        current_hash = _table_orders_hash(current_data)
        expected_hash = getattr(_table_orders_context, 'last_loaded_hash', None)
        if expected_hash and expected_hash != current_hash:
            incoming_data = _merge_table_orders_data(current_data, incoming_data)
            logging.warning(f"Concurrent update detected in table_orders. User: {user}. Applying merge strategy.")

        current_size = len(incoming_data) if incoming_data else 0
        logging.info(f"Attempting to save table_orders. User: {user}. Items count: {current_size}")

        if os.path.exists(TABLE_ORDERS_FILE):
            try:
                old_size = len(current_data)
                if old_size > 0 and current_size == 0:
                    logging.warning(f"CRITICAL: Wipe detected on table_orders.json! User: {user}. Backing up before wipe.")

                backup_dir = os.path.join(os.path.dirname(TABLE_ORDERS_FILE), 'backups', 'table_orders')
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                backup_path = os.path.join(backup_dir, f"table_orders_{timestamp}_{user}.json")
                shutil.copy2(TABLE_ORDERS_FILE, backup_path)

                backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir)], key=os.path.getmtime)
                while len(backups) > 50:
                    os.remove(backups.pop(0))

            except Exception as e:
                logging.error(f"Failed to create backup for table_orders: {e}")

        saved = _save_json_atomic(TABLE_ORDERS_FILE, incoming_data)
        if saved:
            _table_orders_context.last_loaded_hash = _table_orders_hash(incoming_data)
        return saved

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
