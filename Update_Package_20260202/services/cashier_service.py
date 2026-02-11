import os
import json
import shutil
import base64
from datetime import datetime
import uuid
from threading import Lock

# Constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups', 'Caixa')
CASHIER_SESSIONS_FILE = os.path.join(DATA_DIR, 'cashier_sessions.json')
CLOSED_CASHIERS_AUDIT_DIR = r"G:\Back Up Sistema\Caixas Fechados"

# Ensure Backup Directory Exists
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# Lock for thread safety
cashier_lock = Lock()

class CashierService:
    TYPES = {
        'restaurant': 'Caixa Restaurante',
        'guest_consumption': 'Caixa Consumo de Hóspedes',
        'daily_rates': 'Caixa Diárias'
    }

    @staticmethod
    def _load_sessions():
        if not os.path.exists(CASHIER_SESSIONS_FILE):
            return []
        try:
            with open(CASHIER_SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    @staticmethod
    def _save_sessions(sessions):
        # Atomic write pattern could be better, but sticking to simple write for now
        with open(CASHIER_SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, indent=4, ensure_ascii=False)

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
    def get_active_session(cashier_type):
        """Returns the active (open) session for the given type."""
        sessions = CashierService._load_sessions()
        
        # Compatibility mapping
        target_types = [cashier_type]
        if cashier_type == 'guest_consumption':
            target_types.append('reception_room_billing')
        
        for s in sessions:
            if s.get('status') == 'open' and s.get('type') in target_types:
                return s
        return None

    @staticmethod
    def open_session(cashier_type, user, opening_balance=0.0):
        with cashier_lock:
            if CashierService.get_active_session(cashier_type):
                raise ValueError(f"Já existe um caixa aberto para {CashierService.TYPES.get(cashier_type, cashier_type)}")
            
            new_session = {
                "id": f"SESSION_{cashier_type.upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{user}",
                "user": user,
                "type": cashier_type,
                "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "opening_balance": float(opening_balance),
                "transactions": [],
                "status": "open",
                "closed_at": None,
                "closing_balance": None,
                "difference": None
            }
            
            sessions = CashierService._load_sessions()
            sessions.append(new_session)
            CashierService._save_sessions(sessions)
            
            # Audit Log could go here
            return new_session

    @staticmethod
    def close_session(cashier_type=None, user=None, closing_balance=0.0, session_id=None):
        with cashier_lock:
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

            # Calculate totals
            total_in = sum(t['amount'] for t in session['transactions'] if t['type'] == 'in')
            total_out = sum(t['amount'] for t in session['transactions'] if t['type'] == 'out')
            calculated_balance = session['opening_balance'] + total_in - total_out
            
            # Update session
            session['status'] = 'closed'
            session['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
            session['closing_balance'] = float(closing_balance) if closing_balance is not None else 0.0
            session['difference'] = session['closing_balance'] - calculated_balance
            
            # Force user update if provided
            if user:
                session['closed_by'] = user
            
            sessions[session_idx] = session
            CashierService._save_sessions(sessions)
            CashierService.export_closed_sessions_audit(sessions)
            
            return session

    @staticmethod
    def add_transaction(cashier_type, amount, description, payment_method, user, details=None):
        with cashier_lock:
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
                # This ensures payments are not lost if no one explicitly opened the cashier
                # But we should mark it as system-opened
                new_session = {
                    "id": f"SESSION_{cashier_type.upper()}_AUTO_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "user": "Sistema (Auto)",
                    "type": cashier_type,
                    "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                    "opening_balance": 0.0,
                    "transactions": [],
                    "status": "open"
                }
                sessions.append(new_session)
                session_idx = len(sessions) - 1
            
            transaction = {
                "id": f"TX_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "type": "sale" if amount >= 0 else "refund",
                "amount": amount,
                "description": description,
                "payment_method": payment_method,
                "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "user": user,
                "details": details or {}
            }
            
            sessions[session_idx]['transactions'].append(transaction)
            CashierService._save_sessions(sessions)
            
            # Trigger Backup
            CashierService._perform_backup(sessions)
            
            return transaction

    @staticmethod
    def _perform_backup(sessions):
        """
        Creates a backup of the cashier state.
        Maintains rotation (last 30 days).
        Adds basic 'encryption' (base64) as requested.
        """
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
            encrypted_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(encrypted_content)
                
            # Rotation Logic: Keep last 30 days
            # Since we backup on every transaction, this might be too many files.
            # Maybe limit by count or date? User said "Rotation ... maintaining last 30 days".
            # Let's clean up files older than 30 days.
            
            cutoff_time = datetime.now().timestamp() - (30 * 24 * 3600)
            
            for f in os.listdir(BACKUP_DIR):
                fp = os.path.join(BACKUP_DIR, f)
                if os.path.isfile(fp) and f.startswith("backup_cashier_"):
                    if os.path.getmtime(fp) < cutoff_time:
                        os.remove(fp)
                        
        except Exception as e:
            print(f"Cashier Backup Failed: {e}")

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
                if cashier_type == 'guest_consumption' and s['type'] in ['guest_consumption', 'reception_room_billing']:
                    match = True
                elif s['type'] == cashier_type:
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
    def get_current_status(cashier_type):
        """Returns the current status summary for a specific cashier type."""
        session = CashierService.get_active_session(cashier_type)
        if session:
            current_balance = session['opening_balance'] + sum(t['amount'] for t in session['transactions'])
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
