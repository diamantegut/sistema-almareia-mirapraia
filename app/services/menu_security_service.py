import json
import hashlib
import os
import shutil
import logging
from datetime import datetime, timedelta
from app.services.system_config_manager import MENU_ITEMS_FILE, SALES_HISTORY_FILE, get_backup_path, AUDIT_LOGS_FILE, get_data_path

class MenuSecurityService:
    @staticmethod
    def validate_menu_item(item):
        """
        Validates menu item structure and data types.
        """
        required_fields = ['id', 'name', 'price']
        for field in required_fields:
            if field not in item or item[field] is None or item[field] == "":
                # 'price' can be 0, so check for None or empty string specifically if needed
                # But typically price is numeric.
                if field == 'price' and item[field] == 0:
                    pass # 0 is valid
                elif not item[field]:
                    raise ValueError(f"Campo obrigatório ausente: {field}")
        
        # Type checks
        try:
            price = float(item.get('price', 0))
            if price < 0:
                raise ValueError(f"Preço não pode ser negativo: {item.get('name')}")
        except ValueError:
            raise ValueError(f"Preço inválido para o item {item.get('name')}")

        return True

    @staticmethod
    def calculate_hash(item):
        """
        Calculates SHA256 hash of menu item data for integrity check.
        Excludes 'hash' and 'last_updated' fields.
        """
        i_copy = item.copy()
        i_copy.pop('hash', None)
        i_copy.pop('last_updated', None)
        # Sort keys to ensure consistent hash
        i_str = json.dumps(i_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(i_str.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_diff(old_item, new_item):
        """
        Generates a list of changes between old and new menu item state.
        """
        changes = []
        all_keys = set(old_item.keys()) | set(new_item.keys())
        
        ignored_keys = ['hash', 'last_updated', 'version']
        
        for key in all_keys:
            if key in ignored_keys:
                continue
                
            old_val = old_item.get(key)
            new_val = new_item.get(key)
            
            # Compare with type casting for numbers
            try:
                if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                    if abs(float(old_val) - float(new_val)) < 0.0001:
                        continue
            except: pass
            
            if str(old_val) != str(new_val):
                changes.append({
                    'field': key,
                    'old': old_val,
                    'new': new_val
                })
        return changes

    @staticmethod
    def log_audit(action, user, item_id, details, changes=None):
        """
        Logs detailed audit event to a separate immutable log file.
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'user': user,
            'item_id': item_id,
            'details': details,
            'changes': changes or [],
            'hash': hashlib.sha256(json.dumps(details, sort_keys=True).encode('utf-8')).hexdigest()
        }
        
        date_str = datetime.now().strftime('%Y-%m-%d')
        audit_file = os.path.join(os.path.dirname(AUDIT_LOGS_FILE), f"menu_audit_{date_str}.json")
        
        entries = []
        if os.path.exists(audit_file):
            try:
                with open(audit_file, 'r', encoding='utf-8') as f:
                    entries = json.load(f)
            except: pass
            
        entries.append(log_entry)
        
        with open(audit_file, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=4, ensure_ascii=False)

    @staticmethod
    def detect_bulk_changes(old_items, new_items, threshold_count=10, threshold_percent=20):
        """
        Detects if there are mass changes in menu items list.
        Returns (is_bulk, details)
        """
        old_map = {str(i.get('id')): i for i in old_items}
        new_map = {str(i.get('id')): i for i in new_items}
        
        changes = 0
        total = len(new_items)
        
        # Check modified or added
        for pid, p in new_map.items():
            if pid not in old_map:
                changes += 1
            else:
                old_p = old_map[pid]
                if p.get('hash') != old_p.get('hash'):
                    changes += 1
                elif p.get('version') != old_p.get('version'):
                    changes += 1
                    
        # Check removed
        for pid in old_map:
            if pid not in new_map:
                changes += 1
                
        is_bulk = False
        details = f"Alterações detectadas: {changes}"
        
        if total > 0:
            percent = (changes / total) * 100
            if changes >= threshold_count and percent >= threshold_percent:
                is_bulk = True
                details += f" ({percent:.1f}% > {threshold_percent}%)"
                
        return is_bulk, details

    @staticmethod
    def create_menu_sales_backup():
        """
        Creates a dedicated backup of menu items and sales history.
        """
        try:
            backup_dir = get_backup_path('menu_sales_2h')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Files to backup
            files = ['menu_items.json', 'sales_history.json']
            
            for fname in files:
                src = get_data_path(fname)
                if os.path.exists(src):
                    dst = os.path.join(backup_dir, f"{fname}_{timestamp}.bak")
                    shutil.copy2(src, dst)
            
            # Rotation: Keep last 90 days
            cutoff = datetime.now() - timedelta(days=90)
            for f in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, f)
                if os.path.getmtime(fp) < cutoff.timestamp():
                    try:
                        os.remove(fp)
                    except: pass
            
            # Clean up audit logs (1 year retention)
            MenuSecurityService.cleanup_audit_logs()
                    
            return True
        except Exception as e:
            logging.error(f"Erro no backup de Menu/Vendas 2h: {e}")
            return False

    @staticmethod
    def cleanup_audit_logs(days=365):
        """
        Removes audit logs older than the specified number of days (default 1 year).
        """
        try:
            log_dir = os.path.dirname(AUDIT_LOGS_FILE)
            if not os.path.exists(log_dir):
                return
            
            cutoff = datetime.now() - timedelta(days=days)
            
            for fname in os.listdir(log_dir):
                if fname.startswith('menu_audit_') and fname.endswith('.json'):
                    try:
                        # Extract date from filename menu_audit_YYYY-MM-DD.json
                        date_part = fname.replace('menu_audit_', '').replace('.json', '')
                        file_date = datetime.strptime(date_part, '%Y-%m-%d')
                        
                        if file_date < cutoff:
                            os.remove(os.path.join(log_dir, fname))
                            logging.info(f"Audit log removed (retention policy): {fname}")
                    except Exception:
                        pass
        except Exception as e:
            logging.error(f"Error cleaning up audit logs: {e}")

    @staticmethod
    def validate_integrity():
        """
        Verifies the integrity of menu items by checking hashes.
        Returns a report with anomalies.
        """
        try:
            from app.services.data_service import load_menu_items
            items = load_menu_items()
            anomalies = []
            
            for item in items:
                stored_hash = item.get('hash')
                if stored_hash:
                    calculated = MenuSecurityService.calculate_hash(item)
                    if stored_hash != calculated:
                        anomalies.append({
                            'id': item.get('id'),
                            'name': item.get('name'),
                            'issue': 'Hash Mismatch',
                            'stored': stored_hash,
                            'calculated': calculated
                        })
                else:
                    # Missing hash is not necessarily an error if not yet saved with security
                    pass
                    
            return {
                'success': True,
                'total_checked': len(items),
                'anomalies': anomalies
            }
        except Exception as e:
            logging.error(f"Integrity Check Error: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def create_checkpoint(user):
        """
        Creates a manual checkpoint (snapshot) of the menu data.
        """
        try:
            backup_dir = get_backup_path('menu_checkpoints')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            files = ['menu_items.json', 'sales_history.json']
            saved_paths = []
            
            for fname in files:
                src = get_data_path(fname)
                if os.path.exists(src):
                    dst = os.path.join(backup_dir, f"{fname}_{timestamp}_checkpoint.json")
                    shutil.copy2(src, dst)
                    saved_paths.append(dst)
            
            MenuSecurityService.log_audit(
                'CHECKPOINT', 
                user, 
                'ALL', 
                {'message': 'Manual checkpoint created', 'files': saved_paths}
            )
            
            return True, saved_paths[0] if saved_paths else None
        except Exception as e:
            return False, str(e)
