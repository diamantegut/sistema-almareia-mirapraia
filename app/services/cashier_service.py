import os
import json
import shutil
import base64
import errno
import hashlib
from datetime import datetime
import uuid
from threading import Lock
import sys
import time
import tempfile
from contextlib import contextmanager
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from app.services.system_config_manager import get_backup_path, CASHIER_SESSIONS_FILE
except ImportError:
    from system_config_manager import get_backup_path, CASHIER_SESSIONS_FILE

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BACKUP_DIR = get_backup_path('Caixa')
# CLOSED_CASHIERS_AUDIT_DIR = r"G:\Back Up Sistema\Caixas Fechados"
# ISOLATION: Use local backup path
CLOSED_CASHIERS_AUDIT_DIR = get_backup_path("Caixas Fechados")

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

cashier_lock = Lock()

_last_backup_hash = None
_backup_thread_started = False


def _is_test_environment():
    path = os.path.normpath(CASHIER_SESSIONS_FILE).lower()
    parts = path.split(os.sep)
    return 'tests' in parts

def _resolve_fallback_lock_path(lock_path_base):
    lock_root = os.path.join(tempfile.gettempdir(), "almareia_file_locks")
    os.makedirs(lock_root, exist_ok=True)
    token = hashlib.sha256(os.path.abspath(lock_path_base).encode("utf-8")).hexdigest()
    return os.path.join(lock_root, f"{token}.lock")

def _is_permission_lock_error(exc):
    if isinstance(exc, PermissionError):
        return True
    errno_value = getattr(exc, "errno", None)
    if errno_value in (errno.EACCES, errno.EROFS):
        return True
    winerror_value = getattr(exc, "winerror", None)
    return winerror_value == 5

@contextmanager
def file_lock(lock_path_base, timeout=10, stale_timeout=120):
    lock_path = lock_path_base + '.lock'
    active_lock_path = lock_path
    fallback_lock_path = None
    start_time = time.time()
    while True:
        try:
            fd = os.open(active_lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            break
        except FileExistsError:
            try:
                lock_age = time.time() - os.path.getmtime(active_lock_path)
            except OSError:
                lock_age = 0
            if lock_age > stale_timeout:
                try:
                    os.remove(active_lock_path)
                    continue
                except OSError:
                    pass
            if time.time() - start_time > timeout:
                logger.warning(f"Timeout waiting for lock: {active_lock_path}")
                raise TimeoutError(f"Could not acquire lock for {lock_path_base}")
            time.sleep(0.1)
        except OSError as e:
            if _is_permission_lock_error(e):
                if fallback_lock_path is None:
                    fallback_lock_path = _resolve_fallback_lock_path(lock_path_base)
                if active_lock_path != fallback_lock_path:
                    logger.warning(f"Primary lock path unavailable, using temp lock fallback: {lock_path}")
                    active_lock_path = fallback_lock_path
                    start_time = time.time()
                    continue
            logger.error(f"Error acquiring lock: {e}")
            raise
    
    try:
        yield
    finally:
        try:
            if os.path.exists(active_lock_path):
                os.remove(active_lock_path)
        except OSError:
            pass

class CashierService:
    TYPES = {
        'restaurant': 'Caixa Restaurante',
        'guest_consumption': 'Caixa Consumo de Hóspedes',
        'daily_rates': 'Caixa Diárias',
        'reservation_cashier': 'Caixa de Reservas'
    }

    @staticmethod
    def restore_latest_backup():
        """
        Forces a restore from the latest valid backup.
        Useful for manual recovery or when data loss is suspected.
        """
        with file_lock(CASHIER_SESSIONS_FILE):
            recovered = CashierService._recover_from_backup()
            if recovered is not None:
                logger.info("Manual restore successful.")
                return True
            else:
                logger.error("Manual restore failed: No valid backups found.")
                return False

    @staticmethod
    def _recover_from_backup():
        """Attempts to recover sessions from the latest valid backup."""
        logger.info("Initiating Cashier Recovery from Backup...")
        try:
            if not os.path.exists(BACKUP_DIR):
                return None
                
            backups = [f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_cashier_") and f.endswith(".json")]
            if not backups:
                logger.warning("No backups found for recovery.")
                return None
            
            # Sort by name (timestamp is in name YYYYMMDD_HHMMSS)
            backups.sort(reverse=True)
            
            for backup_file in backups:
                try:
                    path = os.path.join(BACKUP_DIR, backup_file)
                    logger.info(f"Trying to recover from: {backup_file}")
                    
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    data = None
                    # Try Base64 Decode
                    try:
                        json_str = base64.b64decode(content).decode('utf-8')
                        data = json.loads(json_str)
                    except Exception:
                        # Try plain JSON
                        try:
                            data = json.loads(content)
                        except:
                            pass
                            
                    if data and isinstance(data, dict) and 'sessions' in data:
                        sessions = data['sessions']
                        if isinstance(sessions, list):
                            logger.info(f"SUCCESSFULLY RECOVERED {len(sessions)} sessions from {backup_file}")
                            # Restore file immediately
                            CashierService._save_sessions(sessions)
                            return sessions
                            
                except Exception as e:
                    logger.error(f"Failed to recover from {backup_file}: {e}")
                    continue
            
            logger.error("All backups failed recovery.")
            return None
        except Exception as e:
            logger.error(f"Recovery process failed: {e}")
            return None

    @staticmethod
    def _load_sessions():
        if not os.path.exists(CASHIER_SESSIONS_FILE):
            logger.warning(f"Sessions file NOT FOUND at {CASHIER_SESSIONS_FILE}. Attempting recovery...")
            recovered = CashierService._recover_from_backup()
            if recovered is not None:
                return recovered
            return []
            
        try:
            file_size = os.path.getsize(CASHIER_SESSIONS_FILE)
            if file_size == 0:
                logger.warning(f"Sessions file {CASHIER_SESSIONS_FILE} is EMPTY (0 bytes). Attempting recovery...")
                recovered = CashierService._recover_from_backup()
                if recovered is not None:
                    return recovered
                return []

            with open(CASHIER_SESSIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if isinstance(data, list):
                if not data and file_size > 10: # If file was big but parsed to empty list? Unlikely for JSON
                     # Check if we have backups but no current sessions
                     if os.path.exists(BACKUP_DIR) and os.listdir(BACKUP_DIR):
                         logger.warning("Loaded EMPTY sessions list, but backups exist. This might be a fresh start or data loss.")
                
                # open_sessions = [s['id'] for s in data if isinstance(s, dict) and s.get('status') == 'open']
                # logger.info(f"Successfully loaded {len(data)} sessions. Open sessions: {open_sessions}")
                return data
            else:
                logger.error(f"Invalid JSON format in {CASHIER_SESSIONS_FILE}: Expected list, got {type(data)}")
                raise ValueError("Invalid JSON format")
                
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"JSON Error in {CASHIER_SESSIONS_FILE}: {e}. Attempting recovery...")
            recovered = CashierService._recover_from_backup()
            if recovered is not None:
                return recovered
            # If we cannot recover, we MUST NOT return empty list if we know it was supposed to have data.
            # But if it's completely corrupted and no backup, we might have to start fresh or raise error.
            # To prevent silent data loss, we raise error.
            raise RuntimeError(f"CRITICAL: Cashier data corrupted and no backup available. Error: {e}")
            
        except Exception as e:
            logger.error(f"Error loading sessions from {CASHIER_SESSIONS_FILE}: {e}")
            raise e

    @staticmethod
    def _save_sessions(sessions):
        # Atomic write pattern: write to temp file then rename
        try:
            # Create a temp file in the same directory to ensure atomic rename works across filesystems
            dir_name = os.path.dirname(CASHIER_SESSIONS_FILE)
            temp_name = f"temp_sessions_{uuid.uuid4().hex}.json"
            temp_path = os.path.join(dir_name, temp_name)
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(sessions, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
                
            # Atomic replacement with retry logic for Windows
            import time
            max_retries = 10
            for i in range(max_retries):
                try:
                    if os.path.exists(CASHIER_SESSIONS_FILE):
                        os.replace(temp_path, CASHIER_SESSIONS_FILE)
                    else:
                        os.rename(temp_path, CASHIER_SESSIONS_FILE)
                    break
                except PermissionError: # WinError 5 or 32
                    if i == max_retries - 1:
                        raise
                    time.sleep(0.1)
                except OSError as e: # Handle other OS errors that might be related to locking
                    if e.errno == 13: # Permission denied (Windows)
                         if i == max_retries - 1:
                            raise
                         time.sleep(0.1)
                    else:
                        raise
                        
            return True
        except Exception as e:
            print(f"Error saving cashier sessions: {e}")
            # Try to cleanup temp file if it exists
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise e

    @staticmethod
    def list_sessions():
        return CashierService._load_sessions()

    @staticmethod
    def persist_sessions(sessions, trigger_backup=False):
        if isinstance(sessions, list):
            for session_obj in sessions:
                if not isinstance(session_obj, dict):
                    continue
                txs = session_obj.get('transactions', [])
                if not isinstance(txs, list):
                    continue
                for tx in txs:
                    if isinstance(tx, dict):
                        CashierService._apply_commission_contract(tx)
        with file_lock(CASHIER_SESSIONS_FILE):
            CashierService._save_sessions(sessions)
        if trigger_backup:
            CashierService._perform_backup(sessions)
        return True

    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'sim', 'yes', 'on', 'removed'}
        return False

    @staticmethod
    def _normalize_waiter_breakdown(waiter_breakdown):
        if not isinstance(waiter_breakdown, dict):
            return {}
        normalized = {}
        for key, val in waiter_breakdown.items():
            waiter = str(key or '').strip()
            if not waiter:
                waiter = 'Sem Colaborador'
            try:
                amount = float(val or 0)
            except Exception:
                amount = 0.0
            normalized[waiter] = normalized.get(waiter, 0.0) + amount
        return normalized

    @staticmethod
    def _build_commission_reference_id(transaction, details):
        existing = transaction.get('commission_reference_id') or details.get('commission_reference_id')
        if existing:
            return str(existing)
        related_charge_id = transaction.get('related_charge_id') or details.get('related_charge_id')
        if related_charge_id:
            return f"charge:{related_charge_id}"
        payment_group_id = details.get('payment_group_id')
        if payment_group_id:
            return f"group:{payment_group_id}"
        close_id = details.get('close_id') or transaction.get('close_id')
        if close_id:
            return f"close:{close_id}"
        table_id = details.get('table_id') or transaction.get('table_id')
        if table_id:
            return f"table:{table_id}:{transaction.get('timestamp', '')}"
        room_number = details.get('room_number') or transaction.get('room_number')
        if room_number:
            return f"room:{room_number}:{transaction.get('timestamp', '')}"
        return f"tx:{transaction.get('id', uuid.uuid4().hex)}"

    @staticmethod
    def _infer_category(transaction, details):
        category = transaction.get('category') or details.get('category')
        if category:
            return str(category)
        tx_type = str(transaction.get('type') or '').lower()
        payment_method = str(transaction.get('payment_method') or '').lower()
        description = str(transaction.get('description') or '').lower()
        if tx_type == 'sale':
            return 'Venda'
        if tx_type == 'in':
            if 'manual' in description:
                return 'Recebimento Manual'
            if 'quarto' in description or 'room' in payment_method or 'quarto' in payment_method:
                return 'Pagamento de Conta'
            return 'Recebimento'
        if tx_type == 'out':
            return 'Saída'
        return '-'

    @staticmethod
    def _infer_commission_eligible(transaction, details, service_fee_removed):
        if 'commission_eligible' in transaction:
            return CashierService._as_bool(transaction.get('commission_eligible'))
        if 'commission_eligible' in details:
            return CashierService._as_bool(details.get('commission_eligible'))
        tx_type = str(transaction.get('type') or '').lower()
        category = str(transaction.get('category') or details.get('category') or '').lower()
        payment_method = str(transaction.get('payment_method') or '').lower()
        if service_fee_removed:
            return False
        if payment_method in {'conta funcionário', 'conta funcionario', 'consumo proprio', 'cortesia'}:
            return False
        if tx_type not in {'sale', 'in'}:
            return False
        if tx_type == 'in' and category not in {'pagamento de conta', 'recebimento manual'}:
            return False
        return True

    @staticmethod
    def _apply_commission_contract(transaction):
        if not isinstance(transaction, dict):
            return transaction
        details = transaction.get('details') or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {}
        if not isinstance(details, dict):
            details = {}
        waiter_breakdown = transaction.get('waiter_breakdown')
        if not waiter_breakdown:
            waiter_breakdown = details.get('waiter_breakdown')
        waiter_breakdown = CashierService._normalize_waiter_breakdown(waiter_breakdown)
        if waiter_breakdown:
            transaction['waiter_breakdown'] = waiter_breakdown
            details['waiter_breakdown'] = waiter_breakdown
        service_fee_removed = CashierService._as_bool(
            transaction.get('service_fee_removed', details.get('service_fee_removed', False))
        )
        transaction['service_fee_removed'] = service_fee_removed
        details['service_fee_removed'] = service_fee_removed
        category = CashierService._infer_category(transaction, details)
        transaction['category'] = category
        details['category'] = category
        reference_id = CashierService._build_commission_reference_id(transaction, details)
        transaction['commission_reference_id'] = reference_id
        details['commission_reference_id'] = reference_id
        operator = transaction.get('operator') or transaction.get('user') or details.get('operator') or details.get('closed_by') or 'Sistema'
        transaction['operator'] = operator
        details['operator'] = operator
        commission_eligible = CashierService._infer_commission_eligible(transaction, details, service_fee_removed)
        transaction['commission_eligible'] = bool(commission_eligible)
        details['commission_eligible'] = bool(commission_eligible)
        contract_meta = details.get('commission_contract') or {}
        if not isinstance(contract_meta, dict):
            contract_meta = {}
        contract_meta['version'] = 1
        contract_meta['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        details['commission_contract'] = contract_meta
        transaction['commission_contract_version'] = 1
        transaction['details'] = details
        return transaction

    @staticmethod
    def export_closed_sessions_audit(sessions=None):
        try:
            drive = os.path.splitdrive(CLOSED_CASHIERS_AUDIT_DIR)[0]
            if drive and not os.path.exists(drive + os.sep):
                return False

            if sessions is None:
                sessions = CashierService._load_sessions()
            if not isinstance(sessions, list):
                return False

            closed_sessions = [s for s in sessions if isinstance(s, dict) and s.get('status') == 'closed']

            os.makedirs(CLOSED_CASHIERS_AUDIT_DIR, exist_ok=True)
            dest_path = os.path.join(CLOSED_CASHIERS_AUDIT_DIR, 'caixas_fechados.json')
            with open(dest_path, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        'exported_at': datetime.now().isoformat(),
                        'closed_sessions': closed_sessions
                    },
                    f,
                    indent=2,
                    ensure_ascii=False
                )
            return True
        except Exception:
            return False

    @staticmethod
    def get_session_details(session_id):
        """Returns the full session details by ID."""
        sessions = CashierService._load_sessions()
        for s in sessions:
            if s.get('id') == session_id:
                return s
        return None

    @staticmethod
    def get_active_session(cashier_type):
        """Returns the active (open) session for the given type."""
        sessions = CashierService._load_sessions()
        
        # Compatibility mapping - Bidirectional
        target_types = [cashier_type]
        
        if cashier_type in ['guest_consumption', 'reception_room_billing']:
            target_types = ['guest_consumption', 'reception_room_billing']
            
        if cashier_type in ['restaurant', 'restaurant_service']:
            target_types = ['restaurant', 'restaurant_service']
        
        # logger.debug(f"Checking active session for {cashier_type}. Target types: {target_types}")
        
        for s in sessions:
            if s.get('status') == 'open' and s.get('type') in target_types:
                return s
        return None

    @staticmethod
    def _calculate_balance(session):
        opening_balance = float(session.get('opening_balance', session.get('initial_balance', 0.0)) or 0.0)
        current_balance = opening_balance
        
        for t in session.get('transactions', []) or []:
            try:
                amount = float(t.get('amount', 0.0) or 0.0)
            except:
                amount = 0.0
            
            t_type = str(t.get('type', '')).strip().lower()
            
            if t_type in ['out', 'withdrawal', 'refund', 'sangria']:
                current_balance -= abs(amount)
            elif t_type in ['in', 'deposit', 'sale', 'suprimento']:
                current_balance += abs(amount)
                
        return current_balance

    @staticmethod
    def get_session_summary(session):
        """Returns a summary of the session including balance by payment method."""
        if not session:
            return None
            
        summary = {
            'opening_balance': float(session.get('opening_balance', 0.0)),
            'current_balance': CashierService._calculate_balance(session),
            'total_in': 0.0,
            'total_out': 0.0,
            'balance_by_method': {}
        }
        
        for t in session.get('transactions', []) or []:
            try:
                amount = float(t.get('amount', 0.0) or 0.0)
            except:
                amount = 0.0
            
            t_type = str(t.get('type', '')).strip().lower()
            method = t.get('payment_method', 'Outros')
            
            if t_type in ['in', 'sale', 'deposit']:
                summary['total_in'] += amount
                summary['balance_by_method'][method] = summary['balance_by_method'].get(method, 0.0) + amount
            elif t_type in ['out', 'withdrawal']:
                summary['total_out'] += amount
                # Optional: Deduct from method balance if tracking cash drawer specifically?
                # Usually withdrawals are cash, so we deduct from 'Dinheiro' if method is not specified or matches
                if method == 'Dinheiro' or method == 'Outros': # Simplified assumption
                     summary['balance_by_method'][method] = summary['balance_by_method'].get(method, 0.0) - amount

        return summary

    @staticmethod
    def _calculate_cash_balance(session):
        """
        Calculates the available PHYSICAL CASH balance in the session.
        """
        # Opening balance is assumed to be Cash (Fundo de Troco)
        try:
            current_cash = float(session.get('opening_balance', session.get('initial_balance', 0.0)) or 0.0)
        except:
            current_cash = 0.0
            
        for t in session.get('transactions', []) or []:
            try:
                amount = float(t.get('amount', 0.0) or 0.0)
            except:
                amount = 0.0
            
            t_type = str(t.get('type', '')).strip().lower()
            method = str(t.get('payment_method', '')).strip().lower()
            
            # Determine if transaction affects Cash
            is_cash = False
            
            # 1. Explicit Cash Payment Methods
            if any(k in method for k in ['dinheiro', 'espécie', 'especie', 'cash']):
                is_cash = True
            
            # 2. Implicit Cash Operations (Sangria/Suprimento)
            elif t_type in ['supply', 'suprimento', 'bleeding', 'sangria']:
                is_cash = True
                
            # 3. Transfers (Internal Cash Movement)
            elif any(k in method for k in ['transfer', 'transferência', 'transferencia']):
                is_cash = True
            
            # 4. Explicit non-cash overrides (Safety check)
            if any(k in method for k in ['cartão', 'cartao', 'crédito', 'credito', 'débito', 'debito', 'pix', 'cheque']):
                is_cash = False
                
            if not is_cash:
                continue
                
            # Apply to balance
            if t_type in ['out', 'withdrawal', 'refund', 'sangria']:
                current_cash -= abs(amount)
            elif t_type in ['in', 'deposit', 'sale', 'suprimento']:
                current_cash += abs(amount)
                
        return current_cash

    @staticmethod
    def open_session(cashier_type, user, opening_balance=0.0):
        with file_lock(CASHIER_SESSIONS_FILE):
            # Check for existing session
            if _is_test_environment() and not os.path.exists(CASHIER_SESSIONS_FILE):
                try:
                    os.makedirs(os.path.dirname(CASHIER_SESSIONS_FILE), exist_ok=True)
                    CashierService._save_sessions([])
                except Exception:
                    pass
                sessions = []
            else:
                sessions = CashierService._load_sessions()
            
            # Type aliasing for check
            check_types = [cashier_type]
            if cashier_type == 'restaurant':
                check_types.append('restaurant_service')
            elif cashier_type == 'guest_consumption':
                check_types.append('reception_room_billing')
            
            for s in sessions:
                if s.get('status') == 'open' and s.get('type') in check_types:
                     raise ValueError(f"Já existe um caixa aberto para {CashierService.TYPES.get(cashier_type, cashier_type)}")

            # Determine Entity based on type
            entity = "Hotel Almareia"
            if cashier_type == 'restaurant':
                entity = "Restaurante Mirapraia"
            
            new_session = {
                "id": f"SESSION_{cashier_type.upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{user}",
                "user": user,
                "type": cashier_type,
                "entity": entity,
                "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "opening_balance": float(opening_balance),
                "transactions": [],
                "status": "open",
                "closed_at": None,
                "closing_balance": None,
                "difference": None
            }
            
            sessions.append(new_session)
            CashierService._save_sessions(sessions)
            
            # Trigger Backup immediately after open
            CashierService._perform_backup(sessions)
            
            return new_session

    @staticmethod
    def close_session(cashier_type=None, user=None, closing_balance=0.0, session_id=None, closing_cash=None, closing_non_cash=None):
        with file_lock(CASHIER_SESSIONS_FILE):
            sessions = CashierService._load_sessions()
            
            # Compatibility: If cashier_type looks like a session ID, treat it as such
            if cashier_type and str(cashier_type).startswith('SESSION_') and not session_id:
                session_id = cashier_type
                cashier_type = None

            target_types = []
            if cashier_type:
                target_types = [cashier_type]
                if cashier_type == 'guest_consumption':
                    target_types.append('reception_room_billing')
                if cashier_type == 'restaurant':
                    target_types.append('restaurant_service')

            session_idx = -1
            for i, s in enumerate(sessions):
                # Match by ID if provided
                if session_id:
                    if s.get('id') == session_id:
                        session_idx = i
                        break
                # Match by Type if no ID
                elif cashier_type:
                    if s.get('status') == 'open' and s.get('type') in target_types:
                        session_idx = i
                        break
            
            if session_idx == -1:
                raise ValueError("Nenhum caixa aberto para fechar.")
            
            session = sessions[session_idx]
            
            if session['status'] != 'open':
                raise ValueError("Este caixa já está fechado.")

            opening_balance = session.get('opening_balance', session.get('initial_balance', 0.0))
            try:
                opening_balance = float(opening_balance) if opening_balance is not None else 0.0
            except Exception:
                opening_balance = 0.0

            total_in = 0.0
            total_out = 0.0
            for t in session.get('transactions', []) or []:
                if not isinstance(t, dict):
                    continue
                try:
                    amount = float(t.get('amount', 0.0) or 0.0)
                except Exception:
                    amount = 0.0
                t_type = str(t.get('type', '')).strip().lower()
                method = str(t.get('payment_method', '')).strip().lower()

                # Determine if transaction affects Cash in Drawer
                is_cash = False
                if any(k in method for k in ['dinheiro', 'espécie', 'especie', 'cash']):
                    is_cash = True
                elif t_type in ['supply', 'suprimento', 'bleeding', 'sangria']:
                    is_cash = True
                elif 'transfer' in method or 'transferência' in method or 'transferencia' in method:
                    # Assuming internal transfers are cash
                    is_cash = True
                
                # If not cash, skip calculation for "Expected Cash"
                if not is_cash:
                    continue

                if t_type in ['out', 'withdrawal', 'refund']:
                    total_out += abs(amount)
                elif t_type in ['in', 'deposit', 'sale']:
                    if amount >= 0:
                        total_in += abs(amount)
                    else:
                        total_out += abs(amount)
                else:
                    if amount >= 0:
                        total_in += abs(amount)
                    else:
                        total_out += abs(amount)

            calculated_balance = opening_balance + total_in - total_out
            
            # Update session
            session['status'] = 'closed'
            session['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
            if closing_balance is None:
                session['closing_balance'] = calculated_balance
            else:
                session['closing_balance'] = float(closing_balance)

            if closing_cash is not None:
                try:
                    session['closing_cash'] = float(closing_cash)
                except Exception:
                    session['closing_cash'] = None
            else:
                session['closing_cash'] = session.get('closing_cash', session['closing_balance'])

            if closing_non_cash is not None:
                try:
                    session['closing_non_cash'] = float(closing_non_cash)
                except Exception:
                    session['closing_non_cash'] = None
            else:
                session['closing_non_cash'] = session.get('closing_non_cash')

            session['difference'] = session['closing_cash'] - calculated_balance
            
            # Force user update if provided
            if user:
                session['closed_by'] = user
            session['reconciliation_status'] = 'daily_pull_pending'
            session['reconciliation_summary'] = {
                'mode': 'daily_pagseguro_pull',
                'message': 'Conciliação disponível no detalhamento após pull diário.'
            }
            
            sessions[session_idx] = session
            CashierService._save_sessions(sessions)
            
            # Backup after closing
            CashierService._perform_backup(sessions)
            
            CashierService.export_closed_sessions_audit(sessions)
            
            return session

    @staticmethod
    def add_transaction(cashier_type, amount, description, payment_method, user, details=None, transaction_type=None, is_withdrawal=False, payment_group_id=None):
        with file_lock(CASHIER_SESSIONS_FILE):
            sessions = CashierService._load_sessions()
            
            target_types = [cashier_type]
            if cashier_type == 'restaurant':
                target_types.append('restaurant_service')
            if cashier_type == 'guest_consumption':
                target_types.append('reception_room_billing')
            
            session_idx = -1
            for i, s in enumerate(sessions):
                s_type = s.get('type')
                if not s_type and cashier_type == 'restaurant':
                    s_type = 'restaurant_service'
                if s.get('status') == 'open' and s_type in target_types:
                    session_idx = i
                    break
            
            if session_idx == -1:
                # Fallback: Create a system session if none exists (Auto-open)
                entity = "Restaurante Mirapraia" if cashier_type == 'restaurant' else "Hotel Almareia"
                new_session = {
                    "id": f"SESSION_{cashier_type.upper()}_AUTO_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "user": "Sistema (Auto)",
                    "type": cashier_type,
                    "entity": entity,
                    "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                    "opening_balance": 0.0,
                    "transactions": [],
                    "status": "open"
                }
                sessions.append(new_session)
                session_idx = len(sessions) - 1
            
            session = sessions[session_idx]
            
            try:
                parsed_amount = float(amount)
            except Exception:
                parsed_amount = 0.0

            tx_type = str(transaction_type).strip() if transaction_type is not None else ''
            if not tx_type:
                if is_withdrawal:
                    tx_type = 'out'
                else:
                    tx_type = "sale" if parsed_amount >= 0 else "refund"
            
            # BALANCE CHECK for withdrawals/sangria
            # Strict Check: Must have enough CASH (specie)
            if tx_type in ['out', 'withdrawal', 'sangria'] or (parsed_amount < 0 and tx_type not in ['in', 'deposit']):
                # Only enforce if it's a cash withdrawal or implicit cash operation
                # If payment_method is explicitly NOT cash (e.g. reversing a card transaction), we might skip this?
                # But 'sangria' is by definition cash removal.
                is_cash_op = True
                if payment_method and any(k in payment_method.lower() for k in ['cartão', 'cartao', 'pix', 'cheque']):
                     is_cash_op = False
                
                if is_cash_op:
                    current_cash = CashierService._calculate_cash_balance(session)
                    required = abs(parsed_amount)
                    
                    if current_cash < required:
                        error_msg = f"Operação Bloqueada: Saldo em DINHEIRO insuficiente. Disponível: R$ {current_cash:.2f}, Solicitado: R$ {required:.2f}"
                        
                        # Audit Log for Blocked Attempt
                        try:
                            from app.services.logger_service import LoggerService
                            LoggerService.log_acao(
                                acao='Sangria Bloqueada',
                                entidade='Caixa',
                                detalhes={
                                    'reason': 'Insufficient Cash Balance',
                                    'available_cash': current_cash,
                                    'requested_amount': required,
                                    'session_id': session.get('id'),
                                    'user': user
                                },
                                nivel_severidade='WARNING',
                                colaborador_id=user
                            )
                        except:
                            pass
                            
                        raise ValueError(error_msg)

            # Ensure details is a dict
            if details is None:
                details = {}
            
            # Add payment_group_id to details if provided
            if payment_group_id:
                details['payment_group_id'] = payment_group_id

            transaction = {
                "id": f"TX_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "type": tx_type,
                "amount": parsed_amount,
                "description": description,
                "payment_method": payment_method,
                "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "user": user,
                "details": details
            }
            CashierService._apply_commission_contract(transaction)
            
            sessions[session_idx]['transactions'].append(transaction)
            CashierService._save_sessions(sessions)

            # --- LEDGER INTEGRATION ---
            try:
                from app.services.ledger_service import LedgerService
                
                # Determine Source/Dest based on amount sign
                # Use mapped name or raw type
                box_name = CashierService.TYPES.get(cashier_type, cashier_type)
                
                # Default direction
                if parsed_amount >= 0:
                    src = "EXTERNO"
                    dst = box_name
                    # Try to extract more info
                    if details and details.get('source'):
                         src = str(details.get('source'))
                    elif 'Mesa' in description:
                         src = description
                else:
                    src = box_name
                    dst = "EXTERNO"
                    if details and details.get('destination'):
                         dst = str(details.get('destination'))

                LedgerService.record_transaction(
                    user=user,
                    source_box=src,
                    dest_box=dst,
                    operation_type=tx_type,
                    value=abs(parsed_amount),
                    payment_method=payment_method or "N/A",
                    reference=f"{description} (Ref: {transaction['id']})"
                )
            except Exception as e:
                logger.error(f"CRITICAL: Failed to record transaction in Immutable Ledger: {e}")
            
            # Trigger Backup
            CashierService._perform_backup(sessions)

            # --- FINANCIAL AUDIT LOG ---
            try:
                from app.services.financial_audit_service import FinancialAuditService
                
                audit_action = None
                if tx_type in ['out', 'withdrawal', 'sangria']:
                    audit_action = FinancialAuditService.EVENT_BLEEDING
                elif tx_type in ['supply', 'suprimento']:
                    audit_action = FinancialAuditService.EVENT_SUPPLY
                elif tx_type == 'refund' or (parsed_amount < 0 and 'refund' in str(description).lower()):
                    audit_action = FinancialAuditService.EVENT_REVERSAL
                elif 'cancel' in str(description).lower():
                    audit_action = FinancialAuditService.EVENT_CANCEL
                
                if audit_action:
                    FinancialAuditService.log_event(
                        user=user,
                        action=audit_action,
                        entity=f"Transaction {transaction['id']}",
                        old_data=None, # New transaction
                        new_data=transaction,
                        details={'session_id': session.get('id')}
                    )
            except Exception as e:
                logger.error(f"Failed to log financial audit: {e}")
            
            return transaction

    @staticmethod
    def _perform_backup(sessions):
        """
        Creates a backup of the cashier state.
        Maintains rotation (last 30 days).
        Adds basic 'encryption' (base64) as requested.
        """
        global _last_backup_hash
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"backup_cashier_{timestamp}.json"
            filepath = os.path.join(BACKUP_DIR, filename)
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'sessions': sessions
            }
            
            # Basic obfuscation/encryption as requested
            # Using base64 encoding of the JSON string
            json_str = json.dumps(data, ensure_ascii=False)
            
            # Optimization: Check hash to avoid duplicate backups during idle times
            import hashlib
            current_hash = hashlib.md5(json_str.encode('utf-8')).hexdigest()
            
            if _last_backup_hash == current_hash:
                # Content hasn't changed, skip writing file but maybe log debug?
                # logger.debug("Skipping backup - content unchanged")
                return
                
            _last_backup_hash = current_hash
            
            encrypted_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(encrypted_content)
                
            # Rotation Logic: Keep last 30 days
            cutoff_time = datetime.now().timestamp() - (30 * 24 * 3600)
            
            for f in os.listdir(BACKUP_DIR):
                fp = os.path.join(BACKUP_DIR, f)
                if os.path.isfile(fp) and f.startswith("backup_cashier_"):
                    if os.path.getmtime(fp) < cutoff_time:
                        os.remove(fp)
                        
        except Exception as e:
            print(f"Cashier Backup Failed: {e}")

    @staticmethod
    def prepare_transactions_for_display(transactions):
        """
        Groups transactions with the same payment_group_id into a single displayable item.
        Also handles Legacy Restaurant Grouping (Venda Mesa X).
        """
        if not transactions:
            return []
            
        processed = []
        seen_groups = set()
        seen_legacy_groups = set()
        
        # Map group_id to list of transactions
        groups = {}
        legacy_groups = {}
        
        for t in transactions:
            details = t.get('details', {}) or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except:
                    details = {}
            gid = details.get('payment_group_id')
            
            # Priority 1: New Payment Group ID
            if gid:
                if gid not in groups:
                    groups[gid] = []
                groups[gid].append(t)
            
            # Priority 2: Legacy Regex Grouping (Only if no Group ID)
            elif t.get('type') == 'sale':
                description = t.get('description', '')
                # Regex for "Venda Mesa X"
                match = re.search(r"Venda Mesa (\d+)", description)
                if match:
                    table_id = match.group(1)
                    # Group key: TableID + Timestamp (assuming same second)
                    # Note: Pagination slicing might split these if they span pages, 
                    # but usually they are adjacent.
                    key = f"{table_id}_{t.get('timestamp')}"
                    
                    if key not in legacy_groups:
                        legacy_groups[key] = []
                    legacy_groups[key].append(t)
        
        for t in transactions:
            details = t.get('details', {}) or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except:
                    details = {}
            gid = details.get('payment_group_id')
            
            # Handle Payment Group ID
            if gid:
                if gid in seen_groups:
                    continue
                
                group_txs = groups[gid]
                base_tx = group_txs[0]
                total_amount = sum(float(tx.get('amount', 0)) for tx in group_txs)
                
                sub_transactions = []
                for tx in group_txs:
                    sub_amount = float(tx.get('amount', 0))
                    percent = (sub_amount / total_amount * 100) if total_amount else 0
                    sub_transactions.append({
                        'method': tx.get('payment_method'),
                        'amount': sub_amount,
                        'timestamp': tx.get('timestamp'),
                        'percent': round(percent, 1)
                    })
                
                group_obj = base_tx.copy()
                group_obj['is_group'] = True
                group_obj['amount'] = total_amount
                base_desc = base_tx.get('description', '')
                if ' - ' in base_desc:
                    parts = base_desc.split(' - ')
                    group_obj['description'] = ' - '.join(parts[:-1])
                
                group_obj['sub_transactions'] = sub_transactions
                group_obj['payment_method'] = "Múltiplo"
                
                processed.append(group_obj)
                seen_groups.add(gid)
                
            # Handle Legacy Grouping
            elif t.get('type') == 'sale' and re.search(r"Venda Mesa (\d+)", t.get('description', '')):
                description = t.get('description', '')
                match = re.search(r"Venda Mesa (\d+)", description)
                table_id = match.group(1)
                key = f"{table_id}_{t.get('timestamp')}"
                
                if key in seen_legacy_groups:
                    continue
                    
                group_txs = legacy_groups.get(key, [t])
                
                # If only one transaction, treat as normal
                if len(group_txs) <= 1:
                    processed.append(t)
                    seen_legacy_groups.add(key)
                    continue
                    
                # Create Group
                base_tx = group_txs[0]
                total_amount = sum(float(tx.get('amount', 0)) for tx in group_txs)
                
                sub_transactions = []
                for tx in group_txs:
                    sub_amount = float(tx.get('amount', 0))
                    percent = (sub_amount / total_amount * 100) if total_amount else 0
                    sub_transactions.append({
                        'method': tx.get('payment_method', 'Outros'),
                        'amount': sub_amount,
                        'timestamp': tx.get('timestamp'),
                        'percent': round(percent, 1)
                    })
                    
                group_obj = base_tx.copy()
                group_obj['is_group'] = True
                group_obj['amount'] = total_amount
                group_obj['description'] = f"Venda Mesa {table_id}"
                
                # Merge notes
                notes = []
                for tx in group_txs:
                    if '[' in tx.get('description', ''):
                        parts = tx['description'].split('[')
                        if len(parts) > 1:
                            note = parts[1].replace(']', '').strip()
                            if note and note not in notes:
                                notes.append(note)
                if notes:
                    group_obj['description'] += f" [{', '.join(notes)}]"
                
                group_obj['sub_transactions'] = sub_transactions
                group_obj['payment_method'] = "Múltiplo"
                
                processed.append(group_obj)
                seen_legacy_groups.add(key)
                
            else:
                processed.append(t)
                
        return processed

    @staticmethod
    def get_paginated_transactions(session_id, page=1, per_page=20):
        """
        Returns a paginated, reversed (newest first), and prepared list of transactions.
        Groups transactions BEFORE slicing to prevent splitting groups across pages.
        """
        session = CashierService.get_session_by_id(session_id)
        if not session:
            return [], False

        all_transactions = session.get('transactions', [])
        # Reverse to get newest first (Display Order: Newest -> Oldest)
        reversed_transactions = list(reversed(all_transactions))
        
        # Prepare (Group) ALL transactions first to ensure groups aren't broken by pagination slicing
        # This is slightly more expensive but ensures consistency
        prepared_all = CashierService.prepare_transactions_for_display(reversed_transactions)
        
        total_items = len(prepared_all)
        start = (page - 1) * per_page
        end = start + per_page
        
        # Slice the prepared list
        sliced_transactions = prepared_all[start:end]
        
        has_more = end < total_items
        
        return sliced_transactions, has_more

    @staticmethod
    def get_session_by_id(session_id):
        sessions = CashierService._load_sessions()
        for s in sessions:
            if s.get('id') == session_id:
                return s
        return None

    @staticmethod
    def get_history(start_date=None, end_date=None, cashier_type=None):
        sessions = CashierService._load_sessions()
        filtered = []
        
        # Parse dates if provided (dd/mm/yyyy)
        start_dt = datetime.strptime(start_date, '%d/%m/%Y') if start_date else None
        end_dt = datetime.strptime(end_date, '%d/%m/%Y') if end_date else None
        
        for s in sessions:
            # Filter by Type
            if cashier_type:
                match = False
                s_type = s.get('type')
                if cashier_type == 'guest_consumption' and s_type in ['guest_consumption', 'reception_room_billing']:
                    match = True
                elif s_type == cashier_type:
                    match = True
                
                if not match:
                    continue
            
            # Filter by Date (Opened At)
            if start_dt or end_dt:
                try:
                    s_dt = datetime.strptime(s['opened_at'].split(' ')[0], '%d/%m/%Y')
                    if start_dt and s_dt < start_dt:
                        continue
                    if end_dt and s_dt > end_dt:
                        continue
                except:
                    pass
            
            filtered.append(s)
        
        # Sort by opened_at descending
        filtered.sort(key=lambda x: datetime.strptime(x['opened_at'], '%d/%m/%Y %H:%M') if x.get('opened_at') else datetime.min, reverse=True)
        return filtered

    @staticmethod
    def validate_transfer_eligibility(source_type, target_type, user):
        """
        Validates if a transfer can occur between two cashier types.
        Both cashiers MUST be open.
        
        Args:
            source_type (str): The source cashier type.
            target_type (str): The destination cashier type.
            user (str): The user attempting the transfer.
            
        Raises:
            ValueError: If validation fails (one or both cashiers closed).
        """
        sessions = CashierService._load_sessions()
        
        # Helper to find open session (Same logic as transfer_funds)
        def find_open_session(c_type):
            types = [c_type]
            if c_type in ['guest_consumption', 'reception', 'reception_room_billing']:
                types = ['guest_consumption', 'reception_room_billing', 'reception']
            elif c_type in ['restaurant', 'restaurant_service']:
                types = ['restaurant_service', 'restaurant']
            
            for s in sessions:
                if s.get('status') == 'open' and s.get('type') in types:
                    return s
            return None

        source_session = find_open_session(source_type)
        target_session = find_open_session(target_type)
        
        error_msg = None
        
        if not source_session and not target_session:
            error_msg = f"Transferência Bloqueada: Ambos os caixas (Origem: {source_type}, Destino: {target_type}) estão FECHADOS."
        elif not source_session:
            error_msg = f"Transferência Bloqueada: Caixa de origem ({source_type}) está FECHADO."
        elif not target_session:
            error_msg = f"Transferência Bloqueada: Caixa de destino ({target_type}) está FECHADO."
            
        if error_msg:
            # Audit Log
            try:
                from app.services.logger_service import LoggerService
                LoggerService.log_acao(
                    acao='Transferência Bloqueada',
                    entidade='Caixa',
                    detalhes={
                        'reason': error_msg,
                        'source_type': source_type,
                        'target_type': target_type,
                        'source_status': 'closed' if not source_session else 'open',
                        'target_status': 'closed' if not target_session else 'open'
                    },
                    nivel_severidade='WARNING',
                    colaborador_id=user
                )
            except Exception as e:
                print(f"Failed to log audit: {e}")
                
            raise ValueError(error_msg)
            
        return source_session, target_session

    @staticmethod
    def transfer_funds(source_type, target_type, amount, description, user):
        with file_lock(CASHIER_SESSIONS_FILE):
            # Use the new validation method
            # Note: This re-loads sessions inside validate, but we need the lock.
            # Ideally validate should take sessions list or be robust.
            # But validate loads sessions internally. Since we are in a lock here, 
            # and validate loads from disk, it's fine but slightly inefficient (double read).
            # To avoid double read, we can refactor.
            # However, for safety and simplicity complying with existing structure:
            
            # We call validate first to ensure rules and auditing
            source_session, target_session = CashierService.validate_transfer_eligibility(source_type, target_type, user)
            
            # Now we reload to ensure we have the latest version for modification within the lock
            # (In case validate took a split second and file changed - unlikely with lock but good practice)
            # Actually, since we are inside `with cashier_lock`, no one else can write.
            # But validate_transfer_eligibility reads the file again.
            # Let's use the sessions returned by validate if we can trust they are fresh.
            # CashierService._load_sessions() reads from disk.
            
            # Since validate_transfer_eligibility is static and loads sessions, 
            # and we are in a lock, the file state shouldn't change between validate call and here
            # IF validate_transfer_eligibility respects the lock? 
            # The lock is re-entrant? No, threading.Lock is NOT re-entrant by default in Python (RLock is).
            # Wait, `cashier_lock = Lock()`. It is NOT re-entrant.
            # So if validate_transfer_eligibility uses the lock, it will deadlock.
            # validate_transfer_eligibility does NOT use the lock in my implementation above. 
            # It just reads. Reading is fine if we hold the lock?
            # Yes, we hold the lock here. validate just reads.
            
            # HOWEVER, we need to modify the sessions list and save it.
            # validate returns session objects from its own load.
            # We should probably reload sessions here to be 100% sure we are working on the list we will save.
            
            sessions = CashierService._load_sessions()
            
            # Re-find sessions in this list (since objects are different from validate's return)
            def find_open_session_internal(c_type, session_list):
                types = [c_type]
                if c_type in ['guest_consumption', 'reception', 'reception_room_billing']:
                    types = ['guest_consumption', 'reception_room_billing', 'reception']
                elif c_type in ['restaurant', 'restaurant_service']:
                    types = ['restaurant_service', 'restaurant']
                
                for s in session_list:
                    if s.get('status') == 'open' and s.get('type') in types:
                        return s
                return None
                
            source_session = find_open_session_internal(source_type, sessions)
            target_session = find_open_session_internal(target_type, sessions)
            
            # Sanity check (should pass if validate passed)
            if not source_session or not target_session:
                 # Should not happen if validate passed, unless file corrupted in between
                 raise ValueError("Erro interno: Sessões não encontradas após validação.")

            # Validate Balance (Saldo Check) - STRICT CASH CHECK
            # Transfers are inherently Cash movements between drawers
            current_cash = CashierService._calculate_cash_balance(source_session)
            
            if current_cash < float(amount):
                error_msg = f"Transferência Bloqueada: Saldo em DINHEIRO insuficiente na origem. Disponível: R$ {current_cash:.2f}, Solicitado: R$ {float(amount):.2f}"
                
                # Audit Log
                try:
                    from app.services.logger_service import LoggerService
                    LoggerService.log_acao(
                        acao='Transferência Bloqueada',
                        entidade='Caixa',
                        detalhes={
                            'reason': 'Insufficient Cash Balance',
                            'available_cash': current_cash,
                            'requested_amount': float(amount),
                            'source_type': source_type,
                            'target_type': target_type,
                            'user': user
                        },
                        nivel_severidade='WARNING',
                        colaborador_id=user
                    )
                except:
                    pass
                    
                raise ValueError(error_msg)

            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            time_str = datetime.now().strftime('%H:%M')
            trans_id_base = datetime.now().strftime('%Y%m%d%H%M%S')

            # Create OUT transaction
            out_trans = {
                "id": f"TRANS_{trans_id_base}_OUT",
                "document_id": trans_id_base,  # Linked Document ID
                "type": "out",
                "category": "Transferência Enviada",
                "amount": float(amount),
                "description": f"Transferência para {target_type}: {description}",
                "payment_method": "Transferência",
                "timestamp": timestamp,
                "time": time_str,
                "user": user
            }
            source_session['transactions'].append(out_trans)

            # Create IN transaction
            in_trans = {
                "id": f"TRANS_{trans_id_base}_IN",
                "document_id": trans_id_base,  # Linked Document ID
                "type": "in",
                "category": "Transferência Recebida",
                "amount": float(amount),
                "description": f"Transferência de {source_type}: {description}",
                "payment_method": "Transferência",
                "timestamp": timestamp,
                "time": time_str,
                "user": user
            }
            target_session['transactions'].append(in_trans)

            CashierService._save_sessions(sessions)
            CashierService._perform_backup(sessions)
            
            # --- LEDGER INTEGRATION ---
            try:
                from app.services.ledger_service import LedgerService
                LedgerService.record_transaction(
                    user=user,
                    source_box=CashierService.TYPES.get(source_type, source_type),
                    dest_box=CashierService.TYPES.get(target_type, target_type),
                    operation_type='TRANSFERENCIA',
                    value=float(amount),
                    payment_method='Transferência Interna',
                    reference=f"{description} (Ref: {trans_id_base})"
                )
            except Exception as e:
                logger.error(f"CRITICAL: Failed to record transfer in Immutable Ledger: {e}")

            # --- FINANCIAL AUDIT LOG ---
            try:
                from app.services.financial_audit_service import FinancialAuditService
                FinancialAuditService.log_event(
                    user=user,
                    action=FinancialAuditService.EVENT_TRANSFER,
                    entity=f"Transfer {trans_id_base}",
                    old_data=None,
                    new_data={
                        'source': source_type,
                        'target': target_type,
                        'amount': float(amount),
                        'description': description
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log transfer audit: {e}")
            
            return True

    @staticmethod
    def get_current_status(cashier_type):
        """Returns the current status summary for a specific cashier type."""
        session = CashierService.get_active_session(cashier_type)
        if session:
            current_balance = session['opening_balance']
            for t in session.get('transactions', []):
                try:
                    amount = float(t.get('amount', 0))
                except:
                    amount = 0.0
                
                t_type = str(t.get('type', '')).lower()
                
                if t_type in ['out', 'withdrawal', 'refund']:
                    current_balance -= abs(amount)
                else:
                    current_balance += amount

            return {
                'status': 'open',
                'user': session['user'],
                'opened_at': session['opened_at'],
                'current_balance': current_balance,
                'transaction_count': len(session['transactions'])
            }
        
        # Get last closed session
        history = CashierService.get_history(cashier_type=cashier_type)
        # Filter for closed ones
        closed = [s for s in history if s.get('status') == 'closed']
        if closed:
            last = closed[0] # history is sorted desc
            return {
                'status': 'closed',
                'last_closed_at': last.get('closed_at'),
                'last_closed_by': last.get('closed_by', last.get('user')),
                'last_closing_balance': last.get('closing_balance'),
                'last_difference': last.get('difference', 0)
            }
            
        return {'status': 'never_opened'}
