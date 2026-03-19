import json
import os
import threading
from datetime import datetime, timedelta
from app.services.system_config_manager import get_data_path
from app.services.card_reconciliation_service import fetch_pagseguro_transactions_detailed, reconcile_transactions, load_card_consumption_map
from app.services.logger_service import log_system_action


PAGSEGURO_DAILY_PULL_FILE = get_data_path('pagseguro_daily_pull.json')
PAGSEGURO_DAILY_PULL_STATUS_FILE = get_data_path('pagseguro_daily_pull_status.json')
_PULL_LOCK = threading.Lock()


def _now_str():
    return datetime.now().strftime('%d/%m/%Y %H:%M:%S')


def _serialize(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def _parse_date_ref(value):
    if isinstance(value, datetime):
        return value.date()
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _normalize_system_method(method):
    text = str(method or '').strip().lower()
    if not text:
        return 'unknown'
    if 'pix' in text:
        return 'pix'
    if 'dinheiro' in text or 'espécie' in text or 'especie' in text:
        return 'cash'
    if 'débito' in text or 'debito' in text:
        return 'debit_card'
    if 'crédito' in text or 'credito' in text:
        return 'credit_card'
    if 'cartão' in text or 'cartao' in text:
        return 'card'
    return 'other'


def _normalize_pagseguro_method(tx):
    type_code = str((tx or {}).get('type') or '').strip()
    if type_code == '1':
        return 'card'
    return 'other'


def load_daily_pull_data():
    if not os.path.exists(PAGSEGURO_DAILY_PULL_FILE):
        return []
    try:
        with open(PAGSEGURO_DAILY_PULL_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
            return payload if isinstance(payload, list) else []
    except Exception:
        return []


def save_daily_pull_data(items):
    os.makedirs(os.path.dirname(PAGSEGURO_DAILY_PULL_FILE), exist_ok=True)
    with open(PAGSEGURO_DAILY_PULL_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def get_pull_status():
    if not os.path.exists(PAGSEGURO_DAILY_PULL_STATUS_FILE):
        return {
            'status': 'not_run',
            'last_run_at': '',
            'date_ref': '',
            'message': '',
            'pulled_count': 0,
            'error': '',
            'in_progress': False,
        }
    try:
        with open(PAGSEGURO_DAILY_PULL_STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {
        'status': 'not_run',
        'last_run_at': '',
        'date_ref': '',
        'message': '',
        'pulled_count': 0,
        'error': '',
        'in_progress': False,
    }


def save_pull_status(status_obj):
    payload = {
        'status': str(status_obj.get('status') or 'not_run'),
        'last_run_at': str(status_obj.get('last_run_at') or ''),
        'date_ref': str(status_obj.get('date_ref') or ''),
        'message': str(status_obj.get('message') or ''),
        'pulled_count': int(status_obj.get('pulled_count') or 0),
        'error': str(status_obj.get('error') or ''),
        'in_progress': bool(status_obj.get('in_progress')),
        'source': str(status_obj.get('source') or ''),
        'requested_by': str(status_obj.get('requested_by') or ''),
        'updated_at': _now_str(),
    }
    os.makedirs(os.path.dirname(PAGSEGURO_DAILY_PULL_STATUS_FILE), exist_ok=True)
    with open(PAGSEGURO_DAILY_PULL_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


def get_daily_snapshot(date_ref):
    target = _parse_date_ref(date_ref)
    if not target:
        return None
    target_key = target.strftime('%Y-%m-%d')
    for item in load_daily_pull_data():
        if str(item.get('date_ref') or '') == target_key:
            return item
    return None


def run_pagseguro_daily_pull(date_ref=None, source='scheduler', requested_by='sistema', force=False):
    target = _parse_date_ref(date_ref)
    if target is None:
        target = (datetime.now() - timedelta(days=1)).date()
    date_key = target.strftime('%Y-%m-%d')
    if not _PULL_LOCK.acquire(blocking=False):
        status = save_pull_status({
            'status': 'error',
            'last_run_at': _now_str(),
            'date_ref': date_key,
            'message': 'Execução concorrente bloqueada.',
            'pulled_count': 0,
            'error': 'PULL_ALREADY_RUNNING',
            'in_progress': False,
            'source': source,
            'requested_by': requested_by,
        })
        return {'success': False, 'status': status}
    try:
        existing = get_daily_snapshot(date_key)
        if existing and not force:
            status = save_pull_status({
                'status': 'success',
                'last_run_at': _now_str(),
                'date_ref': date_key,
                'message': 'Snapshot já existente para a data. Operação idempotente.',
                'pulled_count': int(existing.get('normalized_count') or 0),
                'error': '',
                'in_progress': False,
                'source': source,
                'requested_by': requested_by,
            })
            return {'success': True, 'idempotent': True, 'snapshot': existing, 'status': status}

        save_pull_status({
            'status': 'not_run',
            'last_run_at': _now_str(),
            'date_ref': date_key,
            'message': 'Processando pull diário PagSeguro.',
            'pulled_count': 0,
            'error': '',
            'in_progress': True,
            'source': source,
            'requested_by': requested_by,
        })
        start_dt = datetime(target.year, target.month, target.day, 0, 0, 0)
        end_dt = datetime(target.year, target.month, target.day, 23, 59, 59)
        detailed = fetch_pagseguro_transactions_detailed(start_dt, end_dt)
        raw_transactions = detailed.get('transactions', [])
        errors = detailed.get('errors', [])
        normalized = []
        for tx in raw_transactions:
            tx_dt = _parse_dt(tx.get('date'))
            normalized.append({
                'id': str((tx.get('original_row') or {}).get('code') or ''),
                'provider': tx.get('provider'),
                'timestamp': _serialize(tx_dt),
                'amount': round(float(tx.get('amount', 0.0) or 0.0), 2),
                'payment_method': _normalize_pagseguro_method(tx),
                'status': tx.get('status'),
                'type': tx.get('type'),
            })
        final_status = 'success'
        if errors and normalized:
            final_status = 'partial'
        elif errors and not normalized:
            final_status = 'error'
        snapshot = {
            'date_ref': date_key,
            'period_start': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'period_end': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'pulled_at': _now_str(),
            'source': str(source or ''),
            'requested_by': str(requested_by or ''),
            'pull_status': final_status,
            'raw_count': len(raw_transactions),
            'normalized_count': len(normalized),
            'account_total': int(detailed.get('total_accounts') or 0),
            'account_processed': int(detailed.get('processed_accounts') or 0),
            'account_errors': _serialize(errors),
            'raw_transactions': _serialize(raw_transactions),
            'normalized_transactions': normalized,
        }
        items = load_daily_pull_data()
        replaced = False
        for idx, row in enumerate(items):
            if str(row.get('date_ref') or '') == date_key:
                items[idx] = snapshot
                replaced = True
                break
        if not replaced:
            items.append(snapshot)
        items = sorted(items, key=lambda x: str(x.get('date_ref') or ''))[-45:]
        save_daily_pull_data(items)
        status = save_pull_status({
            'status': final_status,
            'last_run_at': _now_str(),
            'date_ref': date_key,
            'message': 'Pull diário PagSeguro concluído.',
            'pulled_count': len(normalized),
            'error': '; '.join(str(e.get('error') or '') for e in errors[:3]),
            'in_progress': False,
            'source': source,
            'requested_by': requested_by,
        })
        log_system_action(
            'Pull diário PagSeguro',
            {
                'date_ref': date_key,
                'source': source,
                'requested_by': requested_by,
                'status': final_status,
                'raw_count': len(raw_transactions),
                'normalized_count': len(normalized),
                'error_count': len(errors),
                'force': bool(force),
            },
            category='Financeiro'
        )
        return {'success': final_status in ('success', 'partial'), 'snapshot': snapshot, 'status': status}
    except Exception as exc:
        status = save_pull_status({
            'status': 'error',
            'last_run_at': _now_str(),
            'date_ref': date_key,
            'message': 'Falha no pull diário PagSeguro.',
            'pulled_count': 0,
            'error': str(exc),
            'in_progress': False,
            'source': source,
            'requested_by': requested_by,
        })
        log_system_action(
            'Falha no pull diário PagSeguro',
            {
                'date_ref': date_key,
                'source': source,
                'requested_by': requested_by,
                'error': str(exc),
            },
            category='Financeiro'
        )
        return {'success': False, 'status': status}
    finally:
        try:
            current = get_pull_status()
            if bool(current.get('in_progress')):
                current['in_progress'] = False
                save_pull_status(current)
        except Exception:
            pass
        _PULL_LOCK.release()


def ensure_previous_day_snapshot():
    target = (datetime.now() - timedelta(days=1)).date()
    existing = get_daily_snapshot(target)
    if existing:
        return existing
    result = run_pagseguro_daily_pull(date_ref=target, source='auto_missing', requested_by='sistema')
    return result.get('snapshot') if isinstance(result, dict) else None


def compare_session_with_daily_snapshot(session_obj, tolerance_mins=60, tolerance_val=0.05):
    if not isinstance(session_obj, dict):
        return {'status': 'error', 'message': 'Sessão inválida.'}
    closed_dt = _parse_dt(session_obj.get('closed_at'))
    opened_dt = _parse_dt(session_obj.get('opened_at'))
    if not opened_dt or not closed_dt:
        return {'status': 'error', 'message': 'Sessão sem período válido.'}
    snapshot = get_daily_snapshot(closed_dt.date())
    if not snapshot:
        return {
            'status': 'missing_snapshot',
            'date_ref': closed_dt.strftime('%Y-%m-%d'),
            'matched': [],
            'declared_not_found': [],
            'pagseguro_not_declared': [],
            'summary': {
                'total_sistema_cartao': 0.0,
                'total_pagseguro': 0.0,
                'difference': 0.0
            }
        }
    system_transactions = []
    for tx in session_obj.get('transactions', []) or []:
        if str(tx.get('type') or '').strip().lower() != 'sale':
            continue
        method = _normalize_system_method(tx.get('payment_method'))
        if method not in ('card', 'credit_card', 'debit_card'):
            continue
        tx_dt = _parse_dt(tx.get('timestamp'))
        if not tx_dt or tx_dt < opened_dt or tx_dt > closed_dt:
            continue
        system_transactions.append({
            'id': tx.get('id'),
            'timestamp': tx_dt,
            'amount': round(float(tx.get('amount', 0.0) or 0.0), 2),
            'description': tx.get('description', ''),
            'payment_method': method,
            'details': tx.get('details', {}),
            'user': tx.get('user', ''),
        })
    card_transactions = []
    for tx in snapshot.get('normalized_transactions', []) or []:
        tx_dt = _parse_dt(tx.get('timestamp'))
        if not tx_dt or tx_dt < opened_dt or tx_dt > closed_dt:
            continue
        if str(tx.get('payment_method') or '') != 'card':
            continue
        card_transactions.append({
            'id': tx.get('id'),
            'provider': tx.get('provider'),
            'date': tx_dt,
            'amount': round(float(tx.get('amount', 0.0) or 0.0), 2),
            'type': tx.get('type'),
            'status': tx.get('status'),
        })
    results = reconcile_transactions(
        system_transactions=system_transactions,
        card_transactions=card_transactions,
        tolerance_mins=tolerance_mins,
        tolerance_val=tolerance_val,
        consumption_map=load_card_consumption_map()
    )
    total_sistema = round(sum(float(tx.get('amount', 0.0) or 0.0) for tx in system_transactions), 2)
    total_pagseguro = round(sum(float(tx.get('amount', 0.0) or 0.0) for tx in card_transactions), 2)
    diff = round(total_sistema - total_pagseguro, 2)
    return {
        'status': 'ok',
        'date_ref': snapshot.get('date_ref'),
        'snapshot_meta': {
            'pulled_at': snapshot.get('pulled_at'),
            'raw_count': snapshot.get('raw_count'),
            'normalized_count': snapshot.get('normalized_count'),
            'pull_status': snapshot.get('pull_status')
        },
        'matched': _serialize(results.get('matched', [])),
        'declared_not_found': _serialize(results.get('unmatched_system', [])),
        'pagseguro_not_declared': _serialize(results.get('unmatched_card', [])),
        'summary': {
            'matched_count': len(results.get('matched', [])),
            'declared_not_found_count': len(results.get('unmatched_system', [])),
            'pagseguro_not_declared_count': len(results.get('unmatched_card', [])),
            'skipped_consumed_card_count': int(results.get('skipped_consumed_card_count') or 0),
            'total_sistema_cartao': total_sistema,
            'total_pagseguro': total_pagseguro,
            'difference': diff
        }
    }
