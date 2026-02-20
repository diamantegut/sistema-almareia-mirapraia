import json
import hashlib
import os
import shutil
import logging
from datetime import datetime, timedelta
from app.services.system_config_manager import PRODUCTS_FILE, get_backup_path, AUDIT_LOGS_FILE, get_data_path

class StockSecurityService:
    @staticmethod
    def validate_product(product):
        """
        Validates product structure and data types.
        """
        required_fields = ['id', 'name', 'department']
        for field in required_fields:
            if field not in product or not product[field]:
                raise ValueError(f"Campo obrigatório ausente: {field}")
        
        # Type checks
        if not isinstance(product.get('price', 0), (int, float)):
            raise ValueError(f"Preço inválido para o produto {product.get('name')}")
            
        if not isinstance(product.get('min_stock', 0), (int, float)):
            raise ValueError(f"Estoque mínimo inválido para o produto {product.get('name')}")
            
        # Logic checks
        if float(product.get('price', 0)) < 0:
            raise ValueError(f"Preço não pode ser negativo: {product.get('name')}")

        return True

    @staticmethod
    def calculate_hash(product):
        """
        Calculates SHA256 hash of product data for integrity check.
        Excludes 'hash' and 'last_updated' fields to avoid recursion.
        """
        p_copy = product.copy()
        p_copy.pop('hash', None)
        p_copy.pop('last_updated', None)
        # Sort keys to ensure consistent hash
        p_str = json.dumps(p_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(p_str.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_diff(old_product, new_product):
        """
        Generates a list of changes between old and new product state.
        """
        changes = []
        all_keys = set(old_product.keys()) | set(new_product.keys())
        
        ignored_keys = ['hash', 'last_updated', 'version']
        
        for key in all_keys:
            if key in ignored_keys:
                continue
                
            old_val = old_product.get(key)
            new_val = new_product.get(key)
            
            # Compare with type casting for numbers to avoid 10.0 vs 10 diffs
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
    def create_checkpoint():
        """
        Creates a full checkpoint of the products file.
        """
        try:
            if not os.path.exists(PRODUCTS_FILE):
                return None
                
            backup_dir = get_backup_path('checkpoints')
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"products_checkpoint_{timestamp}.json"
            backup_path = os.path.join(backup_dir, filename)
            
            shutil.copy2(PRODUCTS_FILE, backup_path)
            return backup_path
        except Exception as e:
            logging.error(f"Erro ao criar checkpoint: {e}")
            return None

    @staticmethod
    def log_audit(action, user, product_id, details, changes=None):
        """
        Logs detailed audit event to a separate immutable log file.
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'user': user,
            'product_id': product_id,
            'details': details,
            'changes': changes or [],
            'hash': hashlib.sha256(json.dumps(details, sort_keys=True).encode('utf-8')).hexdigest()
        }
        
        # We will use a daily log file for audit to avoid massive files
        date_str = datetime.now().strftime('%Y-%m-%d')
        audit_file = os.path.join(os.path.dirname(AUDIT_LOGS_FILE), f"stock_audit_{date_str}.json")
        
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
    def verify_integrity(products):
        """
        Verifies the integrity of all products by recalculating hashes.
        Returns list of anomalies.
        """
        anomalies = []
        for p in products:
            stored_hash = p.get('hash')
            if not stored_hash:
                continue # Skip legacy items without hash, or flag them?
                
            calculated = StockSecurityService.calculate_hash(p)
            if stored_hash != calculated:
                anomalies.append({
                    'id': p.get('id'),
                    'name': p.get('name'),
                    'issue': 'Hash Mismatch',
                    'stored': stored_hash,
                    'calculated': calculated
                })
        return anomalies

    @staticmethod
    def detect_bulk_changes(old_products, new_products, threshold_count=10, threshold_percent=20):
        """
        Detects if there are mass changes in products list.
        Returns (is_bulk, details)
        """
        old_map = {str(p.get('id')): p for p in old_products}
        new_map = {str(p.get('id')): p for p in new_products}
        
        changes = 0
        total = len(new_products)
        
        # Check modified or added
        for pid, p in new_map.items():
            if pid not in old_map:
                changes += 1
            else:
                old_p = old_map[pid]
                # Check for critical changes that would imply a "reset" or mass update
                # Checking hash is a good proxy for any change
                if p.get('hash') != old_p.get('hash'):
                    changes += 1
                elif p.get('version') != old_p.get('version'):
                    changes += 1
                elif str(p.get('stock')) != str(old_p.get('stock')):
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
    def create_stock_backup():
        """
        Creates a dedicated backup of stock files.
        """
        try:
            backup_dir = get_backup_path('stock_2h')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Files to backup
            files = ['products.json', 'stock_logs.json']
            
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
                    
            return True
        except Exception as e:
            logging.error(f"Erro no backup de estoque 2h: {e}")
            return False
