import json
import os
import traceback
from datetime import datetime
from flask import has_request_context, request
from app.services.system_config_manager import get_data_path


MONITOR_LOG_FILE = get_data_path('data_cleanup_monitor.log')
MONITOR_SUMMARY_FILE = get_data_path('data_cleanup_monitor_summary.json')


def _classify_severity(path, event_type):
    full = str(path or '').lower()
    if event_type == 'unhandled_exception':
        return 'critico'
    critical_tokens = [
        'cashier_sessions.json',
        'table_orders.json',
        'room_charges.json',
        'room_occupancy.json',
        'fiscal_pool.json',
        'fiscal_settings.json',
        'pending_fiscal_emissions.json',
        'users.json',
        'payment_methods.json',
    ]
    medium_tokens = [
        'menu_',
        'stock_',
        'audit_',
        'backups/',
        '.bak',
        '.backup_',
        '.migrated',
    ]
    if any(token in full for token in critical_tokens):
        return 'critico'
    if any(token in full for token in medium_tokens):
        return 'medio'
    return 'baixo'


def _current_impact():
    if not has_request_context():
        return {'route': '', 'endpoint': '', 'method': ''}
    return {
        'route': str(request.path or ''),
        'endpoint': str(request.endpoint or ''),
        'method': str(request.method or ''),
    }


def _derive_service_context(stack):
    for row in reversed(stack):
        file_name = str(row.get('file') or '')
        if '/app/services/' in file_name.replace('\\', '/'):
            return f"{os.path.basename(file_name)}:{row.get('function')}"
    for row in reversed(stack):
        file_name = str(row.get('file') or '')
        if '/app/blueprints/' in file_name.replace('\\', '/'):
            return f"{os.path.basename(file_name)}:{row.get('function')}"
    return ''


def _compact_stack(tb=None):
    if tb is None:
        extracted = traceback.extract_stack()[:-2]
    else:
        extracted = traceback.extract_tb(tb)
    rows = []
    for frame in extracted[-8:]:
        rows.append({
            'file': str(frame.filename),
            'line': int(frame.lineno),
            'function': str(frame.name),
        })
    return rows


def _append_line(payload):
    os.makedirs(os.path.dirname(MONITOR_LOG_FILE), exist_ok=True)
    with open(MONITOR_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')


def _load_lines():
    if not os.path.exists(MONITOR_LOG_FILE):
        return []
    events = []
    with open(MONITOR_LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                events.append(json.loads(text))
            except Exception:
                continue
    return events


def _write_summary():
    events = _load_lines()
    needed = {}
    maybe_remove = {}
    level_counts = {'critico': 0, 'medio': 0, 'baixo': 0}
    for event in events:
        severity = str(event.get('severity') or 'baixo')
        if severity not in level_counts:
            level_counts[severity] = 0
        level_counts[severity] += 1
        path = str(event.get('requested_file') or '').strip()
        if not path:
            continue
        if severity == 'critico':
            needed[path] = needed.get(path, 0) + 1
        else:
            maybe_remove[path] = maybe_remove.get(path, 0) + 1
    summary = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'log_file': MONITOR_LOG_FILE,
        'events_count': len(events),
        'severity_counts': level_counts,
        'arquivos_ainda_necessarios': sorted(
            [{'path': k, 'ocorrencias': v} for k, v in needed.items()],
            key=lambda x: (-x['ocorrencias'], x['path'])
        ),
        'arquivos_podem_ser_removidos_com_seguranca': sorted(
            [{'path': k, 'ocorrencias': v} for k, v in maybe_remove.items()],
            key=lambda x: (-x['ocorrencias'], x['path'])
        ),
    }
    with open(MONITOR_SUMMARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def ensure_monitor_files():
    os.makedirs(os.path.dirname(MONITOR_LOG_FILE), exist_ok=True)
    if not os.path.exists(MONITOR_LOG_FILE):
        with open(MONITOR_LOG_FILE, 'a', encoding='utf-8'):
            pass
    _write_summary()


def record_data_cleanup_event(event_type, requested_file='', error_message='', tb=None):
    stack = _compact_stack(tb=tb)
    impact = _current_impact()
    severity = _classify_severity(requested_file, event_type)
    payload = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'event_type': str(event_type or ''),
        'requested_file': str(requested_file or ''),
        'error_message': str(error_message or ''),
        'severity': severity,
        'impact': impact,
        'service_context': _derive_service_context(stack),
        'stack_simplified': stack,
    }
    _append_line(payload)
    _write_summary()
    return payload
