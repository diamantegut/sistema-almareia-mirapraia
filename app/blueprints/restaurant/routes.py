from flask import render_template, request, redirect, url_for, flash, jsonify, session, send_file, current_app
import copy
from . import restaurant_bp
from app.utils.decorators import login_required
from app.services.data_service import (
    load_restaurant_table_settings, save_restaurant_table_settings,
    load_restaurant_settings, save_restaurant_settings,
    load_menu_items, load_complements, save_complements,
    load_observations, save_observations, load_table_orders, save_table_orders,
    load_room_occupancy, format_room_number, load_breakfast_history,
    load_payment_methods, save_payment_methods,
    save_sales_history, load_sales_history,
    save_stock_entry, log_stock_action, load_products,
    load_room_charges, save_room_charges, load_flavor_groups, load_settings
)
from app.services.user_service import load_users
from app.services.printer_manager import load_printers
from app.services.printing_service import (
    print_cashier_ticket, print_order_items, print_bill, 
    print_cancellation_items, print_fiscal_receipt,
    print_transfer_ticket, print_consolidated_stock_warning,
    print_cashier_ticket_async
)
from app.services.fiscal_service import load_fiscal_settings, process_pending_emissions
from app.services.fiscal_pool_service import FiscalPoolService
from app.services.logger_service import log_system_action
from app.utils.logger import log_action
from app.services.cashier_service import CashierService, file_lock
from app.services.transfer_service import transfer_table_to_room, TransferError
from app.services.system_config_manager import TABLE_ORDERS_FILE
from app.utils.validators import (
    validate_required, sanitize_input, validate_room_number
)
import json
import os
import re
import uuid
import io
import xlsxwriter
import copy
from datetime import datetime
import time

# Idempotency cache for batch submissions (prevents duplicate on refresh)
PROCESSED_BATCHES = {}

# --- Helpers ---

def get_current_cashier(user=None, cashier_type=None):
    # Use centralized service for robust type handling
    if cashier_type:
        return CashierService.get_active_session(cashier_type)
        
    # Fallback for unspecified type (return first open)
    sessions = CashierService._load_sessions()
    for s in reversed(sessions):
        if str(s.get('status', '')).lower().strip() == 'open':
            return s
    return None

# --- Routes ---



@restaurant_bp.route('/restaurant/cashier', methods=['GET', 'POST'])
@login_required
def restaurant_cashier():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and 'restaurante' not in user_perms and 'principal' not in user_perms:
        flash('Acesso não autorizado ao Caixa Restaurante.')
        return redirect(url_for('main.index'))

    # Load sessions directly or via service? app.py loaded all sessions.
    # We will use CashierService._load_sessions() to get all data for display
    sessions = CashierService._load_sessions()
    current_user = session.get('user')
    
    user_sessions = [s for s in sessions if s.get('user') == current_user]
    
    current_cashier = get_current_cashier(cashier_type='restaurant_service')
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'open_cashier':
            try:
                raw_balance = request.form.get('opening_balance', '0')
                if isinstance(raw_balance, str):
                    clean_balance = raw_balance.replace('R$', '').replace(' ', '')
                    if ',' in clean_balance:
                        clean_balance = clean_balance.replace('.', '').replace(',', '.')
                    opening_balance = float(clean_balance)
                else:
                    opening_balance = float(raw_balance)
            except ValueError:
                opening_balance = 0.0
            
            try:
                CashierService.open_session('restaurant', current_user, opening_balance)
                log_action('Caixa Aberto', f'Caixa Restaurante aberto por {current_user} com R$ {opening_balance:.2f}', department='Restaurante')
                flash('Caixa aberto com sucesso.')
            except ValueError as e:
                flash(str(e))
            except Exception as e:
                flash(f'Erro ao abrir caixa: {str(e)}')
            
            return redirect(url_for('restaurant.restaurant_cashier'))
        
        elif action == 'close_cashier':
            if not current_cashier:
                flash('Não há caixa aberto para fechar.')
            else:
                try:
                    raw_closing = request.form.get('closing_balance', '0')
                    if isinstance(raw_closing, str):
                        clean_closing = raw_closing.replace('R$', '').replace(' ', '')
                        if ',' in clean_closing:
                            clean_closing = clean_closing.replace('.', '').replace(',', '.')
                        closing_balance = float(clean_closing)
                    else:
                        closing_balance = float(raw_closing)
                except ValueError:
                    closing_balance = 0.0
                
                try:
                    # Close via Service
                    CashierService.close_session(session_id=current_cashier['id'], user=current_user, closing_balance=closing_balance)
                    
                    # Process Fiscal Batch
                    try:
                        results = process_pending_emissions()
                        if results['success'] > 0:
                            flash(f"Emissão Fiscal em Lote: {results['success']} processadas, {results['failed']} falhas.")
                            log_action('Fiscal_Batch', f"Caixa Fechado. Emissões: {results['success']} OK, {results['failed']} Erros.", department='Restaurante')
                        elif results['failed'] > 0:
                            flash(f"Emissão Fiscal em Lote: {results['failed']} falhas.")
                    except Exception as e:
                        print(f"Error processing fiscal batch: {e}")
                        flash(f"Erro ao processar emissões fiscais: {str(e)}")

                    log_action('Caixa Fechado', f'Caixa Restaurante fechado por {current_user} com saldo final R$ {closing_balance:.2f}', department='Restaurante')
                    flash('Caixa fechado com sucesso.')
                    
                except Exception as e:
                    flash(f"Erro ao fechar caixa: {str(e)}")
                    
            return redirect(url_for('restaurant.restaurant_cashier'))
        
        elif action == 'add_transaction':
            if not current_cashier:
                flash('O caixa precisa estar aberto para lançar transações.')
            else:
                trans_type = request.form.get('type', '').strip().lower()
                description = request.form.get('description')
                try:
                    raw_amount = request.form.get('amount', '0')
                    if isinstance(raw_amount, str):
                        clean_amount = raw_amount.replace('R$', '').replace(' ', '')
                        if ',' in clean_amount:
                            clean_amount = clean_amount.replace('.', '').replace(',', '.')
                        amount = float(clean_amount)
                    else:
                        amount = float(raw_amount)
                except ValueError:
                    amount = 0.0
                
                if amount > 0 and description:
                    try:
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_cashier:
                            for t in current_cashier.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('restaurant.restaurant_cashier'))

                        if trans_type == 'transfer':
                            target_cashier = request.form.get('target_cashier')
                            CashierService.transfer_funds(
                                source_type='restaurant',
                                target_type=target_cashier,
                                amount=amount,
                                description=description,
                                user=current_user,
                                details={'idempotency_key': idempotency_key} if idempotency_key else None
                            )
                            flash('Transferência realizada com sucesso.')
                            log_action('Transferência Caixa', f'Restaurante -> {target_cashier}: R$ {amount:.2f}', department='Restaurante')
                            
                            # Print Ticket
                            try:
                                printers_config = load_printers()
                                target_printer = None
                                for p in printers_config:
                                    if 'bar' in p.get('name', '').lower():
                                        target_printer = p
                                        break
                                if not target_printer and printers_config:
                                    target_printer = printers_config[0]
                                    
                                if target_printer:
                                    print_cashier_ticket_async(target_printer, 'TRANSFERENCIA', amount, session.get('user', 'Sistema'), f"{description} -> {target_cashier}")
                            except Exception as e:
                                print(f"Error printing cashier ticket: {e}")
                        
                        elif trans_type == 'withdrawal':
                            user_role = session.get('role')
                            if user_role not in ['admin', 'gerente', 'supervisor']:
                                flash('Permissão negada. Apenas Gerentes e Supervisores podem realizar sangrias.')
                                return redirect(url_for('restaurant.restaurant_cashier'))
                            
                            CashierService.add_transaction(
                                cashier_type='restaurant',
                                amount=amount,
                                description=description,
                                payment_method='dinheiro',
                                user=current_user,
                                transaction_type='out', # Withdrawal is OUT
                                is_withdrawal=True,
                                details={'idempotency_key': idempotency_key} if idempotency_key else None
                            )
                            log_action('Transação Caixa', f'Restaurante: Sangria de R$ {amount:.2f} - {description}', department='Restaurante')
                            flash('Sangria registrada.')
                            
                            # Print Ticket
                            try:
                                printers_config = load_printers()
                                target_printer = None
                                for p in printers_config:
                                    if 'bar' in p.get('name', '').lower():
                                        target_printer = p
                                        break
                                if not target_printer and printers_config:
                                    target_printer = printers_config[0]
                                    
                                if target_printer:
                                    print_cashier_ticket_async(target_printer, 'withdrawal', amount, session.get('user', 'Sistema'), description)
                            except Exception as e:
                                print(f"Error printing cashier ticket: {e}")

                        elif trans_type == 'deposit':
                            CashierService.add_transaction(
                                cashier_type='restaurant',
                                amount=amount,
                                description=description,
                                payment_method='dinheiro',
                                user=current_user,
                                transaction_type='in', # Deposit is IN
                                is_withdrawal=False,
                                details={'idempotency_key': idempotency_key} if idempotency_key else None
                            )
                            log_action('Transação Caixa', f'Restaurante: Suprimento de R$ {amount:.2f} - {description}', department='Restaurante')
                            
                            # Print Ticket
                            try:
                                printers_config = load_printers()
                                target_printer = None
                                for p in printers_config:
                                    if 'bar' in p.get('name', '').lower():
                                        target_printer = p
                                        break
                                if not target_printer and printers_config:
                                    target_printer = printers_config[0]
                                    
                                if target_printer:
                                    print_cashier_ticket_async(target_printer, 'SUPRIMENTO', amount, session.get('user', 'Sistema'), description)
                            except Exception as e:
                                print(f"Error printing cashier ticket: {e}")

                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                return jsonify({'success': True, 'message': 'Suprimento registrado com sucesso.'})
                            flash('Suprimento registrado.')

                    except ValueError as e:
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': False, 'message': f'Erro: {str(e)}'}), 400
                        flash(f'Erro: {str(e)}')
                    except Exception as e:
                        print(f"Transaction Error: {e}")
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'}), 500
                        flash(f'Erro inesperado: {str(e)}')
                else:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': 'Valor inválido ou descrição ausente.'}), 400
                    flash('Valor inválido ou descrição ausente.')
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    # Fallback for non-deposit actions if they were called via AJAX accidentally
                    return jsonify({'success': True, 'message': 'Operação realizada.'})
                    
                return redirect(url_for('restaurant.restaurant_cashier'))

    current_totals = {}
    total_balance = 0.0
    
    displayed_transactions = []
    has_more = False
    page = 1

    if current_cashier:
        if 'opening_balance' not in current_cashier:
            current_cashier['opening_balance'] = 0.0
            
        total_balance = current_cashier.get('opening_balance', 0.0)
        
        # Calculate totals on raw transactions
        for t in current_cashier['transactions']:
            if t['type'] in ['sale', 'deposit', 'in']:
                total_balance += t['amount']
                if t['type'] in ['sale', 'in']:
                    method = t.get('payment_method', 'Outros')
                    current_totals[method] = current_totals.get(method, 0) + t['amount']
            elif t['type'] in ['withdrawal', 'out']:
                total_balance -= t['amount']
        
        # Group by Payment Group ID first
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        displayed_transactions, has_more = CashierService.get_paginated_transactions(
            current_cashier['id'], page=page, per_page=per_page
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'transactions': displayed_transactions,
                'has_more': has_more,
                'current_page': page
            })

    return render_template('restaurant_cashier.html', 
                           cashier=current_cashier, 
                           total_balance=total_balance,
                           current_totals=current_totals,
                           sessions=user_sessions,
                           displayed_transactions=displayed_transactions,
                           has_more=has_more,
                           current_page=page)

@restaurant_bp.route('/restaurant/complements', methods=['GET', 'POST'])
@login_required
def restaurant_complements():
    complements = load_complements()
    menu_items = load_menu_items()
    categories = sorted(list(set(p.get('category') for p in menu_items if p.get('category'))))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            name = request.form.get('name')
            category = request.form.get('category')
            try:
                price = float(request.form.get('price', 0))
            except ValueError:
                price = 0.0
            
            if name and category:
                new_comp = {
                    'id': str(len(complements) + 1),
                    'name': name,
                    'category': category,
                    'price': price
                }
                complements.append(new_comp)
                save_complements(complements)
                flash('Complemento adicionado.')
            else:
                flash('Nome e Categoria são obrigatórios.')
                
        elif action == 'delete':
            comp_id = request.form.get('id')
            complements = [c for c in complements if c['id'] != comp_id]
            save_complements(complements)
            flash('Complemento removido.')
            
        elif action == 'edit':
            comp_id = request.form.get('id')
            name = request.form.get('name')
            category = request.form.get('category')
            try:
                price = float(request.form.get('price', 0))
            except ValueError:
                price = 0.0
                
            for c in complements:
                if c['id'] == comp_id:
                    c['name'] = name
                    c['category'] = category
                    c['price'] = price
                    break
            save_complements(complements)
            flash('Complemento atualizado.')
            
        return redirect(url_for('restaurant.restaurant_complements'))
        
    return render_template('restaurant_complements.html', complements=complements, categories=categories)

@restaurant_bp.route('/restaurant/observations', methods=['GET', 'POST'])
@login_required
def restaurant_observations():
    observations = load_observations()
    menu_items = load_menu_items()
    categories = sorted(list(set(p.get('category') for p in menu_items if p.get('category'))))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            text = request.form.get('text')
            selected_categories = request.form.getlist('categories')
            
            if text and selected_categories:
                new_obs = {
                    'id': f"obs_{int(datetime.now().timestamp())}",
                    'text': text,
                    'categories': selected_categories
                }
                observations.append(new_obs)
                save_observations(observations)
                flash('Observação adicionada.')
            else:
                flash('Texto e pelo menos uma Categoria são obrigatórios.')
                
        elif action == 'delete':
            obs_id = request.form.get('id')
            observations = [o for o in observations if o['id'] != obs_id]
            save_observations(observations)
            flash('Observação removida.')
            
        elif action == 'edit':
            obs_id = request.form.get('id')
            text = request.form.get('text')
            selected_categories = request.form.getlist('categories')
            
            for o in observations:
                if o['id'] == obs_id:
                    o['text'] = text
                    o['categories'] = selected_categories
                    break
            save_observations(observations)
            flash('Observação atualizada.')
            
        return redirect(url_for('restaurant.restaurant_observations'))
        
    return render_template('restaurant_observations.html', observations=observations, categories=categories)

@restaurant_bp.route('/restaurant/tables')
@login_required
def restaurant_tables():
    # Permission Check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    user_dept = session.get('department')
    
    has_restaurant_access = any('restaurante' in p for p in user_perms)
    
    if user_role not in ['admin', 'gerente', 'supervisor'] and not has_restaurant_access and 'recepcao' not in user_perms and user_dept != 'Serviço':
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))

    orders = load_table_orders()
    occupancy = load_room_occupancy()
    users = load_users()
    table_settings = load_restaurant_table_settings()
    settings = load_restaurant_settings()
    disabled_tables = table_settings.get('disabled_tables', [])
    
    staff_orders = {k: v for k, v in orders.items() if k.startswith('FUNC_')}
    
    current_cashier = get_current_cashier(cashier_type='restaurant')
    is_cashier_open = current_cashier is not None

    # DEBUG LOGGING (Enhanced for Debugging Cashier Status)
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Restaurant Tables Check: Cashier Open? {is_cashier_open}")
        
        if current_cashier:
            logger.info(f" - Active Session Found: ID={current_cashier.get('id')}, Type={current_cashier.get('type')}")
        else:
            logger.warning(" - No active cashier session found for 'restaurant'/'restaurant_service'.")
            # Diagnostic dump
            all_sessions = CashierService._load_sessions()
            open_sessions = [s for s in all_sessions if s.get('status') == 'open']
            logger.info(f" - Diagnostic: Found {len(open_sessions)} open sessions total in DB.")
            for s in open_sessions:
                logger.info(f"   > Open Session: ID={s.get('id')}, Type={s.get('type')}")
    except Exception as e:
        print(f"Error logging cashier status: {e}")

    # Identify tables with Breakfast items
    breakfast_tables = []
    for t_id, order in orders.items():
        if any(item.get('category') == 'Café da Manhã' for item in order.get('items', [])):
            breakfast_tables.append(t_id)

    return render_template('restaurant_tables.html', 
                           open_orders=orders, 
                           occupancy=occupancy,
                           staff_orders=staff_orders,
                           users=users,
                           disabled_tables=disabled_tables,
                           live_music_active=settings.get('live_music_active', False),
                           is_cashier_open=is_cashier_open,
                           breakfast_tables=breakfast_tables)

@restaurant_bp.route('/restaurant/breakfast_report')
@login_required
def breakfast_report():
    history = load_breakfast_history()
    history.sort(key=lambda x: (x.get('date'), x.get('closed_at')), reverse=True)
    return render_template('breakfast_report.html', history=history)

@restaurant_bp.route('/restaurant/open_staff_table', methods=['POST'])
@login_required
def open_staff_table():
    try:
        raw_staff_name = request.form.get('staff_name')
        staff_name = sanitize_input(raw_staff_name)
        
        current_app.logger.info(f"Solicitação de abertura de mesa funcionário: '{staff_name}' (Raw: '{raw_staff_name}') por {session.get('user')}")
        
        if not staff_name:
            flash('Selecione um funcionário.')
            return redirect(url_for('restaurant.restaurant_tables'))
        
        # Ensure ID is safe
        safe_staff_id = staff_name.replace(' ', '_').replace('/', '-').replace('\\', '-')
        table_id = f"FUNC_{safe_staff_id}"
        
        orders = load_table_orders()
        
        if table_id not in orders:
            users = load_users()
            # Verify if staff_name is a valid user
            valid_user = False
            user_found = None
            
            # Check by username or ID
            for u_id, u_data in users.items():
                # Compare both raw and sanitized versions just in case
                u_username = u_data.get('username', '')
                if u_username == staff_name or u_id == staff_name or u_username == raw_staff_name:
                    valid_user = True
                    user_found = u_username
                    break
            
            if not valid_user:
                current_app.logger.warning(f"Tentativa de abrir mesa para funcionário inválido/não encontrado: '{staff_name}'")
                flash(f'Funcionário inválido: {staff_name}')
                return redirect(url_for('restaurant.restaurant_tables'))

            # Create Order
            orders[table_id] = {
                'status': 'open',
                'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'num_adults': 1,
                'customer_type': 'funcionario',
                'staff_name': user_found or staff_name, # Use validated name
                'waiter': session.get('user'),
                'items': [],
                'total': 0.0,
                'created_via': 'open_staff_table_v2' # Debug tag
            }
            
            if save_table_orders(orders):
                log_action('Mesa Funcionario Aberta', f'Mesa funcionário {user_found} aberta por {session.get("user")}', department='Restaurante')
                current_app.logger.info(f"Mesa funcionário {table_id} criada e persistida com sucesso.")
            else:
                current_app.logger.error(f"CRITICAL: Falha ao salvar orders.json ao criar mesa {table_id}. Verifique permissões de disco.")
                flash('Erro CRÍTICO ao salvar conta do funcionário. Contate o suporte.')
                return redirect(url_for('restaurant.restaurant_tables'))
        else:
            current_app.logger.info(f"Mesa funcionário {table_id} já existia. Redirecionando.")
            
        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
        
    except Exception as e:
        current_app.logger.exception(f"Erro não tratado em open_staff_table: {str(e)}")
        flash('Erro interno ao processar solicitação.')
        return redirect(url_for('restaurant.restaurant_tables'))

@restaurant_bp.route('/restaurant/table/<int:table_id>/toggle_disabled', methods=['POST'])
@login_required
def toggle_table_disabled(table_id):
    if session.get('role') != 'admin':
        flash('Acesso restrito à Diretoria.')
        return redirect(url_for('restaurant.restaurant_tables'))
    
    settings = load_restaurant_table_settings()
    disabled = settings.get('disabled_tables', [])
    if table_id in disabled:
        disabled = [t for t in disabled if t != table_id]
        flash(f'Mesa {table_id} reativada.')
        log_action('Mesa Reativada', f'Mesa {table_id} reativada por {session.get("user")}', department='Restaurante')
    else:
        disabled.append(table_id)
        disabled = sorted(set(disabled))
        flash(f'Mesa {table_id} marcada como não utilizável.')
        log_action('Mesa Desativada', f'Mesa {table_id} desativada por {session.get("user")}', department='Restaurante')
    settings['disabled_tables'] = disabled
    save_restaurant_table_settings(settings)
    return redirect(url_for('restaurant.restaurant_tables'))

@restaurant_bp.route('/restaurant/toggle_live_music', methods=['POST'])
@login_required
def toggle_live_music():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        flash('Acesso restrito a Gerentes, Supervisores e Diretoria.')
        return redirect(url_for('restaurant.restaurant_tables'))
    
    settings = load_restaurant_settings()
    current_status = settings.get('live_music_active', False)
    new_status = not current_status
    settings['live_music_active'] = new_status
    save_restaurant_settings(settings)
    
    status_msg = "ATIVADA" if new_status else "DESATIVADA"
    
    if new_status:
        orders = load_table_orders()
        menu_items = load_menu_items()
        couvert = next((p for p in menu_items if str(p['id']) == '32'), None)
        
        updated_count = 0
        
        if couvert:
            for table_id, order in orders.items():
                if order.get('status') != 'open':
                    continue
                
                try:
                    is_room = int(table_id) <= 35
                except:
                    is_room = False
                
                if is_room:
                    continue
                    
                cust_type = order.get('customer_type')
                if cust_type in ['funcionario', 'hospede']:
                    continue
                
                has_cover = any(item['name'] == couvert['name'] for item in order.get('items', []))
                
                if not has_cover:
                    num_adults = float(order.get('num_adults', 1))
                    if num_adults > 0:
                        item_id = str(uuid.uuid4())
                        new_item = {
                            'id': item_id,
                            'printed': True,
                            'name': couvert['name'],
                            'qty': num_adults,
                            'price': float(couvert['price']),
                            'complements': [],
                            'category': couvert.get('category'),
                            'service_fee_exempt': True,
                            'source': 'auto_cover_activation',
                            'waiter': 'Sistema'
                        }
                        order['items'].append(new_item)
                        
                        total = 0
                        for item in order['items']:
                            item_price = item['price']
                            comps_price = sum(c['price'] for c in item.get('complements', []))
                            total += item['qty'] * (item_price + comps_price)
                        order['total'] = total
                        
                        updated_count += 1
            
            if updated_count > 0:
                save_table_orders(orders)
                flash(f'Música ao Vivo {status_msg}. Cover lançado em {updated_count} mesas.')
            else:
                flash(f'Música ao Vivo {status_msg}. Nenhuma mesa elegível para lançamento retroativo.')
        else:
             flash(f'Música ao Vivo {status_msg}. ERRO: Produto "Couvert Artistico" (ID 32) não encontrado.')
    else:
        flash(f'Música ao Vivo {status_msg}.')
        
    return redirect(url_for('restaurant.restaurant_tables'))

from app.services.special_tables_service import SpecialTablesService

@restaurant_bp.route('/restaurant/close_special_table', methods=['POST'])
@login_required
def close_special_table():
    user = session.get('user')
    table_id = request.form.get('table_id')
    
    if not table_id:
        flash('Mesa inválida.')
        return redirect(url_for('restaurant.restaurant_tables'))
        
    str_table_id = str(table_id)
    
    try:
        if str_table_id == '36':
            success, msg = SpecialTablesService.process_table_36_breakfast(table_id, user)
        elif str_table_id == '69':
            success, msg = SpecialTablesService.process_table_69_owners(table_id, user)
        elif str_table_id == '68':
            justification = request.form.get('justification')
            success, msg = SpecialTablesService.process_table_68_courtesy(table_id, user, justification)
        else:
            success, msg = False, "Esta não é uma mesa especial configurada para fechamento automático."
            
        if success:
            flash(msg)
            return redirect(url_for('restaurant.restaurant_tables'))
        else:
            flash(f"Erro: {msg}")
            return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
    except Exception as e:
        current_app.logger.error(f"Erro ao fechar mesa especial {table_id}: {e}")
        flash(f"Erro interno: {str(e)}")
        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

@restaurant_bp.route('/restaurant/table/<table_id>', methods=['GET', 'POST'])
@login_required
def restaurant_table_order(table_id):
    orders = load_table_orders()
    str_table_id = str(table_id)
    room_occupancy = load_room_occupancy()
    breakfast_table_id = '36'
    mode = request.args.get('mode') or request.form.get('mode')
    
    try:
        int_table_id = int(table_id)
        is_room = int_table_id <= 35
    except ValueError:
        is_room = False
        if str_table_id.startswith('FUNC_') and str_table_id not in orders:
             current_app.logger.error(f"Erro de integridade: Tentativa de acessar mesa funcionário inexistente: {str_table_id}")
             flash('Conta de funcionário não encontrada.')
             return redirect(url_for('restaurant.restaurant_tables'))

    if is_room:
        str_table_id = format_room_number(table_id)
    
    complements = load_complements()
    users = load_users()
    
    if str_table_id in orders:
        if str_table_id.startswith('FUNC_'):
            # Debug/Audit log for staff table access
            current_app.logger.debug(f"Acessando mesa funcionário: {str_table_id}")
            
        if 'partial_payments' not in orders[str_table_id]:
            orders[str_table_id]['partial_payments'] = []
        if 'total_paid' not in orders[str_table_id]:
            orders[str_table_id]['total_paid'] = 0.0

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'open_table':
            num_adults_raw = request.form.get('num_adults')
            waiter_name = sanitize_input(request.form.get('waiter'))
            
            # Validate Adults
            try:
                num_adults = int(num_adults_raw)
                if num_adults < 1: raise ValueError
            except (ValueError, TypeError):
                flash('Número de adultos inválido.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id, **({'mode': mode} if mode else {})))

            if is_room:
                if str_table_id not in room_occupancy:
                    flash('ERRO: Não é permitido abrir mesa de quarto sem hóspede (Check-in não realizado).')
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id, **({'mode': mode} if mode else {})))
                
                customer_type = 'hospede'
                room_number = str_table_id
            else:
                customer_type = request.form.get('customer_type')
                if customer_type not in ['passante', 'hospede', 'funcionario']:
                    flash('Tipo de cliente inválido.')
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

                room_number = request.form.get('room_number')
                if room_number:
                    room_number = format_room_number(room_number)
            
            if num_adults:
                if customer_type == 'hospede':
                    if not room_number:
                        flash('Número do quarto é obrigatório para hóspedes.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    # Validate Room Occupancy
                    if room_number not in room_occupancy:
                        flash(f'Quarto {room_number} não está ocupado.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    staff_name = None # Not applicable for hospede
                        
                elif customer_type == 'funcionario':
                    staff_name = sanitize_input(request.form.get('staff_name'))
                    if not staff_name:
                        flash('Selecione o colaborador.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                else:
                    staff_name = None # Passante

                if str_table_id not in orders:
                    customer_name = sanitize_input(request.form.get('customer_name'))
                    
                    orders[str_table_id] = {
                        'items': [], 
                        'total': 0, 
                        'status': 'open', 
                        'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'num_adults': num_adults,
                        'customer_type': customer_type,
                        'customer_name': customer_name,
                        'room_number': room_number if customer_type == 'hospede' else None,
                        'waiter': waiter_name,
                        'staff_name': staff_name
                    }
                    
                    # Logic for Breakfast Icon (07:00 - 10:00)
                    now_hour = datetime.now().hour
                    if 7 <= now_hour < 10:
                        orders[str_table_id]['is_breakfast'] = True
                    else:
                        orders[str_table_id]['is_breakfast'] = False
                    
                    settings = load_restaurant_settings()
                    if settings.get('live_music_active', False) and not is_room and customer_type != 'funcionario':
                        menu_items = load_menu_items()
                        couvert = next((p for p in menu_items if str(p['id']) == '32'), None)
                        if couvert:
                                item_id = str(uuid.uuid4())
                                new_item = {
                                'id': item_id,
                                'printed': True,
                                'name': couvert['name'],
                                'qty': float(num_adults),
                                'price': float(couvert['price']),
                                'complements': [],
                                'category': couvert.get('category'),
                                'service_fee_exempt': False,
                                'source': 'auto_cover_activation',
                                'waiter': 'Sistema'
                            }
                                orders[str_table_id]['items'].append(new_item)
                                orders[str_table_id]['total'] = new_item['price'] * new_item['qty']
                                flash('Mesa aberta com Cover Artístico incluído.')
                    
                    save_table_orders(orders)
                    log_action('Mesa Aberta', f'Mesa {table_id} aberta por {session.get("user")}', department='Restaurante')
                else:
                    flash('Mesa já está aberta.')
                
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id, **({'mode': mode} if mode else {})))
            else:
                flash('Número de pessoas é obrigatório.')

        elif action == 'update_pax':
            if str_table_id not in orders:
                flash('Mesa não encontrada.')
                return redirect(url_for('restaurant.restaurant_tables'))
            
            try:
                # 1. Update Num Adults
                num_adults_raw = request.form.get('num_adults')
                num_adults = int(num_adults_raw)
                if num_adults < 1: raise ValueError
                
                # 2. Update Customer Info
                customer_type = request.form.get('customer_type')
                
                # Basic validation
                if customer_type not in ['passante', 'hospede']:
                     # If current is funcionario, and user didn't change it (or modal didn't send it correctly), preserve it?
                     # But modal inputs are radio buttons for passante/hospede.
                     # If it was funcionario, the radio might default to something or be unchecked?
                     # The template sets 'checked' if matches. If neither matches (funcionario), none checked.
                     # If user submits without checking, customer_type is None.
                     if orders[str_table_id].get('customer_type') == 'funcionario':
                         # Allow updating only num_adults for staff without changing type
                         customer_type = 'funcionario'
                     else:
                         # Default to passante if missing? Or error?
                         if not customer_type:
                             flash('Tipo de cliente inválido.')
                             return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

                orders[str_table_id]['num_adults'] = num_adults
                orders[str_table_id]['customer_type'] = customer_type
                
                if customer_type == 'hospede':
                    room_number = request.form.get('room_number')
                    if not room_number:
                        flash('Número do quarto é obrigatório para hóspede.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    room_number = format_room_number(room_number)
                    if room_number not in room_occupancy:
                         flash(f'Quarto {room_number} não está ocupado.')
                         return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    # Update Info
                    orders[str_table_id]['room_number'] = room_number
                    # Update guest name from occupancy to ensure it's current
                    orders[str_table_id]['customer_name'] = room_occupancy[room_number].get('guest_name', 'Hóspede')
                    
                elif customer_type == 'passante':
                    customer_name = sanitize_input(request.form.get('customer_name'))
                    orders[str_table_id]['room_number'] = None
                    orders[str_table_id]['customer_name'] = customer_name
                
                # If funcionario, we just updated num_adults, kept other info same
                
                save_table_orders(orders)
                log_action('Mesa Atualizada', f'Mesa {table_id} atualizada por {session.get("user")}. Pax: {num_adults}, Tipo: {customer_type}', department='Restaurante')
                flash('Informações da mesa atualizadas com sucesso.')
                
            except (ValueError, TypeError):
                flash('Número de adultos inválido.')
            except Exception as e:
                current_app.logger.error(f"Erro ao atualizar mesa {table_id}: {e}")
                flash(f'Erro ao atualizar: {str(e)}')
            
            return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

        elif action == 'remove_item':
            try:
                item_id = request.form.get('item_id')
                reason = request.form.get('cancellation_reason')
                
                if str_table_id not in orders:
                     msg = 'Mesa não encontrada.'
                     if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                         return jsonify({'success': False, 'error': msg})
                     flash(msg)
                     return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

                order = orders[str_table_id]
                items = order.get('items', [])
                
                target_item = next((i for i in items if str(i.get('id')) == str(item_id)), None)
                
                if not target_item:
                    msg = 'Item não encontrado.'
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                         return jsonify({'success': False, 'error': msg})
                    flash(msg)
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                
                # Permission Check
                if session.get('role') not in ['admin', 'gerente', 'supervisor']:
                    auth_pass = request.form.get('auth_password')
                    if not auth_pass:
                        msg = 'Autorização necessária.'
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                             return jsonify({'success': False, 'error': msg})
                        flash(msg)
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    users = load_users()
                    authorized = False
                    for u, data in users.items():
                        if isinstance(data, dict):
                            u_role = data.get('role')
                            u_pass = data.get('password')
                            if u_role in ['admin', 'gerente', 'supervisor'] and u_pass == auth_pass:
                                authorized = True
                                break
                    
                    if not authorized:
                        msg = 'Senha de autorização inválida.'
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                             return jsonify({'success': False, 'error': msg})
                        flash(msg)
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

                # Validation: Check if printed
                if target_item.get('printed', False) or target_item.get('print_status') == 'printed':
                    # Block if not Supervisor+ (However, if we passed Permission Check, we are effectively authorized)
                    # But if the requirement implies strict role check for printed items specifically:
                    # We can assume that if a waiter provided a password, it WAS a supervisor's password.
                    # So we just proceed. 
                    # But to be safe and explicit, we can log it differently.
                    pass
                
                # Remove
                items.remove(target_item)
                
                # Recalculate Total
                total = 0
                for item in items:
                    item_price = item['price']
                    comps_price = sum(c['price'] for c in item.get('complements', []))
                    total += item['qty'] * (item_price + comps_price)
                order['total'] = total
                
                save_table_orders(orders)
                
                # Audit Log
                log_action('Item Removido', 
                           f'Item {target_item["name"]} removido da Mesa {table_id} por {session.get("user")}. Motivo: {reason}', 
                           department='Restaurante')
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True, 
                        'new_total': total,
                        'message': 'Item removido com sucesso.'
                    })
                
                flash('Item removido com sucesso.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                
            except Exception as e:
                current_app.logger.error(f"Erro ao remover item: {e}")
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                     return jsonify({'success': False, 'error': f'Erro interno: {str(e)}'})
                flash(f'Erro ao remover item: {str(e)}')

        elif action == 'add_batch_items':
            try:
                items_json = request.form.get('items_json')
                if not items_json:
                    raise ValueError("Lista de itens vazia.")
                
                try:
                    batch_items = json.loads(items_json)
                except json.JSONDecodeError:
                    raise ValueError("Dados de itens inválidos (JSON incorreto).")

                if not isinstance(batch_items, list):
                     raise ValueError("Formato de itens inválido.")

                # Idempotency: prevent duplicate submission by batch_id within 60s
                batch_id = request.form.get('batch_id')
                now = time.time()
                # Prune old entries (> 5 minutes)
                for k, t in list(PROCESSED_BATCHES.items()):
                    if now - t > 300:
                        del PROCESSED_BATCHES[k]
                if batch_id:
                    last = PROCESSED_BATCHES.get(batch_id)
                    if last and (now - last) < 60:
                        current_app.logger.warning(f"Duplicate order batch blocked: {batch_id} for table {table_id}")
                        flash('Pedido já enviado recentemente. Ignorando reenvio duplicado.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    PROCESSED_BATCHES[batch_id] = now

                menu_items = load_menu_items()
                products_map = {str(p['id']): p for p in menu_items}
                
                all_comps = load_complements()
                comp_map = {str(c['id']): c for c in all_comps}
                
                waiter = sanitize_input(request.form.get('waiter') or session.get('user', 'Garçom'))
                
                new_order_items = []
                errors = []
                
                for item_data in batch_items:
                    prod_id = str(item_data.get('product'))
                    product = products_map.get(prod_id)
                    
                    if not product:
                        # Fallback: Try finding by Name (handling legacy calls passing name instead of ID)
                        product = next((p for p in menu_items if p['name'] == prod_id), None)
                        if product:
                             prod_id = str(product['id']) # Correct the ID for consistency

                    if not product:
                        errors.append(f"Produto ID {prod_id} não encontrado.")
                        print(f"DEBUG: Product ID {prod_id} not found in map. Keys sample: {list(products_map.keys())[:3]}")
                        continue
                    
                    # Security Block: Frigobar in Restaurant
                    if product.get('category') == 'Frigobar' and mode != 'minibar':
                        # Relaxed restriction: Allow selling Frigobar items in Restaurant but log it.
                        # Previously this was a hard block, causing "Nenhum item válido adicionado".
                        log_system_action('Venda Item Frigobar no Restaurante', 
                                          {'product': product['name'], 'user': session.get('user'), 'table': table_id}, 
                                          category='Aviso')
                        # continue (Removed to allow sale)

                    if not product.get('active', True):
                         msg = f"Produto '{product['name']}' inativo ignorado."
                         errors.append(msg)
                         flash(f"Aviso: {msg}")
                         continue

                    if product.get('paused', False):
                         msg = f"Produto '{product['name']}' está pausado e não pode ser vendido."
                         errors.append(msg)
                         flash(f"Aviso: {msg}")
                         continue
                        
                    try:
                        qty = float(item_data.get('qty', 1))
                    except (ValueError, TypeError):
                        errors.append(f"Quantidade inválida para '{product['name']}'.")
                        continue
                        
                    if qty <= 0: 
                        errors.append(f"Quantidade deve ser positiva para '{product['name']}'.")
                        continue
                    
                    # Prepare Item
                    order_item = {
                        'id': str(uuid.uuid4()),
                        'product_id': prod_id,
                        'name': product['name'],
                        'price': float(product.get('price', 0)),
                        'qty': qty,
                        'category': product.get('category', 'Outros'),
                        'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'waiter': waiter,
                        'printed': False,
                        'print_status': 'pending',
                        'complements': [],
                        'observations': [sanitize_input(obs) for obs in item_data.get('observations', []) if obs],
                        'accompaniments': [],
                        'flavor': sanitize_input(item_data.get('flavor_name')),
                        'questions_answers': item_data.get('questions_answers', []),
                        # Fiscal Data (Copied from Product)
                        'ncm': product.get('ncm'),
                        'cest': product.get('cest'),
                        'cfop': product.get('cfop'),
                        'origin': product.get('origin', 0),
                        'tax_info': product.get('tax_info') # Optional
                    }
                    
                    # Complements (Resolve IDs)
                    if item_data.get('complements'):
                        for c_id in item_data['complements']:
                            comp_obj = comp_map.get(str(c_id))
                            if comp_obj:
                                order_item['complements'].append({
                                    'name': comp_obj['name'],
                                    'price': float(comp_obj['price'])
                                })
                            else:
                                # Fallback if name passed (legacy)
                                order_item['complements'].append({'name': sanitize_input(str(c_id)), 'price': 0.0})

                    # Accompaniments (Resolve IDs)
                    if item_data.get('accompaniments'):
                        for acc_id in item_data['accompaniments']:
                            acc_prod = products_map.get(str(acc_id))
                            if acc_prod:
                                order_item['accompaniments'].append(acc_prod['name']) # Store name string
                            else:
                                order_item['accompaniments'].append(sanitize_input(str(acc_id)))
                                
                    new_order_items.append(order_item)
                    
                if new_order_items:
                    if str_table_id not in orders:
                        flash("Erro: Mesa não encontrada ou fechada.")
                        return redirect(url_for('restaurant.restaurant_tables'))
                        
                    orders[str_table_id]['items'].extend(new_order_items)
                    
                    # Recalculate Total
                    total = 0
                    for item in orders[str_table_id]['items']:
                        item_price = item['price']
                        comps_price = sum(c['price'] for c in item.get('complements', []))
                        total += item['qty'] * (item_price + comps_price)
                    orders[str_table_id]['total'] = total
                    
                    save_table_orders(orders)
                    log_action('Pedido Adicionado', f'Mesa {table_id}: {len(new_order_items)} itens adicionados por {session.get("user")}', department='Restaurante')
                    
                    # Print
                    printers = load_printers()
                    print_res = print_order_items(table_id, waiter, new_order_items, printers, menu_items)
                    
                    # Mark as printed
                    printed_ids = print_res.get('printed_ids', [])
                    
                    # Reload orders to ensure we have latest state (though we are single threaded here usually)
                    # Just update memory object
                    for item in orders[str_table_id]['items']:
                        if item['id'] in printed_ids:
                            item['printed'] = True
                            item['print_status'] = 'printed'
                        elif item in new_order_items and item['id'] not in printed_ids:
                             item['print_status'] = 'error'
                             
                    save_table_orders(orders)
                    
                    if print_res['results'].get('error'):
                        flash(f"Itens adicionados, mas houve erro na impressão: {print_res['results']['error']}")
                    else:
                        flash("Pedido enviado com sucesso!")
                else:
                    if errors:
                        error_msg = "; ".join(errors[:3])
                        if len(errors) > 3: error_msg += "..."
                        flash(f"Nenhum item adicionado. Detalhes: {error_msg}")
                    else:
                        flash("Nenhum item válido adicionado.")
                # Always redirect after handling batch to avoid resubmission on refresh (PRG)
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                        
            except Exception as e:
                flash(f"Erro ao adicionar itens: {str(e)}")
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

        elif action == 'close_order':
            try:
                with file_lock(TABLE_ORDERS_FILE):
                    orders = load_table_orders()
                    if str_table_id not in orders:
                        flash('Mesa não encontrada ou já fechada.')
                        return redirect(url_for('restaurant.restaurant_tables'))
                    order = orders[str_table_id]
                    
                    payment_data_json = request.form.get('payment_data')
                    try:
                        raw_payments = json.loads(payment_data_json) if payment_data_json else []
                    except json.JSONDecodeError:
                        flash('Erro: Dados de pagamento inválidos.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    payment_methods_list = load_payment_methods()
                    method_by_id = {str(m.get('id')): m.get('name') for m in payment_methods_list if m.get('id') is not None}
                    method_by_name = {str(m.get('name')).strip().lower(): m.get('name') for m in payment_methods_list if m.get('name')}
                    
                    payments = []
                    payment_errors = []
                    if not isinstance(raw_payments, list):
                        payment_errors.append('Lista de pagamentos inválida.')
                    else:
                        for idx, p in enumerate(raw_payments):
                            if not isinstance(p, dict):
                                payment_errors.append(f'Pagamento {idx + 1} inválido.')
                                continue
                            raw_method = p.get('method')
                            if not raw_method:
                                raw_method = p.get('name')
                            if not raw_method:
                                raw_method = p.get('id')
                            raw_method_str = str(raw_method).strip() if raw_method is not None else ''
                            method_name = method_by_id.get(raw_method_str)
                            if not method_name:
                                method_name = method_by_name.get(raw_method_str.lower()) if raw_method_str else ''
                            if not method_name:
                                method_name = raw_method_str
                            try:
                                amount = float(p.get('amount', 0))
                            except (TypeError, ValueError):
                                amount = 0.0
                            if amount <= 0:
                                payment_errors.append(f'Valor inválido no pagamento {idx + 1}.')
                            if not method_name:
                                payment_errors.append(f'Método inválido no pagamento {idx + 1}.')
                            if amount > 0 and method_name:
                                payments.append({'method': method_name, 'amount': amount})
                    
                    if payment_errors:
                        flash(' '.join(payment_errors[:3]))
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

                    service_fee_removed = request.form.get('remove_service_fee') == 'on'
                    grand_total = order.get('total', 0) * 1.1
                    if service_fee_removed:
                        grand_total = order.get('total', 0)
                    
                    try:
                        discount = float(request.form.get('discount', 0))
                    except ValueError:
                        discount = 0.0
                        
                    grand_total -= discount
                    if grand_total < 0:
                        grand_total = 0.0
                    
                    already_paid = order.get('total_paid', 0)
                    new_payments_total = sum(float(p.get('amount', 0)) for p in payments)
                    total_paid_all = already_paid + new_payments_total
                    
                    current_app.logger.info(f"Closing Table {table_id}: GrandTotal={grand_total:.2f}, AlreadyPaid={already_paid:.2f}, NewPayments={new_payments_total:.2f}, TotalAll={total_paid_all:.2f}")
    
                    remaining_check = grand_total - already_paid
                    if not payments and remaining_check > 0.01:
                        flash(f'Erro: Nenhum pagamento informado e saldo pendente (R$ {remaining_check:.2f}).')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    remaining = grand_total - total_paid_all
                    if remaining > 0.01: 
                        flash(f'Erro: Valor total pago (R$ {total_paid_all:.2f}) é menor que o total da conta (R$ {grand_total:.2f}). Falta R$ {remaining:.2f}.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    current_cashier = get_current_cashier(cashier_type='restaurant')
                    if not current_cashier:
                        flash('Erro: Caixa fechado. Não é possível finalizar.')
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                    payment_group_id = str(uuid.uuid4()) if len(payments) > 1 else None
                    total_payment_group_amount = sum(float(p.get('amount', 0)) for p in payments) if payment_group_id else 0

                    try:
                        log_system_action(
                            action='COMMISSION_SERVICE_FEE_STATUS',
                            details={
                                'table_id': table_id,
                                'service_fee_removed': service_fee_removed,
                                'grand_total': grand_total,
                                'payments': payments,
                            },
                            user=session.get('user', 'Sistema'),
                            category='Restaurante'
                        )
                    except Exception:
                        pass

                    for p in payments:
                        method = sanitize_input(p.get('method'))
                        try:
                            amount = float(p.get('amount'))
                        except:
                            continue
                        
                        details = {}
                        if payment_group_id:
                            details['payment_group_id'] = payment_group_id
                            details['total_payment_group_amount'] = total_payment_group_amount
                            details['payment_method_code'] = method
                        if service_fee_removed:
                            details['service_fee_removed'] = True

                        CashierService.add_transaction(
                            cashier_type='restaurant',
                            amount=amount,
                            description=f"Venda Mesa {table_id} - {method}",
                            payment_method=method,
                            user=session.get('user'),
                            transaction_type='sale',
                            details=details
                        )
                
                # Deduct Stock
                products_db = load_products()
                low_stock_items = []
                
                for item in order['items']:
                    # Find product by ID first, then name
                    product_obj = None
                    if item.get('product_id'):
                        product_obj = next((p for p in products_db if str(p['id']) == str(item['product_id'])), None)
                    if not product_obj:
                         product_obj = next((p for p in products_db if p['name'] == item['name']), None)
                         
                    if product_obj:
                        qty = item['qty']
                        
                        # Get current balance BEFORE deduction (approximate, since we don't have real-time balance in product_obj)
                        # We should calculate it or assume product_obj might have it if loaded recently?
                        # Actually load_products() might not calculate balance.
                        # But we are about to save an entry.
                        # Let's calculate balance AFTER deduction? Or check min_stock.
                        
                        # We need to know the CURRENT balance. get_product_balances() is expensive?
                        # Let's assume we can get it or we should calculate it.
                        # For now, let's proceed with logging and THEN check balance if possible, 
                        # or just blindly check if we can.
                        # The system seems to rely on 'balance' being calculated elsewhere or on the fly.
                        
                        # Let's use get_product_balances() just for the affected items? No, it calculates all.
                        # Optimization: We can't easily get single balance without iterating all entries.
                        # But we can do it for these items.
                        
                        log_stock_action(
                            user=session.get('user'),
                            action='saida',
                            product=product_obj['name'],
                            qty=qty,
                            details=f"Venda Mesa {table_id}",
                            department='Restaurante'
                        )
                        # Create Entry
                        save_stock_entry({
                            'id': str(uuid.uuid4()),
                            'date': datetime.now().strftime('%d/%m/%Y'),
                            'product': product_obj['name'],
                            'qty': -abs(qty),
                            'unit': product_obj.get('unit', 'un'),
                            'price': product_obj.get('price', 0),
                            'supplier': 'Venda',
                            'invoice': f"Mesa {table_id}",
                            'user': session.get('user')
                        })
                        
                        # Check Low Stock
                        # We need to fetch the balance.
                        # Since get_product_balances() is expensive, we might skip or pay the price.
                        # Given "Verifique a lógica... e mecanismos de notificação", we must check.
                        # Let's assume we can use a helper from stock_service if available, 
                        # or just import get_product_balances from app.services.stock_service
                        
                # After deducting all items, check balances for warning
                from app.services.stock_service import get_product_balances
                current_balances = get_product_balances() # This might be heavy but it's reliable
                
                for item in order['items']:
                    p_name = item['name']
                    # Find min stock
                    p_obj = next((p for p in products_db if p['name'] == p_name), None)
                    if p_obj:
                        min_stock = float(p_obj.get('min_stock', 0))
                        if min_stock > 0:
                            curr_qty = current_balances.get(p_name, 0)
                            if curr_qty < min_stock:
                                low_stock_items.append({'name': p_name, 'qty': curr_qty})
                
                if low_stock_items:
                    printers_config = load_printers()
                    print_consolidated_stock_warning(low_stock_items, printers_config)

                sales_history = load_sales_history()
                if not isinstance(sales_history, list):
                    if isinstance(sales_history, dict):
                        sales_history = list(sales_history.values())
                    else:
                        sales_history = []

                close_id = f"CLOSE_{datetime.now().strftime('%Y%m%d%H%M%S')}_{table_id}_{uuid.uuid4().hex[:6]}"
                order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                order['final_total'] = grand_total
                order['discount'] = discount
                order['status'] = 'closed'
                order['closed_by'] = session.get('user')
                order['close_id'] = close_id
                
                all_payments = []
                if 'partial_payments' in order:
                    all_payments.extend(order['partial_payments'])
                
                for p in payments:
                    all_payments.append({
                        'id': str(uuid.uuid4()),
                        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'amount': float(p.get('amount', 0)),
                        'method': p.get('method'),
                        'user': session.get('user'),
                        'type': 'final_payment'
                    })
                
                order['payments'] = all_payments
                sales_history.append(order)
                if not save_sales_history(sales_history):
                    flash('Erro ao salvar histórico de vendas.')
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                
                del orders[str_table_id]
                if not save_table_orders(orders):
                    sales_history = load_sales_history()
                    sales_history = [s for s in sales_history if s.get('close_id') != close_id]
                    save_sales_history(sales_history)
                    flash('Erro ao atualizar mesas. Tente novamente.')
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                
                log_action('Mesa Fechada', f'Mesa {table_id} fechada por {session.get("user")}. Total: R$ {grand_total:.2f}', department='Restaurante')

                try:
                    all_pms = load_payment_methods()
                    pm_map = {m['name']: m for m in all_pms}

                    fiscal_payments = []
                    for p in all_payments:
                        pm_name = p.get('method', 'Outros')
                        pm_obj = pm_map.get(pm_name)
                        if not pm_obj:
                             pm_obj = next((m for m in all_pms if m['id'] == pm_name), None)
                        
                        is_fiscal = pm_obj.get('is_fiscal', False) if pm_obj else False
                        
                        fiscal_payments.append({
                            'method': pm_name,
                            'amount': float(p.get('amount', 0)),
                            'is_fiscal': is_fiscal
                        })
                    
                    FiscalPoolService.add_to_pool(
                        origin='restaurant',
                        original_id=f"MESA_{table_id}_{datetime.now().strftime('%Y%m%d%H%M')}",
                        total_amount=float(grand_total),
                        items=order['items'],
                        payment_methods=fiscal_payments,
                        user=session.get('user'),
                        customer_info={'name': order.get('customer_name'), 'type': order.get('customer_type')},
                        notes=f"Mesa {table_id}"
                    )
                except Exception as e:
                    print(f"Error adding to fiscal pool: {e}")
                    log_action('Erro Fiscal', f'Falha ao enviar para pool: {e}', department='Restaurante')

                if request.form.get('emit_invoice') == 'on':
                    pass
                
                flash('Mesa fechada com sucesso!')
                return redirect(url_for('restaurant.restaurant_tables'))
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                current_app.logger.exception(f"Erro ao fechar mesa {table_id}: {e}")
                
                # Log to DB
                try:
                    from app.services.logger_service import LoggerService
                    LoggerService.log_acao(
                        acao="Erro Fechamento Mesa",
                        entidade="Restaurante",
                        detalhes=error_details,
                        nivel_severidade="CRITICAL",
                        departamento_id="Restaurante"
                    )
                except:
                    pass

                flash(f'Erro ao fechar conta: {str(e)}')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

        elif action == 'add_partial_payment':
            try:
                amount = float(request.form.get('amount'))
            except (ValueError, TypeError):
                flash('Valor inválido.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

            method = sanitize_input(request.form.get('payment_method'))
            if not method:
                flash('Método de pagamento obrigatório.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
            if amount <= 0:
                flash('Valor deve ser positivo.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
            if str_table_id in orders:
                if 'partial_payments' not in orders[str_table_id]:
                    orders[str_table_id]['partial_payments'] = []
                
                orders[str_table_id]['partial_payments'].append({
                    'id': str(uuid.uuid4()),
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'amount': amount,
                    'method': method,
                    'user': session.get('user')
                })
                
                orders[str_table_id]['total_paid'] = orders[str_table_id].get('total_paid', 0) + amount
                
                # Register in Cashier IMMEDIATELY
                # Ensure using robust get_current_cashier
                current_cashier = get_current_cashier(cashier_type='restaurant')
                if current_cashier:
                    CashierService.add_transaction(
                        cashier_type='restaurant',
                        amount=amount,
                        description=f"Pagamento Parcial Mesa {table_id}",
                        payment_method=method,
                        user=session.get('user'),
                        transaction_type='sale'
                    )
                else:
                    flash('Aviso: Pagamento registrado na mesa, mas CAIXA ESTÁ FECHADO. Lance manualmente no caixa depois.')
                
                # Check if fully paid (Log only)
                grand_total_est = orders[str_table_id].get('total', 0) * 1.1
                if orders[str_table_id]['total_paid'] >= grand_total_est - 0.01:
                     current_app.logger.info(f"Mesa {table_id} totalmente paga via parcial. Total Pago: {orders[str_table_id]['total_paid']:.2f}")

                save_table_orders(orders)
                flash('Pagamento parcial registrado.')

        elif action == 'void_partial_payment':
            payment_id = request.form.get('payment_id')
            if str_table_id in orders:
                 p_list = orders[str_table_id].get('partial_payments', [])
                 to_remove = next((p for p in p_list if p['id'] == payment_id), None)
                 
                 if to_remove:
                     p_list.remove(to_remove)
                     orders[str_table_id]['partial_payments'] = p_list
                     orders[str_table_id]['total_paid'] -= to_remove['amount']
                     
                     # Revert in Cashier
                     current_cashier = get_current_cashier(cashier_type='restaurant')
                     if current_cashier:
                        CashierService.add_transaction(
                            cashier_type='restaurant',
                            amount=to_remove['amount'],
                            description=f"ESTORNO Pagto Parcial Mesa {table_id}",
                            payment_method=to_remove['method'],
                            user=session.get('user'),
                            transaction_type='out', # Money OUT
                            is_withdrawal=False # Not a withdrawal per se, but a correction
                        )
                     
                     save_table_orders(orders)
                     flash('Pagamento estornado.')

        elif action == 'pull_bill':
            if str_table_id in orders:
                orders[str_table_id]['locked'] = True
                save_table_orders(orders)
                
                # Print Bill
                order = orders[str_table_id]
                items = order['items']
                subtotal = order['total']
                service_fee = subtotal * 0.10
                total = subtotal + service_fee
                
                printers = load_printers()
                # Find bill printer
                bill_printer = next((p for p in printers if 'conta' in p.get('name', '').lower() or 'caixa' in p.get('name', '').lower()), None)
                
                # Resolve Guest Name if Hospede
                guest_name = order.get('customer_name')
                room_number = order.get('room_number')
                
                if order.get('customer_type') == 'hospede' and room_number:
                    # Try to fetch from occupancy
                    clean_room = format_room_number(room_number)
                    if clean_room in room_occupancy:
                        guest_name = room_occupancy[clean_room].get('guest_name')
                
                print_bill(bill_printer, table_id, items, subtotal, service_fee, total, order.get('waiter', 'Garçom'), guest_name=guest_name, room_number=room_number)
                flash('Conta puxada (Mesa Bloqueada).')

        elif action == 'unlock_table':
            if str_table_id in orders:
                orders[str_table_id]['locked'] = False
                save_table_orders(orders)
                flash('Mesa desbloqueada.')

        elif action == 'cancel_table':
            if str_table_id in orders:
                order = orders[str_table_id]
                
                # 1. Reverse Partial Payments (Integrity Check)
                if order.get('partial_payments'):
                    current_cashier = get_current_cashier(cashier_type='restaurant')
                    # We proceed even if cashier is closed? Ideally we need it open.
                    # But blocking cancellation might be annoying. 
                    # We'll try to register it. CashierService usually handles auto-opening or we might need to check.
                    # For safety, we just log the transaction.
                    
                    for payment in order['partial_payments']:
                        try:
                            CashierService.add_transaction(
                                cashier_type='restaurant',
                                amount=float(payment['amount']),
                                description=f"ESTORNO Cancelamento Mesa {table_id}",
                                payment_method=payment['method'],
                                user=session.get('user'),
                                transaction_type='out',
                                is_withdrawal=False
                            )
                        except Exception as e:
                            current_app.logger.error(f"Erro ao estornar pagamento parcial na mesa {table_id}: {e}")
                            # Continue to ensure table is cancelled? Or abort?
                            # If we abort, user is stuck. Better to log and continue, 
                            # as the physical money return is the priority manual step.

                # Log cancellation
                log_system_action('Cancelamento Mesa', {'table': table_id, 'reason': 'User Request'}, category='Restaurante')
                
                # Print Cancellation Ticket to Kitchen
                printers = load_printers()
                menu_items = load_menu_items()
                try:
                    print_cancellation_items(table_id, session.get('user'), orders[str_table_id]['items'], printers, menu_items, justification="Cancelamento Mesa")
                except Exception as e:
                    current_app.logger.error(f"Erro ao imprimir cancelamento: {e}")
                
                del orders[str_table_id]
                save_table_orders(orders)
                flash('Mesa cancelada e pagamentos parciais estornados (se houver).')
                return redirect(url_for('restaurant.restaurant_tables'))

        elif action == 'transfer_table':
            target_table_id = request.form.get('target_table_id')
            if not target_table_id:
                flash('Mesa de destino inválida.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
            target_table_id = str(target_table_id)
            if target_table_id == str_table_id:
                flash('Mesa de destino igual à origem.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

            # VALIDATION START
            table_settings = load_restaurant_table_settings()
            disabled_tables = table_settings.get('disabled_tables', [])
            
            if target_table_id in disabled_tables:
                 flash(f'Erro: Mesa de destino {target_table_id} está desabilitada/oculta.')
                 return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

            # Range/Existence Check
            is_standard = target_table_id.isdigit() and 36 <= int(target_table_id) <= 101
            is_open = target_table_id in orders
            is_staff = target_table_id.startswith('FUNC_')
            is_room = target_table_id.isdigit() and 1 <= int(target_table_id) <= 35
            
            if is_room:
                 flash('Para transferir para um quarto (cobrança), use a opção "Enviar para Quarto".')
                 return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

            if not (is_standard or is_open or is_staff):
                 flash(f'Erro: Mesa de destino {target_table_id} inválida ou inexistente.')
                 return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            # VALIDATION END

            # SPECIAL TABLES VALIDATION
            if target_table_id in ['36', '69', '68']:
                # Import here to avoid circular imports if any, or use the one at top
                from app.services.special_tables_service import SpecialTablesService
                
                # Check constraints
                # For full table transfer, we pass all items
                items_to_transfer = orders.get(str_table_id, {}).get('items', [])
                source_opened_at = orders.get(str_table_id, {}).get('opened_at')
                
                valid, msg = SpecialTablesService.validate_transfer_to_special(target_table_id, items_to_transfer, session.get('user'), source_created_at=source_opened_at)
                
                if not valid:
                    flash(f"Transferência bloqueada: {msg}")
                    return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
                    
                # For Mesa 68, we might need justification handled in UI. 
                # If target is 68 and we are here, we might be missing the justification input if it wasn't a special form.
                # However, for now, we apply the strict time/rule checks.

            if str_table_id in orders:
                source_order = orders[str_table_id]
                
                # Check if target exists/open
                if target_table_id not in orders:
                    # Create new order at target
                    orders[target_table_id] = source_order.copy()
                    orders[target_table_id]['items'] = []  # Clear items reference to avoid shared list issues initially
                    # Deep copy items
                    orders[target_table_id]['items'] = copy.deepcopy(source_order['items'])
                    
                    # Update metadata
                    orders[target_table_id]['opened_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    # Se for conta de funcionário pelo destino, ajusta o tipo e o colaborador
                    if is_staff:
                        orders[target_table_id]['customer_type'] = 'funcionario'
                        try:
                            staff_id = target_table_id.replace('FUNC_', '', 1)
                        except Exception:
                            staff_id = target_table_id
                        orders[target_table_id]['staff_name'] = staff_id
                        orders[target_table_id]['room_number'] = None
                        orders[target_table_id]['customer_name'] = None
                    # Se for mesa 36 (Café), normaliza metadados para evitar botão de transferência para quarto
                    if target_table_id == '36':
                        orders[target_table_id]['customer_type'] = 'passante'
                        orders[target_table_id]['customer_name'] = 'Café da Manhã'
                        orders[target_table_id]['room_number'] = None
                        orders[target_table_id]['is_breakfast'] = True
                    # Record transfer info for Undo
                    orders[target_table_id]['last_transfer'] = {
                        'source_table': str_table_id,
                        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'user': session.get('user')
                    }
                    
                    # Log transfer in observations
                    for item in orders[target_table_id]['items']:
                        if 'observations' not in item:
                            item['observations'] = []
                        item['observations'].append(f"Transf de Mesa {table_id}")
                else:
                    # Merge into existing target
                    target_order = orders[target_table_id]
                    # Se destino é mesa de funcionário, garante metadados corretos
                    if is_staff:
                        target_order['customer_type'] = 'funcionario'
                        try:
                            staff_id = target_table_id.replace('FUNC_', '', 1)
                        except Exception:
                            staff_id = target_table_id
                        target_order['staff_name'] = staff_id
                        target_order['room_number'] = None
                        target_order['customer_name'] = None
                    # Se destino é mesa 36 (Café), normaliza metadados
                    if target_table_id == '36':
                        target_order['customer_type'] = 'passante'
                        target_order['customer_name'] = 'Café da Manhã'
                        target_order['room_number'] = None
                        target_order['is_breakfast'] = True
                    transferred_items = source_order['items']
                    for item in transferred_items:
                        if 'observations' not in item:
                            item['observations'] = []
                        item['observations'].append(f"Transf de Mesa {table_id}")
                        target_order['items'].append(item)
                    
                    # Recalculate target total
                    total = 0
                    for item in target_order['items']:
                        item_price = item['price']
                        comps_price = sum(c['price'] for c in item.get('complements', []))
                        total += item['qty'] * (item_price + comps_price)
                    target_order['total'] = total

                # Close source table
                del orders[str_table_id]
                save_table_orders(orders)
                
                log_action('Transferência Mesa', f'Mesa {table_id} transferida para Mesa {target_table_id} por {session.get("user")}', department='Restaurante')
                
                # Print Transfer Notification
                try:
                    printers = load_printers()
                    print_transfer_ticket(table_id, target_table_id, session.get('user', 'Sistema'), printers)
                except Exception as e:
                    current_app.logger.error(f"Erro ao imprimir ticket de transferência: {e}")
                
                flash(f'Mesa transferida para {target_table_id} com sucesso.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=target_table_id))
            else:
                flash('Mesa de origem não encontrada.')
                return redirect(url_for('restaurant.restaurant_tables'))

        elif action == 'cancel_transfer':
            return_table_id = request.form.get('return_table_id')
            if not return_table_id:
                flash('Mesa de destino para devolução inválida.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
            # Validate return_table_id format (simple alphanumeric check)
            if not re.match(r'^[a-zA-Z0-9_]+$', return_table_id):
                flash('ID da mesa de destino inválido.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

            # Logic similar to transfer_table but with specific logging and validation
            if str_table_id in orders:
                source_order = orders[str_table_id]
                
                # Check if target exists/open
                if return_table_id not in orders:
                    # Create new order at target (Restore)
                    orders[return_table_id] = source_order.copy()
                    orders[return_table_id]['items'] = []
                    orders[return_table_id]['items'] = copy.deepcopy(source_order['items'])
                    orders[return_table_id]['opened_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    
                    # Remove last_transfer metadata since we undid it
                    orders[return_table_id].pop('last_transfer', None)

                    # Add observation about undo
                    for item in orders[return_table_id]['items']:
                        if 'observations' not in item: item['observations'] = []
                        item['observations'].append(f"Estorno de Mesa {table_id}")
                    
                    # Recalculate total just in case
                    total = 0
                    for item in orders[return_table_id]['items']:
                        item_price = item['price']
                        comps_price = sum(c['price'] for c in item.get('complements', []))
                        total += item['qty'] * (item_price + comps_price)
                    orders[return_table_id]['total'] = total

                else:
                    # Merge back (user confirmed in frontend)
                    target_order = orders[return_table_id]
                    transferred_items = source_order['items']
                    for item in transferred_items:
                        if 'observations' not in item: item['observations'] = []
                        item['observations'].append(f"Estorno de Mesa {table_id}")
                        target_order['items'].append(item)
                    
                    # Recalculate target total
                    total = 0
                    for item in target_order['items']:
                        item_price = item['price']
                        comps_price = sum(c['price'] for c in item.get('complements', []))
                        total += item['qty'] * (item_price + comps_price)
                    target_order['total'] = total

                # Close current table (the one we are undoing FROM)
                del orders[str_table_id]
                save_table_orders(orders)
                
                log_action(
                    'Estorno Transferência', 
                    f'Mesa {table_id} devolvida para Mesa {return_table_id} por {session.get("user")}. Total itens: {len(source_order["items"])}', 
                    department='Restaurante'
                )
                flash(f'Transferência desfeita. Itens devolvidos para a mesa {return_table_id}.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=return_table_id))


        elif action == 'transfer_to_room':
            room_number = request.form.get('room_number')
            if not room_number:
                flash('Número do quarto obrigatório.')
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            
            try:
                success, msg = transfer_table_to_room(table_id, room_number, session.get('user'), mode='restaurant')
                flash(msg)
                return redirect(url_for('restaurant.restaurant_tables'))
            except TransferError as e:
                flash(f"Erro na transferência: {str(e)}")
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))
            except Exception as e:
                current_app.logger.error(f"Erro inesperado na transferência: {e}")
                flash(f"Erro inesperado: {str(e)}")
                return redirect(url_for('restaurant.restaurant_table_order', table_id=table_id))

        elif action == 'transfer_to_staff_account':
            if str_table_id in orders:
                order = orders[str_table_id]
                if order.get('customer_type') != 'funcionario':
                    flash('Erro: Esta não é uma conta de funcionário.')
                else:
                    sales_history = load_sales_history()
                    order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    # Padroniza método de pagamento com acento para relatórios/financeiro
                    order['payment_method'] = 'Conta Funcionário'
                    # Aplica regra: isento de taxa + 20% de desconto
                    try:
                        subtotal = float(order.get('total', 0) or 0)
                    except Exception:
                        subtotal = 0.0
                    discount_amount = round(subtotal * 0.20, 2)
                    final_total = max(0.0, subtotal - discount_amount)
                    order['service_fee'] = 0.0
                    order['discounts'] = order.get('discounts', [])
                    order['discounts'].append({'type': 'staff', 'percent': 20, 'amount': discount_amount})
                    order['final_total'] = final_total
                    sales_history.append(order)
                    save_sales_history(sales_history)
                    
                    # Lançar transação no caixa do Restaurante para consolidar consumo de funcionário nos relatórios
                    try:
                        desc = f"Consumo Funcionário - {order.get('staff_name')}"
                        CashierService.add_transaction(
                            cashier_type='restaurant',
                            amount=final_total,
                            description=desc,
                            payment_method='Conta Funcionário',
                            user=session.get('user', 'Sistema'),
                            details={
                                'table_id': str_table_id,
                                'staff_name': order.get('staff_name'),
                                'source': 'transfer_to_staff_account',
                                'subtotal': subtotal,
                                'discount': discount_amount
                            },
                            transaction_type='sale'
                        )
                    except Exception as e:
                        current_app.logger.error(f"Falha ao lançar consumo de funcionário no caixa: {e}")
                    
                    # Deduct Stock
                    products_db = load_products()
                    for item in order['items']:
                        product_obj = None
                        if item.get('product_id'):
                            product_obj = next((p for p in products_db if str(p['id']) == str(item['product_id'])), None)
                        if not product_obj:
                             product_obj = next((p for p in products_db if p['name'] == item['name']), None)
                             
                        if product_obj:
                            qty = item['qty']
                            log_stock_action(
                                user=session.get('user'),
                                action='saida',
                                product=product_obj['name'],
                                qty=qty,
                                details=f"Consumo Funcionario {order.get('staff_name')}",
                                department='Restaurante'
                            )
                            save_stock_entry({
                                'id': str(uuid.uuid4()),
                                'date': datetime.now().strftime('%d/%m/%Y'),
                                'product': product_obj['name'],
                                'qty': -abs(qty),
                                'unit': product_obj.get('unit', 'un'),
                                'price': product_obj.get('price', 0),
                                'supplier': 'Consumo Interno',
                                'invoice': f"Func {order.get('staff_name')}",
                                'user': session.get('user')
                            })

                    del orders[str_table_id]
                    save_table_orders(orders)
                    flash('Conta de funcionário salva e mesa liberada.')
                    return redirect(url_for('restaurant.restaurant_tables'))

        # ... other actions ...

    service_fee = 0.0
    grand_total = 0.0
    if str_table_id in orders:
        order = orders[str_table_id]
        # Regra: Funcionário não paga taxa de serviço e recebe 20% de desconto
        if order.get('customer_type') == 'funcionario':
            subtotal = float(order.get('total', 0) or 0)
            staff_discount = round(subtotal * 0.20, 2)
            service_fee = 0.0
            grand_total = max(0.0, subtotal - staff_discount)
            # Anotações auxiliares no objeto em memória (não persistidas aqui)
            order['calculated_staff_discount'] = staff_discount
            order['calculated_service_fee'] = service_fee
            order['calculated_grand_total'] = grand_total
        else:
            service_fee = order.get('total', 0) * 0.1
            grand_total = order.get('total', 0) + service_fee

    products = load_menu_items()
    flavor_groups = load_flavor_groups()
    observations = load_observations()
    settings = load_settings()
    
    # Group products by category
    grouped_products_dict = {}
    
    # PERMISSION CHECK FOR VIEWING INACTIVE PRODUCTS
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    # Only Admin/Manager can see inactive items, BUT paused items are hidden for everyone in order view
    can_manage_items = user_role in ['admin', 'gerente', 'supervisor'] or 'restaurante_full_access' in user_perms
    
    hidden_paused_count = 0
    def _boolish(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true','on','1','checked','paused','yes')
        if isinstance(v, int):
            return v != 0
        return False
    
    filtered_products = []
    for p in products:
        if _boolish(p.get('paused', False)):
            hidden_paused_count += 1
            continue
        if p.get('active', True) or can_manage_items:
            cat = p.get('category', 'Outros')
            if cat == 'Frigobar' and mode != 'minibar' and session.get('department') != 'Serviço':
                continue
            if cat not in grouped_products_dict:
                grouped_products_dict[cat] = []
            grouped_products_dict[cat].append(p)
            filtered_products.append(p)
            
    if hidden_paused_count > 0:
        # Log occasionally or if needed
        pass
            
    # Sort categories based on settings or default to alphabetical
    saved_order = settings.get('category_order', [])
    all_cats = list(grouped_products_dict.keys())
    
    final_sorted_cats = []
    
    # 1. Add configured categories in order
    for cat in saved_order:
        if cat in all_cats:
            final_sorted_cats.append(cat)
            
    # 2. Add remaining categories (alphabetical)
    remaining = sorted([c for c in all_cats if c not in final_sorted_cats])
    final_sorted_cats.extend(remaining)

    grouped_products = [(cat, grouped_products_dict[cat]) for cat in final_sorted_cats]

    # --- Group Order Items ---
    grouped_order_items = []
    if str_table_id in orders:
        items = orders[str_table_id].get('items', [])
        groups = {}
        
        for item in items:
            try:
                # Create a unique key for grouping
                comps_list = item.get('complements', [])
                comps_key = tuple()
                if comps_list:
                    if isinstance(comps_list[0], dict):
                        comps_key = tuple(sorted([(c.get('name', ''), float(c.get('price', 0))) for c in comps_list]))
                    else:
                        comps_key = tuple(sorted([str(c) for c in comps_list]))

                obs_list = item.get('observations', [])
                obs_key = tuple(sorted(obs_list)) if obs_list else tuple()
                
                key = (
                    item.get('name'),
                    item.get('flavor'),
                    comps_key,
                    obs_key,
                    float(item.get('price', 0)),
                    item.get('print_status', 'pending' if not item.get('printed') else 'printed'),
                    item.get('printed', False)
                )
                
                if key not in groups:
                    groups[key] = {
                        'name': item.get('name'),
                        'flavor': item.get('flavor'),
                        'complements': item.get('complements', []),
                        'observations': item.get('observations', []),
                        'price': float(item.get('price', 0)),
                        'qty': 0.0,
                        'total': 0.0,
                        'ids': [],
                        'print_status': item.get('print_status', 'pending' if not item.get('printed') else 'printed'),
                        'printed': item.get('printed', False),
                        'last_item_qty': 0.0
                    }
                
                qty = float(item.get('qty', 0))
                groups[key]['qty'] += qty
                groups[key]['last_item_qty'] = qty
                groups[key]['ids'].append(item.get('id'))

                # Calculate total for this item instance
                comp_total = 0.0
                for c in item.get('complements', []):
                    if isinstance(c, dict):
                        comp_total += float(c.get('price', 0))
                
                item_total = qty * (float(item.get('price', 0)) + comp_total)
                groups[key]['total'] += item_total
            except Exception as e:
                print(f"Error grouping item {item.get('name')}: {e}")
                continue
            
        grouped_order_items = list(groups.values())

    # Check Cashier Status for UI
    current_cashier = get_current_cashier(cashier_type='restaurant')
    is_cashier_open = current_cashier is not None

    payment_methods = load_payment_methods()
    payment_methods = [m for m in payment_methods if 'restaurant' in m.get('available_in', []) or 'caixa_restaurante' in m.get('available_in', [])]
    
    # List of all potential tables for transfer (Exclude 1-35 rooms, so 36-60 + active others)
    # User Request: Exclude 1-35 (rooms) from transfer list
    # User Request: Exclude disabled/hidden tables
    
    # Load table settings to get disabled tables
    table_settings = load_restaurant_table_settings()
    disabled_tables = table_settings.get('disabled_tables', [])
    
    all_tables = []
    
    # 1. Add Standard Tables (36-101) if not disabled
    for i in range(36, 102):
        t_id = str(i)
        if t_id not in disabled_tables:
            all_tables.append(t_id)
    
    # 2. Add open orders that are not in standard range (e.g. staff, or old tables)
    # But ONLY if they are not disabled (unless we want to allow transfer FROM/TO a disabled table if it's already open?)
    # Validating "visible" means we should probably exclude disabled ones even if open, 
    # but if it's open, hiding it might make it impossible to transfer FROM it?
    # The request says "load in interface... visible". 
    # If I am on a disabled table, I can see the page. I want to transfer TO another table.
    # The list is "target" tables. So we definitely exclude disabled tables from the list.
    
    for t_id in orders.keys():
        if t_id not in all_tables:
            # Exclude Rooms (1-35)
            if t_id.isdigit() and 1 <= int(t_id) <= 35:
                continue
            
            # Exclude Disabled Tables
            if t_id in disabled_tables:
                continue
                
            all_tables.append(t_id)
            
    all_tables.sort(key=lambda x: int(x) if x.isdigit() else 9999)

    # Pass occupied tables for UI indicators
    occupied_tables = list(orders.keys())

    return render_template('restaurant_table_order.html', 
                           table_id=table_id, 
                           breakfast_table_id=breakfast_table_id,
                           order=orders.get(str_table_id), 
                           complements=complements, 
                           users=users, 
                           room_occupancy=room_occupancy, 
                           mode=mode, 
                           service_fee=service_fee, 
                           grand_total=grand_total, 
                           products=filtered_products, 
                           observations=observations,
                           grouped_products=grouped_products,
                           grouped_order_items=grouped_order_items,
                           flavor_groups=flavor_groups,
                           is_cashier_open=is_cashier_open,
                           payment_methods=payment_methods,
                           category_colors=settings.get('category_colors', {}),
                           all_tables=all_tables,
                           occupied_tables=occupied_tables,
                           can_manage_items=can_manage_items)

@restaurant_bp.route('/restaurant/dashboard')
@login_required
def restaurant_dashboard():
    return render_template('restaurant_dashboard.html')

@restaurant_bp.route('/restaurant/transfer_item', methods=['POST'])
@login_required
def restaurant_transfer_item():
    try:
        if session.get('role') not in ['admin', 'gerente', 'supervisor']:
             return jsonify({'success': False, 'error': 'Permissão negada. Apenas Gerentes e Supervisores.'}), 403

        data = request.get_json()
        source_table_id = str(data.get('source_table_id'))
        dest_table_id = str(data.get('target_table_id'))
        item_index = data.get('item_index')
        qty_to_transfer = float(data.get('qty'))
        
        # Log transfer attempt for debugging
        current_app.logger.info(f"Transfer Item Request: Source={source_table_id}, Target={dest_table_id}, Qty={qty_to_transfer}, User={session.get('user')}")

        if not source_table_id or not dest_table_id or item_index is None or qty_to_transfer <= 0:
             current_app.logger.warning(f"Invalid transfer data: {data}")
             return jsonify({'success': False, 'error': 'Dados inválidos.'}), 400

        orders = load_table_orders()
        
        if source_table_id not in orders:
            return jsonify({'success': False, 'error': f'Mesa de origem {source_table_id} não encontrada ou fechada.'}), 400
            
        # Validate Destination Table (Security & Existence Check)
        table_settings = load_restaurant_table_settings()
        disabled_tables = table_settings.get('disabled_tables', [])
        
        # 1. Check if disabled/hidden
        if dest_table_id in disabled_tables:
             return jsonify({'success': False, 'error': f'Erro: Mesa de destino {dest_table_id} está desabilitada/oculta.'}), 400
             
        # 2. Check if it's a Room (1-35) - Should use "Transfer to Room"
        if dest_table_id.isdigit() and 1 <= int(dest_table_id) <= 35:
             return jsonify({'success': False, 'error': f'Erro: Use a função "Enviar para Quarto" para transferir para o quarto {dest_table_id}.'}), 400

        # 3. Check if valid physical table (Standard Range 36-101) OR already open (e.g. Staff/Extra)
        # If it's outside range and not open, it's considered "non-existent"
        is_standard = dest_table_id.isdigit() and 36 <= int(dest_table_id) <= 101
        is_open = dest_table_id in orders
        is_staff = dest_table_id.startswith('FUNC_')
        
        if not (is_standard or is_open or is_staff):
             return jsonify({'success': False, 'error': f'Erro: Mesa de destino {dest_table_id} inválida ou inexistente.'}), 400

        if dest_table_id not in orders:
            # Auto-open the destination table if it's closed (Fix for Problem 2)
            # Create a basic open order structure
            orders[dest_table_id] = {
                'items': [], 
                'total': 0, 
                'status': 'open', 
                'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'num_adults': 1, # Default
                'customer_type': 'funcionario' if is_staff else 'passante',
                'customer_name': None if is_staff else 'Transferencia',
                'waiter': session.get('user'),
                'staff_name': dest_table_id.replace('FUNC_', '') if is_staff else None
            }
            # return jsonify({'success': False, 'error': f'Mesa de destino {dest_table_id} não está aberta.'}), 400
            if dest_table_id == '36':
                orders[dest_table_id]['customer_type'] = 'passante'
                orders[dest_table_id]['customer_name'] = 'Café da Manhã'
                orders[dest_table_id]['room_number'] = None
                orders[dest_table_id]['is_breakfast'] = True

        # SPECIAL TABLES VALIDATION FOR ITEM TRANSFER
        if dest_table_id in ['36', '69', '68']:
            from app.services.special_tables_service import SpecialTablesService
            source_opened_at = orders.get(source_table_id, {}).get('opened_at')
            # For item transfer, we pass the specific item (wrapped in list)
            # Actually we just need to pass context, item list is less relevant for time check
            # But we should find the item first to be precise? 
            # Logic below finds item. But we want to fail fast.
            # Let's pass empty list for now as validate_transfer_to_special only checks time for Table 36
            valid, msg = SpecialTablesService.validate_transfer_to_special(dest_table_id, [], session.get('user'), source_created_at=source_opened_at)
            
            if not valid:
                 return jsonify({'success': False, 'error': f"Transferência bloqueada: {msg}"}), 400

        source_order = orders[source_table_id]
        dest_order = orders[dest_table_id]
        if dest_table_id == '36':
            dest_order['customer_type'] = 'passante'
            dest_order['customer_name'] = 'Café da Manhã'
            dest_order['room_number'] = None
            dest_order['is_breakfast'] = True
        
        if source_order.get('locked'):
            return jsonify({'success': False, 'error': 'Não é possível transferir itens de uma conta fechada/puxada.'}), 400

        # Validate and Find Item (Priority: ID -> Index)
        item_id = data.get('item_id')
        item = None
        found_index = -1

        # 1. Try finding by ID
        if item_id:
            for idx, it in enumerate(source_order['items']):
                if str(it.get('id')) == str(item_id):
                    item = it
                    found_index = idx
                    break
        
        # 2. Fallback to Index if not found by ID
        if item is None:
            try:
                idx = int(item_index) if item_index is not None else -1
                if 0 <= idx < len(source_order['items']):
                    item = source_order['items'][idx]
                    found_index = idx
            except (ValueError, TypeError):
                pass

        if item is None:
            current_app.logger.error(f"Transfer Item Failed: Item Not Found. Source={source_table_id}, ItemID={item_id}, Index={item_index}, User={session.get('user')}")
            return jsonify({'success': False, 'error': 'Item não encontrado. Verifique se o item ainda existe na comanda.'}), 404

        # Update item_index to the correct one found
        item_index = found_index

        if item['qty'] < qty_to_transfer:
             return jsonify({'success': False, 'error': f'Quantidade insuficiente. Disponível: {item["qty"]}'}), 400

        new_item = item.copy()
        new_item['id'] = str(uuid.uuid4())
        new_item['qty'] = qty_to_transfer
        new_item['transferred_from'] = source_table_id
        new_item['transferred_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        new_item['transferred_by'] = session.get('user')
        new_item['printed'] = item.get('printed', False)
        new_item['print_status'] = item.get('print_status', 'printed') 
        
        if 'observations' not in new_item:
            new_item['observations'] = []
        new_item['observations'].append(f"Transf de Mesa {source_table_id}")
        if data.get('observations'):
             new_item['observations'].append(data.get('observations'))
        
        if abs(item['qty'] - qty_to_transfer) < 0.001:
            source_order['items'].pop(item_index)
        else:
            item['qty'] -= qty_to_transfer
            
        dest_order['items'].append(new_item)
        
        def calculate_order_total(order_items):
            total = 0
            for i in order_items:
                i_total = i['qty'] * i['price']
                if 'complements' in i:
                    for c in i['complements']:
                        i_total += i['qty'] * c['price']
                total += i_total
            return total

        source_order['total'] = calculate_order_total(source_order['items'])
        dest_order['total'] = calculate_order_total(dest_order['items'])
        
        # VALIDATION: Check if source table total_paid exceeds new total
        # This prevents transferring items that have effectively been paid for
        total_paid = source_order.get('total_paid', 0.0)
        # Apply strict check: total_paid must be <= new total (plus a small margin for float errors)
        # However, service fee is usually added on top. 
        # If total_paid > source_order['total'] * 1.1 (approx), it's definitely an issue.
        # But safely, if total_paid > source_order['total'] (raw), we might be in trouble depending on if service fee was paid.
        # Let's assume raw total for safety, or better:
        # If the user paid 50, and now the bill is 40, we have a problem.
        # We should allow if total_paid <= new_total * 1.1 (assuming service fee might be applicable)
        # But safest is: Warning or Block.
        # Let's BLOCK if total_paid > new_total * 1.1 + 0.01
        
        # Calculate max possible total (with service fee)
        max_new_total = source_order['total'] * 1.1
        
        if total_paid > (max_new_total + 0.10): # 10 cents tolerance
             # Revert changes
             if abs(item.get('qty', 0) + qty_to_transfer - item.get('qty', 0)) < 0.001: # Was popped
                  # This logic is hard to revert perfectly without deep copy.
                  # Better to check BEFORE modifying.
                  pass
             # We need to fail. But we already modified the objects in memory.
             # Since we haven't saved, we can just reload or return error (and not save).
             # Returning error ensures `save_table_orders(orders)` is not called.
             return jsonify({'success': False, 'error': f'Transferência bloqueada: Valor pago (R$ {total_paid:.2f}) excederia o novo total da mesa (aprox R$ {max_new_total:.2f}). Estorne pagamentos parciais antes.'}), 400

        try:
            save_table_orders(orders)
            log_action('Transferência Item', f'Item {item["name"]} (x{qty_to_transfer}) transferido da Mesa {source_table_id} para {dest_table_id}', department='Restaurante')
            return jsonify({'success': True})
        except Exception as save_error:
            return jsonify({'success': False, 'error': f'Erro ao salvar: {str(save_error)}'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@restaurant_bp.route('/api/restaurant/stats')
@login_required
def api_restaurant_stats():
    date_q = request.args.get('date')
    if not date_q:
        date_q = datetime.now().strftime('%Y-%m-%d')
    try:
        target_date = datetime.strptime(date_q, '%Y-%m-%d').date()
    except:
        target_date = datetime.now().date()
    date_br = target_date.strftime('%d/%m/%Y')
    orders = load_table_orders()
    menu_items = load_menu_items()
    product_map = {p['name']: p for p in menu_items}
    bar_cats = {'Cervejas', 'Drinks', 'Vinhos', 'Refrigerante', 'Sucos e Águas', 'Doses'}
    def sector_for(name, fallback_cat=None):
        p = product_map.get(name)
        cat = p.get('category') if p else fallback_cat
        if cat == 'Frigobar':
            return 'Ignore'
        return 'Bar' if cat in bar_cats else 'Cozinha'
    def parse_ts(s):
        try:
            return datetime.strptime(s, '%d/%m/%Y %H:%M')
        except:
            return None
    def in_shift(h, start, end):
        return h >= start and h < end
    kpi_total_orders = 0
    kpi_attend_orders = set()
    shifts = {
        'breakfast': {'hours': [7,8,9,10], 'items': [], 'waiters': {}, 'hourly': {7:0,8:0,9:0,10:0}},
        'lunch': {'hours': list(range(11,17)), 'items': [], 'waiters': {}, 'hourly': {h:0 for h in range(11,17)}, 'hourly_kitchen': {h:0 for h in range(11,17)}, 'hourly_bar': {h:0 for h in range(11,17)}, 'att_hospedes': set(), 'att_passantes': set(), 'rank_kitchen': {}, 'rank_bar': {}},
        'dinner': {'hours': list(range(17,23)), 'items': [], 'waiters': {}, 'hourly': {h:0 for h in range(17,23)}, 'hourly_kitchen': {h:0 for h in range(17,23)}, 'hourly_bar': {h:0 for h in range(17,23)}, 'att_hospedes': set(), 'att_passantes': set(), 'rank_kitchen': {}, 'rank_bar': {}}
    }
    for tid, order in orders.items():
        items = order.get('items', [])
        cust = order.get('customer_type')
        for it in items:
            ts = parse_ts(it.get('created_at') or order.get('opened_at') or '')
            if not ts or ts.date().strftime('%d/%m/%Y') != date_br:
                continue
            h = ts.hour
            qty = float(it.get('qty', 0))
            if qty <= 0:
                continue
            kpi_total_orders += qty
            kpi_attend_orders.add(tid)
            waiter = it.get('waiter') or order.get('waiter') or 'N/A'
            name = it.get('name')
            cat = it.get('category')
            sector = sector_for(name, cat)
            if in_shift(h,7,11):
                shifts['breakfast']['items'].append(it)
                shifts['breakfast']['hourly'][h] = shifts['breakfast']['hourly'].get(h,0) + qty
                shifts['breakfast']['waiters'][waiter] = shifts['breakfast']['waiters'].get(waiter,0) + qty
            elif in_shift(h,11,17):
                s = shifts['lunch']
                s['items'].append(it)
                s['hourly'][h] = s['hourly'].get(h,0) + qty
                s['waiters'][waiter] = s['waiters'].get(waiter,0) + qty
                if sector != 'Ignore':
                    if sector == 'Cozinha':
                        s['hourly_kitchen'][h] = s['hourly_kitchen'].get(h,0) + qty
                        s['rank_kitchen'][name] = s['rank_kitchen'].get(name,0) + qty
                    else:
                        s['hourly_bar'][h] = s['hourly_bar'].get(h,0) + qty
                        s['rank_bar'][name] = s['rank_bar'].get(name,0) + qty
                if cust == 'hospede':
                    s['att_hospedes'].add(tid)
                elif cust != 'funcionario':
                    s['att_passantes'].add(tid)
            elif in_shift(h,17,23):
                s = shifts['dinner']
                s['items'].append(it)
                s['hourly'][h] = s['hourly'].get(h,0) + qty
                s['waiters'][waiter] = s['waiters'].get(waiter,0) + qty
                if sector != 'Ignore':
                    if sector == 'Cozinha':
                        s['hourly_kitchen'][h] = s['hourly_kitchen'].get(h,0) + qty
                        s['rank_kitchen'][name] = s['rank_kitchen'].get(name,0) + qty
                    else:
                        s['hourly_bar'][h] = s['hourly_bar'].get(h,0) + qty
                        s['rank_bar'][name] = s['rank_bar'].get(name,0) + qty
                if cust == 'hospede':
                    s['att_hospedes'].add(tid)
                elif cust != 'funcionario':
                    s['att_passantes'].add(tid)
    def top_n(d,k):
        return [{'name': a, 'qty': b} for a,b in sorted(d.items(), key=lambda x: x[1], reverse=True)[:k]]
    breakfast_top = {}
    for it in shifts['breakfast']['items']:
        breakfast_top[it.get('name')] = breakfast_top.get(it.get('name'),0) + float(it.get('qty',0))
    resp = {
        'date': date_q,
        'kpi': {
            'total_pedidos': kpi_total_orders,
            'total_atendimentos': len(kpi_attend_orders)
        },
        'breakfast': {
            'total_pedidos': sum(float(i.get('qty',0)) for i in shifts['breakfast']['items']),
            'top_items': top_n(breakfast_top,5),
            'movement_hourly': [{'hour': h, 'count': shifts['breakfast']['hourly'].get(h,0)} for h in shifts['breakfast']['hours']],
            'attendants': [{'name': n, 'count': c} for n,c in sorted(shifts['breakfast']['waiters'].items(), key=lambda x: x[1], reverse=True)]
        },
        'lunch': {
            'attendances': {'hospedes': len(shifts['lunch']['att_hospedes']), 'passantes': len(shifts['lunch']['att_passantes'])},
            'movement_hourly': [{'hour': h, 'count': shifts['lunch']['hourly'].get(h,0)} for h in shifts['lunch']['hours']],
            'movement_segmented': {
                'cozinha': [{'hour': h, 'count': shifts['lunch']['hourly_kitchen'].get(h,0)} for h in shifts['lunch']['hours']],
                'bar': [{'hour': h, 'count': shifts['lunch']['hourly_bar'].get(h,0)} for h in shifts['lunch']['hours']]
            },
            'top_kitchen': top_n(shifts['lunch']['rank_kitchen'],6),
            'top_bar': top_n(shifts['lunch']['rank_bar'],6),
            'attendants': [{'name': n, 'count': c} for n,c in sorted(shifts['lunch']['waiters'].items(), key=lambda x: x[1], reverse=True)]
        },
        'dinner': {
            'attendances': {'hospedes': len(shifts['dinner']['att_hospedes']), 'passantes': len(shifts['dinner']['att_passantes'])},
            'movement_hourly': [{'hour': h, 'count': shifts['dinner']['hourly'].get(h,0)} for h in shifts['dinner']['hours']],
            'movement_segmented': {
                'cozinha': [{'hour': h, 'count': shifts['dinner']['hourly_kitchen'].get(h,0)} for h in shifts['dinner']['hours']],
                'bar': [{'hour': h, 'count': shifts['dinner']['hourly_bar'].get(h,0)} for h in shifts['dinner']['hours']]
            },
            'top_kitchen': top_n(shifts['dinner']['rank_kitchen'],4),
            'top_bar': top_n(shifts['dinner']['rank_bar'],4),
            'attendants': [{'name': n, 'count': c} for n,c in sorted(shifts['dinner']['waiters'].items(), key=lambda x: x[1], reverse=True)]
        }
    }
    return jsonify(resp)

@restaurant_bp.route('/api/check_table/<table_id>')
@login_required
def check_table_status(table_id):
    orders = load_table_orders()
    str_table_id = str(table_id)
    if str_table_id in orders:
        return jsonify({'status': 'occupied'})
    return jsonify({'status': 'open'})

@restaurant_bp.route('/api/available_tables')
@login_required
def get_available_tables():
    orders = load_table_orders()
    table_settings = load_restaurant_table_settings()
    disabled_tables = table_settings.get('disabled_tables', [])
    
    available = []
    # Standard Tables Ranges based on template
    # Areas: 40-50, 50-58, 58-62, 70-80, 89-101, 80-89, 36-40, 62-70
    # Simplified: 36-101 excluding gaps if any, but let's be explicit to match UI areas roughly
    # Ranges: 36-101 covers most.
    
    all_tables = []
    all_tables.extend(range(36, 102)) # 36 to 101
    
    for i in all_tables:
        t_id = str(i)
        if t_id not in orders and t_id not in disabled_tables:
            available.append(t_id)
            
    return jsonify(available)

@restaurant_bp.route('/api/products/paused')
@login_required
def get_paused_products():
    """Returns a list of IDs of paused products."""
    menu_items = load_menu_items()
    def _boolish(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true','on','1','checked','paused','yes')
        if isinstance(v, int):
            return v != 0
        return False
    paused_ids = [str(p.get('id')) for p in menu_items if _boolish(p.get('paused', False))]
    return jsonify({'paused_ids': paused_ids})

@restaurant_bp.route('/restaurant/order/edit_item', methods=['POST'])
@login_required
def restaurant_edit_order_item():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and 'restaurante_full_access' not in user_perms:
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    table_id = request.form.get('table_id')
    item_id = request.form.get('item_id')
    new_qty = request.form.get('qty')
    new_obs = request.form.get('observations')

    if not table_id or not item_id:
        return jsonify({'success': False, 'error': 'Dados incompletos.'}), 400

    orders = load_table_orders()
    str_table_id = str(table_id)
    
    if str_table_id not in orders:
        return jsonify({'success': False, 'error': 'Mesa não encontrada.'}), 404

    order = orders[str_table_id]
    item_found = False
    
    for item in order.get('items', []):
        if str(item.get('id')) == str(item_id):
            item_found = True
            if new_qty:
                try:
                    qty_val = float(new_qty)
                    if qty_val > 0:
                        item['qty'] = qty_val
                except ValueError:
                    pass
            
            if new_obs is not None:
                if new_obs.strip():
                    item['observations'] = [x.strip() for x in new_obs.split(',')]
                else:
                    item['observations'] = []
            
            # Recalculate total
            total = 0
            for i in order['items']:
                p = i['price']
                c = sum(cp['price'] for cp in i.get('complements', []))
                total += i['qty'] * (p + c)
            order['total'] = total
            break
    
    if not item_found:
        return jsonify({'success': False, 'error': 'Item não encontrado.'}), 404

    save_table_orders(orders)
    log_action('Item Editado', f'Item editado na Mesa {table_id} por {session.get("user")}', department='Restaurante')
    
    return jsonify({'success': True})

@restaurant_bp.route('/restaurant/product/toggle_active', methods=['POST'])
@login_required
def restaurant_toggle_product_active():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and 'restaurante_full_access' not in user_perms:
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403
        
    product_id = request.form.get('product_id')
    if not product_id:
        return jsonify({'success': False, 'error': 'ID do produto necessário.'}), 400
        
    menu_items = load_menu_items()
    save_menu_items = None
    from app.services.data_service import save_menu_items as _save_menu_items
    save_menu_items = _save_menu_items
    
    found = False
    new_status = True
    
    for p in menu_items:
        if str(p['id']) == str(product_id):
            p['active'] = not p.get('active', True)
            new_status = p['active']
            found = True
            break
            
    if found:
        save_menu_items(menu_items)
        status_str = "Ativo" if new_status else "Pausado"
        log_action('Produto Alterado', f'Produto {product_id} alterado para {status_str} por {session.get("user")}', department='Restaurante')
        return jsonify({'success': True, 'new_status': new_status})
    else:
        return jsonify({'success': False, 'error': 'Produto não encontrado.'}), 404

from app.services import waiting_list_service

@restaurant_bp.route('/fila', methods=['GET', 'POST'])
def public_waiting_list():
    settings = waiting_list_service.get_settings()
    
    # Check if user is already in queue (cookie or session)
    user_entry_id = session.get('waiting_list_id')
    entry = None
    position = 0
    
    if user_entry_id:
        # Check if still valid
        queue = waiting_list_service.get_waiting_list()
        # Find entry
        for i, item in enumerate(queue):
            if item['id'] == user_entry_id:
                entry = item
                # Add position info
                position = i + 1
                break
                
        # If entry not found in active queue (maybe seated/removed), check if we should clear session?
        # For now, let template handle "not found" or just show form again if entry is None.
    
    if request.method == 'POST':
        if not settings.get('is_open'):
            flash('A fila de espera está fechada.')
            return redirect(url_for('restaurant.public_waiting_list'))
            
        # Bot check
        if request.form.get('honeypot'):
            return "Erro", 400
            
        name = request.form.get('name')
        phone = request.form.get('phone')
        party_size = request.form.get('party_size')
        
        if not name or not phone or not party_size:
            flash('Preencha todos os campos.')
            return redirect(url_for('restaurant.public_waiting_list'))
            
        result, error = waiting_list_service.add_customer(name, phone, party_size)
        
        if error:
            flash(error)
        else:
            session['waiting_list_id'] = result['entry']['id']
            session.permanent = True
            return redirect(url_for('restaurant.public_waiting_list'))
            
    return render_template('waiting_list_public.html', entry=entry, position=position, settings=settings)

@restaurant_bp.route('/fila/cancel/<id>')
def cancel_waiting_list_entry(id):
    # Verify ownership via session if public
    if session.get('waiting_list_id') == id or session.get('role') in ['admin', 'gerente', 'recepcao']:
        waiting_list_service.update_customer_status(id, 'cancelled', reason="User cancelled")
        if session.get('waiting_list_id') == id:
            session.pop('waiting_list_id', None)
        flash('Você saiu da fila.')
    return redirect(url_for('restaurant.public_waiting_list'))
