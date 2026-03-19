from datetime import datetime
import threading
from app.services.card_reconciliation_service import fetch_pagseguro_transactions, reconcile_transactions, append_reconciliation_audit
from app.services.financial_discrepancy_service import upsert_card_discrepancy_for_session
from app.services.logger_service import log_system_action


def _parse_tx_datetime(raw_value):
    raw = str(raw_value or '').strip()
    if not raw:
        return None
    for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _is_card_payment_method(payment_method):
    method = str(payment_method or '').strip().lower()
    if not method:
        return False
    if 'dinheiro' in method or 'pix' in method:
        return False
    card_tokens = ['cartão', 'cartao', 'crédito', 'credito', 'débito', 'debito']
    return any(token in method for token in card_tokens)


def _update_reconciliation_status(session_id, status, summary=None):
    from app.services.cashier_service import CashierService
    sessions = CashierService.list_sessions()
    changed = False
    for row in sessions:
        if str(row.get('id')) != str(session_id):
            continue
        row['reconciliation_status'] = status
        row['reconciliation_summary'] = summary or {}
        changed = True
        break
    if changed:
        CashierService.persist_sessions(sessions, trigger_backup=False)


def _find_session(session_id):
    from app.services.cashier_service import CashierService
    for row in CashierService.list_sessions():
        if str(row.get('id')) == str(session_id):
            return row
    return None


def run_reconciliation_for_session(session_id):
    session_obj = _find_session(session_id)
    if not isinstance(session_obj, dict):
        return {'success': False, 'message': 'Sessão não encontrada.'}
    _update_reconciliation_status(session_id, 'processing', summary={'started_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')})
    try:
        opened_at = _parse_tx_datetime(session_obj.get('opened_at'))
        closed_at = _parse_tx_datetime(session_obj.get('closed_at'))
        if not opened_at or not closed_at:
            raise ValueError('Sessão sem período válido para reconciliação.')

        system_transactions = []
        for tx in session_obj.get('transactions', []) or []:
            if str(tx.get('type') or '').strip().lower() != 'sale':
                continue
            if not _is_card_payment_method(tx.get('payment_method')):
                continue
            tx_time = _parse_tx_datetime(tx.get('timestamp'))
            if not tx_time:
                continue
            if tx_time < opened_at or tx_time > closed_at:
                continue
            system_transactions.append({
                'id': tx.get('id'),
                'timestamp': tx_time,
                'amount': float(tx.get('amount', 0.0) or 0.0),
                'description': tx.get('description', ''),
                'payment_method': tx.get('payment_method', ''),
                'details': tx.get('details', {}),
            })

        card_transactions = fetch_pagseguro_transactions(opened_at, closed_at)
        results = reconcile_transactions(system_transactions, card_transactions)
        total_sistema_cartao = round(sum(float(t.get('amount', 0.0) or 0.0) for t in system_transactions), 2)
        total_pagseguro = round(sum(float(t.get('amount', 0.0) or 0.0) for t in card_transactions), 2)
        difference = round(total_sistema_cartao - total_pagseguro, 2)
        summary = {
            'period_start': opened_at.strftime('%Y-%m-%d %H:%M:%S'),
            'period_end': closed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'total_sistema_cartao': total_sistema_cartao,
            'total_pagseguro': total_pagseguro,
            'difference': difference,
            'matched_count': len(results.get('matched', [])),
            'unmatched_system_count': len(results.get('unmatched_system', [])),
            'unmatched_card_count': len(results.get('unmatched_card', [])),
            'transacoes_nao_conciliadas': {
                'sistema': results.get('unmatched_system', []),
                'pagseguro': results.get('unmatched_card', []),
            },
            'finished_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        }
        _update_reconciliation_status(session_id, 'done', summary=summary)
        refreshed = _find_session(session_id) or session_obj
        upsert_card_discrepancy_for_session(refreshed, summary)
        append_reconciliation_audit({
            'id': f"RECON_AUTO_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'source': 'cashier_auto_close',
            'provider': 'pagseguro',
            'period_start': opened_at.strftime('%Y-%m-%d %H:%M:%S'),
            'period_end': closed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'user': refreshed.get('closed_by') or refreshed.get('user') or 'Sistema',
            'summary': {
                'session_id': session_id,
                'matched_count': summary['matched_count'],
                'unmatched_system_count': summary['unmatched_system_count'],
                'unmatched_card_count': summary['unmatched_card_count'],
                'difference': difference
            },
            'results': results
        })
        log_system_action(
            'Conciliação automática do caixa',
            {
                'session_id': session_id,
                'status': 'done',
                'difference': difference,
                'matched_count': summary['matched_count'],
                'unmatched_system_count': summary['unmatched_system_count'],
                'unmatched_card_count': summary['unmatched_card_count'],
            },
            category='Financeiro'
        )
        return {'success': True, 'summary': summary}
    except Exception as exc:
        summary = {
            'error': str(exc),
            'failed_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        }
        _update_reconciliation_status(session_id, 'error', summary=summary)
        log_system_action(
            'Erro na conciliação automática do caixa',
            {
                'session_id': session_id,
                'status': 'error',
                'error': str(exc),
            },
            category='Financeiro'
        )
        return {'success': False, 'message': str(exc)}


def start_reconciliation_for_session_async(session_id):
    worker = threading.Thread(target=run_reconciliation_for_session, args=(session_id,))
    worker.daemon = True
    worker.start()
    return True
