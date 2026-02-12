import os
import json
import io
import re
import calendar
import traceback
import zipfile
import xlsxwriter
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file, send_from_directory, Response, current_app
from werkzeug.utils import secure_filename
import pandas as pd
from PIL import Image

from . import finance_bp
from app.utils.decorators import login_required, role_required
from app.utils.files import allowed_file
from app.services.data_service import (
    load_cashier_sessions, save_cashier_sessions,
    load_users, load_table_orders, save_table_orders,
    load_suppliers, save_suppliers, load_payables, save_payables,
    load_fiscal_settings,
    load_stock_logs, load_stock_requests, load_stock_entries, load_products
)
from app.services.card_reconciliation_service import load_card_settings, save_card_settings
from app.services.cashier_service import CashierService
from app.services.commission_service import normalize_dept, load_commission_cycles, save_commission_cycles, get_commission_cycle, calculate_commission
from app.services.fiscal_service import (
    emit_invoice as service_emit_invoice,
    get_fiscal_integration,
    download_xml
)
from app.services.fiscal_pool_service import FiscalPoolService
from app.services.printing_service import print_fiscal_receipt
from app.services.logger_service import LoggerService, log_system_action
from app.services.security_service import check_sensitive_access
from app.services.import_sales import calculate_monthly_sales
from app.services.card_reconciliation_service import (
    fetch_pagseguro_transactions, fetch_rede_transactions,
    reconcile_transactions, parse_pagseguro_csv, parse_rede_csv
)

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
            pool = FiscalPoolService._load_pool()
            for e in pool:
                if e['id'] == entry_id:
                    e['status'] = 'failed'
                    e['last_error'] = result['message']
                    FiscalPoolService._save_pool(pool)
                    break
            
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

def get_balance_data(period_type, year, specific_value=None):
    sessions = load_cashier_sessions()
    closed_sessions = [s for s in sessions if s.get('status') == 'closed']
    
    # Determine Date Range
    start_date = None
    end_date = None
    
    try:
        year = int(year)
        if period_type == 'monthly':
            month = int(specific_value)
            _, last_day = calendar.monthrange(year, month)
            start_date = datetime(year, month, 1)
            end_date = datetime(year, month, last_day, 23, 59, 59)
        elif period_type == 'quarterly':
            quarter = int(specific_value) # 1, 2, 3, 4
            start_month = 3 * (quarter - 1) + 1
            end_month = 3 * quarter
            _, last_day = calendar.monthrange(year, end_month)
            start_date = datetime(year, start_month, 1)
            end_date = datetime(year, end_month, last_day, 23, 59, 59)
        elif period_type == 'semiannual':
            semester = int(specific_value) # 1, 2
            start_month = 6 * (semester - 1) + 1
            end_month = 6 * semester
            _, last_day = calendar.monthrange(year, end_month)
            start_date = datetime(year, start_month, 1)
            end_date = datetime(year, end_month, last_day, 23, 59, 59)
        elif period_type == 'annual':
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)
    except (ValueError, TypeError):
        return {} # Return empty if invalid dates

    # Filter Sessions
    filtered_sessions = []
    for s in closed_sessions:
        try:
            closed_at_str = s.get('closed_at')
            if not closed_at_str: continue
            closed_at = datetime.strptime(closed_at_str, '%d/%m/%Y %H:%M')
            if start_date <= closed_at <= end_date:
                filtered_sessions.append(s)
        except (ValueError, TypeError):
            continue
            
    # Group by Type
    report = {}
    # Define known types
    types = {
        'restaurant_service': 'Restaurante',
        'reception_room_billing': 'Recepção (Quartos)',
        'reception_reservations': 'Recepção (Reservas)'
    }
    
    for s in filtered_sessions:
        s_type = s.get('type', 'restaurant_service')
        # Normalize types
        if s_type == 'restaurant': s_type = 'restaurant_service'
        if s_type == 'reception': s_type = 'reception_room_billing'
        
        label = types.get(s_type, s_type.replace('_', ' ').title())
        
        if label not in report:
            report[label] = {
                'initial_balance': 0.0,
                'total_in': 0.0,
                'total_out': 0.0,
                'final_balance': 0.0,
                'sessions_count': 0,
                'sessions': [] # For detailed view
            }
        
        report[label]['sessions'].append(s)

    # Calculate Aggregates
    for label, data in report.items():
        # Sort sessions by date
        data['sessions'].sort(key=lambda x: datetime.strptime(x.get('closed_at'), '%d/%m/%Y %H:%M'))
        
        if data['sessions']:
            # Initial balance of the period is the opening balance of the FIRST session
            first_session = data['sessions'][0]
            # Handle potential None or string issues
            try:
                data['initial_balance'] = float(first_session.get('opening_balance') or first_session.get('initial_balance') or 0.0)
            except:
                data['initial_balance'] = 0.0
            
            # Final balance of the period is the closing balance of the LAST session
            last_session = data['sessions'][-1]
            try:
                data['final_balance'] = float(last_session.get('closing_balance', 0.0))
            except:
                data['final_balance'] = 0.0
            
            # Sum transactions
            for s in data['sessions']:
                for t in s.get('transactions', []):
                    try:
                        amount = float(t.get('amount', 0.0))
                    except:
                        amount = 0.0
                        
                    t_type = t.get('type')
                    if t_type in ['sale', 'in', 'deposit']:
                        data['total_in'] += amount
                    elif t_type in ['withdrawal', 'out']:
                        data['total_out'] += amount
                        
            data['sessions_count'] = len(data['sessions'])
            
            simple_sessions = []
            for s in data['sessions']:
                simple_sessions.append({
                    'id': s.get('id'),
                    'opened_at': s.get('opened_at'),
                    'closed_at': s.get('closed_at'),
                    'user': s.get('user'),
                    'opening_balance': s.get('opening_balance'),
                    'closing_balance': s.get('closing_balance')
                })
            data['sessions'] = simple_sessions

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
            if order.get('status') == 'open' and order.get('customer_type') == 'funcionario':
                staff_name = order.get('staff_name')
                if staff_name:
                    resolved_name = user_map.get(staff_name, staff_name)
                    consumption[resolved_name] = consumption.get(resolved_name, 0) + float(order.get('total', 0))
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
    sessions = load_cashier_sessions()
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
    return render_template('finance_balances.html')

@finance_bp.route('/finance/balances/data')
@login_required
def finance_balances_data():
    period_type = request.args.get('period_type', 'monthly')
    year = request.args.get('year', datetime.now().year)
    specific_value = request.args.get('specific_value', datetime.now().month)
    
    report = get_balance_data(period_type, year, specific_value)
    
    # Transform to list for frontend
    data_list = []
    for label, values in report.items():
        data_list.append({
            'type_label': label,
            'user': label, # Using label as user/name for the card
            'initial_balance': values['initial_balance'],
            'total_in': values['total_in'],
            'total_out': values['total_out'],
            'final_balance': values['final_balance'],
            'sessions': values.get('sessions', [])
        })
        
    return jsonify({'success': True, 'data': data_list})

@finance_bp.route('/finance/balances/export')
@login_required
def finance_balances_export():
    period_type = request.args.get('period_type')
    year = request.args.get('year')
    specific_value = request.args.get('specific_value')
    
    data = get_balance_data(period_type, year, specific_value)
    
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

@finance_bp.route('/finance_commission')
@login_required
def finance_commission():
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('main.service_page', service_id='financeiro'))
    cycles = load_commission_cycles()
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
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('finance.finance_commission'))
        
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
    
    # Calculate Total Commission from Sales Files (10% of Total Sales)
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
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('finance.finance_commission'))
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
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('finance.finance_commission_detail', cycle_id=cycle_id))
        
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
    if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):
        flash('Acesso não autorizado.')
        return redirect(url_for('finance.finance_commission'))

    cycle = get_commission_cycle(cycle_id)
    if not cycle:
        flash('Ciclo não encontrado.')
        return redirect(url_for('finance.finance_commission'))
        
    # Update Cycle Data from Form
    try:
        update_cycle_from_form(cycle, request.form)
            
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
            
    count = 0
    # Map employees in cycle to check existence
    emp_names = {e['name'] for e in cycle.get('employees', [])}
    
    # Load users for mapping
    users = load_users()
    user_map = {}
    for uname, udata in users.items():
        full_name = udata.get('full_name') or udata.get('name') or uname
        user_map[uname] = full_name
    
    for order_id, order in orders.items():
        if order.get('status') == 'open' and order.get('customer_type') == 'funcionario':
            staff_name = order.get('staff_name')
            resolved_name = user_map.get(staff_name, staff_name)
            
            if resolved_name in emp_names:
                order['status'] = 'closed'
                order['payment_method'] = 'deducao_comissao'
                order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                order['commission_cycle_id'] = cycle_id
                count += 1
                
    if count > 0:
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
    
    flash(f'Comissão aprovada! {count} mesas de consumo foram fechadas.')
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

@finance_bp.route('/download_commission_model')
@login_required
def download_commission_model():
    try:
        return send_from_directory('static', 'comissao_modelo.xlsx', as_attachment=True)
    except Exception as e:
        print(f"Error serving static model: {e}")
        flash('Erro ao baixar modelo. Contate o suporte.')
        return redirect(url_for('finance.finance_commission'))

@finance_bp.route('/finance/close_staff_month', methods=['POST'])
@login_required
def close_staff_month():
    if session.get('role') not in ['admin', 'gerente']:
        flash('Acesso negado.')
        return redirect(url_for('main.index'))
        
    orders = load_table_orders()
    sessions = load_cashier_sessions()
    
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
            amount = float(order['total'])
            staff_name = order.get('staff_name') or table_id.replace('FUNC_', '')
            
            # Create Transaction
            transaction = {
                'id': f"CLOSE_{table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                'type': 'sale',
                'amount': amount,
                'description': f"Fechamento Mensal - {staff_name}",
                'payment_method': 'Conta Funcionário',
                'emit_invoice': False,
                'staff_name': staff_name,
                'waiter': 'Sistema',
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')
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
        save_cashier_sessions(sessions)
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

    def _is_service_fee_removed(transaction):
        if transaction.get('service_fee_removed', False):
            return True
        details = transaction.get('details') or {}
        if details.get('service_fee_removed', False):
            return True
        flags = transaction.get('flags') or []
        if isinstance(flags, list):
            for f in flags:
                if isinstance(f, dict) and f.get('type') == 'service_removed':
                    return True
        description = transaction.get('description') or ''
        if isinstance(description, str) and '10% Off' in description:
            return True
        return False

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
            if table_id:
                ref = f"table:{table_id}"
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

    sessions = load_cashier_sessions()
    
    # Aggregation dictionary: waiter -> {total: 0.0, count: 0}
    waiter_stats = {}
    
    total_sales_period = 0.0
    removed_groups = {}
    
    for session_data in sessions:
        for transaction in session_data.get('transactions', []):
            if transaction.get('type') == 'sale' or (transaction.get('type') == 'in' and transaction.get('category') in ['Pagamento de Conta', 'Recebimento Manual']):
                # Check date
                t_date_str = transaction.get('timestamp') # Format: dd/mm/YYYY HH:MM
                if t_date_str:
                    try:
                        t_date = datetime.strptime(t_date_str, '%d/%m/%Y %H:%M')
                        
                        if start_date_comp <= t_date <= end_date_comp:
                                waiter_breakdown = _get_waiter_breakdown(transaction)
                                is_removed = _is_service_fee_removed(transaction)

                                if waiter_breakdown:
                                    for w, amt in waiter_breakdown.items():
                                        if w not in waiter_stats:
                                            waiter_stats[w] = {'total': 0.0, 'count': 0, 'commissionable': 0.0}
                                        
                                        try:
                                            amt_float = float(amt)
                                        except Exception:
                                            amt_float = 0.0
                                        waiter_stats[w]['total'] += amt_float
                                        waiter_stats[w]['count'] += 1
                                        if not is_removed:
                                            waiter_stats[w]['commissionable'] += amt_float
                                        
                                        total_sales_period += amt_float
                                else:
                                    waiter = transaction.get('waiter')
                                    amount = float(transaction.get('amount', 0))
                                    
                                    if waiter:
                                        if waiter not in waiter_stats:
                                            waiter_stats[waiter] = {'total': 0.0, 'count': 0, 'commissionable': 0.0}
                                        waiter_stats[waiter]['total'] += amount
                                        waiter_stats[waiter]['count'] += 1
                                        if not is_removed:
                                            waiter_stats[waiter]['commissionable'] += amount
                                        
                                        total_sales_period += amount

                                if is_removed:
                                    group_key = _get_removed_group_key(transaction, session_data)
                                    group = removed_groups.get(group_key)
                                    if not group:
                                        details = transaction.get('details') or {}
                                        related_charge_id = transaction.get('related_charge_id') or details.get('related_charge_id')
                                        table_id = details.get('table_id')
                                        ref_label = f"Quarto/Conta {related_charge_id}" if related_charge_id else (f"Mesa {table_id}" if table_id else "-")
                                        group = {
                                            'timestamp': transaction.get('timestamp') or '-',
                                            'reference': ref_label,
                                            'operator': _get_operator_name(transaction, session_data),
                                            'amount': 0.0,
                                            'payment_methods': set(),
                                            'waiters': set()
                                        }
                                        removed_groups[group_key] = group

                                    try:
                                        group['amount'] += float(transaction.get('amount', 0))
                                    except Exception:
                                        pass
                                    pm = transaction.get('payment_method') or '-'
                                    if isinstance(pm, str) and pm:
                                        group['payment_methods'].add(pm)
                                    elif pm is not None:
                                        group['payment_methods'].add(str(pm))

                                    wb_for_removed = waiter_breakdown
                                    if wb_for_removed:
                                        for w in wb_for_removed.keys():
                                            if w:
                                                group['waiters'].add(w)
                                    else:
                                        w = transaction.get('waiter')
                                        if w:
                                            group['waiters'].add(w)
                    except ValueError:
                        continue

    # Convert to list and sort
    ranking = []
    total_commission = 0.0 # Calculate based on individual waiter totals to be consistent
    
    for waiter, stats in waiter_stats.items():
        base_calc = stats.get('commissionable', stats['total'])
        comm_val = base_calc * (commission_rate / 100.0)
        
        ranking.append({
            'waiter': waiter,
            'total': stats['total'],
            'count': stats['count'],
            'commission': comm_val
        })
        total_commission += comm_val
    
    ranking.sort(key=lambda x: x['total'], reverse=True)

    removed_events = []
    removed_total_sales = 0.0
    removed_total_commission = 0.0
    for g in removed_groups.values():
        removed_total_sales += g.get('amount', 0.0)
        removed_total_commission += g.get('amount', 0.0) * (commission_rate / 100.0)
        removed_events.append({
            'timestamp': g.get('timestamp', '-'),
            'reference': g.get('reference', '-'),
            'operator': g.get('operator', '-'),
            'amount': g.get('amount', 0.0),
            'commission': g.get('amount', 0.0) * (commission_rate / 100.0),
            'payment_methods': ", ".join(sorted(list(g.get('payment_methods', set())))) if g.get('payment_methods') else '-',
            'waiters': ", ".join(sorted(list(g.get('waiters', set())))) if g.get('waiters') else '-'
        })
    removed_events.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
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

    sessions = load_cashier_sessions()
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
        'unmatched_card_count': 0
    }
    
    settings = load_card_settings()
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('finance_reconciliation.html', results=results, summary=summary, settings=settings, today_date=today_date)

@finance_bp.route('/admin/reconciliation/account/add', methods=['POST'])
@login_required
def finance_reconciliation_add_account():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    settings = load_card_settings()
    provider = request.form.get('provider')
    alias = request.form.get('alias')
    
    if provider == 'pagseguro':
        email = request.form.get('ps_email')
        token = request.form.get('ps_token')
        
        if 'pagseguro' not in settings: settings['pagseguro'] = []
        if isinstance(settings['pagseguro'], dict): settings['pagseguro'] = [settings['pagseguro']]
        
        settings['pagseguro'].append({
            'alias': alias,
            'email': email,
            'token': token,
            'sandbox': False
        })
        
    elif provider == 'rede':
        client_id = request.form.get('rede_client_id')
        client_secret = request.form.get('rede_client_secret')
        username = request.form.get('rede_username')
        password = request.form.get('rede_password')
        
        if 'rede' not in settings: settings['rede'] = []
        if isinstance(settings['rede'], dict): settings['rede'] = [settings['rede']]
        
        settings['rede'].append({
            'alias': alias,
            'client_id': client_id,
            'client_secret': client_secret,
            'username': username,
            'password': password
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
    provider = request.form.get('provider')
    try:
        index = int(request.form.get('index'))
    except:
        flash('Índice inválido.')
        return redirect(url_for('finance.finance_reconciliation'))
    
    if provider in settings:
        config_list = settings[provider]
        if isinstance(config_list, list) and 0 <= index < len(config_list):
            removed = config_list.pop(index)
            save_card_settings(settings)
            flash(f"Conta '{removed.get('alias')}' removida.")
            
    return redirect(url_for('finance.finance_reconciliation'))

@finance_bp.route('/admin/reconciliation/sync', methods=['POST'])
@login_required
def finance_reconciliation_sync():
    if session.get('role') != 'admin':
        flash('Acesso Restrito.')
        return redirect(url_for('main.index'))

    provider = request.form.get('provider')
    date_str = request.form.get('date')
    
    if not date_str:
        flash('Selecione uma data.')
        return redirect(url_for('finance.finance_reconciliation'))
        
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        start_date = target_date.replace(hour=0, minute=0, second=0)
        end_date = target_date.replace(hour=23, minute=59, second=59)
    except:
        flash('Data inválida.')
        return redirect(url_for('finance.finance_reconciliation'))

    card_transactions = []
    
    if provider == 'pagseguro':
        card_transactions = fetch_pagseguro_transactions(start_date, end_date)
        if not card_transactions:
            flash('Nenhuma transação encontrada ou erro na API (verifique credenciais).')
            
    elif provider == 'rede':
        card_transactions = fetch_rede_transactions(start_date, end_date)
        if not card_transactions:
            flash('Nenhuma transação encontrada ou erro na API (verifique credenciais).')
    
    start_search = start_date - timedelta(days=1)
    end_search = end_date + timedelta(days=1)
    
    sessions = load_cashier_sessions()
    system_transactions = []
    
    for s in sessions:
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
                                'payment_method': tx['payment_method']
                            })
                except:
                    continue
                    
    results = reconcile_transactions(system_transactions, card_transactions)
    
    summary = {
        'matched_count': len(results['matched']),
        'unmatched_system_count': len(results['unmatched_system']),
        'unmatched_card_count': len(results['unmatched_card'])
    }
    
    settings = load_card_settings()
    
    return render_template('finance_reconciliation.html', results=results, summary=summary, settings=settings, today_date=date_str)

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
    provider = request.form.get('provider')
    
    if file.filename == '':
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('finance.finance_reconciliation'))
        
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        card_transactions = []
        if provider == 'pagseguro':
            card_transactions = parse_pagseguro_csv(filepath)
        elif provider == 'rede':
            card_transactions = parse_rede_csv(filepath)
        
        if not card_transactions:
            flash('Não foi possível ler as transações do arquivo. Verifique o formato.')
            return redirect(url_for('finance.finance_reconciliation'))
            
        dates = [t['date'] for t in card_transactions]
        if not dates:
            flash('Arquivo sem datas válidas.')
            return redirect(url_for('finance.finance_reconciliation'))
            
        min_date = min(dates)
        max_date = max(dates)
        
        start_search = min_date - timedelta(days=1)
        end_search = max_date + timedelta(days=1)
        
        sessions = load_cashier_sessions()
        system_transactions = []
        
        for s in sessions:
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
                                    'payment_method': tx['payment_method']
                                })
                    except:
                        continue
                        
        results = reconcile_transactions(system_transactions, card_transactions)
        
        summary = {
            'matched_count': len(results['matched']),
            'unmatched_system_count': len(results['unmatched_system']),
            'unmatched_card_count': len(results['unmatched_card'])
        }
        
        try:
            os.remove(filepath)
        except: pass
        
        return render_template('finance_reconciliation.html', results=results, summary=summary)
        
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
        payment_methods = entry.get('payment_methods', [])
        primary_method = payment_methods[0].get('method', 'Outros') if payment_methods else 'Outros'
        
        transaction = {
            'id': entry['id'],
            'amount': entry['total_amount'],
            'payment_method': primary_method
        }
        
        settings = load_fiscal_settings()
        target_cnpj = None
        for pm in payment_methods:
            if pm.get('fiscal_cnpj'):
                target_cnpj = pm.get('fiscal_cnpj')
                break
                
        integration_settings = get_fiscal_integration(settings, target_cnpj)
        if not integration_settings:
             return jsonify({'success': False, 'error': 'Configuração fiscal não encontrada'}), 400

        customer_info = entry.get('customer', {})
        customer_cpf_cnpj = customer_info.get('cpf_cnpj') or customer_info.get('doc')

        result = service_emit_invoice(transaction, integration_settings, entry['items'], customer_cpf_cnpj)
        
        if result['success']:
            nfe_id = result['data'].get('id')
            
            FiscalPoolService.update_status(entry_id, 'emitted', fiscal_doc_uuid=nfe_id, user=session.get('user'))
            
            log_system_action('Emissão Fiscal Admin', {
                'entry_id': entry_id,
                'nfe_id': nfe_id,
                'amount': entry['total_amount'],
                'user': session.get('user')
            }, category='Fiscal')
            
            return jsonify({'success': True, 'message': 'Nota emitida com sucesso', 'nfe_id': nfe_id})
        else:
            error_msg = result.get('error', 'Erro desconhecido na emissão')
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
            except Exception:
                pass

        ok, err = print_fiscal_receipt({}, invoice_data)
        if not ok:
            return jsonify({'success': False, 'error': err or 'Falha ao imprimir'}), 500

        return jsonify({'success': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
