import os
import json
import io
import re
import threading
import calendar
import traceback
import zipfile
import xlsxwriter
import requests
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file, send_from_directory, Response, current_app
from werkzeug.utils import secure_filename
import pandas as pd
from PIL import Image

from . import finance_bp
from app.utils.decorators import login_required, role_required
from app.utils.files import allowed_file
from app.services.data_service import (
    load_users, load_table_orders, save_table_orders,
    load_room_charges, save_room_charges,
    load_suppliers, save_suppliers, load_payables, save_payables,
    load_fiscal_settings,
    load_stock_logs, load_stock_requests, load_stock_entries, load_products,
    load_payment_methods
)
from app.services.card_reconciliation_service import load_card_settings, save_card_settings
from app.services.cashier_service import CashierService
from app.services.commission_service import (
    normalize_dept,
    load_commission_cycles,
    save_commission_cycles,
    get_commission_cycle,
    calculate_commission,
    compute_month_total_commission_by_ranking,
    is_service_fee_removed_for_transaction,
)
from app.services.fiscal_service import (
    emit_invoice as service_emit_invoice,
    get_fiscal_integration,
    download_xml,
    process_pending_emissions
)
from app.services.fiscal_pool_service import FiscalPoolService
from app.services.printing_service import print_fiscal_receipt
from app.services.closed_account_service import ClosedAccountService
from app.services.logger_service import LoggerService, log_system_action
from app.services.security_service import check_sensitive_access
from app.services.import_sales import calculate_monthly_sales
from app.services.card_reconciliation_service import (
    fetch_pagseguro_transactions,
    fetch_pagseguro_transactions_detailed,
    reconcile_transactions, parse_pagseguro_csv,
    append_reconciliation_audit, load_reconciliation_audits,
    load_card_consumption_map, register_consumed_card_matches
)
from app.services.financial_discrepancy_service import (
    list_card_discrepancies,
    approve_card_discrepancy,
    approve_card_discrepancies_for_period,
)
from app.services.pagseguro_daily_pull_service import (
    run_pagseguro_daily_pull,
    compare_session_with_daily_snapshot,
    ensure_previous_day_snapshot,
    get_pull_status,
)


def _load_cashier_sessions():
    return CashierService.list_sessions()


def _normalize_pagseguro_configs(settings):
    configs = settings.get('pagseguro', [])
    if isinstance(configs, dict):
        return [configs]
    if isinstance(configs, list):
        return configs
    return []


def _mask_pagseguro_token(token):
    token_str = str(token or '').strip()
    if not token_str:
        return ''
    if len(token_str) <= 8:
        return '*' * len(token_str)
    return f"{token_str[:4]}{'*' * (len(token_str) - 8)}{token_str[-4:]}"


def _pagseguro_environment_label(config):
    sandbox = bool((config or {}).get('sandbox'))
    env = str((config or {}).get('environment') or '').strip().lower()
    if sandbox or env in {'sandbox', 'homolog', 'homologacao', 'homologation'}:
        return 'sandbox'
    return 'production'


def _pagseguro_health_badge(status):
    normalized = str(status or '').strip().lower()
    if normalized == 'ok':
        return ('success', 'OK')
    if normalized == 'error':
        return ('danger', 'Erro')
    return ('secondary', 'Não testado')


def _check_pagseguro_account_health(account, timeout_seconds=12):
    alias = str((account or {}).get('alias') or 'Conta')
    email = str((account or {}).get('email') or '').strip()
    token = str((account or {}).get('token') or '').strip()
    env = _pagseguro_environment_label(account)
    base_url = "https://ws.pagseguro.uol.com.br/v3/transactions"
    if env == 'sandbox':
        base_url = "https://ws.sandbox.pagseguro.uol.com.br/v3/transactions"
    now = datetime.now()
    tested_at = now.strftime('%d/%m/%Y %H:%M:%S')
    if not email or not token:
        return {
            'status': 'error',
            'tested_at': tested_at,
            'error_message': 'Credenciais incompletas (email/token).',
            'http_status': None
        }
    start_dt = now - timedelta(minutes=15)
    params = {
        'email': email,
        'token': token,
        'initialDate': start_dt.strftime('%Y-%m-%dT%H:%M'),
        'finalDate': now.strftime('%Y-%m-%dT%H:%M'),
        'maxPageResults': 1,
        'page': 1
    }
    try:
        response = requests.get(base_url, params=params, timeout=timeout_seconds)
        status_code = int(response.status_code)
        if status_code == 200:
            return {
                'status': 'ok',
                'tested_at': tested_at,
                'error_message': '',
                'http_status': status_code
            }
        if status_code in (401, 403):
            message = f'Falha de autorização na API PagSeguro (HTTP {status_code}).'
        else:
            message = f'API PagSeguro respondeu com erro (HTTP {status_code}).'
        return {
            'status': 'error',
            'tested_at': tested_at,
            'error_message': message,
            'http_status': status_code
        }
    except requests.RequestException as exc:
        return {
            'status': 'error',
            'tested_at': tested_at,
            'error_message': f'Falha de conectividade: {exc}',
            'http_status': None
        }


def _build_pagseguro_accounts_view(settings):
    accounts = _normalize_pagseguro_configs(settings)
    view_rows = []
    for idx, acc in enumerate(accounts):
        status = str(acc.get('health_status') or 'not_tested')
        badge_class, badge_label = _pagseguro_health_badge(status)
        view_rows.append({
            'index': idx,
            'alias': acc.get('alias') or f'Conta {idx + 1}',
            'email': acc.get('email') or '',
            'environment': _pagseguro_environment_label(acc),
            'token_masked': _mask_pagseguro_token(acc.get('token')),
            'status': status,
            'status_badge_class': badge_class,
            'status_badge_label': badge_label,
            'last_test_at': acc.get('last_test_at') or '',
            'last_error': acc.get('last_error') or '',
        })
    return view_rows


def _extract_pagseguro_alias(provider_name):
    text = str(provider_name or '')
    prefix = 'PagSeguro ('
    if text.startswith(prefix) and text.endswith(')'):
        return text[len(prefix):-1]
    return ''


def _serialize_reconciliation_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_reconciliation_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_reconciliation_value(v) for v in value]
    return value


def _extract_room_number_from_transaction(tx):
    details = tx.get('details') or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            details = {}
    room_number = details.get('room_number')
    if room_number:
        return str(room_number)
    description = str(tx.get('description') or '')
    match = re.search(r'quarto\s+(\d+)', description, re.IGNORECASE)
    if match:
        return match.group(1)
    return ''


def _extract_guest_name_from_transaction(tx):
    details = tx.get('details') or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            details = {}
    guest_name = details.get('guest_name')
    if guest_name:
        return str(guest_name)
    return ''


def _build_suspected_time_gap_matches(
    unmatched_system,
    unmatched_card,
    tolerance_val=0.05,
    min_gap_minutes=120,
    max_percent_diff=0.05
):
    suspects = []
    used_card_indexes = set()

    for sys_tx in unmatched_system:
        sys_time = sys_tx.get('timestamp')
        sys_amount = float(sys_tx.get('amount', 0.0) or 0.0)
        if not isinstance(sys_time, datetime):
            continue

        best_idx = -1
        best_gap = None
        for idx, card_tx in enumerate(unmatched_card):
            if idx in used_card_indexes:
                continue
            card_time = card_tx.get('date')
            if not isinstance(card_time, datetime):
                continue
            card_amount = float(card_tx.get('amount', 0.0) or 0.0)
            time_gap = abs((sys_time - card_time).total_seconds()) / 60
            amount_diff = abs(sys_amount - card_amount)
            amount_pct_diff = (amount_diff / sys_amount) if sys_amount > 0 else 0.0
            is_time_gap_case = amount_diff <= tolerance_val and time_gap > min_gap_minutes
            is_percent_case = amount_pct_diff <= max_percent_diff
            if not is_time_gap_case and not is_percent_case:
                continue
            if best_gap is None or time_gap < best_gap:
                best_gap = time_gap
                best_idx = idx

        if best_idx >= 0:
            used_card_indexes.add(best_idx)
            card_item = unmatched_card[best_idx]
            amount_diff = abs(sys_amount - float(card_item.get('amount', 0.0) or 0.0))
            amount_pct_diff = (amount_diff / sys_amount) if sys_amount > 0 else 0.0
            reason = 'Diferença de horário elevada'
            if amount_pct_diff <= max_percent_diff and amount_diff > tolerance_val:
                reason = 'Diferença de valor até 5%'
            approval_signature = f"{sys_tx.get('id','')}|{str(card_item.get('provider',''))}|{float(card_item.get('amount', 0.0) or 0.0):.2f}"
            suspects.append({
                'system': sys_tx,
                'card': card_item,
                'time_gap_minutes': int(best_gap or 0),
                'status': 'needs_admin_approval',
                'approval_signature': approval_signature,
                'reason': reason,
                'amount_diff': round(amount_diff, 2),
                'amount_diff_percent': round(amount_pct_diff * 100, 2)
            })

    return suspects


def _annotate_reconciliation_results(results, settings):
    configs = _normalize_pagseguro_configs(settings)
    aliases = [str(c.get('alias') or '').strip() for c in configs if str(c.get('alias') or '').strip()]
    primary_alias = aliases[0] if aliases else ''

    for item in results.get('matched', []):
        card = item.get('card', {}) or {}
        provider_name = str(card.get('provider', ''))
        alias = _extract_pagseguro_alias(provider_name)
        tags = []
        if alias and len(aliases) > 1 and primary_alias and alias != primary_alias:
            tags.append('Encontrado por outro token (sob confirmação)')
        if item.get('status') == 'matched_group':
            tags.append('Pagamento agrupado conciliado')
        if item.get('status') == 'manual_approved':
            tags.append('Aprovado manualmente pelo ADM')
        item['confirmation_tag'] = ' | '.join(tags) if tags else ''
        item['token_alias'] = alias
    return results


def _load_manual_approval_signatures():
    approvals = set()
    for entry in load_reconciliation_audits():
        if str(entry.get('source')) != 'manual_approval':
            continue
        results = entry.get('results') or {}
        signature = results.get('approval_signature')
        if signature:
            approvals.add(signature)
    return approvals


def _apply_manual_approved_suspects(results, suspected_matches, approved_signatures):
    remaining_suspects = []
    for suspect in suspected_matches:
        signature = suspect.get('approval_signature')
        if signature and signature in approved_signatures:
            manual_match = {
                'system': suspect.get('system'),
                'card': suspect.get('card'),
                'status': 'manual_approved',
                'approval_signature': signature
            }
            results.setdefault('matched', []).append(manual_match)
            if suspect.get('system') in results.get('unmatched_system', []):
                results['unmatched_system'].remove(suspect.get('system'))
            if suspect.get('card') in results.get('unmatched_card', []):
                results['unmatched_card'].remove(suspect.get('card'))
            continue
        remaining_suspects.append(suspect)
    return remaining_suspects


def _save_reconciliation_audit(source, provider, start_date, end_date, results, summary):
    entry = {
        'id': f"RECON_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'source': source,
        'provider': provider,
        'period_start': start_date,
        'period_end': end_date,
        'user': session.get('user'),
        'summary': summary,
        'results': _serialize_reconciliation_value(results)
    }
    append_reconciliation_audit(entry)


@finance_bp.route('/admin/reconciliation/approve', methods=['POST'])
@login_required
def finance_reconciliation_approve():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    provider = request.form.get('provider') or 'pagseguro'
    start_date = request.form.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.form.get('end_date') or start_date
    system_id = request.form.get('system_id')
    card_provider = request.form.get('card_provider')
    card_amount = request.form.get('card_amount')
    card_date = request.form.get('card_date')
    room_number = request.form.get('room_number')
    approved_reason = request.form.get('approved_reason') or 'Aprovação manual por intervalo de horário.'

    append_reconciliation_audit({
        'id': f"RECON_APPROVAL_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'source': 'manual_approval',
        'provider': provider,
        'period_start': start_date,
        'period_end': end_date,
        'user': session.get('user'),
        'summary': {'manual_approval': 1},
        'results': {
            'system_id': system_id,
            'room_number': room_number,
            'card_provider': card_provider,
            'card_amount': card_amount,
            'card_date': card_date,
            'approval_signature': request.form.get('approval_signature') or f"{system_id}|{card_provider}|{float(card_amount or 0):.2f}",
            'approved_reason': approved_reason
        }
    })

    flash('Conciliação marcada para aprovação administrativa.')
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/accounting/emission')
@login_required
def fiscal_emission_page():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
    return render_template('fiscal_emission.html')

@finance_bp.route('/api/fiscal/pool/list', methods=['GET'])
@login_required
def api_fiscal_pool_list():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    filters = {
        'status': request.args.get('status'),
        'date_start': request.args.get('date_start'),
        'date_end': request.args.get('date_end'),
        'fiscal_type': request.args.get('type') # nfce, nfse
    }
    
    # We load raw pool then filter
    pool = FiscalPoolService.get_pool(filters)
    
    # Additional filter for fiscal_type
    if filters['fiscal_type']:
        pool = [p for p in pool if p.get('fiscal_type') == filters['fiscal_type']]
        
    return jsonify(pool)

@finance_bp.route('/api/fiscal/pool/emit', methods=['POST'])
@login_required
def api_fiscal_pool_emit():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.json or {}
    entry_id = data.get('entry_id')
    cpf_cnpj = data.get('cpf_cnpj') # Optional override
    
    if not entry_id:
        return jsonify({'success': False, 'message': 'ID não fornecido'}), 400
        
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'message': 'Entrada não encontrada'}), 404
        
    if entry['status'] == 'emitted':
        return jsonify({'success': False, 'message': 'Nota já emitida'}), 400
        
    # Prepare Transaction
    # We use fiscal_amount as the total for the transaction
    # We might need to select specific items or proration?
    # For now, we pass the full item list and let 'queue_fiscal_emission' logic handle it?
    # Actually 'emit_invoice' takes items. 
    # If fiscal_amount < total_amount, we must adjust items or the emit_invoice logic must handle it.
    # The current 'emit_invoice' (service) calculates total from items.
    # So we should probably PRORATE items here before sending to 'emit_invoice'.
    
    try:
        # Load Settings
        settings = load_fiscal_settings()
        
        # Determine Integration
        target_cnpj = entry.get('cnpj_emitente')
        integration_settings = get_fiscal_integration(settings, target_cnpj)
        
        if not integration_settings:
            return jsonify({'success': False, 'message': 'Configuração fiscal não encontrada para este CNPJ'}), 400
            
        # Prorate Items if Partial
        items_to_emit = entry.get('items', [])
        fiscal_total = float(entry.get('fiscal_amount', 0.0))
        full_total = float(entry.get('total_amount', 0.0))
        
        if fiscal_total <= 0:
             return jsonify({'success': False, 'message': 'Valor fiscal é zero.'}), 400
             
        if full_total > 0 and fiscal_total < full_total:
            ratio = fiscal_total / full_total
            prorated_items = []
            for item in items_to_emit:
                new_item = item.copy()
                new_item['price'] = round(item['price'] * ratio, 2)
                prorated_items.append(new_item)
            items_to_emit = prorated_items
            
        # Determine Payment Method Name (Visual only for NFe usually, but good to match)
        pms = entry.get('payment_methods', [])
        # Find first fiscal method
        pm_name = 'Outros'
        for pm in pms:
            if pm.get('is_fiscal'):
                pm_name = pm.get('method')
                break
        
        transaction = {
            'id': entry['id'], # Use pool ID as transaction ID for tracking
            'amount': fiscal_total,
            'payment_method': pm_name
        }
        
        # Use CPF from request if provided, else from entry
        customer_doc = cpf_cnpj
        if not customer_doc:
            customer = entry.get('customer', {})
            customer_doc = customer.get('cpf_cnpj') or customer.get('doc')
            
        # Call Service
        # We need to import emit_invoice from service (aliased as service_emit_invoice)
        result = service_emit_invoice(transaction, integration_settings, items_to_emit, customer_doc)
        
        if result['success']:
            nfe_data = result['data']
            nfe_id = nfe_data.get('id')
            nfe_serie = nfe_data.get('serie')
            nfe_number = nfe_data.get('numero')
            
            # Update Pool Status
            FiscalPoolService.update_status(
                entry_id, 
                'emitted', 
                fiscal_doc_uuid=nfe_id, 
                serie=nfe_serie, 
                number=nfe_number,
                user=session.get('user')
            )
            
            # Try download XML
            try:
                download_xml(nfe_id, integration_settings)
            except: pass
            
            return jsonify({'success': True})
        else:
            # Update Error
            # We assume update_status can handle storing error? 
            # The current update_status only sets status. 
            # We might need a method to set error. 
            # Or we just set status 'failed' and note the error.
            # Let's modify update_status or add a set_error method in Service.
            # For now, let's misuse 'update_status' to set 'failed' and we need a way to save the error message.
            # FiscalPoolService structure has 'last_error' field?
            # I checked the code, it has 'notes' but not explicit 'last_error' in 'add_to_pool'.
            # I should update FiscalPoolService to support saving error.
            
            # Let's do a quick manual update for now or add 'notes'
            status_error = 'rejected' if 'rejei' in str(result.get('message') or '').lower() else 'manual_retry_required'
            FiscalPoolService.update_status(entry_id, status_error, error_msg=result['message'], user=session.get('user'))
            
            return jsonify({'success': False, 'message': result['message']})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@finance_bp.route('/api/fiscal/print', methods=['POST'])
@login_required
def api_fiscal_print():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.json or {}
    entry_id = data.get('entry_id')
    
    if not entry_id:
        return jsonify({'success': False, 'message': 'ID não fornecido'}), 400
        
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'message': 'Entrada não encontrada'}), 404
        
    if entry['status'] != 'emitted':
        return jsonify({'success': False, 'message': 'Nota não emitida ainda'}), 400
        
    # We need to construct the transaction-like object expected by print_fiscal_receipt
    # Or modify print_fiscal_receipt to accept entry.
    # print_fiscal_receipt expects: transaction_id (for loading data?), or a transaction object?
    # Actually, print_fiscal_receipt is in app.services.printing_service.
    # Let's import it first.
    
    try:
        from app.services.printing_service import print_fiscal_receipt
        
        # We need to pass enough info. 
        # print_fiscal_receipt usually takes (transaction_data, printer_id).
        # Let's check signature of print_fiscal_receipt.
        # Assuming it takes a transaction dict.
        
        # Reconstruct transaction for printing
        # The print function likely looks for 'fiscal_doc_uuid' or similar in the transaction data 
        # to find the XML/PDF.
        
        transaction = {
            'id': entry['id'],
            'fiscal_doc_uuid': entry.get('fiscal_doc_uuid'),
            'fiscal_serie': entry.get('fiscal_serie'),
            'fiscal_number': entry.get('fiscal_number'),
            'amount': entry.get('fiscal_amount'),
            'total_amount': entry.get('total_amount'),
            'items': entry.get('items'),
            'payment_method': 'NFC-e', # Display name
            'timestamp': entry.get('closed_at'),
            'customer': entry.get('customer')
        }
        
        # It handles printer lookup internally or we pass it?
        # Usually printing_service handles it.
        result = print_fiscal_receipt(transaction)
        
        if result:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Falha ao enviar para impressora'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@finance_bp.route('/api/fiscal/analyze_error', methods=['POST'])
@login_required
def api_fiscal_analyze_error():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.json or {}
    entry_id = data.get('entry_id')
    
    if not entry_id:
        return jsonify({'success': False, 'message': 'ID não fornecido'}), 400
        
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'message': 'Entrada não encontrada'}), 404
        
    error_message = entry.get('last_error') or "Erro desconhecido"
    
    # Prepare Context Data (strip unnecessary heavy fields)
    context = {
        "items": entry.get('items'),
        "total": entry.get('total_amount'),
        "fiscal_total": entry.get('fiscal_amount'),
        "payments": entry.get('payment_methods'),
        "customer": entry.get('customer'),
        "origin": entry.get('origin')
    }
    
    try:
        from app.services.fiscal_ai_service import FiscalAIAnalysisService
        result = FiscalAIAnalysisService.analyze_error(entry_id, error_message, context)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- Helpers ---

def _resolve_period_range(period_type, year, specific_value=None):
    year = int(year)
    if period_type == 'monthly':
        month = int(specific_value)
        _, last_day = calendar.monthrange(year, month)
        return datetime(year, month, 1), datetime(year, month, last_day, 23, 59, 59)
    if period_type == 'quarterly':
        quarter = int(specific_value)
        start_month = 3 * (quarter - 1) + 1
        end_month = 3 * quarter
        _, last_day = calendar.monthrange(year, end_month)
        return datetime(year, start_month, 1), datetime(year, end_month, last_day, 23, 59, 59)
    if period_type == 'semiannual':
        semester = int(specific_value)
        start_month = 6 * (semester - 1) + 1
        end_month = 6 * semester
        _, last_day = calendar.monthrange(year, end_month)
        return datetime(year, start_month, 1), datetime(year, end_month, last_day, 23, 59, 59)
    if period_type == 'annual':
        return datetime(year, 1, 1), datetime(year, 12, 31, 23, 59, 59)
    raise ValueError('Invalid period')


def _build_daily_pull_comparison_for_session(session_obj):
    if not isinstance(session_obj, dict):
        return {'status': 'error', 'message': 'Sessão inválida'}
    return compare_session_with_daily_snapshot(session_obj)

def get_balance_data(period_type, year, specific_value=None, user_filter=None, payment_method_filter=None):
    sessions = _load_cashier_sessions()
    closed_sessions = [s for s in sessions if s.get('status') == 'closed']
    user_filter_norm = str(user_filter or '').strip().lower()
    payment_filter_norm = str(payment_method_filter or '').strip().lower()
    
    # Determine Date Range
    start_date = None
    end_date = None
    
    try:
        year = int(year)
        start_date, end_date = _resolve_period_range(period_type, year, specific_value)
    except (ValueError, TypeError):
        return {} # Return empty if invalid dates

    # Filter Sessions
    filtered_sessions = []
    for s in closed_sessions:
        try:
            closed_at_str = s.get('closed_at')
            if not closed_at_str: continue
            closed_at = datetime.strptime(closed_at_str, '%d/%m/%Y %H:%M')
            if not (start_date <= closed_at <= end_date):
                continue
            if user_filter_norm:
                session_user = str(s.get('user') or s.get('closed_by') or '').strip().lower()
                if session_user != user_filter_norm:
                    continue
            if payment_filter_norm:
                txs = s.get('transactions') or []
                if not any(str((tx or {}).get('payment_method') or '').strip().lower() == payment_filter_norm for tx in txs):
                    continue
            filtered_sessions.append(s)
        except (ValueError, TypeError):
            continue
            
    report = {}
    types = {
        'restaurant_service': 'Restaurante',
        'reception_room_billing': 'Recepção (Quartos)',
        'reception_reservations': 'Recepção (Reservas)',
        'reservation_cashier': 'Recepção (Reservas)',
        'guest_consumption': 'Consumo de Hóspedes Restaurante'
    }
    
    for s in filtered_sessions:
        s_type = s.get('type', 'restaurant_service')
        if s_type == 'restaurant':
            s_type = 'restaurant_service'
        if s_type == 'reception':
            s_type = 'reception_room_billing'
        
        label = types.get(s_type, s_type.replace('_', ' ').title())
        
        if label not in report:
            report[label] = {
                'type_key': s_type,
                'initial_balance': 0.0,
                'total_in': 0.0,      # total de todas as entradas (todas as formas)
                'received_in': 0.0,   # recebido no caixa (dinheiro, cartão, pix)
                'transferred_in': 0.0,# transferido (quarto, crédito)
                'total_out': 0.0,     # total de todas as saídas (todas as formas)
                'cash_total_in': 0.0, # entradas apenas em dinheiro
                'cash_total_out': 0.0,# saídas apenas em dinheiro
                'final_balance': 0.0,
                'sessions_count': 0,
                'sessions': []
            }
        
        report[label]['sessions'].append(s)

    for label, data in report.items():
        original_sessions = list(data['sessions'])
        data['sessions'].sort(key=lambda x: datetime.strptime(x.get('closed_at'), '%d/%m/%Y %H:%M'))
        
        if data['sessions']:
            first_session = data['sessions'][0]
            try:
                data['initial_balance'] = float(first_session.get('opening_balance') or first_session.get('initial_balance') or 0.0)
            except:
                data['initial_balance'] = 0.0
            
            last_session = data['sessions'][-1]
            try:
                data['final_balance'] = float(last_session.get('closing_balance', 0.0))
            except:
                data['final_balance'] = 0.0
            
            for s in data['sessions']:
                session_transactions = s.get('transactions', []) or []
                if payment_filter_norm:
                    session_transactions = [
                        t for t in session_transactions
                        if str((t or {}).get('payment_method') or '').strip().lower() == payment_filter_norm
                    ]
                s['_balances_filtered_transactions_count'] = len(session_transactions)
                for t in session_transactions:
                    try:
                        amount = float(t.get('amount', 0.0) or 0.0)
                    except:
                        amount = 0.0
                    
                    t_type = str(t.get('type', '')).strip().lower()
                    method = str(t.get('payment_method', '')).strip().lower()
                    
                    is_cash = False
                    if 'dinheiro' in method or 'espécie' in method or 'especie' in method:
                        is_cash = True
                    elif t_type in ['supply', 'suprimento', 'bleeding', 'sangria']:
                        is_cash = True
                    elif 'transfer' in method or 'transferência' in method or 'transferencia' in method:
                        is_cash = True

                    # Totais gerais (todas as formas de pagamento)
                    is_received = True
                    if 'room' in method or 'quarto' in method or 'credito' in method:
                        is_received = False
                        
                    if t_type in ['out', 'withdrawal', 'refund']:
                        data['total_out'] += abs(amount)
                    elif t_type in ['in', 'deposit', 'sale']:
                        if amount >= 0:
                            data['total_in'] += abs(amount)
                            if is_received:
                                data['received_in'] += abs(amount)
                            else:
                                data['transferred_in'] += abs(amount)
                        else:
                            data['total_out'] += abs(amount)
                    else:
                        if amount >= 0:
                            data['total_in'] += abs(amount)
                            if is_received:
                                data['received_in'] += abs(amount)
                            else:
                                data['transferred_in'] += abs(amount)
                        else:
                            data['total_out'] += abs(amount)

                    # Totais apenas em dinheiro (para cálculo de saldo esperado em espécie)
                    if not is_cash:
                        continue
                    
                    if t_type in ['out', 'withdrawal', 'refund']:
                        data['cash_total_out'] += abs(amount)
                    elif t_type in ['in', 'deposit', 'sale']:
                        if amount >= 0:
                            data['cash_total_in'] += abs(amount)
                        else:
                            data['cash_total_out'] += abs(amount)
                    else:
                        if amount >= 0:
                            data['cash_total_in'] += abs(amount)
                        else:
                            data['cash_total_out'] += abs(amount)
                        
            data['sessions_count'] = len(data['sessions'])
            
            for s in data['sessions']:
                s['continuity_issue'] = False
            
            for idx in range(1, len(data['sessions'])):
                current_session = data['sessions'][idx]
                prev_session = data['sessions'][idx - 1]
                try:
                    prev_close_str = prev_session.get('closed_at')
                    next_open_str = current_session.get('opened_at')
                    if prev_close_str and next_open_str:
                        prev_close = datetime.strptime(prev_close_str, '%d/%m/%Y %H:%M')
                        next_open = datetime.strptime(next_open_str, '%d/%m/%Y %H:%M')
                        prev_close_date = prev_close.date()
                        next_open_date = next_open.date()
                        prev_closing_balance = float(prev_session.get('closing_balance') or 0.0)
                        next_opening_balance = float(current_session.get('opening_balance') or 0.0)
                        if prev_closing_balance > 0.01 and prev_close_date != next_open_date:
                            if abs(prev_closing_balance - next_opening_balance) > 0.01:
                                current_session['continuity_issue'] = True
                except:
                    continue
            
            has_unapproved = False
            for s in original_sessions:
                try:
                    session_diff = float(s.get('difference', 0.0) or 0.0)
                except:
                    session_diff = 0.0
                approved = bool(s.get('difference_approved'))
                if abs(session_diff) > 0.01 and not approved:
                    has_unapproved = True
                    break
            
            simple_sessions = []
            for s in data['sessions']:
                transactions_count = int(s.get('_balances_filtered_transactions_count', 0))
                try:
                    session_diff = float(s.get('difference', 0.0) or 0.0)
                except:
                    session_diff = 0.0
                simple_sessions.append({
                    'id': s.get('id'),
                    'opened_at': s.get('opened_at'),
                    'closed_at': s.get('closed_at'),
                    'user': s.get('user'),
                    'opening_balance': s.get('opening_balance'),
                    'closing_balance': s.get('closing_balance'),
                    'closing_cash': s.get('closing_cash'),
                    'closing_non_cash': s.get('closing_non_cash'),
                    'transactions_count': transactions_count,
                    'difference': session_diff,
                    'difference_approved': bool(s.get('difference_approved')),
                    'continuity_issue': bool(s.get('continuity_issue'))
                })
            data['sessions'] = simple_sessions
            
            try:
                # Usa apenas movimentação em dinheiro para cálculo de saldo esperado
                cash_in = data.get('cash_total_in', data['total_in'])
                cash_out = data.get('cash_total_out', data['total_out'])
                calculated_final = data['initial_balance'] + cash_in - cash_out
                data['calculated_final'] = calculated_final
                # Diferença de caixa (somente dinheiro): usar closing_cash da última sessão se disponível
                try:
                    last_simple_session = data['sessions'][-1] if data.get('sessions') else None
                    final_cash = float(last_simple_session.get('closing_cash', 0.0)) if last_simple_session else 0.0
                except Exception:
                    final_cash = 0.0
                difference = final_cash - calculated_final
                data['difference'] = difference
                data['has_anomaly'] = has_unapproved
                data['has_approved_divergence'] = abs(difference) > 0.01 and not has_unapproved
                data['has_continuity_issue'] = any(s.get('continuity_issue') for s in simple_sessions)
            except:
                data['calculated_final'] = data.get('final_balance', 0.0)
                data['difference'] = 0.0
                data['has_anomaly'] = has_unapproved
                data['has_approved_divergence'] = False
                data['has_continuity_issue'] = any(s.get('continuity_issue') for s in simple_sessions)

    card_discrepancies = list_card_discrepancies(start_date=start_date, end_date=end_date)
    if card_discrepancies:
        sessions = []
        pending_found = False
        approved_found = False
        total_amount = 0.0
        for row in card_discrepancies:
            amount = float(row.get('amount') or 0.0)
            total_amount += amount
            is_pending = str(row.get('status') or '').lower() == 'pending'
            if is_pending:
                pending_found = True
            if str(row.get('status') or '').lower() == 'approved':
                approved_found = True
            details = row.get('details') if isinstance(row.get('details'), dict) else {}
            sessions.append({
                'id': row.get('session_id'),
                'opened_at': details.get('opened_at'),
                'closed_at': details.get('closed_at'),
                'user': details.get('closed_by'),
                'opening_balance': 0.0,
                'closing_balance': 0.0,
                'closing_cash': 0.0,
                'closing_non_cash': 0.0,
                'transactions_count': 0,
                'difference': amount,
                'difference_approved': not is_pending,
                'continuity_issue': False,
                'difference_label': 'Diferença de cartão (sistema x PagSeguro)'
            })
        report['Divergência Cartão'] = {
            'type_key': 'card_discrepancy',
            'initial_balance': 0.0,
            'total_in': 0.0,
            'received_in': 0.0,
            'transferred_in': 0.0,
            'total_out': 0.0,
            'final_balance': round(total_amount, 2),
            'sessions_count': len(sessions),
            'sessions': sessions,
            'calculated_final': 0.0,
            'difference': round(total_amount, 2),
            'has_anomaly': pending_found,
            'has_approved_divergence': approved_found and not pending_found,
            'has_continuity_issue': False,
            'difference_label': 'Diferença de cartão (sistema x PagSeguro)'
        }

    return report

def parse_currency(value):
    if not value: return 0.0
    if isinstance(value, (int, float)): return float(value)
    val_str = str(value).strip()
    
    if ',' in val_str:
        # PT-BR format: 1.234,56
        clean = val_str.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
    else:
        # US format or clean: 1234.56
        clean = val_str.replace('R$', '').replace(' ', '')
        
    try:
        return float(clean)
    except:
        return 0.0

def load_employee_consumption():
    try:
        users = load_users()
        user_map = {}
        for uname, udata in users.items():
            full_name = udata.get('full_name') or udata.get('name') or uname
            user_map[uname] = full_name

        orders = load_table_orders()

        consumption = {}
        for order in orders.values():
            if order.get('customer_type') == 'funcionario' and order.get('status') in ['open', 'locked']:
                staff_name = order.get('staff_name')
                if staff_name:
                    resolved_name = user_map.get(staff_name, staff_name)
                    try:
                        subtotal = float(order.get('total', 0) or 0)
                    except Exception:
                        subtotal = 0.0
                    discounted_total = subtotal * 0.80
                    already_paid = float(order.get('total_paid', 0) or 0)
                    outstanding = max(0.0, discounted_total - already_paid)
                    consumption[resolved_name] = consumption.get(resolved_name, 0) + outstanding
        return consumption
    except Exception as e:
        print(f"Error loading consumption: {e}")
        return {}

def update_cycle_from_form(cycle, form_data):
    """Updates the cycle dictionary with data from the form submission."""
    try:
        raw_total = form_data.get('total_commission', 0)
        form_total_commission = parse_currency(raw_total)
        
        if form_total_commission == 0:
            # Try to auto-calculate if zero (user might want refresh or first calc)
            try:
                 total_sales = calculate_monthly_sales(cycle['month'])
                 cycle['total_commission'] = total_sales * 0.10
            except:
                 pass # Keep as 0 or previous if any
        else:
            cycle['total_commission'] = form_total_commission

        cycle['total_bonus'] = parse_currency(form_data.get('total_bonus', 0))
        cycle['card_percent'] = float(form_data.get('card_percent', 0.8))
        cycle['extras'] = parse_currency(form_data.get('extras', 0))
        
        # New Tax Fields
        cycle['commission_tax_percent'] = float(form_data.get('commission_tax_percent', 12))
        cycle['bonus_tax_percent'] = float(form_data.get('bonus_tax_percent', 12))
        
        # Update Dept Bonuses
        for d in cycle.get('department_bonuses', []):
            d_name = d['name']
            val = form_data.get(f'dept_bonus_{d_name}', 0)
            d['value'] = parse_currency(val)
        
        # Update Employees
        new_employees = []
        employees_json = form_data.get('employees_json')
        
        # Load Consumption Data
        consumption_map = load_employee_consumption()
        
        if employees_json:
            print("DEBUG: Loading from employees_json")
            cycle['employees'] = json.loads(employees_json)
            # Clean employee data
            for e in cycle['employees']:
                e['days_worked'] = parse_currency(e.get('days_worked'))
                e['individual_bonus'] = parse_currency(e.get('individual_bonus'))
                e['individual_deduction'] = parse_currency(e.get('individual_deduction'))
                e['consumption'] = consumption_map.get(e['name'], 0.0)
        else:
            # Fallback: Read from form arrays
            names = form_data.getlist('emp_name') + form_data.getlist('emp_name[]')
            depts = form_data.getlist('emp_dept') + form_data.getlist('emp_dept[]')
            roles = form_data.getlist('emp_role') + form_data.getlist('emp_role[]')
            points = form_data.getlist('emp_points') + form_data.getlist('emp_points[]')
            days = form_data.getlist('emp_days') + form_data.getlist('emp_days[]')
            bonuses = form_data.getlist('emp_bonus') + form_data.getlist('emp_bonus[]')
            deductions = form_data.getlist('emp_deduction') + form_data.getlist('emp_deduction[]')
            
            if names:
                for i in range(len(names)):
                    def get_val(lst, idx, default=''):
                        return lst[idx] if idx < len(lst) else default

                    emp = {
                        'name': names[i],
                        'department': get_val(depts, i),
                        'role': get_val(roles, i),
                        'points': parse_currency(get_val(points, i, 0)),
                        'days_worked': parse_currency(get_val(days, i, 0)),
                        'individual_bonus': parse_currency(get_val(bonuses, i, 0)),
                        'individual_deduction': parse_currency(get_val(deductions, i, 0)),
                        'consumption': consumption_map.get(names[i], 0.0)
                    }
                    new_employees.append(emp)
                
                cycle['employees'] = new_employees
            else:
                flash("Aviso: Nenhum funcionário encontrado no formulário.")
                
    except Exception as e:
        print(f"Error updating cycle from form: {e}")
        traceback.print_exc()
        flash(f"Erro ao processar formulário: {str(e)}")
        raise e

def find_col(cols, candidates):
    lc = [str(c).lower().strip() for c in cols]
    for cand in candidates:
        c = cand.lower()
        if c in lc:
            return cols[lc.index(c)]
    # Tentar match parcial
    for cand in candidates:
        c = cand.lower()
        for i, col in enumerate(lc):
            if c in col:
                return cols[i]
    return None

def get_staff_consumption_for_period(start_date, end_date):
    sessions = _load_cashier_sessions()
    consumption = {} # {'username': amount}
    
    start_dt = start_date.replace(hour=0, minute=0, second=0)
    end_dt = end_date.replace(hour=23, minute=59, second=59)

    for s in sessions:
        for t in s.get('transactions', []):
            if t.get('payment_method') == 'Conta Funcionário':
                try:
                    t_dt = datetime.strptime(t['timestamp'], '%d/%m/%Y %H:%M')
                    if start_dt <= t_dt <= end_dt:
                        staff = t.get('staff_name')
                        if staff:
                            consumption[staff] = consumption.get(staff, 0) + float(t['amount'])
                except:
                    pass
    return consumption

# --- Routes ---

@finance_bp.route('/finance/cashier_reports')
@login_required
@role_required(['admin', 'gerente'])
def finance_cashier_reports():
    # Get Filter Parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    department_filter = request.args.get('department', 'all')
    
    # Format dates for Service (dd/mm/yyyy)
    svc_start = None
    svc_end = None
    try:
        if start_date_str:
            svc_start = datetime.strptime(start_date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        if end_date_str:
            svc_end = datetime.strptime(end_date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        pass
    
    # Get History
    history = CashierService.get_history(start_date=svc_start, end_date=svc_end)
    
    # Filter by department if needed
    if department_filter != 'all':
        target_type = None
        if department_filter == 'restaurant_service': target_type = 'restaurant'
        elif department_filter == 'reception_room_billing': target_type = 'guest_consumption'
        elif department_filter == 'reception_reservations': target_type = 'daily_rates'
        else: target_type = department_filter
        
        history = [s for s in history if s.get('type') == target_type or (target_type == 'guest_consumption' and s.get('type') == 'reception_room_billing')]

    # Separate by department for template compatibility or unified view
    restaurant_service_sessions = []
    reception_room_billing_sessions = []
    reception_reservations_sessions = []
    
    for s in history:
        # Calculate totals if missing
        if 'total_in' not in s:
            s['total_in'] = sum(t['amount'] for t in s.get('transactions', []) if t.get('amount', 0) >= 0)
        if 'total_out' not in s:
            s['total_out'] = abs(sum(t['amount'] for t in s.get('transactions', []) if t.get('amount', 0) < 0))
            
        # Ensure opening/closing balance
        if 'opening_balance' not in s: s['opening_balance'] = s.get('initial_balance', 0.0)
        if 'closing_balance' not in s: s['closing_balance'] = 0.0
            
        stype = s.get('type')
        if stype == 'restaurant':
            restaurant_service_sessions.append(s)
        elif stype in ['guest_consumption', 'reception_room_billing']:
            reception_room_billing_sessions.append(s)
        elif stype == 'daily_rates':
            reception_reservations_sessions.append(s)
            
    # Get Current Status Summary
    status_summary = {
        'restaurant': CashierService.get_current_status('restaurant'),
        'guest_consumption': CashierService.get_current_status('guest_consumption'),
        'daily_rates': CashierService.get_current_status('daily_rates')
    }
            
    return render_template('finance_cashier_reports.html', 
                           restaurant_service_sessions=restaurant_service_sessions,
                           reception_room_billing_sessions=reception_room_billing_sessions,
                           reception_reservations_sessions=reception_reservations_sessions,
                           status_summary=status_summary,
                           filters={
                               'start_date': start_date_str, 
                               'end_date': end_date_str, 
                               'department': department_filter
                           })

@finance_bp.route('/finance/balances')
@login_required
def finance_balances():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    users_map = load_users() or {}
    users_for_filter = []
    if isinstance(users_map, dict):
        for username, data in users_map.items():
            if not isinstance(data, dict):
                continue
            users_for_filter.append({
                'username': username,
                'name': data.get('full_name') or data.get('name') or username
            })
    users_for_filter.sort(key=lambda u: str(u.get('name') or '').lower())
    payment_methods = load_payment_methods() or []
    return render_template('finance_balances.html', users=users_for_filter, payment_methods=payment_methods)

def _ensure_admin_finance_balances_access():
    role_value = str(session.get('role') or '').strip().lower()
    permissions_value = session.get('permissions')
    permissions = permissions_value if isinstance(permissions_value, list) else []
    permissions_norm = {str(item or '').strip().lower() for item in permissions}
    if role_value in {'admin', 'administracao_sistema'} or 'administracao_sistema' in permissions_norm:
        return None
    from app.services.permission_service import build_authorization_required_response
    return build_authorization_required_response(
        route_key=str(request.endpoint or 'finance.finance_balances'),
        module_key='finance',
        sensitivity='financeiro_critico',
        message='Você não possui acesso a esta área',
        context={'path': request.path, 'target': 'finance_balances'},
        status_code=403,
    )

@finance_bp.route('/api/finance/session/<session_id>', methods=['GET'])
@login_required
def api_finance_session_details(session_id):
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    session_data = CashierService.get_session_details(session_id)
    if not session_data:
        return jsonify({'success': False, 'message': 'Sessão não encontrada'}), 404
    comparison = _build_daily_pull_comparison_for_session(session_data)
    payload = dict(session_data)
    payload['card_comparison'] = comparison
    return jsonify({'success': True, 'data': payload})

@finance_bp.route('/api/finance/session/<session_id>/approve_divergence', methods=['POST'])
@login_required
def api_finance_session_approve_divergence(session_id):
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    
    sessions = _load_cashier_sessions()
    updated = False
    for s in sessions:
        if s.get('id') == session_id and s.get('status') == 'closed':
            s['difference_approved'] = True
            updated = True
            break
    card_updated = approve_card_discrepancy(session_id, approved_by=session.get('user'))
    if updated:
        CashierService.persist_sessions(sessions, trigger_backup=False)
    if updated or card_updated:
        log_system_action(
            'Aprovação de divergência financeira',
            {
                'session_id': session_id,
                'cash_divergence_approved': bool(updated),
                'card_divergence_approved': bool(card_updated),
                'approved_by': session.get('user')
            },
            category='Financeiro'
        )
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Sessão não encontrada'}), 404

@finance_bp.route('/api/finance/balances/approve_divergences', methods=['POST'])
@login_required
def api_finance_approve_divergences():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    
    payload = request.json or {}
    period_type = payload.get('period_type', 'monthly')
    year = payload.get('year')
    specific_value = payload.get('specific_value')
    type_key = payload.get('type_key')
    
    if not year or (period_type != 'annual' and not specific_value) or not type_key:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos'}), 400
    
    try:
        start_date, end_date = _resolve_period_range(period_type, year, specific_value)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Período inválido'}), 400
    
    if type_key == 'card_discrepancy':
        updated = approve_card_discrepancies_for_period(start_date, end_date, approved_by=session.get('user'))
        if updated > 0:
            log_system_action(
                'Aprovação de divergências de cartão',
                {
                    'period_type': period_type,
                    'year': year,
                    'specific_value': specific_value,
                    'updated_discrepancies': updated,
                    'approved_by': session.get('user')
                },
                category='Financeiro'
            )
        return jsonify({'success': True, 'updated_sessions': updated})

    sessions = _load_cashier_sessions()
    closed_sessions = [s for s in sessions if s.get('status') == 'closed']
    
    updated = 0
    for s in closed_sessions:
        s_closed_at = s.get('closed_at')
        if not s_closed_at:
            continue
        try:
            closed_at = datetime.strptime(s_closed_at, '%d/%m/%Y %H:%M')
        except (ValueError, TypeError):
            continue
        if not (start_date <= closed_at <= end_date):
            continue
        
        s_type = s.get('type')
        if s_type == 'restaurant':
            s_type_norm = 'restaurant_service'
        elif s_type == 'reception':
            s_type_norm = 'reception_room_billing'
        else:
            s_type_norm = s_type
        
        if s_type_norm != type_key:
            continue
        
        try:
            diff = float(s.get('difference', 0.0) or 0.0)
        except:
            diff = 0.0
        
        if abs(diff) > 0.01 and not s.get('difference_approved'):
            s['difference_approved'] = True
            updated += 1
    
    if updated > 0:
        CashierService.persist_sessions(sessions, trigger_backup=False)
        log_system_action(
            'Aprovação de divergências de caixa',
            {
                'period_type': period_type,
                'year': year,
                'specific_value': specific_value,
                'type_key': type_key,
                'updated_sessions': updated,
                'approved_by': session.get('user')
            },
            category='Financeiro'
        )
    
    return jsonify({'success': True, 'updated_sessions': updated})

@finance_bp.route('/finance/balances/data')
@login_required
def finance_balances_data():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    period_type = request.args.get('period_type', 'monthly')
    year = request.args.get('year', datetime.now().year)
    specific_value = request.args.get('specific_value', datetime.now().month)
    user_filter = request.args.get('user_filter')
    payment_method_filter = request.args.get('payment_method_filter')
    try:
        worker = threading.Thread(target=ensure_previous_day_snapshot)
        worker.daemon = True
        worker.start()
    except Exception:
        pass
    
    report = get_balance_data(
        period_type,
        year,
        specific_value,
        user_filter=user_filter,
        payment_method_filter=payment_method_filter
    )
    
    data_list = []
    for label, values in report.items():
        data_list.append({
            'type_label': label,
            'user': label,
            'initial_balance': values['initial_balance'],
            'total_in': values['total_in'],
            'received_in': values.get('received_in', 0.0),
            'transferred_in': values.get('transferred_in', 0.0),
            'total_out': values['total_out'],
            'final_balance': values['final_balance'],
            'calculated_final': values.get('calculated_final', values.get('final_balance', 0.0)),
            'difference': values.get('difference', 0.0),
            'has_anomaly': values.get('has_anomaly', False),
            'has_approved_divergence': values.get('has_approved_divergence', False),
            'has_continuity_issue': values.get('has_continuity_issue', False),
            'type_key': values.get('type_key'),
            'difference_label': values.get('difference_label'),
            'sessions': values.get('sessions', [])
        })
        
    return jsonify({'success': True, 'data': data_list})

@finance_bp.route('/finance/balances/export')
@login_required
def finance_balances_export():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    period_type = request.args.get('period_type')
    year = request.args.get('year')
    specific_value = request.args.get('specific_value')
    user_filter = request.args.get('user_filter')
    payment_method_filter = request.args.get('payment_method_filter')
    
    data = get_balance_data(
        period_type,
        year,
        specific_value,
        user_filter=user_filter,
        payment_method_filter=payment_method_filter
    )
    
    # Create Excel
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('Balanço')
    
    # Headers
    headers = ['Caixa', 'Saldo Inicial', 'Entradas', 'Saídas', 'Saldo Final', 'Sessões']
    bold = workbook.add_format({'bold': True})
    money = workbook.add_format({'num_format': 'R$ #,##0.00'})
    
    for col, h in enumerate(headers):
        worksheet.write(0, col, h, bold)
        
    row = 1
    for caixa, values in data.items():
        worksheet.write(row, 0, caixa)
        worksheet.write(row, 1, values['initial_balance'], money)
        worksheet.write(row, 2, values['total_in'], money)
        worksheet.write(row, 3, values['total_out'], money)
        worksheet.write(row, 4, values['final_balance'], money)
        worksheet.write(row, 5, values['sessions_count'])
        row += 1
        
    workbook.close()
    output.seek(0)
    
    filename = f"balanco_{period_type}_{year}_{specific_value}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)

@finance_bp.route('/api/closed_accounts', methods=['GET'])
@login_required
def api_closed_accounts():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=20, type=int)
    origin = str(request.args.get('origin') or '').strip()
    filters = {}
    if origin:
        filters['origin'] = origin
    result = ClosedAccountService.search_closed_accounts(filters=filters, page=page, per_page=per_page)
    sessions = CashierService.list_sessions()
    room_charges = load_room_charges()
    items = []
    for acc in result.get('items', []):
        row = dict(acc or {})
        row['closed_at'] = row.get('closed_at') or row.get('timestamp')
        row['closed_by'] = row.get('closed_by') or row.get('user') or '-'
        row['status'] = row.get('status') or 'closed'
        try:
            row['total'] = float(row.get('total', 0.0) or 0.0)
        except Exception:
            row['total'] = 0.0
        reopen_context = _build_closed_account_reopen_context(row, sessions, room_charges)
        row['can_reopen'] = bool(reopen_context.get('can_reopen'))
        row['reopen_block_reason'] = reopen_context.get('block_reason')
        row['cashier_session_id'] = reopen_context.get('cashier_session_id')
        row['cashier_session_status'] = reopen_context.get('cashier_session_status')
        row['reversal_transactions_count'] = len(reopen_context.get('reversal_indexes', []))
        items.append(row)
    return jsonify({
        'items': items,
        'page': result.get('page', page),
        'pages': result.get('pages', 1),
        'total': result.get('total', len(items))
    })


def _parse_generic_datetime(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _tx_details(tx):
    details = tx.get('details')
    if isinstance(details, dict):
        return details
    return {}


def _extract_closed_charge_ids(account):
    charge_ids = []
    details = account.get('details') if isinstance(account.get('details'), dict) else {}
    explicit = str(details.get('charge_id') or '').strip()
    if explicit:
        charge_ids.append(explicit)
    original_id = str(account.get('original_id') or '').strip()
    if 'CHARGE_' in original_id:
        idx = original_id.find('CHARGE_')
        parsed = original_id[idx:]
        if parsed:
            charge_ids.append(parsed)
    for item in (account.get('items') or []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get('id') or '').strip()
        if item_id and item_id.startswith('CHARGE_'):
            charge_ids.append(item_id)
    unique = []
    for cid in charge_ids:
        if cid not in unique:
            unique.append(cid)
    return unique


def _extract_account_payment_amounts(account):
    amounts = []
    payments = account.get('payments') or []
    if isinstance(payments, list):
        for pay in payments:
            if not isinstance(pay, dict):
                continue
            try:
                amounts.append(round(float(pay.get('amount') or 0.0), 2))
            except Exception:
                continue
    if not amounts:
        try:
            total = round(float(account.get('total') or 0.0), 2)
            if total > 0:
                amounts.append(total)
        except Exception:
            pass
    return amounts


def _select_reversal_indexes(session_obj, account, charge_ids, room_number=None):
    transactions = list((session_obj or {}).get('transactions') or [])
    closed_at = _parse_generic_datetime(account.get('closed_at') or account.get('timestamp'))
    expected_amounts = _extract_account_payment_amounts(account)
    candidates = []
    origin = str(account.get('origin') or '').strip().lower()
    account_id = str(account.get('original_id') or '').strip()
    for idx, tx in enumerate(transactions):
        if str(tx.get('type') or '').lower() != 'sale':
            continue
        try:
            amount = round(float(tx.get('amount') or 0.0), 2)
        except Exception:
            continue
        details = _tx_details(tx)
        tx_time = _parse_generic_datetime(tx.get('timestamp'))
        if origin == 'restaurant_table':
            if str(details.get('table_id') or '') != account_id:
                continue
        elif charge_ids:
            related_charge = str(details.get('related_charge_id') or details.get('charge_id') or '')
            if related_charge:
                if related_charge not in charge_ids:
                    continue
            else:
                if room_number and str(details.get('room_number') or '') != str(room_number):
                    continue
        elif room_number and str(details.get('room_number') or '') != str(room_number):
            continue
        if closed_at and tx_time:
            diff_hours = abs((closed_at - tx_time).total_seconds()) / 3600.0
            if diff_hours > 12:
                continue
        candidates.append({'index': idx, 'amount': amount, 'time': tx_time, 'tx': tx})
    if not candidates:
        return []
    selected = []
    used = set()
    for amount in expected_amounts:
        best = None
        best_score = None
        for cand in candidates:
            if cand['index'] in used:
                continue
            if abs(cand['amount'] - amount) > 0.05:
                continue
            score = 0.0
            if closed_at and cand['time']:
                score = abs((closed_at - cand['time']).total_seconds())
            if best is None or score < best_score:
                best = cand
                best_score = score
        if best is None:
            return []
        used.add(best['index'])
        selected.append(best['index'])
    if not selected and expected_amounts:
        return []
    return sorted(selected)


def _find_session_by_id(sessions, session_id):
    for idx, session_obj in enumerate(sessions):
        if str(session_obj.get('id') or '') == str(session_id or ''):
            return idx, session_obj
    return None, None


def _build_closed_account_reopen_context(account, sessions, room_charges):
    context = {
        'can_reopen': False,
        'block_reason': '',
        'cashier_session_id': None,
        'cashier_session_status': None,
        'reversal_indexes': [],
        'charge_ids': [],
        'room_number': None,
        'session_index': None
    }
    if str(account.get('status') or '').lower() == 'reopened':
        context['block_reason'] = 'Conta já reaberta.'
        return context
    origin = str(account.get('origin') or '').strip().lower()
    details = account.get('details') if isinstance(account.get('details'), dict) else {}
    charge_ids = _extract_closed_charge_ids(account)
    context['charge_ids'] = charge_ids
    room_number = details.get('room_number')
    if not room_number:
        candidate_room = str(account.get('original_id') or '').strip()
        if candidate_room.isdigit():
            room_number = candidate_room
    context['room_number'] = room_number
    target_session_id = None
    if origin == 'restaurant_table':
        table_id = str(account.get('original_id') or '').strip()
        closed_at = _parse_generic_datetime(account.get('closed_at') or account.get('timestamp'))
        best = None
        best_score = None
        for session_obj in sessions:
            for tx in (session_obj.get('transactions') or []):
                if str(tx.get('type') or '').lower() != 'sale':
                    continue
                tx_details = _tx_details(tx)
                if str(tx_details.get('table_id') or '') != table_id:
                    continue
                tx_dt = _parse_generic_datetime(tx.get('timestamp'))
                score = 0.0
                if closed_at and tx_dt:
                    score = abs((closed_at - tx_dt).total_seconds())
                if best is None or score < best_score:
                    best = session_obj
                    best_score = score
        if best:
            target_session_id = best.get('id')
    else:
        session_ids = []
        if charge_ids:
            for charge in (room_charges or []):
                cid = str(charge.get('id') or '')
                if cid in charge_ids:
                    sid = str(charge.get('reception_cashier_id') or '').strip()
                    if sid:
                        session_ids.append(sid)
        session_ids = [sid for sid in session_ids if sid]
        unique_session_ids = []
        for sid in session_ids:
            if sid not in unique_session_ids:
                unique_session_ids.append(sid)
        if len(unique_session_ids) == 1:
            target_session_id = unique_session_ids[0]
        elif len(unique_session_ids) > 1:
            context['block_reason'] = 'Conta vinculada a mais de um caixa de recepção.'
            return context
    if not target_session_id:
        context['block_reason'] = 'Caixa original não identificado.'
        return context
    session_index, session_obj = _find_session_by_id(sessions, target_session_id)
    if session_obj is None:
        context['block_reason'] = 'Caixa original não encontrado.'
        return context
    context['cashier_session_id'] = str(session_obj.get('id') or '')
    context['cashier_session_status'] = str(session_obj.get('status') or '')
    context['session_index'] = session_index
    if str(session_obj.get('status') or '').lower() != 'open':
        context['block_reason'] = 'Caixa original já está fechado.'
        return context
    reversal_indexes = _select_reversal_indexes(session_obj, account, charge_ids, room_number=room_number)
    if not reversal_indexes:
        context['block_reason'] = 'Pagamentos da conta não encontrados no caixa original.'
        return context
    context['reversal_indexes'] = reversal_indexes
    context['can_reopen'] = True
    return context


def _apply_closed_account_reopen(account, reason, user):
    sessions = CashierService.list_sessions()
    room_charges = load_room_charges()
    context = _build_closed_account_reopen_context(account, sessions, room_charges)
    if not context.get('can_reopen'):
        return False, context.get('block_reason') or 'Conta não elegível para reabertura.'
    session_index = context.get('session_index')
    if session_index is None:
        return False, 'Sessão de caixa inválida.'
    origin = str(account.get('origin') or '').strip().lower()
    table_id = str(account.get('original_id') or '').strip()
    orders = None
    if origin == 'restaurant_table':
        orders = load_table_orders()
        if str(table_id) in orders and orders[str(table_id)].get('items'):
            return False, 'Mesa já está em operação.'
    else:
        charge_ids = set(context.get('charge_ids') or [])
        if not charge_ids:
            return False, 'Cobrança de recepção sem identificação de charge.'
        has_charge = any(str(charge.get('id') or '') in charge_ids for charge in room_charges)
        if not has_charge:
            return False, 'Cobranças da recepção não encontradas para reabertura.'
    session_obj = sessions[session_index]
    transactions = list(session_obj.get('transactions') or [])
    removed_transactions = []
    for tx_index in sorted(context.get('reversal_indexes', []), reverse=True):
        if tx_index < 0 or tx_index >= len(transactions):
            continue
        removed_transactions.append(transactions.pop(tx_index))
    if not removed_transactions:
        return False, 'Nenhum pagamento removido do caixa.'
    session_obj['transactions'] = transactions
    sessions[session_index] = session_obj
    CashierService.persist_sessions(sessions, trigger_backup=False)
    if origin == 'restaurant_table':
        new_order = {
            'items': list(account.get('items') or []),
            'total': float(account.get('total') or 0.0),
            'status': 'open',
            'waiter': (account.get('details') or {}).get('waiter') if isinstance(account.get('details'), dict) else '',
            'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'reopened_from_closed_id': account.get('id'),
            'reopened_by': user,
        }
        orders[str(table_id)] = new_order
        save_table_orders(orders)
    else:
        charge_ids = set(context.get('charge_ids') or [])
        if not charge_ids:
            return False, 'Cobrança de recepção sem identificação de charge.'
        changed = 0
        for charge in room_charges:
            cid = str(charge.get('id') or '')
            if cid not in charge_ids:
                continue
            charge['status'] = 'pending'
            charge.pop('payment_method', None)
            charge.pop('payments', None)
            charge.pop('paid_at', None)
            charge.pop('reception_cashier_id', None)
            charge['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            changed += 1
        if changed == 0:
            return False, 'Nenhuma cobrança foi restaurada para pendente.'
        save_room_charges(room_charges)
    removed_ids = [str(tx.get('id') or '') for tx in removed_transactions if isinstance(tx, dict)]
    ok = ClosedAccountService.mark_as_reopened(
        account.get('id'),
        user,
        reason,
        metadata={
            'reopened_cashier_session_id': context.get('cashier_session_id'),
            'reversed_transaction_ids': removed_ids
        }
    )
    if not ok:
        return False, 'Falha ao atualizar status da conta fechada.'
    log_system_action(
        'Reabertura de conta fechada',
        {
            'closed_account_id': account.get('id'),
            'origin': account.get('origin'),
            'original_id': account.get('original_id'),
            'cashier_session_id': context.get('cashier_session_id'),
            'removed_transactions': removed_ids,
            'reopened_by': user,
            'reason': reason
        },
        category='Financeiro'
    )
    return True, ''


@finance_bp.route('/api/closed_accounts/<closed_id>', methods=['GET'])
@login_required
def api_closed_account_details(closed_id):
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    account = ClosedAccountService.get_closed_account(closed_id)
    if not account:
        return jsonify({'success': False, 'error': 'Conta fechada não encontrada'}), 404
    sessions = CashierService.list_sessions()
    room_charges = load_room_charges()
    context = _build_closed_account_reopen_context(account, sessions, room_charges)
    payload = dict(account)
    payload['closed_at'] = payload.get('closed_at') or payload.get('timestamp')
    payload['can_reopen'] = bool(context.get('can_reopen'))
    payload['reopen_block_reason'] = context.get('block_reason')
    payload['cashier_session_id'] = context.get('cashier_session_id')
    payload['cashier_session_status'] = context.get('cashier_session_status')
    payload['reversal_transactions_count'] = len(context.get('reversal_indexes', []))
    return jsonify({'success': True, 'data': payload})

@finance_bp.route('/admin/reopen_account', methods=['POST'])
@login_required
def admin_reopen_account():
    denied = _ensure_admin_finance_balances_access()
    if denied is not None:
        return denied
    payload = request.get_json(silent=True) or {}
    closed_id = str(payload.get('id') or '').strip()
    reason = str(payload.get('reason') or '').strip()
    if not closed_id:
        return jsonify({'success': False, 'error': 'ID não informado'}), 400
    if not reason:
        return jsonify({'success': False, 'error': 'Motivo obrigatório'}), 400
    target = ClosedAccountService.get_closed_account(closed_id)
    if not target:
        return jsonify({'success': False, 'error': 'Conta fechada não encontrada'}), 404
    if str(target.get('status') or 'closed') == 'reopened':
        return jsonify({'success': True, 'message': 'Conta já marcada como reaberta'})
    ok, error = _apply_closed_account_reopen(target, reason, session.get('user') or 'Sistema')
    if not ok:
        return jsonify({'success': False, 'error': error}), 400
    return jsonify({'success': True})

@finance_bp.route('/finance_commission')
@login_required
def finance_commission():
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('main.service_page', service_id='financeiro'))
    cycles = load_commission_cycles()
    # Auto-create current month cycle if missing
    now = datetime.now()
    cur_month = now.strftime('%Y-%m')
    has_current = any(c.get('month') == cur_month for c in cycles)
    if not has_current:
        cycle_id = datetime.now().strftime('%Y%m%d%H%M%S')
        name = f"Comissão {cur_month}"
        # Initialize employees from users
        users = load_users()
        employees = []
        for username, data in users.items():
            dept = data.get('department', 'Outros')
            role = data.get('role', '')
            try:
                score = float(data.get('score', 0))
            except:
                score = 0
            employees.append({
                'name': data.get('full_name', username),
                'department': dept,
                'role': role,
                'points': score, 
                'days_worked': 30,
                'individual_bonus': 0,
                'individual_deduction': 0
            })
        dept_bonuses = [
            {'name': 'Cozinha', 'value': 0},
            {'name': 'Serviço', 'value': 0},
            {'name': 'Manutenção', 'value': 0},
            {'name': 'Recepção', 'value': 0},
            {'name': 'Estoque', 'value': 0},
            {'name': 'Governança', 'value': 0}
        ]
        # Set initial commission based on /commission_ranking logic (10% default)
        try:
            initial_commission = compute_month_total_commission_by_ranking(cur_month, commission_rate=10.0)
        except Exception:
            # Fallback: 10% of monthly sales if helper fails
            try:
                total_sales = calculate_monthly_sales(cur_month)
                initial_commission = total_sales * 0.10
            except:
                initial_commission = 0
        # Inherit last tax percents if exist
        default_comm_tax = 12.0
        default_bonus_tax = 12.0
        if cycles:
            sorted_cycles = sorted(cycles, key=lambda x: x['id'], reverse=True)
            last_cycle = sorted_cycles[0]
            default_comm_tax = float(last_cycle.get('commission_tax_percent', 12.0))
            default_bonus_tax = float(last_cycle.get('bonus_tax_percent', 12.0))
        new_cycle = {
            'id': cycle_id,
            'name': name,
            'month': cur_month,
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'status': 'draft',
            'total_commission': initial_commission,
            'total_bonus': 0,
            'card_percent': 0.80,
            'commission_tax_percent': default_comm_tax,
            'bonus_tax_percent': default_bonus_tax,
            'extras': 0,
            'employees': employees,
            'department_bonuses': dept_bonuses,
            'results': {}
        }
        cycles.append(new_cycle)
        save_commission_cycles(cycles)
    # Sort by date desc (assuming id starts with YYYYMMDD)
    cycles.sort(key=lambda x: x['id'], reverse=True)
    return render_template('finance_commission.html', cycles=cycles)

@finance_bp.route('/finance/accounts_payable', methods=['GET', 'POST'])
@login_required
def accounts_payable():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('main.index'))
    
    payables = load_payables()
    suppliers = load_suppliers()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            import uuid
            supplier_name = request.form.get('supplier')
            description = request.form.get('description')
            amount = request.form.get('amount')
            due_date = request.form.get('due_date')
            barcode = request.form.get('barcode')
            
            new_payable = {
                'id': str(uuid.uuid4()),
                'type': request.form.get('type', 'supplier'),
                'supplier': supplier_name,
                'description': description,
                'amount': float(amount) if amount else 0.0,
                'due_date': due_date,
                'barcode': barcode,
                'tax_type': request.form.get('tax_type'),
                'cnpj': request.form.get('cnpj'),
                'status': 'pending',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            payables.append(new_payable)
            save_payables(payables)
            flash('Conta adicionada com sucesso!', 'success')
            
        elif action == 'pay':
            payable_id = request.form.get('id')
            payment_date = request.form.get('payment_date', datetime.now().strftime('%Y-%m-%d'))
            
            for p in payables:
                if p['id'] == payable_id:
                    p['status'] = 'paid'
                    p['payment_date'] = payment_date
                    p['paid_by'] = session.get('user')
                    break
            save_payables(payables)
            flash('Pagamento registrado!', 'success')
            
        elif action == 'delete':
            payable_id = request.form.get('id')
            payables = [p for p in payables if p['id'] != payable_id]
            save_payables(payables)
            flash('Conta removida.', 'success')

    return render_template('accounts_payable.html', payables=payables, suppliers=suppliers)

@finance_bp.route('/finance/manage_suppliers', methods=['GET', 'POST'])
@login_required
def manage_suppliers():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('main.index'))
        
    suppliers = load_suppliers()
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            original_name = request.form.get('original_name')
            new_name = request.form.get('name')
            pix = request.form.get('pix')
            cnpj = request.form.get('cnpj')
            
            for s in suppliers:
                s_name = s['name'] if isinstance(s, dict) else s
                if s_name == original_name:
                    if isinstance(s, dict):
                        s['name'] = new_name
                        s['pix'] = pix
                        s['cnpj'] = cnpj
                    else:
                        # Convert to dict if it was string
                        idx = suppliers.index(s)
                        suppliers[idx] = {'name': new_name, 'pix': pix, 'cnpj': cnpj}
                    break
            save_suppliers(suppliers)
            flash('Fornecedor atualizado!', 'success')
            
    return render_template('manage_suppliers.html', suppliers=suppliers)

@finance_bp.route('/finance/commission/new', methods=['POST'])
@login_required
def finance_commission_new():
    name = request.form.get('name')
    month = request.form.get('month') # YYYY-MM
    
    if not name or not month:
        flash('Nome e Mês de referência são obrigatórios.')
        return redirect(url_for('finance.finance_commission'))
        
    cycle_id = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # Initialize with default employees from users.json
    users = load_users()
    employees = []
    
    for username, data in users.items():
        dept = data.get('department', 'Outros')
        role = data.get('role', '')
        
        try:
            score = float(data.get('score', 0))
        except:
            score = 0

        employees.append({
            'name': data.get('full_name', username),
            'department': dept,
            'role': role,
            'points': score, 
            'days_worked': 30,
            'individual_bonus': 0,
            'individual_deduction': 0
        })
        
    # Default Department Bonuses structure
    dept_bonuses = [
        {'name': 'Cozinha', 'value': 0},
        {'name': 'Serviço', 'value': 0},
        {'name': 'Manutenção', 'value': 0},
        {'name': 'Recepção', 'value': 0},
        {'name': 'Estoque', 'value': 0}
    ]
    
    # Calculate Total Commission using commission ranking logic (default 10%)
    try:
        initial_commission = compute_month_total_commission_by_ranking(month, commission_rate=10.0)
    except Exception:
        # Fallback to 10% of monthly sales
        try:
            total_sales = calculate_monthly_sales(month)
            initial_commission = total_sales * 0.10
        except:
            initial_commission = 0

    # Load existing cycles to find the last one and inherit tax rates
    cycles = load_commission_cycles()
    
    # Defaults
    default_comm_tax = 12.0
    default_bonus_tax = 12.0
    
    if cycles:
        # Sort by id desc to get the most recent
        sorted_cycles = sorted(cycles, key=lambda x: x['id'], reverse=True)
        last_cycle = sorted_cycles[0]
        default_comm_tax = float(last_cycle.get('commission_tax_percent', 12.0))
        default_bonus_tax = float(last_cycle.get('bonus_tax_percent', 12.0))

    new_cycle = {
        'id': cycle_id,
        'name': name,
        'month': month,
        'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'status': 'draft',
        'total_commission': initial_commission,
        'total_bonus': 0,
        'card_percent': 0.80,
        'commission_tax_percent': default_comm_tax,
        'bonus_tax_percent': default_bonus_tax,
        'extras': 0,
        'employees': employees,
        'department_bonuses': dept_bonuses,
        'results': {}
    }
    
    cycles.append(new_cycle)
    save_commission_cycles(cycles)
    
    flash('Ciclo de comissão criado com sucesso.')
    return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))

@finance_bp.route('/finance/commission/<cycle_id>')
@login_required
def finance_commission_detail(cycle_id):
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('finance.finance_commission'))
        
    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
    
    # Ensure all standard departments exist in the cycle and remove others
    standard_depts = ['Cozinha', 'Serviço', 'Manutenção', 'Recepção', 'Estoque', 'Governança']
    existing_depts_map = {d['name']: d['value'] for d in cycle.get('department_bonuses', [])}
    
    new_dept_bonuses = []
    changed = False
    
    # Rebuild the list strictly
    for std in standard_depts:
        val = existing_depts_map.get(std, 0)
        new_dept_bonuses.append({'name': std, 'value': val})
        
    # Check if anything changed (order, new items, removed items)
    current_names = [d['name'] for d in cycle.get('department_bonuses', [])]
    if current_names != standard_depts:
        cycle['department_bonuses'] = new_dept_bonuses
        changed = True
            
    if changed:
        # Save updates to file so they persist
        cycles = load_commission_cycles()
        for i, c in enumerate(cycles):
            if c['id'] == cycle_id:
                cycles[i] = cycle
                break
        save_commission_cycles(cycles)

    # Load Consumption Data and update in-memory cycle for display
    consumption_map = load_employee_consumption()
    for emp in cycle['employees']:
        if cycle.get('status') != 'approved':
             emp['consumption'] = consumption_map.get(emp['name'], 0.0)

    # Sort main employee list alphabetically for the table view
    cycle['employees'].sort(key=lambda x: x.get('name', '').lower())

    dept_rankings = {d: [] for d in standard_depts}
    
    for emp in cycle['employees']:
        emp_dept_norm = normalize_dept(emp.get('department', ''))
        
        # Match with standard depts
        matched = False
        for std in standard_depts:
            if normalize_dept(std) == emp_dept_norm:
                dept_rankings[std].append(emp)
                matched = True
                break
        
        if not matched:
            # Handle non-standard departments (e.g. Governança)
            d_name = emp.get('department', 'Outros')
            if not d_name: d_name = 'Outros'
            if d_name not in dept_rankings:
                dept_rankings[d_name] = []
            dept_rankings[d_name].append(emp)
            
    # Sort each department by points descending
    dept_totals = {}
    for d in dept_rankings:
        dept_rankings[d].sort(key=lambda x: float(x.get('points', 0) or 0), reverse=True)
        
        # Calculate totals per department
        total = 0
        for emp in dept_rankings[d]:
            if 'calculated' in emp and isinstance(emp['calculated'], dict) and 'total' in emp['calculated']:
                try:
                    total += float(emp['calculated']['total'])
                except (ValueError, TypeError):
                    pass
        dept_totals[d] = total
        
    return render_template('commission_cycle_detail.html', cycle=cycle, dept_rankings=dept_rankings, dept_totals=dept_totals)

@finance_bp.route('/finance/commission/<cycle_id>/refresh_scores', methods=['POST'])
@login_required
def finance_commission_refresh_scores(cycle_id):
    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
    
    # Update from form FIRST to preserve edits
    try:
        update_cycle_from_form(cycle, request.form)
    except Exception as e:
        print(f"Error updating cycle form data: {e}")
        
    users = load_users()
    # Build lookup map: Name -> Score
    name_to_score = {}
    for u, data in users.items():
        try:
            score = float(data.get('score', 0))
        except:
            score = 0
        
        # Map username
        name_to_score[u] = score
        # Map full name if exists
        if data.get('full_name'):
            name_to_score[data['full_name']] = score
            
    # Update employees
    count = 0
    for emp in cycle['employees']:
        emp_name = emp['name']
        if emp_name in name_to_score:
            emp['points'] = name_to_score[emp_name]
            count += 1
            
    # Save
    cycles = load_commission_cycles()
    for i, c in enumerate(cycles):
        if c['id'] == cycle_id:
            cycles[i] = cycle
            break
    save_commission_cycles(cycles)
    
    flash(f'Pontuações atualizadas para {count} funcionários.')
    return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))

@finance_bp.route('/finance/commission/<cycle_id>/employee/update', methods=['POST'])
@login_required
def finance_commission_update_employee(cycle_id):
    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
        
    emp_name = request.form.get('emp_name')
    if not emp_name:
        flash('Nome do funcionário é obrigatório.')
        return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))
        
    # Find employee
    employee = None
    for e in cycle['employees']:
        if e['name'] == emp_name:
            employee = e
            break
            
    if not employee:
        flash(f'Funcionário {emp_name} não encontrado neste ciclo.')
        return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))
        
    # Update fields
    try:
        employee['department'] = request.form.get('emp_dept')
        employee['role'] = request.form.get('emp_role')
        employee['points'] = parse_currency(request.form.get('emp_points'))
        employee['days_worked'] = parse_currency(request.form.get('emp_days'))
        employee['individual_bonus'] = parse_currency(request.form.get('emp_bonus'))
        employee['individual_deduction'] = parse_currency(request.form.get('emp_deduction'))
        
        # Save
        cycles = load_commission_cycles()
        for i, c in enumerate(cycles):
            if c['id'] == cycle_id:
                cycles[i] = cycle
                break
        save_commission_cycles(cycles)
        
        flash(f'Dados de {emp_name} atualizados com sucesso.')
        
    except Exception as e:
        print(traceback.format_exc())
        flash(f'Erro ao atualizar funcionário: {str(e)}')
        
    return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))

@finance_bp.route('/finance/commission/<cycle_id>/calculate', methods=['POST'])
@login_required
def finance_commission_calculate(cycle_id):
    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
        
    # Update Cycle Data from Form
    try:
        update_cycle_from_form(cycle, request.form)
        # Se total_commission ficou 0 após update, preencher com cálculo baseado no ranking do mês
        if float(cycle.get('total_commission', 0) or 0) == 0 and cycle.get('month'):
            try:
                cycle['total_commission'] = compute_month_total_commission_by_ranking(cycle['month'], commission_rate=10.0)
            except Exception:
                pass
            
        # Run Calculation
        cycle = calculate_commission(cycle)
        cycle['status'] = 'calculated'
        cycle['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        # Save
        cycles = load_commission_cycles()
        # Replace
        for i, c in enumerate(cycles):
            if c['id'] == cycle_id:
                cycles[i] = cycle
                break
        save_commission_cycles(cycles)
        
        flash('Cálculo realizado e salvo com sucesso!')
        
    except Exception as e:
        print(traceback.format_exc())
        flash(f'Erro ao calcular: {str(e)}')
        
    return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))

@finance_bp.route('/finance/commission/<cycle_id>/approve', methods=['POST'])
@login_required
def finance_commission_approve(cycle_id):
    if session.get('role') != 'admin':
        flash('Apenas administradores podem aprovar.')
        return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))
        
    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
        
    orders = load_table_orders()
    import uuid
    count_closed = 0
    count_partial = 0
    employees = cycle.get('employees', [])
    emp_names = {e['name'] for e in employees}
    name_to_emp = {e['name']: e for e in employees}

    users = load_users()
    user_map = {}
    for uname, udata in users.items():
        full_name = udata.get('full_name') or udata.get('name') or uname
        user_map[uname] = full_name

    for order_id, order in orders.items():
        if order.get('customer_type') == 'funcionario' and order.get('status') in ['open', 'locked']:
            staff_name = order.get('staff_name')
            resolved_name = user_map.get(staff_name, staff_name)

            if resolved_name in emp_names:
                if 'partial_payments' not in order:
                    order['partial_payments'] = []
                if 'total_paid' not in order:
                    order['total_paid'] = 0.0

                try:
                    subtotal = float(order.get('total', 0) or 0)
                except Exception:
                    subtotal = 0.0
                discounted_total = subtotal * 0.80
                already_paid = float(order.get('total_paid', 0) or 0)
                outstanding_now = max(0.0, discounted_total - already_paid)

                emp = name_to_emp.get(resolved_name, {})
                consumption_used = float(emp.get('consumption', 0) or 0)

                pay_amount = min(outstanding_now, consumption_used)

                if pay_amount > 0.001:
                    payment_entry = {
                        'id': str(uuid.uuid4()),
                        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'amount': round(pay_amount, 2),
                        'method': 'Dedução Comissão',
                        'user': session.get('user')
                    }
                    order['partial_payments'].append(payment_entry)
                    order['total_paid'] = round(already_paid + pay_amount, 2)
                    

                if emp is not None:
                    try:
                        emp['commission_deduction'] = round(pay_amount, 2) if pay_amount else 0.0
                    except Exception:
                        emp['commission_deduction'] = 0.0
                    try:
                        emp['consumption_remaining'] = round(outstanding_after, 2)
                    except Exception:
                        emp['consumption_remaining'] = 0.0
                    try:
                        emp['consumption_considered'] = round(consumption_used, 2)
                    except Exception:
                        emp['consumption_considered'] = emp.get('consumption', 0.0)
                outstanding_after = max(0.0, (subtotal * 0.80) - order.get('total_paid', 0))
                if outstanding_after <= 0.001:
                    order['status'] = 'closed'
                    order['payment_method'] = 'deducao_comissao'
                    order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    order['commission_cycle_id'] = cycle_id
                    count_closed += 1
                else:
                    count_partial += 1
    if count_closed > 0 or count_partial > 0:
        save_table_orders(orders)
            
    cycle['status'] = 'approved'
    cycle['approved_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    cycle['approved_by'] = session.get('user')
    
    # Save cycle
    cycles = load_commission_cycles()
    for i, c in enumerate(cycles):
        if c['id'] == cycle_id:
            cycles[i] = cycle
            break
    save_commission_cycles(cycles)
    
    if count_partial > 0:
        flash(f'Comissão aprovada! {count_closed} contas fechadas e {count_partial} contas registradas com pagamento parcial.', 'info')
    else:
        flash(f'Comissão aprovada! {count_closed} contas fechadas.', 'success')
    return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))

@finance_bp.route('/finance/commission/<cycle_id>/delete', methods=['POST'])
@login_required
def finance_commission_delete(cycle_id):
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso negado.')
        return redirect(url_for('finance.finance_commission'))
        
    cycles = load_commission_cycles()
    cycles = [c for c in cycles if c['id'] != cycle_id]
    save_commission_cycles(cycles)
    
    flash('Ciclo excluído.')
    return redirect(url_for('finance.finance_commission'))

 

@finance_bp.route('/finance/close_staff_month', methods=['POST'])
@login_required
def close_staff_month():
    if session.get('role') not in ['admin', 'gerente']:
        flash('Acesso negado.')
        return redirect(url_for('main.index'))
        
    orders = load_table_orders()
    sessions = _load_cashier_sessions()
    
    # Use CashierService helper to find active session
    current_session = CashierService.get_active_session()
    # Or mimic original logic: sessions[-1] if open. 
    # But safer to use get_active_session. Original code used manual check.
    # Original:
    # cashier_status = load_cashier_status() # Undefined? Ah, I missed where this was imported or defined. 
    # It probably doesn't exist and would crash, or I missed it.
    # Let's rely on sessions list.
    
    if not current_session and sessions and sessions[-1].get('status') == 'open':
        current_session = sessions[-1]
    
    if not current_session:
        flash('Erro: É necessário ter um caixa aberto (Recepção ou Restaurante) para registrar o fechamento.')
        return redirect(url_for('main.service_page', service_id='financeiro'))

    count = 0
    total_amount = 0.0
    
    # Identify staff orders (keys starting with FUNC_)
    staff_keys = [k for k in orders.keys() if k.startswith('FUNC_')]
    
    for table_id in staff_keys:
        order = orders[table_id]
        if order.get('items') and order.get('total', 0) > 0:
            try:
                subtotal = float(order.get('total', 0) or 0)
            except Exception:
                subtotal = 0.0
            discount_amount = round(subtotal * 0.20, 2)
            amount = max(0.0, subtotal - discount_amount)
            staff_name = order.get('staff_name') or table_id.replace('FUNC_', '')
            
            # Create Transaction
            transaction = {
                'id': f"CLOSE_{table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                'type': 'sale',
                'category': 'Conta Funcionário',
                'amount': amount,
                'description': f"Fechamento Mensal - {staff_name}",
                'payment_method': 'Conta Funcionário',
                'emit_invoice': False,
                'staff_name': staff_name,
                'waiter': 'Sistema',
                'service_fee_removed': True,
                'commission_eligible': False,
                'commission_reference_id': f"STAFF_MONTHLY_{table_id}",
                'operator': session.get('user', 'Sistema'),
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'details': {
                    'subtotal': subtotal,
                    'discount': discount_amount,
                    'category': 'Conta Funcionário',
                    'service_fee_removed': True,
                    'commission_eligible': False,
                    'commission_reference_id': f"STAFF_MONTHLY_{table_id}",
                    'closed_by': session.get('user', 'Sistema')
                }
            }
            
            current_session['transactions'].append(transaction)
            # Legacy total_sales update if needed
            current_session['total_sales'] = current_session.get('total_sales', 0) + amount
            
            if 'payment_methods' not in current_session:
                current_session['payment_methods'] = {}
            current_session['payment_methods']['Conta Funcionário'] = current_session['payment_methods'].get('Conta Funcionário', 0) + amount
            
            total_amount += amount
            count += 1
            
            # --- FISCAL POOL INTEGRATION ---
            try:
                # Add to Fiscal Pool
                FiscalPoolService.add_to_pool(
                    origin='restaurant', # Staff consumption comes from restaurant tables
                    original_id=table_id,
                    total_amount=amount,
                    items=order.get('items', []),
                    payment_methods=[{'method': 'Conta Funcionário', 'amount': amount, 'is_fiscal': False}],
                    user=session.get('user', 'Sistema'),
                    customer_info={'name': staff_name, 'cpf_cnpj': ''},
                    notes='Consumo Funcionário - Fechamento Mensal'
                )
            except Exception as e:
                print(f"Error adding staff order to fiscal pool: {e}")
                LoggerService.log_acao(
                    acao="Erro Fiscal Pool (Staff)",
                    entidade="Sistema",
                    detalhes={"error": str(e), "table": table_id},
                    nivel_severidade="ERRO"
                )
            # -------------------------------

            # Remove/Close the order
            del orders[table_id]
        elif not order.get('items'):
            # Empty order, just remove
            del orders[table_id]
            
    if count > 0:
        CashierService.persist_sessions(sessions, trigger_backup=False)
        save_table_orders(orders)
        flash(f'Sucesso: {count} contas fechadas. Total lançado: R$ {total_amount:.2f}')
    else:
        # Check if there were empty orders removed
        if len(staff_keys) > 0:
            save_table_orders(orders)
            flash('Contas vazias foram limpas. Nenhuma cobrança gerada.')
        else:
            flash('Nenhuma conta de funcionário encontrada.')
            
    return redirect(url_for('main.service_page', service_id='financeiro'))

@finance_bp.route('/generate_commission_dashboard', methods=['POST'])
@login_required
def generate_commission_dashboard():
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso negado.')
        return redirect(url_for('finance.finance_commission'))

    if 'file' not in request.files:
        flash('Nenhum arquivo enviado.')
        return redirect(url_for('finance.finance_commission'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('finance.finance_commission'))

    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            # Ler o arquivo Excel enviado
            try:
                # Engine 'openpyxl' is default for xlsx
                df_editavel = pd.read_excel(file, sheet_name='Editavel', header=None)
                df_funcionarios = pd.read_excel(file, sheet_name='Funcionarios')
                df_departamentos = pd.read_excel(file, sheet_name='Departamentos')
            except ValueError as e:
                flash(f'Erro ao ler abas da planilha: {str(e)}. Certifique-se que o modelo está correto.')
                return redirect(url_for('finance.finance_commission'))

            # Helper para limpar valores monetários/percentuais
            def clean_val(v):
                if pd.isna(v): return 0.0
                if isinstance(v, (int, float)): return float(v)
                s = str(v).replace('R$', '').replace('%', '').replace('.', '').replace(',', '.').strip()
                try:
                    return float(s)
                except:
                    return 0.0

            # Extrair valores totais (layout fixo do modelo)
            # Row 2 (index 2) -> Col 1 (index 1) é o valor
            total_comissao = clean_val(df_editavel.iloc[2, 1])
            total_bonificacao = clean_val(df_editavel.iloc[3, 1])
            pct_cartao = clean_val(df_editavel.iloc[4, 1])
            descontos_extras = clean_val(df_editavel.iloc[19, 1])
            
            # Recalcular
            total_bruto = total_comissao + total_bonificacao
            ded_convencao = total_bruto * 0.20
            ded_imposto = (total_bruto - ded_convencao) * 0.12
            ded_cartao = (total_bruto * pct_cartao) * 0.02
            total_deducoes = ded_convencao + ded_imposto + ded_cartao
            liquido_distribuir = total_bruto - total_deducoes - descontos_extras

            # Calculate Staff Consumption (16th prev month to 15th curr month)
            today = datetime.now()
            target_month = today.month
            target_year = today.year
            
            end_date = datetime(target_year, target_month, 15)
            if target_month == 1:
                start_date = datetime(target_year - 1, 12, 16)
            else:
                start_date = datetime(target_year, target_month - 1, 16)
                
            staff_consumption = get_staff_consumption_for_period(start_date, end_date)
            
            # Processar Funcionários
            col_nome = find_col(df_funcionarios.columns, ['Nome', 'Funcionario'])
            col_dept = find_col(df_funcionarios.columns, ['Departamento', 'Setor'])
            col_pontos = find_col(df_funcionarios.columns, ['Pontos', 'Pontuação'])
            col_ded = find_col(df_funcionarios.columns, ['DeducaoIndividual', 'Dedução'])
            col_bon = find_col(df_funcionarios.columns, ['BonificacaoIndividual', 'Bônus'])
            col_dias = find_col(df_funcionarios.columns, ['DiasTrabalhados', 'Dias'])
            
            if not col_nome or not col_pontos:
                flash('Colunas obrigatórias (Nome, Pontos) não encontradas na aba Funcionarios.')
                return redirect(url_for('finance.finance_commission'))
            
            # Ler departamentos e bônus
            bonus_depts_total = 0
            
            # Tentar encontrar o cabeçalho correto em Departamentos
            possible_headers = ['Bônus', 'Bonus', 'Valor', 'valor']
            col_dept_bonus = find_col(df_departamentos.columns, possible_headers)
            
            if not col_dept_bonus:
                 try:
                     df_dept_v2 = pd.read_excel(file, sheet_name='Departamentos', header=1)
                     col_dept_bonus = find_col(df_dept_v2.columns, possible_headers)
                     if col_dept_bonus:
                         df_departamentos = df_dept_v2
                 except:
                     pass
            
            if col_dept_bonus:
                df_departamentos[col_dept_bonus] = df_departamentos[col_dept_bonus].apply(clean_val)
                bonus_depts_total = df_departamentos[col_dept_bonus].sum()
            else:
                try:
                     df_dept_raw = pd.read_excel(file, sheet_name='Departamentos', header=None)
                     if df_dept_raw.shape[1] >= 2:
                         soma_raw = 0
                         for val in df_dept_raw.iloc[:, 1]:
                             soma_raw += clean_val(val)
                         bonus_depts_total = soma_raw
                except:
                    pass
            
            # Calcular total de bônus individuais para subtrair do bolo antes do rateio por pontos
            total_bonus_indiv = 0
            if col_bon:
                df_funcionarios['temp_bonus'] = df_funcionarios[col_bon].apply(clean_val)
                total_bonus_indiv = df_funcionarios['temp_bonus'].sum()
            
            # Valor Base para os Pontos
            valor_base_pontos = liquido_distribuir - bonus_depts_total - total_bonus_indiv
            
            # Definir Potes (Fixo conforme regra)
            pcts = {1: 0.10, 2: 0.30, 3: 0.33, 4: 0.17, 5: 0.10}
            potes = {k: valor_base_pontos * v for k, v in pcts.items()}
            
            funcs_por_ponto = {1: [], 2: [], 3: [], 4: [], 5: []}
            
            for index, row in df_funcionarios.iterrows():
                try:
                    ponto = int(row[col_pontos]) if pd.notna(row[col_pontos]) else 0
                except:
                    ponto = 0
                
                if ponto in funcs_por_ponto:
                    dias = 30
                    if col_dias and pd.notna(row[col_dias]):
                        try:
                            dias = int(row[col_dias])
                        except:
                            pass
                    
                    bonus_val = 0.0
                    if col_bon: bonus_val = clean_val(row[col_bon])
                    
                    ded_val = 0.0
                    if col_ded: ded_val = clean_val(row[col_ded])

                    f = {
                        'Nome': row[col_nome],
                        'Departamento': row[col_dept] if col_dept and pd.notna(row[col_dept]) else 'Geral',
                        'Dias': dias,
                        'Deducao': ded_val,
                        'Bonus': bonus_val,
                        'Ponto': ponto
                    }
                    funcs_por_ponto[ponto].append(f)

            # Calcular Valor
            for p, lista in funcs_por_ponto.items():
                total_dias_ponto = sum(f['Dias'] for f in lista)
                valor_pote = potes[p]
                valor_por_dia = valor_pote / total_dias_ponto if total_dias_ponto > 0 else 0
                
                for f in lista:
                    f['ComissaoBruta'] = f['Dias'] * valor_por_dia
                    f['ComissaoLiquida'] = f['ComissaoBruta'] + f['Bonus'] - f['Deducao']
            
            # Gerar Excel Resultado
            output = io.BytesIO()
            wb = xlsxwriter.Workbook(output, {'in_memory': True})
            
            fmt_money = wb.add_format({'num_format': 'R$ #,##0.00'})
            fmt_header = wb.add_format({'bold': True, 'bg_color': '#D9EAD3', 'border': 1})
            
            # Aba Resumo
            ws_resumo = wb.add_worksheet("Dashboard")
            ws_resumo.write(0, 0, "Resumo da Distribuição", fmt_header)
            ws_resumo.write(1, 0, "Líquido Total", fmt_header)
            ws_resumo.write(1, 1, liquido_distribuir, fmt_money)
            ws_resumo.write(2, 0, "Base para Pontos", fmt_header)
            ws_resumo.write(2, 1, valor_base_pontos, fmt_money)
            
            ws_resumo.write(4, 0, "Ponto", fmt_header)
            ws_resumo.write(4, 1, "Valor do Pote", fmt_header)
            ws_resumo.write(4, 2, "Qtd Funcionários", fmt_header)
            ws_resumo.write(4, 3, "Valor/Dia (30 dias)", fmt_header)
            
            row = 5
            for p in range(1, 6):
                ws_resumo.write(row, 0, f"Ponto {p} ({int(pcts[p]*100)}%)")
                ws_resumo.write(row, 1, potes[p], fmt_money)
                ws_resumo.write(row, 2, len(funcs_por_ponto[p]))
                
                total_dias_ponto = sum(f['Dias'] for f in funcs_por_ponto[p])
                val_dia = potes[p] / total_dias_ponto if total_dias_ponto > 0 else 0
                ws_resumo.write(row, 3, val_dia * 30, fmt_money)
                
                row += 1
                
            # Aba Detalhada
            ws_detalhe = wb.add_worksheet("Detalhamento")
            cols = ['Nome', 'Departamento', 'Ponto', 'Dias', 'ComissaoPontos', 'BonusIndiv', 'DeducaoIndiv', 'ConsumoInterno', 'TotalReceber']
            for i, c in enumerate(cols):
                ws_detalhe.write(0, i, c, fmt_header)
            
            row = 1
            all_processed = []
            for p in funcs_por_ponto:
                for f in funcs_por_ponto[p]:
                    all_processed.append(f)
            
            all_processed.sort(key=lambda x: x['Nome'])
            
            for f in all_processed:
                ws_detalhe.write(row, 0, f['Nome'])
                ws_detalhe.write(row, 1, f['Departamento'])
                ws_detalhe.write(row, 2, f['Ponto'])
                ws_detalhe.write(row, 3, f['Dias'])
                ws_detalhe.write(row, 4, f['ComissaoBruta'], fmt_money)
                ws_detalhe.write(row, 5, f['Bonus'], fmt_money)
                ws_detalhe.write(row, 6, f['Deducao'], fmt_money)
                ws_detalhe.write(row, 7, f.get('ConsumoInterno', 0.0), fmt_money)
                ws_detalhe.write(row, 8, f['ComissaoLiquida'], fmt_money)
                row += 1
                
            ws_detalhe.set_column(0, 0, 30)
            ws_detalhe.set_column(1, 8, 15)
            
            wb.close()
            output.seek(0)
            
            return send_file(output, download_name=f"Resultado_Comissao_{datetime.now().strftime('%d-%m-%Y')}.xlsx", as_attachment=True)

        except Exception as e:
            flash(f'Erro ao processar arquivo: {str(e)}')
            return redirect(url_for('finance.finance_commission'))
            
    flash('Arquivo inválido.')
    return redirect(url_for('finance.finance_commission'))

@finance_bp.route('/commission_ranking')
@login_required
def commission_ranking():
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso negado.')
        return redirect(url_for('main.index'))

    def _get_waiter_breakdown(transaction):
        waiter_breakdown = transaction.get('waiter_breakdown')
        if not waiter_breakdown:
            details = transaction.get('details') or {}
            waiter_breakdown = details.get('waiter_breakdown')
        if isinstance(waiter_breakdown, dict) and waiter_breakdown:
            return waiter_breakdown
        return None

    def _get_operator_name(transaction, session_data):
        return transaction.get('user') or session_data.get('user') or '-'

    def _get_removed_group_key(transaction, session_data):
        details = transaction.get('details') or {}
        timestamp = transaction.get('timestamp') or '-'
        operator = _get_operator_name(transaction, session_data)
        related_charge_id = transaction.get('related_charge_id') or details.get('related_charge_id')
        if related_charge_id:
            ref = f"charge:{related_charge_id}"
        else:
            table_id = details.get('table_id')
            room_number = details.get('room_number')
            if table_id:
                ref = f"table:{table_id}"
            elif room_number:
                ref = f"room:{room_number}"
            else:
                ref = f"tx:{transaction.get('id', '-')}"
        return f"{ref}|{timestamp}|{operator}"

    # Get filter parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    try:
        commission_rate = float(request.args.get('commission_rate', 10))
    except ValueError:
        commission_rate = 10.0

    # Default dates if not provided: Start of current month to today
    now = datetime.now()
    if not start_date_str:
        start_date = now.replace(day=1)
        start_date_str = start_date.strftime('%Y-%m-%d') # For HTML input
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except:
            start_date = now.replace(day=1)

    if not end_date_str:
        end_date = now
        end_date_str = end_date.strftime('%Y-%m-%d')
    else:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except:
            end_date = now
            
    # Set end_date to end of day for comparison
    end_date_comp = end_date.replace(hour=23, minute=59, second=59)
    # Start date to beginning of day
    start_date_comp = start_date.replace(hour=0, minute=0, second=0)

    def _normalize_waiter_breakdown_map(waiter_breakdown):
        if not isinstance(waiter_breakdown, dict):
            return {}
        normalized = {}
        for key, value in waiter_breakdown.items():
            waiter_name = str(key or '').strip() or 'Sem Colaborador'
            try:
                amount = float(value or 0)
            except Exception:
                amount = 0.0
            normalized[waiter_name] = normalized.get(waiter_name, 0.0) + amount
        return normalized

    def _get_transaction_details(transaction):
        details = transaction.get('details') or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {}
        if not isinstance(details, dict):
            details = {}
        return details

    def _get_transaction_category(transaction, details):
        return str(transaction.get('category') or details.get('category') or '').strip()

    def _is_ranking_transaction(transaction):
        details = _get_transaction_details(transaction)
        tx_type = str(transaction.get('type') or '').strip().lower()
        tx_category = _get_transaction_category(transaction, details)
        if tx_type == 'sale':
            return True
        if tx_type == 'in' and tx_category in ['Pagamento de Conta', 'Recebimento Manual']:
            return True
        return False

    def _get_commission_reference(transaction, details):
        ref = transaction.get('commission_reference_id') or details.get('commission_reference_id')
        if ref:
            return str(ref)
        related_charge_id = transaction.get('related_charge_id') or details.get('related_charge_id')
        if related_charge_id:
            return f"charge:{related_charge_id}"
        table_id = details.get('table_id')
        if table_id:
            return f"table:{table_id}:{transaction.get('timestamp', '')}"
        room_number = details.get('room_number')
        if room_number:
            return f"room:{room_number}:{transaction.get('timestamp', '')}"
        return f"tx:{transaction.get('id', '-')}"

    def _get_reference_label(transaction, details):
        related_charge_id = transaction.get('related_charge_id') or details.get('related_charge_id')
        table_id = details.get('table_id')
        room_number = details.get('room_number')
        if related_charge_id:
            return f"Quarto/Conta {related_charge_id}"
        if table_id:
            return f"Mesa {table_id}"
        if room_number:
            return f"Quarto {room_number}"
        return "-"

    sessions = _load_cashier_sessions()
    waiter_stats = {}
    logical_groups = {}
    total_sales_period = 0.0
    audit_counters = {
        'total_transactions': 0,
        'logical_accounts': 0,
        'eligible_accounts': 0,
        'removed_or_ineligible_accounts': 0,
    }

    for session_data in sessions:
        for transaction in session_data.get('transactions', []):
            if not _is_ranking_transaction(transaction):
                continue
            t_date_str = transaction.get('timestamp')
            if not t_date_str:
                continue
            try:
                t_date = datetime.strptime(t_date_str, '%d/%m/%Y %H:%M')
            except Exception:
                continue
            if not (start_date_comp <= t_date <= end_date_comp):
                continue
            details = _get_transaction_details(transaction)
            reference_key = _get_commission_reference(transaction, details)
            waiter_breakdown = _normalize_waiter_breakdown_map(_get_waiter_breakdown(transaction))
            try:
                tx_amount = float(transaction.get('amount', 0) or 0)
            except Exception:
                tx_amount = 0.0
            group = logical_groups.get(reference_key)
            if not group:
                group = {
                    'reference_key': reference_key,
                    'reference': _get_reference_label(transaction, details),
                    'timestamp': t_date_str,
                    'amount': 0.0,
                    'payment_methods': set(),
                    'operators': set(),
                    'waiters': set(),
                    'service_fee_removed': False,
                    'commission_eligible_values': [],
                    'waiter_breakdown': {},
                    'waiter_breakdown_sum': 0.0,
                }
                logical_groups[reference_key] = group
            group['amount'] += tx_amount
            group['timestamp'] = max(group.get('timestamp') or '', t_date_str)
            pm = transaction.get('payment_method') or '-'
            group['payment_methods'].add(str(pm))
            operator_name = transaction.get('operator') or details.get('operator') or _get_operator_name(transaction, session_data)
            group['operators'].add(str(operator_name or '-'))
            if waiter_breakdown:
                current_sum = sum(max(0.0, float(v or 0)) for v in waiter_breakdown.values())
                if current_sum >= group.get('waiter_breakdown_sum', 0.0):
                    group['waiter_breakdown'] = waiter_breakdown
                    group['waiter_breakdown_sum'] = current_sum
                for waiter_name in waiter_breakdown.keys():
                    group['waiters'].add(waiter_name)
            else:
                fallback_waiter = transaction.get('waiter') or transaction.get('user') or 'Sem Colaborador'
                group['waiters'].add(str(fallback_waiter))
            group['service_fee_removed'] = bool(group['service_fee_removed'] or is_service_fee_removed_for_transaction(transaction))
            if 'commission_eligible' in transaction:
                group['commission_eligible_values'].append(bool(transaction.get('commission_eligible')))
            elif 'commission_eligible' in details:
                group['commission_eligible_values'].append(bool(details.get('commission_eligible')))
            audit_counters['total_transactions'] += 1

    ranking = []
    removed_events = []
    removed_total_sales = 0.0
    removed_total_commission = 0.0
    total_commission = 0.0

    for group in logical_groups.values():
        total_sales_period += group.get('amount', 0.0)
        audit_counters['logical_accounts'] += 1
        explicit_eligible = True
        if group.get('commission_eligible_values'):
            explicit_eligible = all(bool(v) for v in group.get('commission_eligible_values'))
        is_removed = bool(group.get('service_fee_removed'))
        is_commission_eligible = bool(explicit_eligible and not is_removed)
        if is_commission_eligible:
            audit_counters['eligible_accounts'] += 1
        else:
            audit_counters['removed_or_ineligible_accounts'] += 1
        breakdown = group.get('waiter_breakdown') or {}
        breakdown_sum = sum(max(0.0, float(v or 0)) for v in breakdown.values())
        waiter_distribution = {}
        if breakdown and breakdown_sum > 0:
            for waiter_name, amount in breakdown.items():
                try:
                    share = float(amount or 0) / breakdown_sum
                except Exception:
                    share = 0.0
                if share > 0:
                    waiter_distribution[waiter_name] = share
        if not waiter_distribution:
            fallback_waiter = next(iter(group.get('waiters') or ['Sem Colaborador']))
            waiter_distribution[fallback_waiter] = 1.0
        for waiter_name, share in waiter_distribution.items():
            allocated_amount = group.get('amount', 0.0) * share
            if waiter_name not in waiter_stats:
                waiter_stats[waiter_name] = {'total': 0.0, 'commissionable': 0.0, 'logical_refs': set()}
            waiter_stats[waiter_name]['total'] += allocated_amount
            waiter_stats[waiter_name]['logical_refs'].add(group.get('reference_key'))
            if is_commission_eligible:
                waiter_stats[waiter_name]['commissionable'] += allocated_amount
        if not is_commission_eligible:
            removed_total_sales += group.get('amount', 0.0)
            removed_total_commission += group.get('amount', 0.0) * (commission_rate / 100.0)
            removed_events.append({
                'timestamp': group.get('timestamp', '-'),
                'reference': group.get('reference', '-'),
                'reference_key': group.get('reference_key'),
                'operator': ", ".join(sorted(list(group.get('operators', set())))) if group.get('operators') else '-',
                'amount': group.get('amount', 0.0),
                'commission': group.get('amount', 0.0) * (commission_rate / 100.0),
                'reason': '10% removido' if is_removed else 'Não elegível',
                'payment_methods': ", ".join(sorted(list(group.get('payment_methods', set())))) if group.get('payment_methods') else '-',
                'waiters': ", ".join(sorted(list(group.get('waiters', set())))) if group.get('waiters') else '-'
            })

    for waiter, stats in waiter_stats.items():
        base_calc = stats.get('commissionable', 0.0)
        comm_val = base_calc * (commission_rate / 100.0)
        ranking.append({
            'waiter': waiter,
            'total': stats.get('total', 0.0),
            'count': len(stats.get('logical_refs', set())),
            'commission': comm_val
        })
        total_commission += comm_val

    ranking.sort(key=lambda x: x['total'], reverse=True)
    removed_events.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    try:
        log_system_action(
            action='COMMISSION_RANKING_VIEW',
            details={
                'start_date': start_date_str,
                'end_date': end_date_str,
                'commission_rate': commission_rate,
                'audit_counters': audit_counters,
                'total_sales_period': total_sales_period,
                'removed_total_sales': removed_total_sales,
            },
            user=session.get('user', 'Sistema'),
            category='Financeiro'
        )
    except Exception:
        pass
    
    return render_template('commission_ranking.html', 
                           ranking=ranking, 
                           removed_events=removed_events,
                           start_date=start_date_str, 
                           end_date=end_date_str, 
                           commission_rate=commission_rate,
                           total_sales=total_sales_period,
                           total_commission=total_commission,
                           removed_total_sales=removed_total_sales,
                           removed_total_commission=removed_total_commission)

@finance_bp.route('/admin/invoice-report', methods=['GET'])
@login_required
def admin_invoice_report():
    if session.get('role') != 'admin':
        flash('Acesso restrito à Diretoria.')
        return redirect(url_for('main.index'))

    # Security Check: Sensitive Access
    try:
        check_sensitive_access(
            action="Relatório Financeiro",
            user=session.get('user', 'Admin'),
            details="Acesso ao relatório de faturamento/notas fiscais."
        )
    except Exception as e:
        print(f"Security Log Error: {e}")

    sessions = _load_cashier_sessions()
    # load_payment_methods is in data_service? No, it was local in app.py then moved.
    # Check import. It is in app.services.data_service in app.py now (after my previous fix).
    # I imported load_payment_methods in routes.py imports? No, I missed it.
    # Let's assume it's there or import it. I'll add it to the import list above.
    from app.services.data_service import load_payment_methods
    payment_methods = load_payment_methods()
    
    # Get filters
    filter_method = request.args.get('payment_method')
    filter_invoice = request.args.get('invoice_status') # 'all', 'yes', 'no'
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    report_data = []

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%d/%m/%Y %H:%M')
        except ValueError:
            return datetime.min

    for s in sessions:
        for t in s.get('transactions', []):
            is_restaurant_sale = t.get('type') == 'sale'
            is_reception_payment = t.get('type') == 'in' and t.get('category') == 'Pagamento de Conta'
            if not is_restaurant_sale and not is_reception_payment:
                continue

            # Check dates
            t_date = parse_date(t.get('timestamp', ''))
            if start_date:
                try:
                    s_date = datetime.strptime(start_date, '%Y-%m-%d')
                    if t_date < s_date: continue
                except ValueError: pass
            if end_date:
                try:
                    e_date = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                    if t_date >= e_date: continue
                except ValueError: pass

            # Check payment method
            if filter_method and t.get('payment_method') != filter_method:
                continue

            # Check invoice status
            invoice_val = t.get('emit_invoice', False)
            if filter_invoice == 'yes' and not invoice_val:
                continue
            if filter_invoice == 'no' and invoice_val:
                continue
            
            if 'amount' in t:
                try:
                    t['amount'] = float(t.get('amount', 0))
                except (TypeError, ValueError):
                    t['amount'] = 0.0

            report_data.append(t)

    # Sort descending
    report_data.sort(key=lambda x: parse_date(x.get('timestamp', '')), reverse=True)

    return render_template('admin_invoice_report.html', 
                           report_data=report_data, 
                           payment_methods=payment_methods,
                           today=datetime.now().strftime('%Y-%m-%d'))

@finance_bp.route('/accounting')
@login_required
def accounting_dashboard():
    # Only allow Admin or specific roles
    if session.get('role') != 'admin' and 'financeiro' not in session.get('permissions', []):
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    # Scan fiscal_xmls directory
    base_dir = os.path.join(os.getcwd(), 'fiscal_xmls')
    structure = {}
    
    if os.path.exists(base_dir):
        for cnpj in os.listdir(base_dir):
            cnpj_path = os.path.join(base_dir, cnpj)
            if os.path.isdir(cnpj_path):
                structure[cnpj] = {}
                for month in os.listdir(cnpj_path):
                    month_path = os.path.join(cnpj_path, month)
                    if os.path.isdir(month_path):
                        files = [f for f in os.listdir(month_path) if f.endswith('.xml')]
                        structure[cnpj][month] = files
                        
    return render_template('accounting.html', structure=structure)

@finance_bp.route('/accounting/download/<cnpj>/<month>/<filename>')
@login_required
def accounting_download_file(cnpj, month, filename):
    # Security check to prevent directory traversal
    safe_cnpj = secure_filename(cnpj)
    safe_month = secure_filename(month)
    safe_filename = secure_filename(filename)
    
    directory = os.path.join(os.getcwd(), 'fiscal_xmls', safe_cnpj, safe_month)
    return send_from_directory(directory, safe_filename, as_attachment=True)

@finance_bp.route('/accounting/zip/<cnpj>/<month>')
@login_required
def accounting_download_zip(cnpj, month):
    safe_cnpj = secure_filename(cnpj)
    safe_month = secure_filename(month)
    
    directory = os.path.join(os.getcwd(), 'fiscal_xmls', safe_cnpj, safe_month)
    if not os.path.exists(directory):
        return "Diretório não encontrado", 404
        
    # Create a zip in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.xml'):
                    zf.write(os.path.join(root, file), file)
                    
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'xmls_{safe_cnpj}_{safe_month}.zip'
    )

@finance_bp.route('/admin/reconciliation')
@login_required
def finance_reconciliation():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
        
    results = {
        'matched': [],
        'unmatched_system': [],
        'unmatched_card': []
    }
    summary = {
        'matched_count': 0,
        'unmatched_system_count': 0,
        'unmatched_card_count': 0,
        'suspected_count': 0
    }
    
    settings = load_card_settings()
    today_date = datetime.now().strftime('%Y-%m-%d')
    pagseguro_accounts = _build_pagseguro_accounts_view(settings)
    pull_status = get_pull_status()
    
    return render_template(
        'finance_reconciliation.html',
        results=results,
        suspected_matches=[],
        summary=summary,
        settings=settings,
        pagseguro_accounts=pagseguro_accounts,
        pull_status=pull_status,
        today_date=today_date,
        start_date=today_date,
        end_date=today_date
    )

@finance_bp.route('/admin/reconciliation/account/add', methods=['POST'])
@login_required
def finance_reconciliation_add_account():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    settings = load_card_settings()
    provider = (request.form.get('provider') or 'pagseguro').strip().lower()
    alias = request.form.get('alias')
    
    if provider != 'pagseguro':
        flash('A reconciliação está restrita ao PagSeguro.')
        return redirect(url_for('finance.finance_reconciliation'))

    email = request.form.get('ps_email')
    token = request.form.get('ps_token')
    environment = (request.form.get('ps_environment') or 'production').strip().lower()
    sandbox = environment == 'sandbox'
    
    if 'pagseguro' not in settings:
        settings['pagseguro'] = []
    if isinstance(settings['pagseguro'], dict):
        settings['pagseguro'] = [settings['pagseguro']]
    
    settings['pagseguro'].append({
        'alias': alias,
        'email': email,
        'token': token,
        'sandbox': sandbox,
        'environment': environment,
        'health_status': 'not_tested',
        'last_test_at': '',
        'last_error': ''
    })
        
    save_card_settings(settings)
    flash('Conta adicionada com sucesso.')
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/admin/reconciliation/account/remove', methods=['POST'])
@login_required
def finance_reconciliation_remove_account():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    settings = load_card_settings()
    provider = (request.form.get('provider') or 'pagseguro').strip().lower()
    try:
        index = int(request.form.get('index'))
    except:
        flash('Índice inválido.')
        return redirect(url_for('finance.finance_reconciliation'))
    
    if provider != 'pagseguro':
        flash('A reconciliação está restrita ao PagSeguro.')
        return redirect(url_for('finance.finance_reconciliation'))
    if provider in settings:
        config_list = settings[provider]
        if isinstance(config_list, list) and 0 <= index < len(config_list):
            removed = config_list.pop(index)
            save_card_settings(settings)
            flash(f"Conta '{removed.get('alias')}' removida.")
            
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/admin/reconciliation/account/update', methods=['POST'])
@login_required
def finance_reconciliation_update_account():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
    settings = load_card_settings()
    provider = (request.form.get('provider') or 'pagseguro').strip().lower()
    if provider != 'pagseguro':
        flash('A reconciliação está restrita ao PagSeguro.')
        return redirect(url_for('finance.finance_reconciliation'))
    try:
        index = int(request.form.get('index'))
    except Exception:
        flash('Índice inválido.')
        return redirect(url_for('finance.finance_reconciliation'))
    alias = str(request.form.get('alias') or '').strip()
    email = str(request.form.get('ps_email') or '').strip()
    environment = (request.form.get('ps_environment') or 'production').strip().lower()
    if environment not in {'production', 'sandbox'}:
        environment = 'production'
    if not alias or not email:
        flash('Alias e e-mail são obrigatórios para editar a conta.')
        return redirect(url_for('finance.finance_reconciliation'))
    config_list = settings.get('pagseguro')
    if isinstance(config_list, dict):
        config_list = [config_list]
    if not isinstance(config_list, list) or not (0 <= index < len(config_list)):
        flash('Conta PagSeguro não encontrada para edição.')
        return redirect(url_for('finance.finance_reconciliation'))
    current = dict(config_list[index] or {})
    previous_token = str(current.get('token') or '')
    new_token = str(request.form.get('ps_token') or '').strip()
    token_to_save = new_token if new_token else previous_token
    changed_credentials = (
        str(current.get('email') or '').strip() != email
        or _pagseguro_environment_label(current) != environment
        or bool(new_token)
    )
    current['alias'] = alias
    current['email'] = email
    current['token'] = token_to_save
    current['environment'] = environment
    current['sandbox'] = environment == 'sandbox'
    if changed_credentials:
        current['health_status'] = 'not_tested'
        current['last_error'] = ''
        current['last_test_at'] = ''
        current['last_http_status'] = None
    config_list[index] = current
    settings['pagseguro'] = config_list
    save_card_settings(settings)
    flash(f"Conta '{alias}' atualizada com sucesso.")
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/admin/reconciliation/account/edit/<int:index>', methods=['GET'])
@login_required
def finance_reconciliation_edit_account(index):
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
    settings = load_card_settings()
    config_list = settings.get('pagseguro')
    if isinstance(config_list, dict):
        config_list = [config_list]
    if not isinstance(config_list, list) or not (0 <= index < len(config_list)):
        flash('Conta PagSeguro não encontrada para edição.')
        return redirect(url_for('finance.finance_reconciliation'))
    account = dict(config_list[index] or {})
    return render_template(
        'finance_reconciliation_edit_account.html',
        account_index=index,
        account={
            'alias': account.get('alias') or '',
            'email': account.get('email') or '',
            'environment': _pagseguro_environment_label(account),
        },
    )

@finance_bp.route('/admin/reconciliation/health-check', methods=['POST'])
@login_required
def finance_reconciliation_health_check():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
    settings = load_card_settings()
    if isinstance(settings.get('pagseguro'), dict):
        settings['pagseguro'] = [settings['pagseguro']]
    accounts = settings.get('pagseguro') or []
    if not isinstance(accounts, list) or not accounts:
        flash('Nenhuma conta PagSeguro configurada para teste.')
        return redirect(url_for('finance.finance_reconciliation'))
    check_index_raw = (request.form.get('index') or '').strip()
    indexes = []
    if check_index_raw:
        try:
            idx = int(check_index_raw)
            if 0 <= idx < len(accounts):
                indexes = [idx]
        except Exception:
            indexes = []
        if not indexes:
            flash('Conta selecionada para teste não é válida.')
            return redirect(url_for('finance.finance_reconciliation'))
    else:
        indexes = list(range(len(accounts)))
    ok_count = 0
    err_count = 0
    error_details = []
    for idx in indexes:
        account = dict(accounts[idx] or {})
        result = _check_pagseguro_account_health(account)
        account['health_status'] = result.get('status') or 'error'
        account['last_test_at'] = result.get('tested_at') or datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        account['last_error'] = result.get('error_message') or ''
        account['last_http_status'] = result.get('http_status')
        accounts[idx] = account
        if account['health_status'] == 'ok':
            ok_count += 1
        else:
            err_count += 1
            alias = str(account.get('alias') or f'Conta {idx + 1}')
            err_msg = str(account.get('last_error') or 'Erro desconhecido')
            error_details.append(f"{alias}: {err_msg}")
        append_reconciliation_audit({
            'id': f"RECON_HEALTH_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'source': 'health_check',
            'provider': 'pagseguro',
            'period_start': '',
            'period_end': '',
            'user': session.get('user'),
            'summary': {'ok': 1 if account['health_status'] == 'ok' else 0, 'error': 1 if account['health_status'] != 'ok' else 0},
            'results': {
                'alias': account.get('alias'),
                'environment': _pagseguro_environment_label(account),
                'status': account.get('health_status'),
                'http_status': account.get('last_http_status'),
                'error': account.get('last_error'),
                'tested_at': account.get('last_test_at')
            }
        })
    settings['pagseguro'] = accounts
    save_card_settings(settings)
    flash(f'Health check finalizado: {ok_count} OK, {err_count} com erro.')
    if error_details:
        for detail in error_details[:5]:
            flash(f'Falha PagSeguro - {detail}')
        if len(error_details) > 5:
            flash(f'... e mais {len(error_details) - 5} conta(s) com erro. Abra Configurar para ver detalhes completos.')
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/admin/reconciliation/sync', methods=['POST'])
@login_required
def finance_reconciliation_sync():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    provider = (request.form.get('provider') or 'pagseguro').strip().lower()
    start_date_str = (request.form.get('start_date') or '').strip()
    end_date_str = (request.form.get('end_date') or '').strip()
    date_str = (request.form.get('date') or '').strip()

    if not start_date_str and not end_date_str and date_str:
        start_date_str = date_str
        end_date_str = date_str

    if not start_date_str or not end_date_str:
        flash('Selecione o período inicial e final.')
        return redirect(url_for('finance.finance_reconciliation'))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except:
        flash('Data inválida.')
        return redirect(url_for('finance.finance_reconciliation'))

    if end_date < start_date:
        flash('Período inválido: data final menor que data inicial.')
        return redirect(url_for('finance.finance_reconciliation'))

    card_transactions = []
    
    if provider != 'pagseguro':
        flash('A reconciliação está restrita ao PagSeguro.')
        return redirect(url_for('finance.finance_reconciliation'))
    fetch_detail = fetch_pagseguro_transactions_detailed(start_date, end_date)
    card_transactions = fetch_detail.get('transactions', []) if isinstance(fetch_detail, dict) else []
    if not card_transactions:
        flash('Nenhuma transação encontrada ou erro na API PagSeguro (verifique credenciais).')
    
    start_search = start_date
    end_search = end_date
    
    sessions = _load_cashier_sessions()
    system_transactions = []
    
    for s in sessions:
        session_type = str(s.get('type', '')).lower()
        if session_type not in ['guest_consumption', 'reception_room_billing', 'reservation_cashier', 'reception', 'restaurant', 'restaurant_service']:
            continue
        for tx in s.get('transactions', []):
            if tx['type'] == 'sale': 
                try:
                    tx_time = datetime.strptime(tx['timestamp'], '%d/%m/%Y %H:%M')
                    if start_search <= tx_time <= end_search:
                        pm = tx.get('payment_method', '').lower()
                        if 'dinheiro' not in pm and 'pix' not in pm:
                            system_transactions.append({
                                'id': tx['id'],
                                'timestamp': tx_time,
                                'amount': float(tx['amount']),
                                'description': tx['description'],
                                'payment_method': tx['payment_method'],
                                'details': tx.get('details', {}),
                                'user': tx.get('user', ''),
                                'room_number': _extract_room_number_from_transaction(tx),
                                'guest_name': _extract_guest_name_from_transaction(tx)
                            })
                except:
                    continue
                    
    consumption_map = load_card_consumption_map()
    results = reconcile_transactions(system_transactions, card_transactions, consumption_map=consumption_map)
    
    settings = load_card_settings()
    pagseguro_accounts = _normalize_pagseguro_configs(settings)
    if len(pagseguro_accounts) > 1:
        flash(f'Conciliação PagSeguro processada em {len(pagseguro_accounts)} tokens.')
    results = _annotate_reconciliation_results(results, settings)
    approved_signatures = _load_manual_approval_signatures()
    suspected_matches = _build_suspected_time_gap_matches(
        results.get('unmatched_system', []),
        results.get('unmatched_card', [])
    )
    suspected_matches = _apply_manual_approved_suspects(results, suspected_matches, approved_signatures)
    results = _annotate_reconciliation_results(results, settings)
    summary = {
        'matched_count': len(results['matched']),
        'unmatched_system_count': len(results['unmatched_system']),
        'unmatched_card_count': len(results['unmatched_card']),
        'suspected_count': len(suspected_matches),
        'skipped_consumed_card_count': int(results.get('skipped_consumed_card_count') or 0),
        'pagseguro_total_accounts': int((fetch_detail or {}).get('total_accounts') or 0),
        'pagseguro_processed_accounts': int((fetch_detail or {}).get('processed_accounts') or 0),
        'pagseguro_errors': len((fetch_detail or {}).get('errors') or [])
    }
    display_start = start_date.strftime('%Y-%m-%d')
    display_end = end_date.strftime('%Y-%m-%d')
    _save_reconciliation_audit(
        source='api_sync',
        provider=provider,
        start_date=display_start,
        end_date=display_end,
        results=results,
        summary=summary
    )
    consumed_count = register_consumed_card_matches(
        results.get('matched', []),
        source='api_sync',
        period_start=display_start,
        period_end=display_end,
        user=session.get('user') or ''
    )
    if consumed_count:
        flash(f'{consumed_count} pagamentos PagSeguro vinculados e bloqueados para reuso em outros caixas.')
    if summary['skipped_consumed_card_count'] > 0:
        flash(f"{summary['skipped_consumed_card_count']} pagamentos já conciliados foram ignorados para evitar reuso.")
    if summary['pagseguro_errors'] > 0:
        flash(f"{summary['pagseguro_errors']} ocorrências de erro em contas PagSeguro durante o pull.")
    log_system_action(
        'Conciliação de Cartões',
        {
            'provider': provider,
            'period_start': display_start,
            'period_end': display_end,
            'matched_count': summary['matched_count'],
            'unmatched_system_count': summary['unmatched_system_count'],
            'unmatched_card_count': summary['unmatched_card_count'],
            'user': session.get('user')
        },
        category='Financeiro'
    )

    return render_template(
        'finance_reconciliation.html',
        results=results,
        suspected_matches=suspected_matches,
        summary=summary,
        settings=settings,
        pagseguro_accounts=_build_pagseguro_accounts_view(settings),
        pull_status=get_pull_status(),
        today_date=display_start,
        start_date=display_start,
        end_date=display_end
    )


@finance_bp.route('/admin/reconciliation/pagseguro/daily-pull', methods=['POST'])
@login_required
def finance_reconciliation_daily_pull():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))
    target = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        output = run_pagseguro_daily_pull(
            date_ref=target,
            source='manual_admin',
            requested_by=session.get('user') or 'admin',
            force=True
        )
        snapshot = output.get('snapshot') or {}
        status_info = output.get('status') or {}
        flash(
            f"Pull diário PagSeguro ({status_info.get('status', 'not_run')}) para {snapshot.get('date_ref') or target}. "
            f"Transações: {snapshot.get('normalized_count', 0)}."
        )
    except Exception as exc:
        flash(f'Falha no pull diário PagSeguro: {exc}')
    return redirect(url_for('finance.finance_reconciliation'))


@finance_bp.route('/admin/reconciliation/pagseguro/daily-pull/dev', methods=['POST'])
@login_required
def finance_reconciliation_daily_pull_dev():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso Restrito.'}), 403
    runtime_env = str(current_app.config.get('ALMAREIA_RUNTIME_ENV') or '').strip().lower()
    if runtime_env != 'development':
        return jsonify({'success': False, 'message': 'Endpoint DEV-only indisponível em produção.'}), 403
    payload = request.json or {}
    target_date = str(payload.get('date') or '').strip()
    if not target_date:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        output = run_pagseguro_daily_pull(
            date_ref=target_date,
            source='dev_manual',
            requested_by=session.get('user') or 'admin',
            force=True
        )
        snapshot = output.get('snapshot') or {}
        status_info = output.get('status') or {}
        return jsonify({
            'success': bool(output.get('success')),
            'status': status_info.get('status', 'not_run'),
            'date_ref': snapshot.get('date_ref'),
            'normalized_count': snapshot.get('normalized_count', 0)
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500


@finance_bp.route('/admin/reconciliation/pagseguro/daily-pull/status', methods=['GET'])
@login_required
def finance_reconciliation_daily_pull_status():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso Restrito.'}), 403
    return jsonify({'success': True, 'data': get_pull_status()})

@finance_bp.route('/admin/reconciliation/upload', methods=['POST'])
@login_required
def finance_reconciliation_upload():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    if 'file' not in request.files:
        flash('Nenhum arquivo enviado.')
        return redirect(url_for('finance.finance_reconciliation'))
        
    file = request.files['file']
    provider = (request.form.get('provider') or 'pagseguro').strip().lower()
    
    if file.filename == '':
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('finance.finance_reconciliation'))
        
    if file:
        filename = secure_filename(file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER') or os.path.join(os.getcwd(), 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        if provider != 'pagseguro':
            flash('A reconciliação por arquivo está restrita ao PagSeguro.')
            return redirect(url_for('finance.finance_reconciliation'))
        card_transactions = parse_pagseguro_csv(filepath)
        
        if not card_transactions:
            flash('Não foi possível ler as transações do arquivo. Verifique o formato.')
            return redirect(url_for('finance.finance_reconciliation'))
            
        dates = [t['date'] for t in card_transactions]
        if not dates:
            flash('Arquivo sem datas válidas.')
            return redirect(url_for('finance.finance_reconciliation'))
            
        min_date = min(dates)
        max_date = max(dates)
        
        start_search = min_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_search = max_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        sessions = _load_cashier_sessions()
        system_transactions = []
        
        for s in sessions:
            session_type = str(s.get('type', '')).lower()
            if session_type not in ['guest_consumption', 'reception_room_billing', 'reservation_cashier', 'reception', 'restaurant', 'restaurant_service']:
                continue
            for tx in s.get('transactions', []):
                if tx['type'] == 'sale': 
                    try:
                        tx_time = datetime.strptime(tx['timestamp'], '%d/%m/%Y %H:%M')
                        if start_search <= tx_time <= end_search:
                            pm = tx.get('payment_method', '').lower()
                            if 'dinheiro' not in pm and 'pix' not in pm:
                                system_transactions.append({
                                    'id': tx['id'],
                                    'timestamp': tx_time,
                                    'amount': float(tx['amount']),
                                    'description': tx['description'],
                                    'payment_method': tx['payment_method'],
                                    'details': tx.get('details', {}),
                                    'user': tx.get('user', ''),
                                    'room_number': _extract_room_number_from_transaction(tx),
                                    'guest_name': _extract_guest_name_from_transaction(tx)
                                })
                    except:
                        continue
                        
        results = reconcile_transactions(system_transactions, card_transactions)
        
        try:
            os.remove(filepath)
        except: pass
        settings = load_card_settings()
        results = _annotate_reconciliation_results(results, settings)
        approved_signatures = _load_manual_approval_signatures()
        suspected_matches = _build_suspected_time_gap_matches(
            results.get('unmatched_system', []),
            results.get('unmatched_card', [])
        )
        suspected_matches = _apply_manual_approved_suspects(results, suspected_matches, approved_signatures)
        results = _annotate_reconciliation_results(results, settings)
        summary = {
            'matched_count': len(results['matched']),
            'unmatched_system_count': len(results['unmatched_system']),
            'unmatched_card_count': len(results['unmatched_card']),
            'suspected_count': len(suspected_matches)
        }
        display_start = min_date.strftime('%Y-%m-%d')
        display_end = max_date.strftime('%Y-%m-%d')
        _save_reconciliation_audit(
            source='file_upload',
            provider=provider,
            start_date=display_start,
            end_date=display_end,
            results=results,
            summary=summary
        )
        log_system_action(
            'Conciliação de Cartões via Arquivo',
            {
                'provider': provider,
                'period_start': display_start,
                'period_end': display_end,
                'matched_count': summary['matched_count'],
                'unmatched_system_count': summary['unmatched_system_count'],
                'unmatched_card_count': summary['unmatched_card_count'],
                'user': session.get('user'),
                'filename': filename
            },
            category='Financeiro'
        )
        
        return render_template(
            'finance_reconciliation.html',
            results=results,
            suspected_matches=suspected_matches,
            summary=summary,
            settings=settings,
            pagseguro_accounts=_build_pagseguro_accounts_view(settings),
            pull_status=get_pull_status(),
            today_date=display_start,
            start_date=display_start,
            end_date=display_end
        )
        
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/config/fiscal/emit/<entry_id>', methods=['POST'])
@login_required
def fiscal_emit(entry_id):
    if session.get('role') not in ['admin', 'gerente']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404
        
    if entry['status'] == 'emitted':
        return jsonify({'success': False, 'error': 'Nota já emitida'}), 400
        
    try:
        process_result = process_pending_emissions(specific_id=entry_id)
        refreshed = FiscalPoolService.get_entry(entry_id) or {}
        if process_result.get('success', 0) > 0 and refreshed.get('status') == 'emitted':
            nfe_id = refreshed.get('fiscal_doc_uuid')
            log_system_action('Emissão Fiscal Admin', {
                'entry_id': entry_id,
                'nfe_id': nfe_id,
                'amount': refreshed.get('total_amount'),
                'user': session.get('user')
            }, category='Fiscal')
            return jsonify({'success': True, 'message': 'Nota emitida com sucesso', 'nfe_id': nfe_id})

        error_msg = refreshed.get('last_error') or 'Falha ao emitir NFC-e (SEFAZ não autorizou ou XML indisponível).'
        log_system_action('Erro Emissão Fiscal Admin', {
            'entry_id': entry_id,
            'error': error_msg,
            'user': session.get('user')
        }, category='Fiscal')
        return jsonify({'success': False, 'error': error_msg}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@finance_bp.route('/config/fiscal/print/<entry_id>', methods=['POST'])
@login_required
def fiscal_print(entry_id):
    if session.get('role') not in ['admin', 'gerente']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404

    if entry.get('status') != 'emitted':
        return jsonify({'success': False, 'error': 'Nota ainda não foi emitida'}), 400

    fiscal_doc_uuid = entry.get('fiscal_doc_uuid')
    if not fiscal_doc_uuid:
        return jsonify({'success': False, 'error': 'UUID fiscal não encontrado'}), 400

    try:
        settings = load_fiscal_settings()
        payment_methods = entry.get('payment_methods', [])
        target_cnpj = None
        for pm in payment_methods:
            if pm.get('fiscal_cnpj'):
                target_cnpj = pm.get('fiscal_cnpj')
                break

        integration_settings = get_fiscal_integration(settings, target_cnpj)
        if not integration_settings:
            return jsonify({'success': False, 'error': 'Configuração fiscal não encontrada'}), 400

        import xml.etree.ElementTree as ET
        import re as _re

        xml_path = download_xml(fiscal_doc_uuid, integration_settings)

        invoice_data = {
            "valor_total": float(entry.get('total_amount', 0.0) or 0.0),
            "ambiente": "homologacao" if integration_settings.get('environment') == 'homologation' else "producao",
        }

        if xml_path and os.path.exists(xml_path):
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()

                for elem in root.iter():
                    tag = elem.tag.split('}')[-1]
                    if tag == 'infNFe' and not invoice_data.get('chave'):
                        _id = elem.attrib.get('Id') or elem.attrib.get('id')
                        if _id:
                            invoice_data['chave'] = _re.sub(r'[^0-9]', '', _id)
                    elif tag == 'chNFe' and elem.text and not invoice_data.get('chave'):
                        invoice_data['chave'] = _re.sub(r'[^0-9]', '', elem.text)
                    elif tag == 'nProt' and elem.text:
                        invoice_data.setdefault('autorizacao', {})['numero_protocolo'] = elem.text.strip()
                    elif tag == 'dhEmi' and elem.text and not invoice_data.get('data_emissao'):
                        invoice_data['data_emissao'] = elem.text.strip()
                    elif tag == 'vNF' and elem.text:
                        try:
                            invoice_data['valor_total'] = float(elem.text.replace(',', '.'))
                        except Exception:
                            pass

                items = []
                for det in root.iter():
                    tag = det.tag.split('}')[-1]
                    if tag != 'det':
                        continue
                    prod = None
                    for child in list(det):
                        ctag = child.tag.split('}')[-1]
                        if ctag == 'prod':
                            prod = child
                            break
                    if prod is None:
                        continue
                    data = {}
                    for child in list(prod):
                        ctag = child.tag.split('}')[-1]
                        if ctag == 'cProd':
                            data['code'] = (child.text or '').strip()
                        elif ctag == 'xProd':
                            data['name'] = (child.text or '').strip()
                        elif ctag == 'qCom':
                            try:
                                data['qty'] = float(str(child.text).replace(',', '.'))
                            except Exception:
                                data['qty'] = 0.0
                        elif ctag == 'uCom':
                            data['unit'] = (child.text or '').strip()
                        elif ctag == 'vUnCom':
                            try:
                                data['unit_price'] = float(str(child.text).replace(',', '.'))
                            except Exception:
                                data['unit_price'] = 0.0
                        elif ctag == 'vProd':
                            try:
                                data['total'] = float(str(child.text).replace(',', '.'))
                            except Exception:
                                data['total'] = 0.0
                    if data:
                        items.append(data)

                if items:
                    invoice_data['items'] = items

            except Exception:
                pass
        else:
            items = []
            for it in entry.get('items', []):
                data = {
                    'code': str(it.get('id') or it.get('code') or ''),
                    'name': str(it.get('name') or ''),
                    'qty': float(it.get('qty', 0.0) or 0.0),
                    'unit': str(it.get('unit', 'UN') or 'UN'),
                    'unit_price': float(it.get('price', 0.0) or 0.0),
                }
                data['total'] = round(data['qty'] * data['unit_price'], 2)
                items.append(data)
            if items:
                invoice_data['items'] = items

        ok, err = print_fiscal_receipt({}, invoice_data, force_print=True)
        if not ok:
            return jsonify({'success': False, 'error': err or 'Falha ao imprimir'}), 500

        return jsonify({'success': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
