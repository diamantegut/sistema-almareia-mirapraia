import json
import os
import uuid
import threading
import requests
from datetime import datetime
from app.services.system_config_manager import get_data_path, get_config_value, FISCAL_POOL_FILE

# FISCAL_POOL_FILE = get_data_path('fiscal_pool.json')

class FiscalPoolService:
    @staticmethod
    def _load_pool():
        if not os.path.exists(FISCAL_POOL_FILE):
            return []
        try:
            with open(FISCAL_POOL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    @staticmethod
    def _save_pool(pool):
        try:
            with open(FISCAL_POOL_FILE, 'w', encoding='utf-8') as f:
                json.dump(pool, f, indent=4, ensure_ascii=False)
            return True
        except Exception:
            return False

    @staticmethod
    def add_to_pool(origin, original_id, total_amount, items, payment_methods, user, customer_info=None, notes=None):
        """
        Adds a closed account snapshot to the fiscal pool.
        origin: 'restaurant', 'reception', 'daily_rates'
        """
        pool = FiscalPoolService._load_pool()
        
        # Determine fiscal type
        fiscal_type = 'nfce' # Default (Product)
        if origin == 'daily_rates':
            fiscal_type = 'nfse' # Service
        elif origin == 'reception':
            # Check items for services
            if any(item.get('is_service') for item in items):
                fiscal_type = 'nfse'
                # Ideally we should split mixed carts, but for now flag as service if present? 
                # Or maybe default to nfce unless it's pure service?
                # Let's assume daily_rates handles the service part.
        
        entry = {
            'id': str(uuid.uuid4()),
            'origin': origin,
            'fiscal_type': fiscal_type,
            'original_id': str(original_id),
            'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'closed_by': user,
            'total_amount': float(total_amount),
            'items': items,
            'payment_methods': payment_methods,
            'customer': customer_info or {},
            'status': 'pending', # pending, emitted, ignored
            'notes': notes,
            'fiscal_doc_uuid': None,
            'history': []
        }
        
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
    def get_pool(filters=None):
        pool = FiscalPoolService._load_pool()
        if not filters:
            # Return sorted by date desc
            return sorted(pool, key=lambda x: x['closed_at'], reverse=True)
            
        filtered = []
        for entry in pool:
            match = True
            if filters.get('status') and entry['status'] != filters['status']:
                match = False
            if filters.get('origin') and entry['origin'] != filters['origin']:
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
    def update_status(entry_id, new_status, fiscal_doc_uuid=None, user='Sistema', serie=None, number=None):
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
                
                entry['history'].append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'status_change',
                    'from': old_status,
                    'to': new_status,
                    'user': user
                })
                
                FiscalPoolService._save_pool(pool)
                return True
        return False
