import json
import os
from datetime import datetime
from threading import Lock

# Define path for closed accounts storage
CLOSED_ACCOUNTS_FILE = os.path.join("data", "closed_accounts.json")
closed_accounts_lock = Lock()

class ClosedAccountService:
    @staticmethod
    def _load_closed_accounts():
        if not os.path.exists(CLOSED_ACCOUNTS_FILE):
            return []
        try:
            with open(CLOSED_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure backward compatibility for missing 'status'
                for acc in data:
                    if 'status' not in acc:
                        acc['status'] = 'closed'
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    @staticmethod
    def _save_closed_accounts(accounts):
        # Ensure directory exists
        os.makedirs(os.path.dirname(CLOSED_ACCOUNTS_FILE), exist_ok=True)
        with open(CLOSED_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=4, ensure_ascii=False)

    @staticmethod
    def save_closed_account(account_data):
        """
        Saves a closed account to the immutable record.
        account_data should contain:
        - origin: 'restaurant_table' or 'reception_room'
        - original_id: table_id or room_number
        - items: list of items
        - total: float
        - payments: list of payments (method, amount)
        - closed_at: timestamp
        - closed_by: user
        - details: dict with extra info (waiter, guest name, etc.)
        """
        with closed_accounts_lock:
            accounts = ClosedAccountService._load_closed_accounts()
            
            # Generate a unique ID for the closed account record
            closed_id = f"CLOSED_{datetime.now().strftime('%Y%m%d%H%M%S')}_{account_data.get('original_id', 'unknown')}"
            
            record = {
                "id": closed_id,
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                **account_data
            }
            
            accounts.append(record)
            ClosedAccountService._save_closed_accounts(accounts)
            return closed_id

    @staticmethod
    def get_closed_account(closed_id):
        with closed_accounts_lock:
            accounts = ClosedAccountService._load_closed_accounts()
            for acc in accounts:
                if acc['id'] == closed_id:
                    return acc
            return None

    @staticmethod
    def mark_as_reopened(closed_id, reopened_by, reason):
        """Marks a closed account as reopened."""
        with closed_accounts_lock:
            accounts = ClosedAccountService._load_closed_accounts()
            updated = False
            for acc in accounts:
                if acc['id'] == closed_id:
                    acc['status'] = 'reopened'
                    acc['reopened_by'] = reopened_by
                    acc['reopen_reason'] = reason
                    acc['reopened_at'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    updated = True
                    break
            
            if updated:
                ClosedAccountService._save_closed_accounts(accounts)
                return True
            return False

    @staticmethod
    def search_closed_accounts(filters=None, page=None, per_page=20):
        """
        Searches closed accounts with multiple filters.
        filters: dict with keys:
            - start_date (str: dd/mm/yyyy)
            - end_date (str: dd/mm/yyyy)
            - min_value (float)
            - max_value (float)
            - user (str)
            - origin (str)
            - status (str)
        
        If page is provided, returns a dict with pagination info.
        Otherwise returns a list of accounts.
        """
        with closed_accounts_lock:
            accounts = ClosedAccountService._load_closed_accounts()
            
            if not filters:
                filtered = accounts
            else:
                filtered = []
                
                # Parse dates if provided
                start_dt = None
                end_dt = None
                if filters.get('start_date'):
                    try:
                        start_dt = datetime.strptime(filters['start_date'], '%d/%m/%Y')
                    except ValueError:
                        pass
                if filters.get('end_date'):
                    try:
                        end_dt = datetime.strptime(filters['end_date'], '%d/%m/%Y')
                    except ValueError:
                        pass
                        
                user_filter = filters.get('user', '').lower()
                origin_filter = filters.get('origin')
                status_filter = filters.get('status')
                
                for acc in accounts:
                    # 1. Date Filter
                    # Timestamp format: dd/mm/yyyy HH:MM:SS
                    acc_ts_str = acc.get('timestamp', '').split(' ')[0]
                    try:
                        acc_dt = datetime.strptime(acc_ts_str, '%d/%m/%Y')
                    except ValueError:
                        continue # Skip invalid dates
                    
                    if start_dt and acc_dt < start_dt:
                        continue
                    if end_dt and acc_dt > end_dt:
                        continue
                        
                    # 2. Value Filter
                    total = float(acc.get('total', 0.0))
                    if filters.get('min_value') is not None and total < float(filters['min_value']):
                        continue
                    if filters.get('max_value') is not None and total > float(filters['max_value']):
                        continue
                        
                    # 3. User Filter
                    # Check both 'user' field and 'closed_by'
                    acc_user = (acc.get('user') or acc.get('closed_by') or '').lower()
                    if user_filter and user_filter not in acc_user:
                        continue
                        
                    # 4. Origin Filter
                    if origin_filter and acc.get('origin') != origin_filter:
                        continue
                        
                    # 5. Status Filter
                    # Default status is 'closed' (implied if missing)
                    acc_status = acc.get('status', 'closed')
                    if status_filter and status_filter != 'all':
                        if status_filter == 'reopened' and acc_status != 'reopened':
                            continue
                        if status_filter == 'closed' and acc_status == 'reopened':
                            continue
                            
                    filtered.append(acc)
                
            # Sort by ID descending (newest first)
            sorted_accounts = sorted(filtered, key=lambda x: x.get('id', ''), reverse=True)
            
            if page is not None:
                try:
                    page = int(page)
                    per_page = int(per_page)
                except ValueError:
                    page = 1
                    per_page = 20
                    
                total_items = len(sorted_accounts)
                total_pages = (total_items + per_page - 1) // per_page
                
                # Ensure page is within bounds
                if page < 1: page = 1
                if page > total_pages and total_pages > 0: page = total_pages
                
                start = (page - 1) * per_page
                end = start + per_page
                items = sorted_accounts[start:end]
                
                return {
                    'items': items,
                    'total': total_items,
                    'page': page,
                    'per_page': per_page,
                    'pages': total_pages
                }
            
            return sorted_accounts

    @staticmethod
    def get_recent_closed_accounts(limit=50, origin=None):
        """Returns the most recent closed accounts, optionally filtered by origin."""
        with closed_accounts_lock:
            accounts = ClosedAccountService._load_closed_accounts()
            
            if origin:
                accounts = [acc for acc in accounts if acc.get('origin') == origin]
            
            # Sort by ID (which starts with CLOSED_YYYYMMDD...) as timestamp string is dd/mm/yyyy and not sortable directly
            return sorted(accounts, key=lambda x: x.get('id', ''), reverse=True)[:limit]
