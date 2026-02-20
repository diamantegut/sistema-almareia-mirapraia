import json
import os
import glob
import sqlite3
import re
from datetime import datetime, timedelta
import uuid

# Configuration
DATA_DIR = os.path.join(os.getcwd(), 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups', 'table_orders')
SALES_HISTORY_FILE = os.path.join(DATA_DIR, 'sales_history.json')
LOGS_DB = os.path.join(DATA_DIR, 'department_logs.db')

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def parse_backup_timestamp(filename):
    # table_orders_20260218_152627_Angelo.json
    try:
        parts = os.path.basename(filename).split('_')
        date_str = parts[2] # 20260218
        time_str = parts[3] # 152627
        dt_str = f"{date_str}{time_str}"
        return datetime.strptime(dt_str, "%Y%m%d%H%M%S")
    except Exception as e:
        return None

def get_db_connection():
    try:
        conn = sqlite3.connect(LOGS_DB)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def parse_log_timestamp(ts_str):
    try:
        # Try ISO first
        return datetime.fromisoformat(ts_str)
    except:
        try:
            # Try standard DB format 'YYYY-MM-DD HH:MM:SS'
            return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
        except:
            try:
                return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            except:
                return None

def normalize_key(order):
    # Create a unique key for deduplication
    # opened_at + table (if available) + items count + total
    opened = order.get('opened_at', '')
    total = float(order.get('total', 0) or 0)
    # total might change slightly due to service fee, so round it
    total = round(total, 2)
    
    # Try to find table ID
    table = order.get('table_id') or order.get('room_number') or order.get('customer_name') or 'unknown'
    
    # Count items
    items_count = len(order.get('items', []))
    
    return f"{opened}_{table}_{items_count}_{total}"

def main():
    print("Starting Sales History Recovery...")
    
    # 1. Load Current History
    if os.path.exists(SALES_HISTORY_FILE):
        history = load_json(SALES_HISTORY_FILE)
        if not isinstance(history, list):
            history = []
    else:
        history = []
        
    print(f"Loaded {len(history)} existing sales records.")
    
    # Index History
    history_index = set()
    for h in history:
        # We index by close_id if present, else heuristic
        if h.get('close_id'):
            history_index.add(h.get('close_id'))
        
        # Also add heuristic key
        history_index.add(normalize_key(h))

    # 2. Get Logs
    conn = get_db_connection()
    logs = []
    if conn:
        cursor = conn.cursor()
        # Get relevant logs: Mesa Fechada or Cancelamento
        cursor.execute("SELECT * FROM logs_acoes_departamento WHERE acao IN ('Mesa Fechada', 'Cancelamento Mesa') ORDER BY timestamp")
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
    print(f"Loaded {len(logs)} relevant logs.")

    # 3. Scan Backups
    backup_files = sorted(glob.glob(os.path.join(BACKUP_DIR, '*.json')))
    print(f"Found {len(backup_files)} backup files.")
    
    recovered_count = 0
    
    # We iterate backups to track state
    # previous_state: { table_id: { 'data': order_dict, 'timestamp': dt } }
    previous_state = {}
    
    for i, backup_path in enumerate(backup_files):
        current_dt = parse_backup_timestamp(backup_path)
        if not current_dt: continue
        
        current_data = load_json(backup_path)
        if current_data is None: continue
        
        # Tables present in this backup
        current_tables = set(current_data.keys())
        previous_tables = set(previous_state.keys())
        
        # Tables that disappeared since last backup
        disappeared_tables = previous_tables - current_tables
        
        for table_id in disappeared_tables:
            last_seen_order = previous_state[table_id]['data']
            last_seen_time = previous_state[table_id]['timestamp']
            
            # Skip if empty or trivial
            if not last_seen_order.get('items'):
                continue
                
            # Check if it was just transferred?
            # If transferred, it disappears from ID X but appears in ID Y.
            # We won't track transfers perfectly here, but we rely on logs.
            
            # Search logs between last_seen_time and current_dt
            # Buffer: +/- 2 minutes
            start_window = last_seen_time - timedelta(minutes=5)
            end_window = current_dt + timedelta(minutes=5)
            
            relevant_logs = []
            for l in logs:
                l_ts = parse_log_timestamp(l['timestamp'])
                if l_ts and start_window <= l_ts <= end_window:
                     det = l.get('detalhes', '') or ''
                     if f"Mesa {table_id}" in det or f"'table': '{table_id}'" in det or f"'table': {table_id}" in det:
                         relevant_logs.append(l)
            
            is_cancelled = any(l['acao'] == 'Cancelamento Mesa' for l in relevant_logs)
            is_closed = any(l['acao'] == 'Mesa Fechada' for l in relevant_logs)
            
            if is_cancelled:
                # Confirmed Cancelled - Do not recover
                continue
            
            should_recover = False
            recovery_reason = ""
            
            if is_closed:
                # Confirmed Closed - Check if in history
                candidate_key = normalize_key(last_seen_order)
                
                # Check history
                found = False
                
                for h in history:
                    if normalize_key(h) == candidate_key:
                        found = True
                        break
                    # Fallback
                    if h.get('opened_at') == last_seen_order.get('opened_at') and abs(float(h.get('total',0)) - float(last_seen_order.get('total',0))) < 1.0:
                         found = True
                         break
                
                if not found:
                    should_recover = True
                    recovery_reason = "Log 'Mesa Fechada' found but missing in Sales History"
            
            else:
                # Silent Disappearance
                candidate_key = normalize_key(last_seen_order)
                found = False
                for h in history:
                     if normalize_key(h) == candidate_key:
                        found = True
                        break
                     if h.get('opened_at') == last_seen_order.get('opened_at'):
                         found = True
                         break
                
                if not found:
                    if float(last_seen_order.get('total', 0)) > 0:
                        should_recover = True
                        recovery_reason = "Silent Disappearance (No Cancel/Close Log) and missing in History"
            
            if should_recover:
                print(f"RECOVERING Table {table_id}: {recovery_reason}")
                print(f"  Opened: {last_seen_order.get('opened_at')}, Total: {last_seen_order.get('total')}")
                
                # Prepare Order for History
                recovered_order = last_seen_order.copy()
                recovered_order['status'] = 'closed'
                recovered_order['recovered_via'] = 'script_v1'
                recovered_order['recovery_reason'] = recovery_reason
                recovered_order['closed_at'] = current_dt.strftime('%d/%m/%Y %H:%M') # Approx close time
                recovered_order['final_total'] = recovered_order.get('total')
                recovered_order['close_id'] = f"RECOVERED_{uuid.uuid4().hex}"
                
                history.append(recovered_order)
                recovered_count += 1
                
                # Update Index
                history_index.add(normalize_key(recovered_order))

        # Update previous_state with current
        # If table persists, we update its data (maybe items added)
        # If table is new, we add it.
        # If table disappeared, it's already handled above and removed from set implicitly by reconstruction.
        previous_state = {} 
        for tid, data in current_data.items():
            previous_state[tid] = {'data': data, 'timestamp': current_dt}

    print(f"Recovery Complete. Recovered {recovered_count} orders.")
    
    if recovered_count > 0:
        # Backup existing history first
        backup_hist = SALES_HISTORY_FILE + f".backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        if os.path.exists(SALES_HISTORY_FILE):
            os.rename(SALES_HISTORY_FILE, backup_hist)
            print(f"Backed up original history to {os.path.basename(backup_hist)}")
        
        save_json(SALES_HISTORY_FILE, history)
        print("Sales History Updated.")
    else:
        print("No missing orders found.")

if __name__ == "__main__":
    main()
