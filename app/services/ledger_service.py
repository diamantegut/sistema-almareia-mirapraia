import json
import os
import hashlib
import time
import uuid
from datetime import datetime
from contextlib import contextmanager
from app.services.system_config_manager import FINANCIAL_LEDGER_FILE

# --- File Locking Mechanism (copied from transfer_service.py for consistency) ---
@contextmanager
def file_lock(lock_file):
    lock_path = lock_file + '.lock'
    timeout = 5
    start_time = time.time()
    while True:
        try:
            # Atomic creation of lock file
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Could not acquire lock for {lock_file}")
            time.sleep(0.1)
        except OSError as e:
            # Handle other OS errors
             if time.time() - start_time > timeout:
                raise TimeoutError(f"OS Error acquiring lock: {e}")
             time.sleep(0.1)
            
    try:
        yield
    finally:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass

class LedgerService:
    FILE_PATH = FINANCIAL_LEDGER_FILE

    @staticmethod
    def _calculate_hash(record, previous_hash):
        """
        Calculates SHA256 hash based on record content and previous hash.
        Fields used: timestamp, user, source, destination, type, value, method, reference.
        """
        # Create a deterministic string representation
        # We explicitly select fields to ensure consistency
        payload = (
            f"{previous_hash}|"
            f"{record.get('timestamp')}|"
            f"{record.get('user')}|"
            f"{record.get('source_box')}|"
            f"{record.get('dest_box')}|"
            f"{record.get('operation_type')}|"
            f"{str(record.get('value'))}|"
            f"{record.get('payment_method')}|"
            f"{record.get('reference')}"
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def _load_ledger():
        if not os.path.exists(LedgerService.FILE_PATH):
            return []
        try:
            with open(LedgerService.FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _save_ledger(data):
        # Atomic write
        temp_path = LedgerService.FILE_PATH + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            if os.path.exists(LedgerService.FILE_PATH):
                os.replace(temp_path, LedgerService.FILE_PATH)
            else:
                os.rename(temp_path, LedgerService.FILE_PATH)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e

    @classmethod
    def record_transaction(cls, user, source_box, dest_box, operation_type, value, payment_method, reference):
        """
        Records a new transaction in the immutable ledger.
        """
        timestamp = datetime.now().isoformat()
        
        # Validate value
        try:
            value = float(value)
        except ValueError:
            raise ValueError("Invalid value amount")

        with file_lock(cls.FILE_PATH):
            ledger = cls._load_ledger()
            
            # Determine previous hash
            if not ledger:
                previous_hash = "0" * 64 # Genesis hash
            else:
                previous_hash = ledger[-1].get('current_hash')

            new_record = {
                'id': str(uuid.uuid4()),
                'timestamp': timestamp,
                'user': user,
                'source_box': source_box,
                'dest_box': dest_box,
                'operation_type': operation_type,
                'value': value,
                'payment_method': payment_method,
                'reference': reference,
                'previous_hash': previous_hash
            }

            # Calculate and append current hash
            current_hash = cls._calculate_hash(new_record, previous_hash)
            new_record['current_hash'] = current_hash

            ledger.append(new_record)
            cls._save_ledger(ledger)
            
            return new_record

    @classmethod
    def reverse_transaction(cls, original_tx_id, user, reason):
        """
        Creates a reversal transaction for a given transaction ID.
        Does NOT delete the original.
        """
        with file_lock(cls.FILE_PATH):
            ledger = cls._load_ledger()
            
            # Find original transaction
            original_tx = next((item for item in ledger if item["id"] == original_tx_id), None)
            
            if not original_tx:
                raise ValueError("Transaction not found")
            
            if original_tx['operation_type'] == 'REVERSAL':
                raise ValueError("Cannot reverse a reversal")

            # Create reversal record
            # Reversal swaps source/dest logic or just negates value? 
            # Usually for a ledger, we want to show money moving back.
            # So Source becomes Dest, Dest becomes Source.
            
            previous_hash = ledger[-1].get('current_hash')
            timestamp = datetime.now().isoformat()
            
            reversal_record = {
                'id': str(uuid.uuid4()),
                'timestamp': timestamp,
                'user': user,
                'source_box': original_tx['dest_box'], # Swapped
                'dest_box': original_tx['source_box'], # Swapped
                'operation_type': 'REVERSAL',
                'value': original_tx['value'],
                'payment_method': original_tx['payment_method'],
                'reference': f"ESTORNO: {reason} (Ref: {original_tx_id})",
                'previous_hash': previous_hash
            }

            current_hash = cls._calculate_hash(reversal_record, previous_hash)
            reversal_record['current_hash'] = current_hash

            ledger.append(reversal_record)
            cls._save_ledger(ledger)
            
            return reversal_record

    @classmethod
    def verify_integrity(cls):
        """
        Verifies the cryptographic integrity of the entire ledger.
        Returns (bool, message)
        """
        with file_lock(cls.FILE_PATH):
            ledger = cls._load_ledger()
            
            if not ledger:
                return True, "Ledger empty"

            expected_prev_hash = "0" * 64
            
            for i, record in enumerate(ledger):
                # 1. Check if previous hash matches the chain
                if record['previous_hash'] != expected_prev_hash:
                    return False, f"Broken chain at index {i} (ID: {record['id']}). Prev hash mismatch."
                
                # 2. Check if current hash is valid
                calculated_hash = cls._calculate_hash(record, expected_prev_hash)
                if calculated_hash != record['current_hash']:
                    return False, f"Data tampering detected at index {i} (ID: {record['id']}). Hash mismatch."
                
                expected_prev_hash = record['current_hash']
                
            return True, "Ledger integrity verified"

    @classmethod
    def get_transactions(cls, filters=None):
        """
        Get transactions with optional filtering.
        filters: dict of field -> value
        """
        ledger = cls._load_ledger()
        if not filters:
            return ledger
        
        filtered = []
        for item in ledger:
            match = True
            for k, v in filters.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                filtered.append(item)
        return filtered

    @classmethod
    def rebuild_balance(cls, box_name, date_cutoff=None):
        """
        Reconstrói o saldo de um caixa específico a partir do zero usando o Ledger Imutável.
        date_cutoff: se fornecido, calcula o saldo até essa data (inclusive).
        """
        ledger = cls._load_ledger()
        balance = 0.0
        
        cutoff_dt = None
        if date_cutoff:
            try:
                cutoff_dt = datetime.fromisoformat(date_cutoff)
            except:
                pass

        for tx in ledger:
            # Check Date
            if cutoff_dt:
                tx_dt = datetime.fromisoformat(tx['timestamp'])
                if tx_dt > cutoff_dt:
                    continue

            value = float(tx['value'])
            
            # Logic: 
            # If box is DESTINATION -> Money IN (+ value)
            # If box is SOURCE -> Money OUT (- value)
            # REVERSAL is just a transaction with swapped source/dest, so logic holds.
            
            if tx['dest_box'] == box_name:
                balance += value
            elif tx['source_box'] == box_name:
                balance -= value
                
        return balance
