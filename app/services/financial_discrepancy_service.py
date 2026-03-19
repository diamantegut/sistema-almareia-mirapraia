import json
import os
from datetime import datetime
from app.services.system_config_manager import get_data_path


FINANCIAL_DISCREPANCIES_FILE = get_data_path('financial_discrepancies.json')


def _now_str():
    return datetime.now().strftime('%d/%m/%Y %H:%M:%S')


def _parse_dt(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def load_financial_discrepancies():
    if not os.path.exists(FINANCIAL_DISCREPANCIES_FILE):
        return []
    try:
        with open(FINANCIAL_DISCREPANCIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_financial_discrepancies(items):
    os.makedirs(os.path.dirname(FINANCIAL_DISCREPANCIES_FILE), exist_ok=True)
    with open(FINANCIAL_DISCREPANCIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def upsert_card_discrepancy_for_session(session_obj, reconciliation_summary):
    if not isinstance(session_obj, dict):
        return None
    if not isinstance(reconciliation_summary, dict):
        return None
    session_id = str(session_obj.get('id') or '').strip()
    if not session_id:
        return None
    amount = float(reconciliation_summary.get('difference') or 0.0)
    status = 'pending' if abs(amount) > 0.01 else 'approved'
    items = load_financial_discrepancies()
    payload = {
        'type': 'card',
        'source': 'reconciliation',
        'session_id': session_id,
        'amount': round(amount, 2),
        'status': status,
        'details': {
            'opened_at': session_obj.get('opened_at'),
            'closed_at': session_obj.get('closed_at'),
            'cashier_type': session_obj.get('type'),
            'closed_by': session_obj.get('closed_by') or session_obj.get('user'),
            'summary': reconciliation_summary
        },
        'updated_at': _now_str(),
    }
    existing = None
    for row in items:
        if str(row.get('type')) == 'card' and str(row.get('source')) == 'reconciliation' and str(row.get('session_id')) == session_id:
            existing = row
            break
    if existing:
        existing.update(payload)
        if status == 'pending':
            existing.pop('approved_at', None)
            existing.pop('approved_by', None)
        save_financial_discrepancies(items)
        return existing
    payload['created_at'] = _now_str()
    items.append(payload)
    save_financial_discrepancies(items)
    return payload


def list_card_discrepancies(start_date=None, end_date=None):
    rows = []
    for item in load_financial_discrepancies():
        if str(item.get('type')) != 'card':
            continue
        details = item.get('details') if isinstance(item.get('details'), dict) else {}
        dt = _parse_dt(details.get('closed_at')) or _parse_dt(item.get('updated_at')) or _parse_dt(item.get('created_at'))
        if start_date and dt and dt < start_date:
            continue
        if end_date and dt and dt > end_date:
            continue
        rows.append(item)
    return rows


def approve_card_discrepancy(session_id, approved_by=''):
    target = str(session_id or '').strip()
    if not target:
        return False
    items = load_financial_discrepancies()
    changed = False
    for item in items:
        if str(item.get('type')) == 'card' and str(item.get('session_id')) == target and str(item.get('status')) == 'pending':
            item['status'] = 'approved'
            item['approved_at'] = _now_str()
            item['approved_by'] = str(approved_by or '')
            item['updated_at'] = _now_str()
            changed = True
    if changed:
        save_financial_discrepancies(items)
    return changed


def approve_card_discrepancies_for_period(start_date, end_date, approved_by=''):
    updated = 0
    items = load_financial_discrepancies()
    for item in items:
        if str(item.get('type')) != 'card' or str(item.get('status')) != 'pending':
            continue
        details = item.get('details') if isinstance(item.get('details'), dict) else {}
        dt = _parse_dt(details.get('closed_at')) or _parse_dt(item.get('updated_at')) or _parse_dt(item.get('created_at'))
        if dt is None:
            continue
        if dt < start_date or dt > end_date:
            continue
        item['status'] = 'approved'
        item['approved_at'] = _now_str()
        item['approved_by'] = str(approved_by or '')
        item['updated_at'] = _now_str()
        updated += 1
    if updated > 0:
        save_financial_discrepancies(items)
    return updated
