import os
import json
import sys
import glob
from datetime import datetime
import traceback
import csv
import io
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')

def _read_json_file(file_path, default):
    try:
        if not os.path.exists(file_path):
            return default
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def _parse_datetime(value, formats):
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except Exception:
            continue
    return None

def _same_ymd(dt, ymd):
    try:
        return dt.strftime('%Y-%m-%d') == ymd
    except Exception:
        return False

def _read_text_lines(file_path):
    try:
        if not os.path.exists(file_path):
            return []
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return [line.rstrip('\n') for line in f.readlines()]
    except Exception:
        return []

def _ensure_log_dir(subdir):
    path = os.path.join(LOGS_DIR, subdir)
    os.makedirs(path, exist_ok=True)
    return path

def _write_log(subdir, entry):
    try:
        log_dir = _ensure_log_dir(subdir)
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{today}.json"
        filepath = os.path.join(log_dir, filename)
        
        current_logs = []
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        current_logs = data
            except json.JSONDecodeError:
                pass
        
        current_logs.append(entry)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(current_logs, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        sys.stderr.write(f"Logging error ({subdir}): {e}\n")
        # traceback.print_exc() # Optional: print to stderr
        return False

def log_order_action(order_data, action="create", user="Sistema"):
    """
    Logs order-related actions.
    order_data: dict containing order details (id, table, items, etc.)
    """
    entry = {
        'id': f"ORD_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'timestamp_iso': datetime.now().isoformat(),
        'action': action,
        'user': user,
        'order_id': order_data.get('id'),
        'table': str(order_data.get('table_id', '')),
        'waiter': order_data.get('waiter_name', user),
        'items': order_data.get('items', []),
        'total': order_data.get('total', 0),
        'status': order_data.get('status', 'unknown')
    }
    return _write_log('orders', entry)

def log_system_action(action, message=None, user="Sistema", category="Geral", details=None):
    entry_details = None
    if details is not None and message is not None:
        entry_details = {
            'message': message,
            'details': details
        }
    elif details is not None:
        entry_details = details
    else:
        entry_details = message

    entry = {
        'id': f"SYS_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'timestamp_iso': datetime.now().isoformat(),
        'action': action,
        'user': user,
        'category': category,
        'details': entry_details
    }
    return _write_log('system', entry)

def list_log_files(log_type):
    """Returns available log dates for a type."""
    log_dir = os.path.join(LOGS_DIR, log_type)
    if not os.path.exists(log_dir):
        return []
    
    files = glob.glob(os.path.join(log_dir, "*.json"))
    dates = []
    for f in files:
        basename = os.path.basename(f)
        date_str = os.path.splitext(basename)[0]
        dates.append(date_str)
    
    dates.sort(reverse=True)
    return dates

def get_logs(log_type, date_str):
    """Retrieves logs for a specific date."""
    filepath = os.path.join(LOGS_DIR, log_type, f"{date_str}.json")
    if os.path.exists(filepath):
        data = _read_json_file(filepath, [])
        return data if isinstance(data, list) else []

    if log_type == 'stock':
        data = _read_json_file(os.path.join(DATA_DIR, 'stock_logs.json'), [])
        if not isinstance(data, list):
            return []
        out = []
        for row in data:
            dt = _parse_datetime(row.get('date'), ['%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S'])
            if not dt or not _same_ymd(dt, date_str):
                continue
            out.append({
                'timestamp': dt.strftime('%d/%m/%Y %H:%M:%S'),
                'user': row.get('user', ''),
                'department': row.get('department', ''),
                'action': row.get('action', ''),
                'product': row.get('product', ''),
                'qty': row.get('qty', 0),
                'details': row.get('details', '')
            })
        return out

    if log_type == 'inspection':
        data = _read_json_file(os.path.join(DATA_DIR, 'inspection_logs.json'), [])
        if not isinstance(data, list):
            return []
        out = []
        for row in data:
            dt = _parse_datetime(row.get('timestamp'), ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'])
            if not dt or not _same_ymd(dt, date_str):
                continue
            out.append({
                'timestamp': dt.strftime('%d/%m/%Y %H:%M:%S'),
                'room_number': row.get('room_number', ''),
                'user': row.get('user', ''),
                'result': row.get('result', ''),
                'observation': row.get('observation', '')
            })
        return out

    if log_type == 'cleaning':
        data = _read_json_file(os.path.join(DATA_DIR, 'cleaning_logs.json'), [])
        if not isinstance(data, list):
            return []
        out = []
        for row in data:
            start = _parse_datetime(row.get('start_time'), ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'])
            if not start or not _same_ymd(start, date_str):
                continue
            out.append({
                'start_time': row.get('start_time', ''),
                'end_time': row.get('end_time', ''),
                'room': row.get('room', ''),
                'maid': row.get('maid', ''),
                'duration_minutes': row.get('duration_minutes', ''),
                'type': row.get('type', '')
            })
        return out

    if log_type == 'audit':
        data = _read_json_file(os.path.join(DATA_DIR, 'audit_logs.json'), [])
        if not isinstance(data, list):
            return []
        out = []
        for row in data:
            dt = _parse_datetime(row.get('timestamp'), ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'])
            if not dt or not _same_ymd(dt, date_str):
                continue
            out.append({
                'timestamp': dt.strftime('%d/%m/%Y %H:%M:%S'),
                'user': row.get('user', ''),
                'action': row.get('action', ''),
                'target_id': row.get('target_id', ''),
                'justification': row.get('justification', ''),
                'target_details': row.get('target_details', None)
            })
        return out

    if log_type == 'backups':
        out = []
        log_sources = [
            ('backup_log.txt', os.path.join(LOGS_DIR, 'backup_log.txt')),
            ('backup_manager.log', os.path.join(LOGS_DIR, 'backup_manager.log')),
            ('reception_backup.log', os.path.join(LOGS_DIR, 'reception_backup.log')),
        ]
        bracket_re = re.compile(r'^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s+(?P<level>[A-Z]+):\s+(?P<msg>.*)$')
        manager_re = re.compile(r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d+)\s+-\s+(?P<level>[A-Z]+)\s+-\s+(?P<msg>.*)$')
        for source_name, source_path in log_sources:
            for line in _read_text_lines(source_path):
                m1 = bracket_re.match(line)
                if m1:
                    dt = _parse_datetime(m1.group('ts'), ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'])
                    if dt and _same_ymd(dt, date_str):
                        out.append({
                            'timestamp': dt.strftime('%d/%m/%Y %H:%M:%S'),
                            'source': source_name,
                            'level': m1.group('level'),
                            'message': m1.group('msg')
                        })
                    continue
                m2 = manager_re.match(line)
                if m2:
                    dt = _parse_datetime(m2.group('ts'), ['%Y-%m-%d %H:%M:%S'])
                    if dt and _same_ymd(dt, date_str):
                        out.append({
                            'timestamp': dt.strftime('%d/%m/%Y %H:%M:%S'),
                            'source': source_name,
                            'level': m2.group('level'),
                            'message': m2.group('msg')
                        })
                    continue
                if date_str and date_str in line:
                    out.append({
                        'timestamp': date_str,
                        'source': source_name,
                        'level': '',
                        'message': line
                    })
        return out

    return []

def export_logs_to_csv(log_type, date_str):
    """Exports logs to CSV format string."""
    logs = get_logs(log_type, date_str)
    if not logs:
        return ""
        
    output = io.StringIO()
    
    if log_type == 'orders':
        fieldnames = ['timestamp', 'user', 'action', 'table', 'waiter', 'total', 'status', 'items']
    elif log_type == 'system':
        fieldnames = ['timestamp', 'user', 'action', 'category', 'details']
    elif log_type == 'actions':
        fieldnames = ['timestamp', 'user', 'department', 'action', 'details']
    elif log_type == 'stock':
        fieldnames = ['timestamp', 'department', 'user', 'action', 'product', 'qty', 'details']
    elif log_type == 'inspection':
        fieldnames = ['timestamp', 'room_number', 'user', 'result', 'observation']
    elif log_type == 'cleaning':
        fieldnames = ['start_time', 'end_time', 'room', 'maid', 'duration_minutes', 'type']
    elif log_type == 'audit':
        fieldnames = ['timestamp', 'user', 'action', 'target_id', 'justification', 'target_details']
    elif log_type == 'backups':
        fieldnames = ['timestamp', 'source', 'level', 'message']
    else:
        fieldnames = list(logs[0].keys()) if isinstance(logs[0], dict) else []
        
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    
    for log in logs:
        row = log.copy()
        if log_type == 'orders' and isinstance(row.get('items'), list):
             # Simplify items for CSV: "2x Coke; 1x Burger"
             try:
                 items_str = "; ".join([f"{i.get('quantity', 1)}x {i.get('name', 'Item')}" for i in row['items']])
                 row['items'] = items_str
             except:
                 row['items'] = str(row['items'])
        
        if log_type == 'system' and isinstance(row.get('details'), (dict, list)):
            row['details'] = json.dumps(row['details'], ensure_ascii=False)
        if log_type in ['audit'] and isinstance(row.get('target_details'), (dict, list)):
            row['target_details'] = json.dumps(row['target_details'], ensure_ascii=False)
        if log_type in ['actions', 'stock'] and isinstance(row.get('details'), (dict, list)):
            row['details'] = json.dumps(row['details'], ensure_ascii=False)
            
        writer.writerow(row)
        
    return output.getvalue()
