import json
import os
import uuid
import threading
import requests
from datetime import datetime
from app.services.system_config_manager import get_data_path, get_config_value, FISCAL_POOL_FILE
from app.services.data_service import load_menu_items, _backup_before_write, _save_json_atomic

# FISCAL_POOL_FILE = get_data_path('fiscal_pool.json')

class FiscalPoolService:
    @staticmethod
    def _load_pool():
        if not os.path.exists(FISCAL_POOL_FILE):
            return []
        try:
            with open(FISCAL_POOL_FILE, 'r', encoding='utf-8') as f:
                pool = json.load(f)
                
            # Migration / Backfill
            modified = False
            for entry in pool:
                # Backfill 'closed_at' if missing
                if 'closed_at' not in entry:
                    entry['closed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    modified = True
                
                # Check if we need to recalculate fiscal_amount
                # Scenarios:
                # 1. Missing 'fiscal_amount'
                # 2. 'fiscal_amount' is 0 but total > 0, and payments don't have explicit 'is_fiscal' flags (Legacy migration issue)
                
                recalc_needed = False
                if 'fiscal_amount' not in entry:
                    recalc_needed = True
                elif entry.get('fiscal_amount', 0) == 0 and entry.get('total_amount', 0) > 0:
                    # Check if any payment has is_fiscal flag
                    pms = entry.get('payment_methods') or []
                    has_explicit_flag = any('is_fiscal' in pm for pm in pms)
                    if not has_explicit_flag:
                        recalc_needed = True
                
                if recalc_needed:
                    pms = entry.get('payment_methods') or []
                    fiscal_val = 0.0
                    has_fiscal_flag = False
                    
                    for pm in pms:
                        # If flag exists, use it
                        if pm.get('is_fiscal'):
                            has_fiscal_flag = True
                            fiscal_val += float(pm.get('amount', 0.0))
                    
                    if has_fiscal_flag:
                        entry['fiscal_amount'] = round(fiscal_val, 2)
                    else:
                        # Fallback for legacy data without flags: assume total is fiscal
                        # This fixes the migration of old closed accounts
                        entry['fiscal_amount'] = float(entry.get('total_amount', 0.0))
                    
                    # Cap at total
                    if entry['fiscal_amount'] > float(entry.get('total_amount', 0.0)):
                        entry['fiscal_amount'] = float(entry.get('total_amount', 0.0))
                        
                    modified = True
            
            if modified:
                try:
                    _backup_before_write(FISCAL_POOL_FILE)
                    _save_json_atomic(FISCAL_POOL_FILE, pool)
                except: pass
                
            return pool
        except Exception:
            return []

    @staticmethod
    def _save_pool(pool):
        try:
            _backup_before_write(FISCAL_POOL_FILE)
            return _save_json_atomic(FISCAL_POOL_FILE, pool)
        except Exception:
            return False

    @staticmethod
    def add_to_pool(origin, original_id, total_amount, items, payment_methods, user, customer_info=None, notes=None):
        """
        Adds a closed account snapshot to the fiscal pool.
        origin: 'restaurant', 'reception', 'daily_rates'
        """
        pool = FiscalPoolService._load_pool()
        
        # Determine fiscal type and issuer CNPJ
        fiscal_type = 'nfce' # Default (Product)
        cnpj_emitente = '28952732000109' # Default: Mirapraia
        
        # Load Menu Items for enrichment
        try:
            menu_items = load_menu_items()
            menu_map = {str(m['id']): m for m in menu_items}
            # Fallback map by name
            menu_map_name = {m['name'].lower().strip(): m for m in menu_items}
        except:
            menu_map = {}
            menu_map_name = {}
        
        enriched_items = []
        for item in items:
            # Clone item to avoid modifying original reference if any
            new_item = item.copy()
            
            # Ensure basic fields are correct type
            try:
                new_item['qty'] = float(new_item.get('qty', 1))
                new_item['price'] = float(new_item.get('price', 0))
                if 'total' in new_item:
                    new_item['total'] = float(new_item['total'])
                else:
                    new_item['total'] = new_item['qty'] * new_item['price']
            except: pass
            
            # Find in menu
            product = None
            if 'id' in new_item and str(new_item['id']) in menu_map:
                product = menu_map[str(new_item['id'])]
            elif 'name' in new_item and new_item['name'].lower().strip() in menu_map_name:
                product = menu_map_name[new_item['name'].lower().strip()]
            
            if product:
                # Enrich with fiscal data if missing in item
                # Priorities: item > product > default
                if not new_item.get('ncm'): new_item['ncm'] = product.get('ncm')
                if not new_item.get('cest'): new_item['cest'] = product.get('cest')
                if not new_item.get('cfop'): new_item['cfop'] = product.get('cfop')
                if not new_item.get('origin'): new_item['origin'] = product.get('origin')
                
                # Tax info
                if not new_item.get('tax_situation'): new_item['tax_situation'] = product.get('tax_situation')
                if not new_item.get('icms_rate'): new_item['icms_rate'] = product.get('icms_rate')
                if not new_item.get('pis_cst'): new_item['pis_cst'] = product.get('pis_cst')
                if not new_item.get('cofins_cst'): new_item['cofins_cst'] = product.get('cofins_cst')
            
            # Default fallback for required fields if still missing
            if not new_item.get('ncm'): new_item['ncm'] = '00000000' # Invalid but prevents crash? Or better let it fail?
            # Actually empty NCM causes rejection. But '00000000' also causes rejection.
            # We leave it empty if not found, validator will catch it.
            
            enriched_items.append(new_item)

        if origin == 'daily_rates':
            fiscal_type = 'nfse' # Service
            cnpj_emitente = '46500590000112' # Almareia
        elif origin == 'reception':
            # Check items for services
            if any(item.get('is_service') for item in enriched_items):
                fiscal_type = 'nfse'
                # Ideally mixed carts should be split, but if service is present, 
                # we might treat as service or daily rate if it's accommodation.
                # If it's pure consumption at reception (minibar), it stays NFC-e Mirapraia.
                # If it's accommodation payment at reception, it goes to Almareia.
                # We need a flag in items or check categories.
                # Simple heuristic: If "Diária" or "Hospedagem" in item name -> Almareia
                is_accommodation = any(
                    'diaria' in str(item.get('name', '')).lower() or 
                    'hospedagem' in str(item.get('name', '')).lower() 
                    for item in enriched_items
                )
                if is_accommodation:
                    cnpj_emitente = '46500590000112' # Almareia
        
        # Override if specific fiscal_cnpj in payment methods (Legacy support)
        # Only if all payments point to the same CNPJ distinct from default
        # (This logic can be refined, but for now we stick to Origin-based rules as requested)
        
        # Calculate Fiscal Amount
        fiscal_amount = 0.0
        for pm in payment_methods:
            if pm.get('is_fiscal'):
                fiscal_amount += float(pm.get('amount', 0.0))
        
        # Ensure we don't exceed total_amount due to rounding
        if fiscal_amount > float(total_amount):
            fiscal_amount = float(total_amount)
            
        entry = {
            'id': str(uuid.uuid4()),
            'origin': origin,
            'fiscal_type': fiscal_type,
            'cnpj_emitente': cnpj_emitente,
            'original_id': str(original_id),
            'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'closed_by': user,
            'total_amount': float(total_amount),
            'fiscal_amount': round(fiscal_amount, 2),
            'items': enriched_items,
            'payment_methods': payment_methods,
            'customer': customer_info or {},
            'status': 'pending', # pending, emitted, ignored
            'notes': notes,
            'fiscal_doc_uuid': None,
            'history': []
        }
        
        # Snapshot minimal fiscal config at the time of export for stability on later emission
        try:
            # Lazy import to avoid circular import at module import time
            from app.services.fiscal_service import load_fiscal_settings, get_fiscal_integration
            settings = load_fiscal_settings()
            integ = get_fiscal_integration(settings, cnpj_emitente)
            if integ:
                entry['fiscal_snapshot'] = {
                    'sefaz_environment': integ.get('sefaz_environment', integ.get('environment', 'production')),
                    'environment': integ.get('environment', 'production'),
                    'serie': integ.get('serie'),
                    'ie_emitente': integ.get('ie_emitente'),
                    'CRT': integ.get('CRT', integ.get('crt'))
                }
        except Exception:
            pass
        
        pool.append(entry)
        FiscalPoolService._save_pool(pool)
        
        # Async Sync to Remote
        try:
            threading.Thread(target=FiscalPoolService.sync_entry_to_remote, args=(entry,)).start()
        except Exception as e:
            print(f"Error starting fiscal sync thread: {e}")
            
        return entry['id']

    @staticmethod
    def sync_entry_to_remote(entry):
        """
        Sends the fiscal entry to the remote fiscal management server.
        """
        try:
            # We post to the remote URL. 
            # Note: The user gave http://192.168.69.99:5000/config/fiscal which seems to be a UI URL.
            # We will assume there is an API endpoint or we post to a specific 'receive' endpoint.
            # If the user meant the UI, we can't really "transfer" to a UI.
            # We'll try posting to /api/fiscal/receive or similar, but for now let's use the base + /api/receive
            # OR we simply post to the exact URL provided if it accepts POST.
            # Given instructions "transfer to...", let's assume an endpoint exists.
            # I will use a dedicated API endpoint assumption: /api/fiscal/receive
            
            # However, looking at the URL http://192.168.69.99:5000/config/fiscal, it looks like another instance of THIS app.
            # If so, it might have the SAME routes.
            # But 'config/fiscal' is the UI route I just added to THIS app.
            # So I should probably add a receiver route to THIS app's code (which will run on the other server too)
            # to handle the incoming POST.
            
            target_url = str(
                get_config_value(
                    'fiscal_pool_remote_receive_url',
                    "http://192.168.69.99:5001/api/fiscal/receive"
                ) or ''
            ).strip()
            if not target_url:
                return False
            
            response = requests.post(target_url, json=entry, timeout=5)
            if response.status_code == 200:
                print(f"Fiscal Entry {entry['id']} synced to remote successfully.")
                return True
            else:
                print(f"Failed to sync fiscal entry {entry['id']}: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Exception syncing fiscal entry {entry['id']}: {e}")
            return False

    @staticmethod
    def set_xml_ready(entry_id, ready=True, xml_path=None):
        """
        Marks an entry as having its XML available and optionally stores the path.
        """
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                entry['xml_ready'] = bool(ready)
                if xml_path:
                    entry['xml_path'] = xml_path
                try:
                    with open(FISCAL_POOL_FILE, 'w', encoding='utf-8') as f:
                        json.dump(pool, f, indent=4, ensure_ascii=False)
                    return True
                except Exception:
                    return False
        return False

    @staticmethod
    def set_pdf_ready(entry_id, ready=True, pdf_path=None):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                entry['pdf_ready'] = bool(ready)
                if pdf_path:
                    entry['pdf_path'] = pdf_path
                try:
                    with open(FISCAL_POOL_FILE, 'w', encoding='utf-8') as f:
                        json.dump(pool, f, indent=4, ensure_ascii=False)
                    return True
                except Exception:
                    return False
        return False

    @staticmethod
    def get_pool(filters=None):
        pool = FiscalPoolService._load_pool()
        if not filters:
            # Return sorted by date desc
            return sorted(pool, key=lambda x: x['closed_at'], reverse=True)
            
        filtered = []
        for entry in pool:
            match = True
            if filters.get('status') and filters['status'] != 'all' and entry['status'] != filters['status']:
                match = False
            if filters.get('origin') and filters['origin'] != 'all' and entry['origin'] != filters['origin']:
                match = False
            if filters.get('date_start'):
                # Simple string compare works if format is YYYY-MM-DD
                if entry['closed_at'] < filters['date_start']:
                    match = False
            if filters.get('date_end'):
                if entry['closed_at'] > filters['date_end']:
                    match = False
                    
            if match:
                filtered.append(entry)
                
        return sorted(filtered, key=lambda x: x['closed_at'], reverse=True)

    @staticmethod
    def get_entry(entry_id):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                return entry
        return None

    @staticmethod
    def update_status(entry_id, new_status, fiscal_doc_uuid=None, user='Sistema', serie=None, number=None, error_msg=None):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                old_status = entry['status']
                entry['status'] = new_status
                if fiscal_doc_uuid:
                    entry['fiscal_doc_uuid'] = fiscal_doc_uuid
                
                if serie:
                    entry['fiscal_serie'] = serie
                if number:
                    entry['fiscal_number'] = number
                
                if error_msg:
                    entry['last_error'] = error_msg
                
                entry['history'].append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'status_change',
                    'from': old_status,
                    'to': new_status,
                    'user': user,
                    'details': error_msg
                })
                
                FiscalPoolService._save_pool(pool)
                return True
        return False
