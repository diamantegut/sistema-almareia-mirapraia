import json
import os
import hashlib
from app.services.path_resolver import PathResolver, get_audit_events

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

PATH_RESOLVER_MODE = 'legacy'
_PATH_RESOLVER = None

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

def _get_path_resolver():
    global _PATH_RESOLVER
    if _PATH_RESOLVER is None:
        _PATH_RESOLVER = PathResolver(
            base_dir=BASE_DIR,
            config_loader=load_system_config,
            mode=PATH_RESOLVER_MODE
        )
    return _PATH_RESOLVER

def get_data_path(filename):
    resolver = _get_path_resolver()
    return str(resolver.resolve_data(filename))

def get_project_root_path(filename):
    return os.path.join(BASE_DIR, str(filename or ''))

def get_legacy_root_json_path(filename):
    name = os.path.basename(str(filename or ''))
    return get_project_root_path(name)

def resolve_json_read_path(filename, canonical_path=None):
    canonical = str(canonical_path or get_data_path(filename))
    if os.path.exists(canonical):
        return canonical, False
    legacy = get_legacy_root_json_path(filename)
    if os.path.abspath(legacy) != os.path.abspath(canonical) and os.path.exists(legacy):
        return legacy, True
    return canonical, False

def build_json_pair_snapshot(filename):
    name = os.path.basename(str(filename or ''))
    canonical = get_data_path(name)
    legacy = get_legacy_root_json_path(name)
    def _meta(path):
        if not os.path.exists(path):
            return {
                'exists': False,
                'size': 0,
                'mtime': None,
                'sha256': None,
                'valid_json': False
            }
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
        sha256 = None
        valid_json = False
        try:
            digest = hashlib.sha256()
            with open(path, 'rb') as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            sha256 = digest.hexdigest()
        except Exception:
            sha256 = None
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                json.load(stream)
            valid_json = True
        except Exception:
            valid_json = False
        return {
            'exists': True,
            'size': int(size),
            'mtime': float(mtime),
            'sha256': sha256,
            'valid_json': valid_json
        }
    canonical_meta = _meta(canonical)
    legacy_meta = _meta(legacy)
    return {
        'name': name,
        'canonical_path': canonical,
        'legacy_path': legacy,
        'canonical': canonical_meta,
        'legacy': legacy_meta
    }

CRITICAL_JSON_RECONCILIATION_FILES = (
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
)

def build_critical_json_reconciliation_report():
    report = []
    for name in CRITICAL_JSON_RECONCILIATION_FILES:
        snapshot = build_json_pair_snapshot(name)
        canonical = snapshot['canonical']
        legacy = snapshot['legacy']
        divergent = bool(
            canonical.get('exists') and
            legacy.get('exists') and
            canonical.get('sha256') != legacy.get('sha256')
        )
        newer = 'none'
        canonical_mtime = canonical.get('mtime')
        legacy_mtime = legacy.get('mtime')
        if canonical.get('exists') and (not legacy.get('exists') or (canonical_mtime or 0) >= (legacy_mtime or 0)):
            newer = 'data'
        elif legacy.get('exists'):
            newer = 'legacy_root'
        snapshot['divergent'] = divergent
        snapshot['newer'] = newer
        report.append(snapshot)
    return report

def get_log_path(filename):
    resolver = _get_path_resolver()
    return str(resolver.resolve_log(filename))

def get_backup_path(subpath=''):
    resolver = _get_path_resolver()
    return str(resolver.resolve_backup(subpath))

def get_fiscal_path(subpath=''):
    resolver = _get_path_resolver()
    return str(resolver.resolve_fiscal(subpath))

def validate_paths():
    resolver = _get_path_resolver()
    report = resolver.validate(['data', 'log', 'backup', 'fiscal'])
    return list(report.checks.items())

def get_path_resolution_audit(limit=200):
    return get_audit_events(limit=limit)

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
FINANCIAL_LEDGER_FILE = get_data_path('financial_ledger.json')
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
FIXED_ASSETS_FILE = get_data_path('fixed_assets.json')
ASSET_CONFERENCES_FILE = get_data_path('asset_conferences.json')
SALES_PRODUCTS_FILE = get_data_path('sales_products.json')
SUPPLIERS_FILE = get_data_path('suppliers.json')
CONFERENCES_FILE = get_data_path('conferences.json')
CONFERENCE_PRESETS_FILE = get_data_path('conference_presets.json')
CONFERENCE_SKIPPED_FILE = get_data_path('conference_skipped_items.json')
BAR_DATA_FILE = get_data_path('bar_data.json')

# Hotel Operations
ROOM_OCCUPANCY_FILE = get_data_path('room_occupancy.json')
MANUAL_ALLOCATIONS_FILE = get_data_path('manual_allocations.json')
GUEST_DETAILS_FILE = get_data_path('guest_details.json')
MANUAL_RESERVATIONS_FILE = get_data_path('manual_reservations.json')
RESERVATION_DAILY_SPLITS_FILE = get_data_path('reservation_daily_splits.json')
RESERVATIONS_DIR = get_data_path('reservations')
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
FINANCIAL_AUDIT_LOGS_FILE = get_data_path('financial_audit_logs.json')
FINANCIAL_RISK_EVENTS_FILE = get_data_path('financial_risk_events.json')
PASSWORD_RESET_REQUESTS_FILE = get_data_path('password_reset_requests.json')
DEPARTMENT_PERMISSIONS_FILE = get_data_path('department_permissions.json')

SYSTEM_STATUS_FILE = get_data_path('system_status.json')
FISCAL_POOL_FILE = get_data_path('fiscal_pool.json')
LAST_SYNC_FILE = get_data_path('last_sync.json')
BACKUP_CONFIG_FILE = get_data_path('backup_config.json')
OTA_BOOKING_INTEGRATIONS_FILE = get_data_path('ota_booking_integrations.json')
OTA_BOOKING_SECRET_KEY_FILE = get_data_path('ota_booking_secret.key')
OTA_BOOKING_TOKEN_CACHE_FILE = get_data_path('ota_booking_token_cache.json')
OTA_BOOKING_DISTRIBUTION_LOGS_FILE = get_data_path('ota_booking_distribution_logs.json')
OTA_BOOKING_ERROR_LOGS_FILE = get_data_path('ota_booking_error_logs.json')
OTA_BOOKING_STATUS_HISTORY_FILE = get_data_path('ota_booking_status_history.json')
OTA_BOOKING_PENDING_RATES_FILE = get_data_path('ota_booking_pending_rates.json')
OTA_BOOKING_CHANNEL_CTA_CTD_FILE = get_data_path('ota_booking_channel_cta_ctd.json')
OTA_BOOKING_COMMERCIAL_RESTRICTIONS_FILE = get_data_path('ota_booking_commercial_restrictions.json')
OTA_BOOKING_COMMERCIAL_AUDIT_FILE = get_data_path('ota_booking_commercial_audit.json')
OTA_BOOKING_CATEGORY_MAPPING_FILE = get_data_path('ota_booking_category_mapping.json')
CHANNEL_MANAGER_CHANNELS_FILE = get_data_path('channel_manager_channels.json')
CHANNEL_MANAGER_CHANNELS_LOGS_FILE = get_data_path('channel_manager_channels_logs.json')
CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE = get_data_path('channel_manager_category_mappings.json')
CHANNEL_MANAGER_CATEGORY_MAPPINGS_LOGS_FILE = get_data_path('channel_manager_category_mappings_logs.json')
CHANNEL_MANAGER_TARIFFS_FILE = get_data_path('channel_manager_tariffs.json')
CHANNEL_MANAGER_TARIFFS_LOGS_FILE = get_data_path('channel_manager_tariffs_logs.json')
CHANNEL_MANAGER_INVENTORY_SHARED_FILE = get_data_path('channel_manager_inventory_shared.json')
CHANNEL_MANAGER_INVENTORY_PARTIAL_CLOSURES_FILE = get_data_path('channel_manager_inventory_partial_closures.json')
CHANNEL_MANAGER_INVENTORY_AUDIT_FILE = get_data_path('channel_manager_inventory_audit.json')
CHANNEL_MANAGER_RESTRICTIONS_FILE = get_data_path('channel_manager_restrictions.json')
CHANNEL_MANAGER_RESTRICTIONS_AUDIT_FILE = get_data_path('channel_manager_restrictions_audit.json')
CHANNEL_MANAGER_SYNC_LOGS_FILE = get_data_path('channel_manager_sync_logs.json')
CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE = get_data_path('channel_manager_commercial_audit.json')
CHANNEL_MANAGER_COMMISSIONS_FILE = get_data_path('channel_manager_commissions.json')
CHANNEL_MANAGER_COMMISSIONS_AUDIT_FILE = get_data_path('channel_manager_commissions_audit.json')
PENDING_FISCAL_EMISSIONS_FILE = get_data_path('pending_fiscal_emissions.json')
FISCAL_NSU_FILE = get_data_path('fiscal_nsu.json')
FISCAL_SEFAZ_BLOCK_FILE = get_data_path('fiscal_sefaz_block.json')
FISCAL_SEFAZ_LAST_CHECK_FILE = get_data_path('fiscal_sefaz_last_check.json')
FISCAL_SEFAZ_LOCK_FILE = get_data_path('fiscal_sefaz_lock.json')

# Miscellaneous
OBSERVATIONS_FILE = get_data_path('observations.json')
FISCAL_SETTINGS_FILE = get_data_path('fiscal_settings.json')
LAUNDRY_DATA_DIR = get_data_path('laundry_data')
INSPECTION_LOGS_FILE = get_data_path('inspection_logs.json')
RESTAURANT_TABLE_SETTINGS_FILE = get_data_path('restaurant_table_settings.json')
RESTAURANT_SETTINGS_FILE = get_data_path('restaurant_settings.json')
FLAVOR_GROUPS_FILE = get_data_path('flavor_groups.json')
QUALITY_AUDITS_FILE = get_data_path('quality_audits.json')
REVENUE_EVENTS_FILE = get_data_path('revenue_events.json')
REVENUE_BAR_RULES_FILE = get_data_path('revenue_bar_rules.json')
REVENUE_BAR_CHANGES_FILE = get_data_path('revenue_bar_changes.json')
REVENUE_ADVANCED_SETTINGS_FILE = get_data_path('revenue_advanced_settings.json')
REVENUE_BOOKING_COMMISSION_LOGS_FILE = get_data_path('revenue_booking_commission_logs.json')
INVENTORY_RESTRICTIONS_FILE = get_data_path('inventory_restrictions.json')
INVENTORY_RESTRICTION_LOGS_FILE = get_data_path('inventory_restriction_logs.json')
PROMOTIONAL_PACKAGES_FILE = get_data_path('promotional_packages.json')
PROMOTIONAL_PACKAGES_LOGS_FILE = get_data_path('promotional_packages_logs.json')
STAY_RESTRICTIONS_FILE = get_data_path('stay_restrictions.json')
STAY_RESTRICTIONS_LOGS_FILE = get_data_path('stay_restrictions_logs.json')
REVENUE_PROMOTIONS_FILE = get_data_path('revenue_promotions.json')
REVENUE_PROMOTIONS_LOGS_FILE = get_data_path('revenue_promotions_logs.json')
REVENUE_WEEKDAY_BASE_RATES_FILE = get_data_path('revenue_weekday_base_rates.json')
ARRIVAL_DEPARTURE_RESTRICTIONS_FILE = get_data_path('arrival_departure_restrictions.json')
ARRIVAL_DEPARTURE_RESTRICTIONS_LOGS_FILE = get_data_path('arrival_departure_restrictions_logs.json')
CHANNEL_SALES_RESTRICTIONS_FILE = get_data_path('channel_sales_restrictions.json')
CHANNEL_SALES_RESTRICTIONS_LOGS_FILE = get_data_path('channel_sales_restrictions_logs.json')
BLACKOUT_DATES_FILE = get_data_path('blackout_dates.json')
BLACKOUT_DATES_LOGS_FILE = get_data_path('blackout_dates_logs.json')
CHANNEL_ALLOTMENTS_FILE = get_data_path('channel_allotments.json')
CHANNEL_ALLOTMENTS_LOGS_FILE = get_data_path('channel_allotments_logs.json')
INVENTORY_PROTECTION_RULES_FILE = get_data_path('inventory_protection_rules.json')
INVENTORY_PROTECTION_LOGS_FILE = get_data_path('inventory_protection_logs.json')

# Static Assets
PRODUCT_PHOTOS_DIR = os.path.join(BASE_DIR, 'Produtos', 'Fotos')
SAEPEARL_TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates', 'saepearl_external')
SAEPEARL_ASSETS_DIR = os.path.join(SAEPEARL_TEMPLATE_DIR, "assets")
SALES_DIR = os.path.join(BASE_DIR, 'Vendas')
SALES_EXCEL_PATH = os.path.join(SALES_DIR, 'Produtos.xlsx')

DEPARTMENTS = [
    'Recepção', 'Restaurante', 'Cozinha', 'Governança', 
    'Lavanderia', 'Manutenção', 'Admin', 'RH', 'Serviço', 'Estoque'
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
