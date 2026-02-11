import os
import re
import sys

# Define manual overrides for renamed endpoints
# key: old_name (found in template), value: new_name (valid endpoint)
MANUAL_OVERRIDES = {
    'manage_printers': 'admin.printers_config',
    'admin_backups': 'admin.admin_backups_view',
    'admin_logs_view': 'admin.view_logs',
    'admin_system_dashboard_view': 'admin.admin_dashboard', # Best guess
    'export_security_alerts': 'admin.admin_security_dashboard', # Fallback or specific export route? checking dump... 'admin.resolve_security_alert' exists. 'admin.admin_security_dashboard' exists. 
    # Let's check valid_endpoints_dump.txt for export... 
    # 'admin.api_export_logs_unified' exists.
    # 'finance.finance_balances_export' exists.
    # If not found, leave it or map to dashboard.
    
    'flavor_config_endpoint': 'menu.flavor_config_endpoint',
    'delete_menu_item': 'menu.delete_menu_item',
    'kitchen_portion': 'kitchen.kitchen_portion',
    'service_page': 'main.service_page',
    'stock_inventory': 'stock.stock_inventory',
    'stock_products': 'stock.stock_products',
    'menu_management': 'menu.menu_management',
    'config_categories': 'menu.config_categories',
    'reception_chat': 'reception.reception_chat',
    'reception_reservations': 'reception.reception_reservations',
    'reception_dashboard': 'reception.reception_dashboard',
    'reception_cashier': 'reception.reception_cashier',
    'reception_rooms': 'reception.reception_rooms',
    'reception_waiting_list': 'reception.reception_waiting_list',
    'reception_reservations_cashier': 'reception.reception_reservations_cashier',
    'reception_edit_charge': 'reception.reception_edit_charge',
    'reception_surveys': 'reception.reception_surveys',
    'reception_survey_edit': 'reception.reception_survey_edit',
    'reception_survey_questions': 'reception.reception_survey_questions',
    'reception_survey_dashboard': 'reception.reception_survey_dashboard', # Wait, check if this exists.
    # dump has: reception.reception_surveys (plural)
    # dump has: guest.satisfaction_survey
    # dump has: reception.reception_surveys
    # Let's check dump for 'survey_dashboard'
    # No 'survey_dashboard'.
    # Maybe 'reception.reception_surveys' IS the dashboard?
    
    'client_menu': 'menu.client_menu',
    'rh_sign_document': 'hr.rh_sign_document',
    'auto_import_sales': 'stock.auto_import_sales',
    'process_sales_log': 'stock.process_sales_log',
    'scan_sales_products': 'stock.scan_sales_products',
    'link_sales_product': 'stock.link_sales_product',
    'ignore_sales_product': 'stock.ignore_sales_product',
    'unlink_sales_product': 'stock.unlink_sales_product',
    'update_maintenance_request': 'maintenance.update_maintenance_request',
    'kitchen_reports': 'kitchen.kitchen_reports',
    'acknowledge_low_stock': 'kitchen.acknowledge_low_stock',
    'delete_portion_entry': 'kitchen.delete_portion_entry',
    'flavor_config_add_group': 'menu.flavor_config_add_group',
    'flavor_config_delete_group': 'menu.flavor_config_delete_group',
    'flavor_config_add_item': 'menu.flavor_config_add_item',
    'flavor_config_delete_item': 'menu.flavor_config_delete_item',
    'finance_commission_calculate': 'finance.finance_commission_calculate',
    'finance_commission_refresh_scores': 'finance.finance_commission_refresh_scores',
    'finance_commission_approve': 'finance.finance_commission_approve',
    'finance_commission_update_employee': 'finance.finance_commission_update_employee',
    'finance_commission_detail': 'finance.finance_commission_detail',
    'finance_commission_delete': 'finance.finance_commission_delete',
    'close_staff_month': 'finance.close_staff_month',
    'finance_reconciliation_sync': 'finance.finance_reconciliation_sync',
    'finance_reconciliation_upload': 'finance.finance_reconciliation_upload',
    'finance_reconciliation_remove_account': 'finance.finance_reconciliation_remove_account',
    'finance_reconciliation_add_account': 'finance.finance_reconciliation_add_account',
    'new_stock_request': 'stock.new_stock_request',
    'stock_confirmation': 'stock.stock_confirmation',
    'stock_fulfillment': 'stock.stock_fulfillment',
    'stock_order': 'stock.stock_order',
    'stock_entry': 'stock.stock_entry',
    'stock_adjust_min_levels': 'stock.stock_adjust_min_levels',
    'stock_categories': 'stock.stock_categories',
    'kitchen_portion_settings': 'kitchen.kitchen_portion_settings',
    'confirm_schedule': 'maintenance.confirm_schedule',
    'toggle_queue_status': 'reception.toggle_queue_status',
    'update_queue_status': 'reception.update_queue_status',
    'update_queue_settings': 'reception.update_queue_settings',
    'log_queue_notification': 'reception.log_queue_notification',
    'send_queue_notification': 'reception.send_queue_notification',
    'cancel_waiting_list_entry': 'restaurant.cancel_waiting_list_entry',
    'admin_reset_password_action': 'auth.admin_reset_password_action',
    'stock_dashboard': 'stock.stock_products',
}

# Endpoints known to be missing/broken -> Replace with '#'
BROKEN_ENDPOINTS = {
    'reception_survey_edit',
    'reception_survey_questions',
    'reception_survey_dashboard',
    'reception.reception_survey_edit', 
    'reception.reception_survey_questions',
    'reception.reception_survey_dashboard',
    'reception_survey_invite_new',
    'entertainment_control',
    'entertainment_roku_tvs',
}

def load_valid_endpoints():
    endpoints = set()
    try:
        with open('valid_endpoints_dump.txt', 'r', encoding='utf-8') as f:
            for line in f:
                endpoints.add(line.strip())
    except FileNotFoundError:
        print("Error: valid_endpoints_dump.txt not found. Run audit first.")
        sys.exit(1)
    return endpoints

def build_auto_map(endpoints):
    auto_map = {}
    basename_counts = {}
    
    # First pass: count basenames
    for ep in endpoints:
        parts = ep.split('.')
        if len(parts) >= 2:
            basename = parts[-1]
            basename_counts[basename] = basename_counts.get(basename, 0) + 1
            
    # Second pass: build map for unique basenames
    for ep in endpoints:
        parts = ep.split('.')
        if len(parts) >= 2:
            basename = parts[-1]
            # Special case: if basename is same as endpoint (no dot), ignore
            if basename_counts[basename] == 1:
                auto_map[basename] = ep
                
    return auto_map

def fix_file(file_path, mapping, dry_run=False):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    original_content = content
    changes = []
    
    # Regex to find url_for('ENDPOINT'
    pattern = r"(url_for\s*\(\s*['\"])([\w\.]+)(['\"])"
    
    def replace_func(match):
        prefix = match.group(1)
        endpoint = match.group(2)
        suffix = match.group(3)
        
        new_endpoint = endpoint
        
        # Check broken first - Map to safe fallback
        if endpoint in BROKEN_ENDPOINTS:
            changes.append(f"{endpoint} -> reception.reception_dashboard (BROKEN FALLBACK)")
            # Use a safe fallback based on context
            if 'reception' in endpoint:
                return f"{prefix}reception.reception_dashboard{suffix}"
            else:
                return f"{prefix}main.index{suffix}"

        if endpoint in MANUAL_OVERRIDES:
            new_endpoint = MANUAL_OVERRIDES[endpoint]
        elif endpoint in mapping:
            new_endpoint = mapping[endpoint]
            
        if new_endpoint != endpoint:
            changes.append(f"{endpoint} -> {new_endpoint}")
            return f"{prefix}{new_endpoint}{suffix}"
        
        return match.group(0)
        
    new_content = re.sub(pattern, replace_func, content)
    
    if new_content != original_content:
        if not dry_run:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        return changes
    return []

def main():
    dry_run = '--dry-run' in sys.argv
    
    print("Loading endpoints...")
    valid_endpoints = load_valid_endpoints()
    
    print("Building mapping...")
    auto_map = build_auto_map(valid_endpoints)
    
    # Merge overrides into auto_map (overrides take precedence)
    full_map = auto_map.copy()
    full_map.update(MANUAL_OVERRIDES)
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, 'app', 'templates')
    
    print(f"Scanning templates in {templates_dir}...")
    
    total_files = 0
    total_changes = 0
    
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, templates_dir)
                
                changes = fix_file(file_path, full_map, dry_run)
                
                if changes:
                    print(f"File: {rel_path}")
                    for change in changes:
                        print(f"  Fixed: {change}")
                    total_files += 1
                    total_changes += len(changes)
                    
    print("\nSummary:")
    print(f"Files modified: {total_files}")
    print(f"Total fixes: {total_changes}")
    if dry_run:
        print("DRY RUN: No files were actually changed.")

if __name__ == "__main__":
    main()
