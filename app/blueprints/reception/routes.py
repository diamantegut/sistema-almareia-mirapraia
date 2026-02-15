import json
import uuid
import os
import re
import random
import traceback
import subprocess
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app, send_file

from . import reception_bp
from app.utils.decorators import login_required
from app.services.data_service import (
    load_room_charges, save_room_charges, load_menu_items, load_products, 
    save_stock_entry, load_cashier_sessions, save_cashier_sessions, 
    load_payment_methods, load_room_occupancy, save_room_occupancy,
    load_cleaning_status, save_cleaning_status, load_checklist_items, save_checklist_items,
    add_inspection_log, normalize_text, format_room_number, normalize_room_simple,
    ARCHIVED_ORDERS_FILE, load_table_orders, save_table_orders,
    load_audit_logs, save_audit_logs
)
from app.services.system_config_manager import RESERVATIONS_DIR
from app.services.printer_manager import load_printers, load_printer_settings, save_printer_settings
from app.services.printing_service import process_and_print_pending_bills, print_individual_bills_thermal, print_cashier_ticket, print_cashier_ticket_async
from app.services.logger_service import log_system_action, LoggerService
from app.utils.logger import log_action
from app.services.transfer_service import return_charge_to_restaurant, TableOccupiedError, TransferError
from app.services.cashier_service import CashierService
from app.services.fiscal_pool_service import FiscalPoolService
from app.services import waiting_list_service
from app.services.reservation_service import ReservationService
from app.services.whatsapp_chat_service import WhatsAppChatService
chat_service = WhatsAppChatService()
from app.services.whatsapp_service import WhatsAppService
from app.utils.validators import (
    validate_required, validate_phone, validate_cpf, validate_email, 
    sanitize_input, validate_date, validate_room_number
)

# --- Helpers ---

def verify_reception_integrity():
    """Checks if critical data files and services are available."""
    try:
        # 1. Check Data Files Loading
        load_room_occupancy()
        load_cleaning_status()
        load_room_charges()
        load_table_orders()
        
        # 2. Check Session Context
        if not session.get('user'):
            return False, "Sessão de usuário inválida."
            
        return True, "Sistema íntegro."
    except Exception as e:
        return False, f"Falha na integridade de dados: {str(e)}"

def parse_br_currency(val):
    if not val: return 0.0
    if isinstance(val, (float, int)): return float(val)
    val = str(val).strip()
    val = val.replace('R$', '').replace(' ', '')
    if ',' in val:
        val_clean = val.replace('.', '').replace(',', '.')
        try:
            return float(val_clean)
        except ValueError:
            return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0

# --- Routes ---

@reception_bp.route('/reception')
@login_required
def reception_dashboard():
    # Permission Check
    user_role = session.get('role')
    role_norm = normalize_text(str(user_role or ''))
    
    user_dept = session.get('department')
    dept_norm = normalize_text(str(user_dept or ''))
    
    user_perms = session.get('permissions') or []
    has_reception_permission = isinstance(user_perms, (list, tuple, set)) and any(normalize_text(str(p)) == 'recepcao' for p in user_perms)

    if role_norm not in ['admin', 'gerente', 'recepcao', 'supervisor'] and dept_norm != 'recepcao' and not has_reception_permission:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    return render_template('reception_dashboard.html')

@reception_bp.route('/reception/rooms', methods=['GET', 'POST'])
@login_required
def reception_rooms():
    # 1. Integrity Check
    is_valid, msg = verify_reception_integrity()
    if not is_valid:
        flash(f"ERRO CRÍTICO: {msg}", 'error')
        log_system_action('Integrity Check Failed', 'Reception', msg)
        return redirect(url_for('main.index'))

    # Permission Check
    user_role = session.get('role')
    role_norm = normalize_text(str(user_role or ''))
    
    user_dept = session.get('department')
    dept_norm = normalize_text(str(user_dept or ''))
    
    user_perms = session.get('permissions') or []
    has_reception_permission = isinstance(user_perms, (list, tuple, set)) and any(normalize_text(str(p)) == 'recepcao' for p in user_perms)

    if role_norm not in ['admin', 'gerente', 'recepcao', 'supervisor'] and dept_norm != 'recepcao' and not has_reception_permission:
         flash('Acesso restrito.')
         return redirect(url_for('main.index'))

    occupancy = load_room_occupancy()
    cleaning_status = load_cleaning_status()
    checklist_items = load_checklist_items()
    
    # Pre-allocation integration
    upcoming_checkins = {}
    try:
        res_service = ReservationService()
        upcoming_list = res_service.get_upcoming_checkins()
        for item in upcoming_list:
            upcoming_checkins[item['room']] = item
    except Exception as e:
        print(f"Error loading upcoming checkins: {e}")

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'pay_charge':
            current_user = session.get('user')
            # Find current open reception session
            current_session = CashierService.get_active_session('guest_consumption')
            if not current_session:
                 current_session = CashierService.get_active_session('reception_room_billing')
            
            if not current_session:
                flash('É necessário abrir o caixa de Consumo de Hóspedes antes de receber pagamentos.')
                return redirect(url_for('reception.reception_cashier'))
            
            charge_id = request.form.get('charge_id')
            
            # MULTI-PAYMENT LOGIC
            payment_data_json = request.form.get('payment_data')
            payments = []
            
            if payment_data_json:
                try:
                    payments = json.loads(payment_data_json)
                except json.JSONDecodeError:
                    flash('Erro ao processar dados de pagamento.')
                    return redirect(url_for('reception.reception_rooms'))
            
            if not payments:
                flash('Nenhum pagamento informado.')
                return redirect(url_for('reception.reception_rooms'))

            emit_invoice = session.get('role') == 'admin' and request.form.get('emit_invoice') == 'on'
            
            room_charges = load_room_charges()
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge and charge.get('status') == 'pending':
                payment_methods_list = load_payment_methods()
                
                # Validate Total
                total_paid = sum(float(p.get('amount', 0)) for p in payments)
                charge_total = float(charge['total'])
                
                if abs(total_paid - charge_total) > 0.05: # Tolerance
                     flash(f'Valor pago (R$ {total_paid:.2f}) difere do total da conta (R$ {charge_total:.2f}).')
                     return redirect(url_for('reception.reception_rooms'))

                # Generate Payment Group ID
                payment_group_id = str(uuid.uuid4()) if len(payments) > 1 else None
                total_payment_group_amount = total_paid if payment_group_id else 0
                
                # Prepare Fiscal Payments List
                fiscal_payments = []
                primary_payment_method_id = payments[0].get('id')

                # Process Transactions
                for p in payments:
                    p_amount = float(p.get('amount', 0))
                    p_id = p.get('id')
                    p_name = p.get('name')
                    
                    # Verify name against ID if possible
                    p_method_obj = next((m for m in payment_methods_list if str(m['id']) == str(p_id)), None)
                    if p_method_obj:
                        p_name = p_method_obj['name']
                        is_fiscal = p_method_obj.get('is_fiscal', False)
                    else:
                        is_fiscal = False
                    
                    fiscal_payments.append({
                        'method': p_name,
                        'amount': p_amount,
                        'is_fiscal': is_fiscal
                    })

                    CashierService.add_transaction(
                        cashier_type='guest_consumption',
                        amount=p_amount,
                        description=f"Pagamento Quarto {charge['room_number']} ({p_name})",
                        payment_method=p_name,
                        user=current_user,
                        details={
                            'room_number': charge['room_number'],
                            'emit_invoice': emit_invoice,
                            'category': 'Pagamento de Conta',
                            'payment_group_id': payment_group_id,
                            'total_payment_group_amount': total_payment_group_amount,
                            'payment_details': payments # Store all payments in details too
                        }
                    )

                # Update Charge
                charge['status'] = 'paid'
                charge['payment_method'] = 'Múltiplos' if len(payments) > 1 else fiscal_payments[0]['method']
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['reception_cashier_id'] = current_session['id']
                charge['payment_details'] = payments
                save_room_charges(room_charges)
                
                flash(f"Pagamento de R$ {charge['total']:.2f} recebido com sucesso.")

                # FISCAL POOL INTEGRATION
                try:
                    items_list = charge.get('items', [])
                    if isinstance(items_list, str):
                        try: items_list = json.loads(items_list)
                        except: items_list = []
                    
                    occupancy = load_room_occupancy()
                    guest_name = occupancy.get(str(charge['room_number']), {}).get('guest_name', 'Hóspede')

                    FiscalPoolService.add_to_pool(
                        origin='reception',
                        original_id=charge['id'],
                        total_amount=float(charge['total']),
                        items=items_list,
                        payment_methods=fiscal_payments,
                        user=current_user,
                        customer_info={'room_number': charge['room_number'], 'guest_name': guest_name}
                    )
                except Exception as e:
                    current_app.logger.error(f"Error adding charge to fiscal pool: {e}")

            else:
                flash('Conta não encontrada ou já paga.')
            
            return redirect(url_for('reception.reception_rooms'))
        
        if action == 'add_checklist_item':
            new_item = request.form.get('item_name')
            if new_item and new_item not in checklist_items:
                checklist_items.append(new_item)
                save_checklist_items(checklist_items)
                flash('Item adicionado ao checklist.')
            return redirect(url_for('reception.reception_rooms'))
            
        if action == 'delete_checklist_item':
            item_to_delete = request.form.get('item_name')
            if item_to_delete in checklist_items:
                checklist_items.remove(item_to_delete)
                save_checklist_items(checklist_items)
                flash('Item removido do checklist.')
            return redirect(url_for('reception.reception_rooms'))

        if action == 'inspect_room':
            try:
                room_num_raw = sanitize_input(request.form.get('room_number'))
                # Format room number
                room_num = format_room_number(room_num_raw)
                
                result = sanitize_input(request.form.get('inspection_result')) # 'passed' or 'failed'
                observation = sanitize_input(request.form.get('observation'))
                
                if result not in ['passed', 'failed']:
                     flash('Resultado da inspeção inválido.')
                     return redirect(url_for('reception.reception_rooms'))

                # Log the inspection
                log_entry = {
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'room_number': room_num,
                    'user': session.get('user', 'Recepção'),
                    'result': result,
                    'observation': observation,
                }
                add_inspection_log(log_entry)

                if room_num:
                    if str(room_num) not in cleaning_status:
                        cleaning_status[str(room_num)] = {}
                    
                    if result == 'passed':
                        cleaning_status[str(room_num)]['status'] = 'inspected'
                        cleaning_status[str(room_num)]['inspected_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        cleaning_status[str(room_num)]['inspected_by'] = session.get('user', 'Recepção')
                        # Clear any previous rejection info
                        cleaning_status[str(room_num)].pop('rejection_reason', None)
                        flash(f'Quarto {room_num} inspecionado e liberado para uso.')
                    else:
                        # Failed inspection
                        cleaning_status[str(room_num)]['status'] = 'rejected'
                        cleaning_status[str(room_num)]['rejected_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        cleaning_status[str(room_num)]['rejected_by'] = session.get('user', 'Recepção')
                        cleaning_status[str(room_num)]['rejection_reason'] = observation
                        flash(f'Quarto {room_num} reprovado na inspeção. Governança notificada.')
                
                save_cleaning_status(cleaning_status)
            except Exception as e:
                traceback.print_exc()
                flash(f'Erro ao realizar inspeção: {str(e)}')
                
            return redirect(url_for('reception.reception_rooms'))

        if action == 'transfer_guest':
            old_room_raw = sanitize_input(request.form.get('old_room'))
            new_room_raw = sanitize_input(request.form.get('new_room'))
            reason = sanitize_input(request.form.get('reason'))
            
            if not validate_room_number(old_room_raw)[0] or not validate_room_number(new_room_raw)[0]:
                flash('Erro na Transferência: Números de quarto inválidos.')
                return redirect(url_for('reception.reception_rooms'))
                
            if not reason:
                flash('Erro na Transferência: Motivo é obrigatório.')
                return redirect(url_for('reception.reception_rooms'))

            # Format room numbers
            old_room = format_room_number(old_room_raw)
            new_room = format_room_number(new_room_raw)
            
            if not old_room or not new_room:
                flash('Quartos de origem e destino são obrigatórios.')
                return redirect(url_for('reception.reception_rooms'))
                
            if old_room not in occupancy:
                flash(f'Quarto de origem {old_room} não está ocupado.')
                return redirect(url_for('reception.reception_rooms'))
                
            if new_room in occupancy:
                flash(f'Quarto de destino {new_room} já está ocupado.')
                return redirect(url_for('reception.reception_rooms'))
            
            # Transfer Occupancy
            guest_data = occupancy.pop(old_room)
            occupancy[new_room] = guest_data
            save_room_occupancy(occupancy)
            
            # Transfer Restaurant Table/Orders
            orders = load_table_orders()
            if str(old_room) in orders:
                order_data = orders.pop(str(old_room))
                order_data['room_number'] = str(new_room)
                orders[str(new_room)] = order_data
                save_table_orders(orders)
            
            # Transfer Pending Charges (Room Charges)
            room_charges = load_room_charges()
            charges_updated = False
            for charge in room_charges:
                if format_room_number(charge.get('room_number')) == old_room and charge.get('status') == 'pending':
                    charge['room_number'] = new_room
                    charges_updated = True
            
            if charges_updated:
                save_room_charges(room_charges)
            
            # Mark old room as dirty
            cleaning_status = load_cleaning_status()
            if not isinstance(cleaning_status, dict):
                cleaning_status = {}
            
            cleaning_status[old_room] = {
                'status': 'dirty',
                'marked_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'last_guest': guest_data.get('guest_name', ''),
                'note': f'Transferência para quarto {new_room}'
            }
            save_cleaning_status(cleaning_status)
            
            log_action('Troca de Quarto', f'Hóspede {guest_data.get("guest_name")} transferido do Quarto {old_room} para {new_room}. Motivo: {reason}', department='Recepção')
            flash(f'Hóspede transferido com sucesso do Quarto {old_room} para {new_room}.')
            return redirect(url_for('reception.reception_rooms'))

        if action == 'edit_guest_name':
            room_num_raw = sanitize_input(request.form.get('room_number'))
            new_name = sanitize_input(request.form.get('new_name'))
            
            if not validate_room_number(room_num_raw)[0]:
                flash('Erro na Edição: Número de quarto inválido.')
                return redirect(url_for('reception.reception_rooms'))
                
            if not validate_required(new_name, "Novo Nome")[0]:
                flash('Erro na Edição: Novo nome é obrigatório.')
                return redirect(url_for('reception.reception_rooms'))
            
            room_num = format_room_number(room_num_raw)
            
            if room_num in occupancy and new_name:
                old_name = occupancy[room_num].get('guest_name')
                occupancy[room_num]['guest_name'] = new_name
                save_room_occupancy(occupancy)
                
                log_action('Edição de Hóspede', f'Nome alterado de "{old_name}" para "{new_name}" no Quarto {room_num}.', department='Recepção')
                flash(f'Nome do hóspede do Quarto {room_num} atualizado com sucesso.')
            else:
                flash('Erro ao atualizar nome do hóspede. Verifique os dados.')
            
            return redirect(url_for('reception.reception_rooms'))

        if action == 'cancel_charge':
            if session.get('role') != 'admin':
                flash('Apenas administradores podem cancelar consumos.')
                return redirect(url_for('reception.reception_rooms'))
                
            charge_id = request.form.get('charge_id')
            reason = request.form.get('cancellation_reason')
            
            room_charges = load_room_charges()
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge:
                old_status = charge.get('status')
                charge['status'] = 'cancelled'
                charge['cancelled_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['cancelled_by'] = session.get('user')
                charge['cancellation_reason'] = reason
                
                save_room_charges(room_charges)
                
                log_action('Cancelamento de Consumo', 
                          f"Consumo {charge_id} (Quarto {charge.get('room_number')}) cancelado. Motivo: {reason}", 
                          department='Recepção')
                flash(f'Consumo cancelado com sucesso.')
            else:
                flash('Consumo não encontrado.')
                
            return redirect(url_for('reception.reception_rooms'))

        if action == 'checkin':
            # 1. Sanitization & Input Extraction
            room_num_raw = sanitize_input(request.form.get('room_number'))
            guest_name = sanitize_input(request.form.get('guest_name'))
            doc_id = sanitize_input(request.form.get('doc_id'))
            email = sanitize_input(request.form.get('email'))
            phone = sanitize_input(request.form.get('phone'))
            checkin_date = sanitize_input(request.form.get('checkin_date'))
            checkout_date = sanitize_input(request.form.get('checkout_date'))
            num_adults_raw = request.form.get('num_adults', 1)

            # 2. Validation
            valid_room, msg_room = validate_room_number(room_num_raw)
            if not valid_room:
                log_system_action('Validation Error', 'Checkin', f"Invalid Room: {room_num_raw} - {msg_room}")
                flash(f'Erro no Check-in: {msg_room}')
                return redirect(url_for('reception.reception_rooms'))
            
            valid_name, msg_name = validate_required(guest_name, "Nome do Hóspede")
            if not valid_name:
                log_system_action('Validation Error', 'Checkin', f"Invalid Name: {msg_name}")
                flash(f'Erro no Check-in: {msg_name}')
                return redirect(url_for('reception.reception_rooms'))

            # Optional Validations
            if doc_id:
                # Simple check: if it looks like CPF (11 digits), validate it. Otherwise assume passport/RG.
                digits = re.sub(r'\D', '', doc_id)
                if len(digits) == 11:
                    valid_cpf, msg_cpf = validate_cpf(doc_id)
                    if not valid_cpf:
                        log_system_action('Validation Error', 'Checkin', f"Invalid CPF: {doc_id} - {msg_cpf}")
                        flash(f'Erro no Check-in: {msg_cpf}')
                        return redirect(url_for('reception.reception_rooms'))

            if email:
                valid_email, msg_email = validate_email(email)
                if not valid_email:
                    log_system_action('Validation Error', 'Checkin', f"Invalid Email: {email} - {msg_email}")
                    flash(f'Erro no Check-in: {msg_email}')
                    return redirect(url_for('reception.reception_rooms'))

            if phone:
                valid_phone, msg_phone = validate_phone(phone)
                if not valid_phone:
                    log_system_action('Validation Error', 'Checkin', f"Invalid Phone: {phone} - {msg_phone}")
                    flash(f'Erro no Check-in: {msg_phone}')
                    return redirect(url_for('reception.reception_rooms'))

            valid_in, msg_in = validate_date(checkin_date, '%Y-%m-%d')
            valid_out, msg_out = validate_date(checkout_date, '%Y-%m-%d')
            if not (valid_in and valid_out):
                log_system_action('Validation Error', 'Checkin', f"Invalid Dates: {checkin_date}/{checkout_date} - {msg_in or msg_out}")
                flash(f'Erro no Check-in: {msg_in or msg_out}')
                return redirect(url_for('reception.reception_rooms'))

            try:
                num_adults = int(num_adults_raw)
                if num_adults < 1: raise ValueError
            except ValueError:
                flash('Erro no Check-in: Número de adultos inválido.')
                return redirect(url_for('reception.reception_rooms'))

            # Format room number
            room_num = format_room_number(room_num_raw)
            
            # Validation: Check if room is already occupied
            if str(room_num) in occupancy:
                current_guest = occupancy[str(room_num)].get('guest_name', 'Hóspede Desconhecido')
                # Allow update ONLY if guest name matches exactly (Edit Check-in scenario)
                # Otherwise, block to prevent overwrite
                if current_guest.lower() != guest_name.lower():
                    log_system_action('Checkin Blocked', 'Checkin', f"Attempt to overwrite occupied room {room_num} ({current_guest}) with {guest_name}")
                    flash(f'Erro: Quarto {room_num} já está ocupado por {current_guest}. Realize o check-out ou verifique o número do quarto.')
                    return redirect(url_for('reception.reception_rooms'))
                else:
                    # It's an update for the same guest
                    log_system_action('Checkin Update', 'Checkin', f"Updating info for {guest_name} in room {room_num}")
            
            # Logic continues
            if room_num and guest_name:
                # Convert dates to DD/MM/YYYY for storage/display
                try:
                    if checkin_date:
                        checkin_date = datetime.strptime(checkin_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                    if checkout_date:
                        checkout_date = datetime.strptime(checkout_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass # Already validated above, but safety net

                occupancy[room_num] = {
                    'guest_name': guest_name,
                    'checkin': checkin_date,
                    'checkout': checkout_date,
                    'num_adults': num_adults,
                    'checked_in_at': datetime.now().strftime('%d/%m/%Y %H:%M')
                }
                save_room_occupancy(occupancy)
                
                # Automatically open restaurant table for the room
                orders = load_table_orders()
                if str(room_num) not in orders:
                    orders[str(room_num)] = {
                        'items': [], 
                        'total': 0, 
                        'status': 'open', 
                        'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'num_adults': num_adults,
                        'customer_type': 'hospede',
                        'room_number': str(room_num)
                    }
                    save_table_orders(orders)
                    log_action('Check-in', f'Check-in Quarto {room_num} - {guest_name}', department='Recepção')
                    flash(f'Check-in realizado e Mesa {room_num} aberta automaticamente.')
                else:
                    # Update existing order details if needed
                    orders[str(room_num)]['num_adults'] = num_adults
                    orders[str(room_num)]['room_number'] = str(room_num) # ensure link
                    save_table_orders(orders)
                    log_action('Check-in (Update)', f'Check-in (Atualização) Quarto {room_num} - {guest_name}', department='Recepção')
                    flash(f'Check-in realizado para Quarto {room_num}.')
        
        elif action == 'checkout':
            room_num_raw = sanitize_input(request.form.get('room_number'))
            
            valid_room, msg_room = validate_room_number(room_num_raw)
            if not valid_room:
                flash(f'Erro no Check-out: {msg_room}')
                return redirect(url_for('reception.reception_rooms'))
                
            room_num = format_room_number(room_num_raw)
            
            # Check for pending charges
            room_charges = load_room_charges()
            has_pending = False
            for c in room_charges:
                if format_room_number(c.get('room_number')) == room_num and c.get('status') == 'pending':
                    has_pending = True
                    break
            
            if has_pending:
                flash('Check-out bloqueado: Existem contas pendentes transferidas do restaurante. Regularize no Caixa da Recepção.')
                return redirect(url_for('reception.reception_rooms'))
                
            if room_num in occupancy:
                # Mark as Dirty (Checkout Type) for Governance
                cleaning_status = load_cleaning_status()
                if not isinstance(cleaning_status, dict):
                    cleaning_status = {}
                    
                cleaning_status[room_num] = {
                    'status': 'dirty_checkout',
                    'marked_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'last_guest': occupancy[room_num].get('guest_name', '')
                }
                save_cleaning_status(cleaning_status)

                del occupancy[room_num]
                save_room_occupancy(occupancy)
                
                # Automatically Close Restaurant Table for the room upon Checkout
                orders = load_table_orders()
                if str(room_num) in orders:
                    # Prevent data loss: Check if order has items or total
                    order_to_close = orders[str(room_num)]
                    if order_to_close.get('items') or order_to_close.get('total', 0) > 0:
                        # Archive to a separate file for recovery
                        try:
                            archive_file = ARCHIVED_ORDERS_FILE
                            archived = {}
                            if os.path.exists(archive_file):
                                with open(archive_file, 'r', encoding='utf-8') as f:
                                    try:
                                        archived = json.load(f)
                                    except: pass
                            
                            archive_id = f"{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            archived[archive_id] = order_to_close
                            
                            with open(archive_file, 'w', encoding='utf-8') as f:
                                json.dump(archived, f, indent=4, ensure_ascii=False)
                            current_app.logger.info(f"Archived unclosed order for Room {room_num} to {archive_id}")
                        except Exception as e:
                            current_app.logger.error(f"Error archiving order: {e}")
                    
                    # Close table
                    del orders[str(room_num)]
                    save_table_orders(orders)
                    flash(f'Check-out realizado e Mesa {room_num} fechada/arquivada.')
                else:
                    flash(f'Check-out realizado para Quarto {room_num}.')
            else:
                flash('Quarto não está ocupado.')
                
        return redirect(url_for('reception.reception_rooms'))
    
    # Load Products for "Add Item" modal (Using Menu Items for consistency)
    products = []
    try:
        menu_items = load_menu_items()
        products = [p for p in menu_items if p.get('active', True)]
        products.sort(key=lambda x: x['name'])
    except Exception as e:
        current_app.logger.error(f"Error loading products: {e}")

    # Load and Group Pending Charges for "Ver Consumo" modal
    try:
        room_charges = load_room_charges()
        pending_charges = [c for c in room_charges if c.get('status') == 'pending']
        
        grouped_charges = {}
        for charge in pending_charges:
            room_num = str(charge.get('room_number'))
            if room_num not in grouped_charges:
                grouped_charges[room_num] = []
            
            # Ensure source is set for display
            if 'source' not in charge:
                has_minibar = any(item.get('category') == 'Frigobar' for item in charge.get('items', []))
                charge['source'] = 'minibar' if has_minibar else 'restaurant'
                
            grouped_charges[room_num].append(charge)
            
        pending_rooms = list(grouped_charges.keys())
        print(f"[DEBUG reception_rooms] Loaded {len(pending_charges)} pending charges for rooms: {pending_rooms}")

        payment_methods = load_payment_methods()
        payment_methods = [m for m in payment_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]
        
    except Exception as e:
        print(f"[ERROR reception_rooms] Failed to load consumption data: {e}")
        grouped_charges = {}
        pending_rooms = []
        payment_methods = []

    return render_template('reception_rooms.html', 
                           occupancy=occupancy, 
                           cleaning_status=cleaning_status,
                           checklist_items=checklist_items,
                           grouped_charges=grouped_charges,
                           pending_rooms=pending_rooms,
                           payment_methods=payment_methods,
                           products=products,
                           upcoming_checkins=upcoming_checkins,
                           today=datetime.now().strftime('%Y-%m-%d'))

@reception_bp.route('/reception/cashier', methods=['GET', 'POST'])
@login_required
def reception_cashier():
    current_user = session.get('user')
    
    # Permission Check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
        flash('Acesso não autorizado ao Caixa da Recepção.')
        return redirect(url_for('main.index'))

    # Find current open session (Specific Type)
    sessions = load_cashier_sessions()
    current_session = None
    
    # Prioritize guest_consumption
    for s in sessions:
        if s.get('status') == 'open' and s.get('type') == 'guest_consumption':
            current_session = s
            break
            
    # Fallback to reception_room_billing
    if not current_session:
        for s in sessions:
            if s.get('status') == 'open' and s.get('type') == 'reception_room_billing':
                current_session = s
                break
    
    # Load printer configuration for report
    printers = load_printers()
    printer_settings = load_printer_settings()
            
    # Load pending room charges
    try:
        room_charges = load_room_charges()
    except Exception as e:
        print(f"[ERROR] Failed to load room charges: {e}")
        room_charges = []

    pending_charges = [c for c in room_charges if c.get('status') == 'pending']
    
    # Group charges by room
    room_occupancy = load_room_occupancy()
    grouped_charges = {}
    
    for charge in pending_charges:
        # Determine source if missing
        if 'source' not in charge:
            has_minibar = any(item.get('category') == 'Frigobar' for item in charge.get('items', []))
            charge['source'] = 'minibar' if has_minibar else 'restaurant'

        room_num = str(charge.get('room_number'))
        if room_num not in grouped_charges:
            grouped_charges[room_num] = {
                'room_number': room_num,
                'guest_name': room_occupancy.get(room_num, {}).get('guest_name', 'Desconhecido'),
                'charges': [],
                'total_debt': 0.0
            }
        
        grouped_charges[room_num]['charges'].append(charge)
        grouped_charges[room_num]['total_debt'] += float(charge.get('total', 0.0))
    
    # Sort grouped charges by room number
    sorted_rooms = sorted(grouped_charges.values(), key=lambda x: int(x['room_number']) if x['room_number'].isdigit() else 999)

    payment_methods = load_payment_methods()
    # Filter for reception availability
    payment_methods = [m for m in payment_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]

    if request.method == 'POST':
        action = request.form.get('action')
        print(f"DEBUG: POST action={action}, form={request.form}")
        
        if action == 'open_cashier':
            if current_session:
                flash(f'Já existe um Caixa Recepção Restaurante aberto (Usuário: {current_session.get("user")}).')
            else:
                try:
                    initial_balance = parse_br_currency(request.form.get('opening_balance', '0'))
                except ValueError:
                    initial_balance = 0.0
                
                try:
                    CashierService.open_session(
                        cashier_type='guest_consumption',
                        user=current_user,
                        opening_balance=initial_balance
                    )
                    log_action('Caixa Aberto', f'Caixa Recepção Restaurante aberto por {current_user} com R$ {initial_balance:.2f}', department='Recepção')
                    flash('Caixa da Recepção aberto com sucesso.')
                except ValueError as e:
                    flash(str(e))
                
                return redirect(url_for('reception.reception_cashier'))
                
        elif action == 'close_cashier':
            if not current_session:
                flash('Não há caixa aberto para fechar.')
            else:
                try:
                    raw_closing = request.form.get('closing_balance')
                    user_closing_balance = parse_br_currency(raw_closing) if raw_closing else None
                except ValueError:
                    user_closing_balance = None
                
                try:
                    closed_session = CashierService.close_session(
                        session_id=current_session['id'],
                        user=current_user,
                        closing_balance=user_closing_balance
                    )
                    
                    log_action('Caixa Fechado', f'Caixa Recepção Restaurante fechado por {current_user} com saldo final R$ {closed_session["closing_balance"]:.2f}', department='Recepção')
                    
                    log_system_action(
                        action='close_cashier',
                        details={
                            'session_id': closed_session['id'],
                            'closing_balance': closed_session['closing_balance'],
                            'difference': closed_session.get('difference', 0.0),
                            'opened_at': closed_session.get('opened_at'),
                            'closed_at': closed_session.get('closed_at'),
                            'department': 'Recepção'
                        },
                        user=current_user,
                        category='Caixa'
                    )

                    flash('Caixa fechado com sucesso.')
                except Exception as e:
                    flash(f'Erro ao fechar caixa: {e}')
                
                return redirect(url_for('reception.reception_cashier'))

        elif action == 'pay_charge':
            if not current_session:
                flash('É necessário abrir o Caixa Recepção Restaurante antes de receber pagamentos.')
                return redirect(url_for('reception.reception_cashier'))

            charge_id = request.form.get('charge_id')
            payment_data_json = request.form.get('payment_data')
            emit_invoice = False 
            
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge and charge.get('status') == 'pending':
                charge_total = float(charge.get('total', 0))
                if abs(charge_total) < 0.01:
                    charge['status'] = 'paid'
                    charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    charge['reception_cashier_id'] = current_session['id']
                    charge['payment_method'] = 'Isento/Zerado'
                    
                    save_room_charges(room_charges)
                    log_action('Conta Zerada Fechada', f'Quarto {charge["room_number"]}: R$ 0.00 fechado.', department='Recepção')
                    flash(f"Conta do Quarto {charge['room_number']} (R$ 0.00) fechada com sucesso.")
                    
                    if request.form.get('redirect_to') == 'reception_rooms':
                        return redirect(url_for('reception.reception_rooms'))
                    return redirect(url_for('reception.reception_cashier'))

                payments_to_process = []
                
                if payment_data_json:
                    try:
                        payments_list = json.loads(payment_data_json)
                        for p in payments_list:
                            payments_to_process.append({
                                'method_id': p.get('id'),
                                'method_name': p.get('name'),
                                'amount': float(p.get('amount', 0))
                            })
                    except Exception as e:
                        print(f"Error processing payment data: {e}")
                        flash('Erro ao processar dados de pagamento.')
                        return redirect(url_for('reception.reception_cashier'))
                else:
                    method_id = request.form.get('payment_method')
                    if method_id:
                        method_name = next((m['name'] for m in payment_methods if m['id'] == method_id), method_id)
                        payments_to_process.append({
                            'method_id': method_id,
                            'method_name': method_name,
                            'amount': float(charge['total'])
                        })
                
                if not payments_to_process:
                    flash('Nenhum pagamento informado.')
                    if request.form.get('redirect_to') == 'reception_rooms':
                        return redirect(url_for('reception.reception_rooms'))
                    return redirect(url_for('reception.reception_cashier'))

                charge['status'] = 'paid'
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['reception_cashier_id'] = current_session['id']
                
                if len(payments_to_process) > 1:
                    charge['payment_method'] = 'Múltiplos'
                    charge['payment_details'] = payments_to_process
                else:
                    charge['payment_method'] = payments_to_process[0]['method_id']
                
                save_room_charges(room_charges)
                
                log_action('Início Pagamento', f'Iniciando processamento de pagamento para Quarto {charge["room_number"]}. Total: R$ {charge["total"]}', department='Recepção')

                payment_group_id = str(uuid.uuid4()) if len(payments_to_process) > 1 else None
                total_payment_group_amount = sum(float(p['amount']) for p in payments_to_process) if payment_group_id else 0

                for payment in payments_to_process:
                    details = {}
                    if payment_group_id:
                        details['payment_group_id'] = payment_group_id
                        details['total_payment_group_amount'] = total_payment_group_amount
                        details['payment_method_code'] = payment['method_name']

                    transaction = {
                        'id': f"TRANS_{datetime.now().strftime('%Y%m%d%H%M%S')}_{int(payment['amount']*100)}",
                        'type': 'in',
                        'category': 'Pagamento de Conta',
                        'description': f"Pagamento Quarto {charge['room_number']} ({payment['method_name']})",
                        'amount': payment['amount'],
                        'payment_method': payment['method_name'],
                        'emit_invoice': emit_invoice,
                        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'time': datetime.now().strftime('%H:%M'),
                        'waiter': charge.get('waiter'),
                        'waiter_breakdown': charge.get('waiter_breakdown'),
                        'service_fee_removed': charge.get('service_fee_removed', False),
                        'related_charge_id': charge['id'],
                        'details': details
                    }
                    current_session['transactions'].append(transaction)
                    log_action('Transação Parcial', f'Pagamento parcial: R$ {payment["amount"]:.2f} via {payment["method_name"]}', department='Recepção')
                
                save_cashier_sessions(sessions)
                
                try:
                    all_payment_methods = load_payment_methods()
                    pm_map = {m['id']: m for m in all_payment_methods}

                    items_list = charge.get('items', [])
                    if isinstance(items_list, str):
                        try: items_list = json.loads(items_list)
                        except: items_list = []
                    
                    occupancy = load_room_occupancy()
                    guest_name = occupancy.get(str(charge['room_number']), {}).get('guest_name', 'Hóspede')

                    fiscal_payments = []
                    for p in payments_to_process:
                        # Determine is_fiscal
                        pm_id = p.get('method_id')
                        # If method_id not available (passed from name?), try to find by name
                        pm_obj = pm_map.get(pm_id)
                        if not pm_obj:
                             # Fallback lookup by name
                             pm_obj = next((m for m in all_payment_methods if m['name'] == p['method_name']), None)
                        
                        is_fiscal = pm_obj.get('is_fiscal', False) if pm_obj else False

                        fiscal_payments.append({
                            'method': p['method_name'],
                            'amount': p['amount'],
                            'is_fiscal': is_fiscal
                        })

                    FiscalPoolService.add_to_pool(
                        origin='reception_charge',
                        original_id=f"CHARGE_{charge['id']}",
                        total_amount=float(charge['total']),
                        items=items_list,
                        payment_methods=fiscal_payments,
                        user=current_user,
                        customer_info={'room_number': charge['room_number'], 'guest_name': guest_name}
                    )
                    log_action('Sincronização Fiscal', f'Conta {charge["id"]} enviada para pool fiscal.', department='Recepção')
                except Exception as e:
                    print(f"Error adding charge to fiscal pool: {e}")
                    # Use a simpler logging mechanism if LoggerService is not available or too complex to import
                    print(f"CRITICAL: Fiscal Pool Error: {e}")
                    log_action('Erro Fiscal', f'Falha ao enviar conta {charge["id"]} para pool fiscal: {e}', department='Recepção')

                log_action('Pagamento Concluído', f'Quarto {charge["room_number"]}: R$ {charge["total"]:.2f} via {charge["payment_method"]}', department='Recepção')
                flash(f"Pagamento de R$ {charge['total']:.2f} recebido com sucesso.")
            else:
                flash('Conta não encontrada ou já paga.')
            
            redirect_to = request.form.get('redirect_to')
            if redirect_to == 'reception_rooms':
                return redirect(url_for('reception.reception_rooms'))
                
            return redirect(url_for('reception.reception_cashier'))

        elif action == 'add_transaction':
            if not current_session:
                flash('É necessário abrir o caixa da recepção antes de realizar movimentações.')
                return redirect(url_for('reception.reception_cashier'))
                
            trans_type = request.form.get('type', '').strip().lower()
            description = request.form.get('description')
            try:
                amount = parse_br_currency(request.form.get('amount', '0'))
            except ValueError:
                amount = 0.0
            
            if amount > 0 and description:
                try:
                    if trans_type == 'transfer':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                        target_cashier = request.form.get('target_cashier')
                        source_type = current_session.get('type', 'reception')
                        
                        CashierService.transfer_funds(
                            source_type=source_type,
                            target_type=target_cashier,
                            amount=amount,
                            description=description,
                            user=current_user,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                        
                        try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
                                    target_printer = p
                                    break
                            if not target_printer and printers_config:
                                target_printer = printers_config[0]
                            
                            if target_printer:
                                print_cashier_ticket_async(target_printer, 'TRANSFERENCIA', amount, session.get('user', 'Sistema'), f"{description} -> {target_cashier}")
                        except Exception as e:
                            print(f"Error printing cashier ticket: {e}")

                        log_action('Transferência Caixa', f'Recepção -> {target_cashier}: R$ {amount:.2f}', department='Recepção')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Transferência realizada com sucesso.'})
                        flash('Transferência realizada com sucesso.')
                    
                    elif trans_type == 'deposit':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                        CashierService.add_transaction(
                            cashier_type=current_session.get('type', 'guest_consumption'),
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='in',
                            is_withdrawal=False,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                        log_action('Transação Caixa', f'Recepção Restaurante: Suprimento de R$ {amount:.2f} - {description}', department='Recepção')
                        
                        try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
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

                        flash('Suprimento registrado com sucesso.')
                        
                    elif trans_type == 'withdrawal':
                         # Idempotency Check
                         idempotency_key = request.form.get('idempotency_key')
                         if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                         CashierService.add_transaction(
                            cashier_type=current_session.get('type', 'guest_consumption'),
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='out',
                            is_withdrawal=True,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                         log_action('Transação Caixa', f'Recepção Restaurante: Sangria de R$ {amount:.2f} - {description}', department='Recepção')
                         
                         try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
                                    target_printer = p
                                    break
                            if not target_printer and printers_config:
                                target_printer = printers_config[0]
                            
                            if target_printer:
                                print_cashier_ticket_async(target_printer, 'SANGRIA', amount, session.get('user', 'Sistema'), description)
                         except Exception as e:
                            print(f"Error printing cashier ticket: {e}")

                         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Sangria registrada com sucesso.'})
                         flash('Sangria registrada com sucesso.')

                except ValueError as e:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})
                    flash(f'Erro: {str(e)}')
                except Exception as e:
                    current_app.logger.error(f"Transaction Error: {e}")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})
                    flash(f'Erro inesperado: {str(e)}')
            else:
                msg = 'Valor inválido ou descrição ausente.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': msg})
                flash(msg)
            
            return redirect(url_for('reception.reception_cashier'))

    # Calculate totals for display
    total_in = 0
    total_out = 0
    balance = 0
    current_totals = {}
    total_balance = 0.0

    if current_session:
        total_in = sum(t['amount'] for t in current_session['transactions'] if t['type'] in ['in', 'sale', 'deposit'])
        total_out = sum(t['amount'] for t in current_session['transactions'] if t['type'] in ['out', 'withdrawal'])
        
        initial_balance = current_session.get('initial_balance', current_session.get('opening_balance', 0.0))
        balance = initial_balance + total_in - total_out
        
        for t in current_session['transactions']:
            if t['type'] in ['in', 'sale', 'deposit']:
                method = t.get('payment_method', 'Outros')
                current_totals[method] = current_totals.get(method, 0.0) + t['amount']
        
        if 'opening_balance' not in current_session:
            current_session['opening_balance'] = initial_balance

        # Calculate Total Balance
        total_balance = current_session.get('opening_balance', 0.0)
        for t in current_session.get('transactions', []):
            if t['type'] in ['in', 'sale', 'deposit']:
                total_balance += float(t['amount'])
            elif t['type'] in ['out', 'withdrawal']:
                total_balance -= float(t['amount'])

    products = []
    try:
        menu_items = load_menu_items()
        products = [p for p in menu_items if p.get('active', True)]
        products.sort(key=lambda x: x['name'])
    except Exception as e:
        current_app.logger.error(f"Error loading menu items: {e}")

    printer_settings = load_printer_settings()
    printers = load_printers()
    
    displayed_transactions = []
    has_more = False
    current_page = 1
    
    if current_session:
        try:
            current_page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
        except ValueError:
            current_page = 1
            per_page = 20

        displayed_transactions, has_more = CashierService.get_paginated_transactions(current_session.get('id'), page=current_page, per_page=per_page)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
            return jsonify({
                'transactions': displayed_transactions,
                'has_more': has_more,
                'current_page': current_page
            })

    return render_template('reception_cashier.html', 
                         cashier=current_session, 
                         displayed_transactions=displayed_transactions,
                         has_more=has_more,
                         current_page=current_page,
                         pending_charges=pending_charges,
                         grouped_charges=sorted_rooms,
                         payment_methods=payment_methods,
                         products=products,
                         printers=printers,
                         printer_settings=printer_settings,
                         total_balance=total_balance,
                         current_totals=current_totals)

@reception_bp.route('/api/reception/calculate_reservation_update', methods=['POST'])
@login_required
def api_calculate_reservation_update():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        new_room = data.get('new_room')
        new_checkin = data.get('new_checkin')
        new_checkout = data.get('new_checkout')
        
        service = ReservationService()
        
        # Now the service handles all logic including collision check
        calculation = service.calculate_reservation_update(res_id, new_room, new_checkin, new_checkout)
            
        return jsonify({'success': True, 'data': calculation})
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/move_reservation', methods=['POST'])
@login_required
def api_move_reservation():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        new_room = data.get('new_room')
        
        # Optional date overrides from Drag & Drop
        new_checkin = data.get('checkin')
        new_checkout = data.get('checkout')
        
        price_adj = data.get('price_adjustment') # dict {type, amount}
        
        if not res_id or not new_room:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        service = ReservationService()
        occupancy = load_room_occupancy()
        
        service.save_manual_allocation(
            reservation_id=res_id,
            room_number=new_room,
            checkin=new_checkin,
            checkout=new_checkout,
            price_adjustment=price_adj,
            occupancy_data=occupancy
        )
        
        return jsonify({'success': True})
    except ValueError as e:
         return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/resize_reservation', methods=['POST'])
@login_required
def api_resize_reservation():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        checkin = data.get('checkin')
        checkout = data.get('checkout')
        room_number = data.get('room_number')
        price_adj = data.get('price_adjustment')
        
        if not res_id or not checkin or not checkout:
             return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
             
        service = ReservationService()
        occupancy = load_room_occupancy()
        
        service.save_manual_allocation(
            reservation_id=res_id,
            room_number=room_number,
            checkin=checkin,
            checkout=checkout,
            price_adjustment=price_adj,
            occupancy_data=occupancy
        )
        return jsonify({'success': True})
    except ValueError as e:
         return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/upload_reservations', methods=['POST'])
@login_required
def api_upload_reservations():
    try:
        file = request.files.get('file')
        if not file or not file.filename:
             return jsonify({'success': False, 'error': 'Arquivo inválido'}), 400
             
        filename = file.filename.lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.csv')):
             return jsonify({'success': False, 'error': 'Formato não suportado. Use Excel (.xlsx) ou CSV.'}), 400
        
        target_dir = RESERVATIONS_DIR
        os.makedirs(target_dir, exist_ok=True)
        
        save_path = os.path.join(target_dir, f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file.save(save_path)
        
        return jsonify({'success': True, 'message': 'Arquivo carregado com sucesso.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/create_manual_reservation', methods=['POST'])
@login_required
def api_create_manual_reservation():
    try:
        data = request.json
        if not data.get('guest_name') or not data.get('checkin') or not data.get('checkout'):
             return jsonify({'success': False, 'error': 'Dados obrigatórios faltando.'}), 400
             
        # Block past check-in dates for manual creations
        try:
            cin = datetime.strptime(data.get('checkin'), '%d/%m/%Y').date()
            today = datetime.now().date()
            if cin < today:
                return jsonify({'success': False, 'error': 'Check-in não pode ser anterior a hoje.'}), 400
        except Exception:
            return jsonify({'success': False, 'error': 'Formato de data inválido. Use DD/MM/AAAA.'}), 400
        
        room_number = str(data.get('room_number') or '').strip()
        service = ReservationService()
        occupancy = load_room_occupancy()
        if room_number:
            try:
                service.check_collision('new', room_number, data.get('checkin'), data.get('checkout'), occupancy_data=occupancy)
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
        else:
            req_category = (data.get('category') or '').strip()
            if req_category:
                if not service.has_availability_for_category(req_category, data.get('checkin'), data.get('checkout')):
                    alts = service.available_categories_for_period(data.get('checkin'), data.get('checkout'), exclude_category=req_category)
                    if alts:
                        bullet = "\n".join([f" - {c}" for c in alts])
                        msg = f'Indisponível na categoria "{req_category}" para o período {data.get("checkin")}–{data.get("checkout")}. Disponível nas categorias:\n{bullet}'
                        return jsonify({'success': False, 'error': msg, 'available_categories': alts}), 200
                    return jsonify({'success': False, 'error': f'Não há disponibilidade para o período {data.get("checkin")}–{data.get("checkout")} em nenhuma categoria.'}), 200
        
        new_res = service.create_manual_reservation(data)
        
        # Trigger pre-allocation immediately?
        service.auto_pre_allocate(window_hours=48)
        
        if room_number:
            occupancy = load_room_occupancy()
            try:
                service.save_manual_allocation(
                    reservation_id=new_res['id'],
                    room_number=room_number,
                    checkin=data.get('checkin'),
                    checkout=data.get('checkout'),
                    occupancy_data=occupancy
                )
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
        
        return jsonify({'success': True, 'reservation': new_res})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/auto_pre_allocate', methods=['POST'])
@login_required
def api_run_pre_allocation():
    try:
        service = ReservationService()
        actions = service.auto_pre_allocate(window_hours=24)
        return jsonify({'success': True, 'actions': actions})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/reservations')
@login_required
def reception_reservations():
    from datetime import timedelta
    service = ReservationService()
    
    start_date_str = request.args.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            start_date = datetime.now()
    else:
        start_date = datetime.now()
        
    # Reset time to midnight
    start_date = datetime(start_date.year, start_date.month, start_date.day)
    
    num_days = 31
    
    occupancy = load_room_occupancy()
    reservations = service.get_february_reservations()
    
    grid = service.get_occupancy_grid(occupancy, start_date, num_days)
    grid = service.allocate_reservations(grid, reservations, start_date, num_days)
    segments = service.get_gantt_segments(grid, start_date, num_days)
    
    days = []
    curr = start_date
    for i in range(num_days):
        days.append({
            'day': curr.day,
            'weekday': curr.strftime('%a'),
            'is_weekend': curr.weekday() >= 5
        })
        curr += timedelta(days=1)
        
    mapping = service.get_room_mapping()
    grouped_rooms = []
    for cat, rooms in mapping.items():
        grouped_rooms.append({'category': cat, 'rooms': rooms})
        
    return render_template('reception_reservations.html',
                          start_date=start_date,
                          days=days,
                          grouped_rooms=grouped_rooms,
                          segments=segments,
                          grid=grid,
                          year=start_date.year,
                          month=start_date.month)

@reception_bp.route('/reception/surveys')
@login_required
def reception_surveys():
    # Permission check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    # Placeholder data for template
    stats_by_audience = {'hotel': {'sent': 0, 'responded': 0}, 'restaurant': {'sent': 0, 'responded': 0}}
    return render_template('reception_surveys.html', stats_by_audience=stats_by_audience)

@reception_bp.route('/reception/print_pending_bills', methods=['POST'])
@login_required
def print_reception_pending_bills():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
        return jsonify({'success': False, 'message': 'Acesso não autorizado.'}), 403

    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400
            
        printer_id = sanitize_input(data.get('printer_id'))
        save_default = bool(data.get('save_default', False))
        room_filter = sanitize_input(data.get('room_number'))
        
        if not printer_id:
            return jsonify({'success': False, 'message': 'Nenhuma impressora selecionada.'}), 400

        if save_default:
            settings = load_printer_settings()
            settings['default_reception_report_printer_id'] = printer_id
            save_printer_settings(settings)
            
        printers = load_printers()
        printer_name = next((p['name'] for p in printers if p['id'] == printer_id), None)
        
        if not printer_name:
             return jsonify({'success': False, 'message': 'Impressora não encontrada no sistema.'}), 404
        
        room_charges = load_room_charges()
        if not isinstance(room_charges, list):
            room_charges = []
            
        pending_charges = []
        for c in room_charges:
             if isinstance(c, dict) and c.get('status') == 'pending':
                 pending_charges.append(c)
        
        if room_filter:
            pending_charges = [c for c in pending_charges if str(c.get('room_number')) == str(room_filter)]
            
        room_occupancy = load_room_occupancy()
        
        formatted_bills = []
        
        for charge in pending_charges:
            room_num = str(charge.get('room_number'))
            guest_name = room_occupancy.get(room_num, {}).get('guest_name', 'Desconhecido')
            
            products = []
            for item in charge.get('items', []):
                products.append({
                    "name": item.get('name', 'Item'),
                    "qty": float(item.get('qty', 1)),
                    "unit_price": float(item.get('price', 0)),
                    "subtotal": float(item.get('total', 0))
                })
            
            service_fee = float(charge.get('service_fee', 0))
            if service_fee > 0:
                products.append({
                    "name": "Taxa de Serviço (10%)",
                    "qty": 1.0,
                    "unit_price": service_fee,
                    "subtotal": service_fee
                })
            
            formatted_bills.append({
                "origin": {
                    "client": guest_name,
                    "table": f"Quarto {room_num}",
                    "order_id": charge.get('id', 'N/A')
                },
                "products": products
            })
            
        if not formatted_bills:
            return jsonify({'success': False, 'message': 'Não há contas pendentes para imprimir.'})

        result = process_and_print_pending_bills(formatted_bills, printer_name)
        
        if result['errors']:
             return jsonify({'success': False, 'message': f"Erros na impressão: {', '.join(result['errors'])}"}), 500
             
        return jsonify({
            'success': True, 
            'message': f'Relatório enviado para {printer_name}. {result["summary"]["total_bills_count"]} contas processadas.'
        })

    except Exception as e:
        print(f"Error printing reception report: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Erro interno: {str(e)}"}), 500

@reception_bp.route('/api/reception/return_to_restaurant', methods=['POST'])
@login_required
def api_reception_return_to_restaurant():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and 'recepcao' not in user_perms:
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Dados inválidos'}), 400

        charge_id = sanitize_input(data.get('charge_id'))
        target_table_id = sanitize_input(data.get('target_table_id')) 
        user_name = session.get('user', 'Unknown')
        
        if not charge_id:
            return jsonify({'success': False, 'error': 'ID da cobrança não fornecido'})

        success, message = return_charge_to_restaurant(charge_id, user_name, target_table_id=target_table_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
            
    except TableOccupiedError as e:
        return jsonify({
            'success': False, 
            'error': str(e),
            'error_code': 'TABLE_OCCUPIED',
            'free_tables': e.free_tables
        }), 409
    except TransferError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error returning charge to restaurant: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/pay_charge/<charge_id>', methods=['POST'])
@login_required
def reception_pay_charge(charge_id):
    try:
        data = request.json
        payments = data.get('payments', [])
        room_num = data.get('room_num')
        
        if not payments:
            return jsonify({'success': False, 'message': 'Nenhum pagamento informado.'})

        room_charges = load_room_charges()
        charge = next((c for c in room_charges if c['id'] == charge_id), None)
        
        if not charge:
            return jsonify({'success': False, 'message': 'Conta não encontrada.'})
            
        if charge.get('status') == 'paid':
             return jsonify({'success': False, 'message': 'Conta já paga.'})

        # Load session
        sessions = load_cashier_sessions()
        
        # Debug Logging for Session Verification
        open_sessions = [s for s in sessions if s.get('status') == 'open']
        current_app.logger.info(f"Payment Verification: Found {len(open_sessions)} open sessions. Types: {[s.get('type') for s in open_sessions]}")

        # Check for any valid reception session type
        # Valid types: 'reception' (legacy), 'guest_consumption', 'reception_room_billing'
        valid_types = ['reception', 'guest_consumption', 'reception_room_billing']
        
        current_session = next((s for s in reversed(sessions) 
                                if s['status'] == 'open' and s.get('type') in valid_types), None)
        
        if not current_session:
             current_app.logger.warning("Payment Verification Failed: No open reception cashier session found.")
             return jsonify({'success': False, 'message': 'Caixa da recepção fechado. Abra o caixa para receber pagamentos.'})

        current_app.logger.info(f"Payment Verification Success: Using session {current_session.get('id')} of type {current_session.get('type')}")

        # Calculate total paid
        total_paid = sum(float(p['amount']) for p in payments)
        charge_total = float(charge.get('total', 0))
        
        # Register transactions
        user = session.get('user', 'Sistema')
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
        payment_methods_list = load_payment_methods()
        
        payment_group_id = str(uuid.uuid4()) if len(payments) > 1 else None
        total_payment_group_amount = total_paid if payment_group_id else 0
        
        for p in payments:
            method_id = str(p.get('method'))
            method_name = next((m['name'] for m in payment_methods_list if str(m['id']) == method_id), 'Desconhecido')
            
            details = {}
            if payment_group_id:
                details['payment_group_id'] = payment_group_id
                details['total_payment_group_amount'] = total_payment_group_amount
                details['payment_method_code'] = method_name
            
            transaction = {
                'id': f"PAY_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}",
                'type': 'in',
                'category': 'Pagamento Item',
                'description': f"Pagamento Item Quarto {room_num} ({method_name})",
                'amount': float(p['amount']),
                'payment_method': method_name,
                'timestamp': timestamp,
                'user': user,
                'related_charge_id': charge_id,
                'details': details
            }
            current_session['transactions'].append(transaction)
            
        save_cashier_sessions(sessions)
        
        # Update charge
        charge['status'] = 'paid'
        charge['paid_at'] = timestamp
        charge['reception_cashier_id'] = current_session['id']
        charge['payment_details'] = payments
        
        save_room_charges(room_charges)
        
        log_action('Pagamento Item', f'Quarto {room_num}: R$ {total_paid:.2f} pago.', department='Recepção')
        
        return jsonify({'success': True})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})

@reception_bp.route('/reception/charge/edit', methods=['POST'])
@login_required
def reception_edit_charge():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and 'recepcao' not in user_perms:
        flash('Acesso não autorizado para editar contas.')
        return redirect(url_for('reception.reception_cashier'))

    charge_id = sanitize_input(request.form.get('charge_id'))
    new_date = sanitize_input(request.form.get('new_date'))
    new_status = sanitize_input(request.form.get('new_status'))
    new_notes = sanitize_input(request.form.get('new_notes'))
    justification = sanitize_input(request.form.get('justification'))
    
    if not justification:
        flash('Justificativa é obrigatória para edição de contas.')
        return redirect(url_for('reception.reception_cashier'))

    items_to_add_json = request.form.get('items_to_add', '[]')
    items_to_remove_json = request.form.get('items_to_remove', '[]')
    removal_justifications_json = request.form.get('removal_justifications', '{}')
    
    try:
        items_to_add = json.loads(items_to_add_json)
        items_to_remove = json.loads(items_to_remove_json)
        removal_justifications = json.loads(removal_justifications_json)
        
        # Validate structure of items to add
        if not isinstance(items_to_add, list): raise ValueError("Items to add must be a list")
        if not isinstance(items_to_remove, list): raise ValueError("Items to remove must be a list")
        
        for item in items_to_add:
            if 'id' not in item or 'qty' not in item:
                 raise ValueError("Invalid item structure in added items")
                 
    except (json.JSONDecodeError, ValueError) as e:
        flash(f'Erro ao processar itens da conta: {str(e)}')
        return redirect(url_for('reception.reception_cashier'))

    room_charges = load_room_charges()
    charge = next((c for c in room_charges if c['id'] == charge_id), None)
    
    if not charge:
        flash('Conta não encontrada.')
        return redirect(url_for('reception.reception_cashier'))
        
    old_status = charge.get('status')
    original_total = float(charge.get('total', 0))
        
    changes = []
    
    if new_date and new_date != charge.get('date'):
        changes.append(f"Data: {charge.get('date')} -> {new_date}")
        charge['date'] = new_date
        
    if new_status and new_status != charge.get('status'):
        changes.append(f"Status: {charge.get('status')} -> {new_status}")
        charge['status'] = new_status
        
    if new_notes != charge.get('notes', ''):
        changes.append(f"Obs: {charge.get('notes', '')} -> {new_notes}")
        charge['notes'] = new_notes

    try:
        menu_items = load_menu_items()
        products_insumos = load_products() 
    except Exception as e:
        current_app.logger.error(f"Error loading data for edit charge: {e}")
        menu_items = []
        products_insumos = []

    insumo_map = {str(i['id']): i for i in products_insumos}
    
    if items_to_remove:
        current_items = charge.get('items', [])
        kept_items = []
        removed_list = charge.get('removed_items', [])

        for item in current_items:
            if item.get('id') in items_to_remove:
                item_name = item.get('name')
                qty_removed = float(item.get('qty', 1))
                
                product_def = next((p for p in menu_items if p['name'] == item_name), None)
                
                if product_def and product_def.get('recipe'):
                    try:
                        for ingred in product_def['recipe']:
                            ing_id = str(ingred['ingredient_id'])
                            ing_qty = float(ingred['qty'])
                            total_refund = ing_qty * qty_removed
                            
                            insumo_data = insumo_map.get(ing_id)
                            
                            if insumo_data:
                                entry_data = {
                                    'id': f"REFUND_{charge.get('table_id', 'REC')}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ing_id}",
                                    'user': session.get('user', 'Sistema'),
                                    'product': insumo_data['name'],
                                    'supplier': f"ESTORNO: Recp {charge.get('room_number')}",
                                    'qty': total_refund, 
                                    'price': insumo_data.get('price', 0),
                                    'invoice': f"Edição Conta: {item_name}",
                                    'date': datetime.now().strftime('%d/%m/%Y'),
                                    'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                                }
                                save_stock_entry(entry_data)
                    except Exception as e:
                        print(f"Stock refund error (Reception): {e}")
                
                justification_text = removal_justifications.get(item.get('id'), 'Sem justificativa')
                changes.append(f"Item Removido: {item_name} (x{qty_removed}) - Justificativa: {justification_text}")
                
                # Store for reversibility
                removed_item_entry = item.copy()
                removed_item_entry.update({
                    'removed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'removed_by': session.get('user', 'Sistema'),
                    'removal_justification': justification_text
                })
                removed_list.append(removed_item_entry)
            else:
                kept_items.append(item)
        
        charge['items'] = kept_items
        charge['removed_items'] = removed_list

    if items_to_add:
        for new_item in items_to_add:
            prod_id = new_item.get('id')
            try:
                qty = float(new_item.get('qty', 1))
            except ValueError:
                qty = 1.0
                
            product_def = next((p for p in menu_items if str(p['id']) == str(prod_id)), None)
            
            if product_def:
                if product_def.get('recipe'):
                    try:
                        for ingred in product_def['recipe']:
                            ing_id = str(ingred['ingredient_id'])
                            ing_qty = float(ingred['qty'])
                            total_needed = ing_qty * qty
                            
                            insumo_data = insumo_map.get(ing_id)
                            
                            if insumo_data:
                                entry_data = {
                                    'id': f"SALE_REC_{charge.get('room_number')}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ing_id}",
                                    'user': session.get('user', 'Sistema'),
                                    'product': insumo_data['name'],
                                    'supplier': f"VENDA: Recp {charge.get('room_number')}",
                                    'qty': -total_needed, 
                                    'price': insumo_data.get('price', 0),
                                    'invoice': f"Edição Conta",
                                    'date': datetime.now().strftime('%d/%m/%Y'),
                                    'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                                }
                                save_stock_entry(entry_data)
                    except Exception as e:
                        print(f"Stock deduction error (Reception): {e}")

                item_entry = {
                    'id': str(uuid.uuid4()),
                    'name': product_def['name'],
                    'qty': qty,
                    'price': float(product_def['price']),
                    'category': product_def.get('category', 'Outros'),
                    'source': 'reception_edit',
                    'added_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'added_by': session.get('user')
                }
                charge.get('items', []).append(item_entry)
                changes.append(f"Item Adicionado: {product_def['name']} (x{qty})")

    if 'items' not in charge:
        charge['items'] = []
        
    taxable_total = 0.0
    total_items = 0.0
    
    for item in charge['items']:
        item_price = float(item.get('price', 0))
        item_qty = float(item.get('qty', 1))
        
        comps_price = sum(float(c.get('price', 0)) for c in item.get('complements', []))
        
        line_total = item_qty * (item_price + comps_price)
        total_items += line_total
        
        if not item.get('service_fee_exempt', False):
            taxable_total += line_total

    service_fee_removed = request.form.get('remove_service_fee') == 'on'
    
    if service_fee_removed != charge.get('service_fee_removed', False):
        if service_fee_removed:
            changes.append("Comissão de 10% removida")
        else:
            changes.append("Comissão de 10% restaurada")
        charge['service_fee_removed'] = service_fee_removed

    if service_fee_removed:
        service_fee = 0.0
    else:
        service_fee = taxable_total * 0.10
        
    grand_total = total_items + service_fee
    
    current_total = float(charge.get('total', 0))
    if abs(grand_total - current_total) > 0.01:
        changes.append(f"Recálculo Total: {current_total:.2f} -> {grand_total:.2f}")
        charge['total'] = grand_total
        charge['service_fee'] = service_fee

    if changes:
        audit_entry = {
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'user': session.get('user'),
            'changes': changes,
            'justification': justification
        }
        
        sessions = load_cashier_sessions()
        
        cashier_id = charge.get('reception_cashier_id')
        paying_session = next((s for s in sessions if s['id'] == cashier_id), None)
        
        current_reception_cashier = next((s for s in reversed(sessions) 
                                        if s['status'] == 'open' and s.get('type') == 'reception'), None)

        if old_status == 'paid':
            if paying_session and paying_session['status'] == 'open':
                transaction_found = False
                for t in paying_session['transactions']:
                    if t['type'] == 'in' and f"Quarto {charge.get('room_number')}" in t['description'] and abs(t['amount'] - original_total) < 0.01:
                        if new_status == 'paid':
                            t['amount'] = grand_total
                            t['description'] = t['description'] + " (Editada)"
                            changes.append(f"Transação atualizada de R$ {original_total:.2f} para R$ {grand_total:.2f}")
                        elif new_status == 'pending':
                            paying_session['transactions'].remove(t)
                            changes.append(f"Pagamento de R$ {original_total:.2f} estornado (removido do caixa aberto)")
                        transaction_found = True
                        break
                
                if not transaction_found and new_status == 'pending':
                     changes.append("AVISO: Transação original não encontrada para estorno automático.")

            else:
                if current_reception_cashier:
                    if new_status == 'pending':
                        reversal_trans = {
                            'id': f"REV_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                            'type': 'out', 
                            'category': 'Estorno/Correção',
                            'description': f"Estorno Ref. Quarto {charge.get('room_number')} (Edição de Conta)",
                            'amount': original_total,
                            'payment_method': 'Outros', 
                            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                            'time': datetime.now().strftime('%H:%M')
                        }
                        current_reception_cashier['transactions'].append(reversal_trans)
                        changes.append(f"Estorno de R$ {original_total:.2f} lançado no caixa atual para reabertura.")
                        
                        charge.pop('reception_cashier_id', None)
                        charge.pop('paid_at', None)

                    elif new_status == 'paid' and abs(grand_total - original_total) > 0.01:
                        diff = grand_total - original_total
                        
                        if diff > 0:
                            adj_trans = {
                                'id': f"ADJ_IN_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                'type': 'in',
                                'category': 'Ajuste de Conta',
                                'description': f"Ajuste Adicional Quarto {charge.get('room_number')}",
                                'amount': diff,
                                'payment_method': 'Outros', 
                                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                                'time': datetime.now().strftime('%H:%M')
                            }
                            current_reception_cashier['transactions'].append(adj_trans)
                            changes.append(f"Diferença de R$ {diff:.2f} lançada como entrada no caixa atual.")
                        else:
                            adj_trans = {
                                'id': f"ADJ_OUT_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                'type': 'out',
                                'category': 'Devolução/Ajuste',
                                'description': f"Devolução Diferença Quarto {charge.get('room_number')}",
                                'amount': abs(diff),
                                'payment_method': 'Outros',
                                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                                'time': datetime.now().strftime('%H:%M')
                            }
                            current_reception_cashier['transactions'].append(adj_trans)
                            changes.append(f"Diferença de R$ {abs(diff):.2f} lançada como saída (devolução) no caixa atual.")
                else:
                    if new_status == 'pending' or (new_status == 'paid' and abs(grand_total - original_total) > 0.01):
                        changes.append("AVISO CRÍTICO: Ajuste financeiro necessário mas nenhum caixa de recepção está aberto. O saldo financeiro pode estar inconsistente.")

        elif old_status != 'paid' and new_status == 'paid':
             if current_reception_cashier:
                payment_trans = {
                    'id': f"MANUAL_PAY_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'type': 'in',
                    'category': 'Recebimento Manual',
                    'description': f"Recebimento Manual Ref. Quarto {charge.get('room_number')} (Edição)",
                    'amount': grand_total,
                    'payment_method': 'Outros',
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'time': datetime.now().strftime('%H:%M'),
                    'waiter': charge.get('waiter'),
                    'waiter_breakdown': charge.get('waiter_breakdown'),
                    'service_fee_removed': charge.get('service_fee_removed', False)
                }
                current_reception_cashier['transactions'].append(payment_trans)
                
                charge['reception_cashier_id'] = current_reception_cashier['id']
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                
                changes.append(f"Pagamento Manual de R$ {grand_total:.2f} registrado no caixa atual.")
             else:
                changes.append("AVISO: Pagamento não registrado financeiramente pois não há caixa aberto.")

        save_cashier_sessions(sessions)

        if 'audit_log' not in charge:
            charge['audit_log'] = []
        charge['audit_log'].append(audit_entry)
        
        save_room_charges(room_charges)
        log_system_action('Edição de Conta', f"Conta {charge_id} editada: {', '.join(changes)}")
        flash('Conta atualizada com sucesso.')
    else:
        flash('Nenhuma alteração realizada.')

    source_page = request.form.get('source_page')
    if source_page == 'reception_rooms':
        return redirect(url_for('reception.reception_rooms'))
        
    return redirect(url_for('reception.reception_cashier'))

import logging

@reception_bp.route('/reception/reservations-cashier', methods=['GET', 'POST'])
@login_required
def reception_reservations_cashier():
    logging.warning(f"DEBUG: Entering reception_reservations_cashier method={request.method}")
    if 'user' not in session: return redirect(url_for('auth.login'))

    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'reservas' not in user_perms and 'principal' not in user_perms:
        flash('Acesso não autorizado ao Caixa de Reservas.')
        return redirect(url_for('main.index'))

    current_user = session.get('user')
    
    # Use Service to get session
    current_session = CashierService.get_active_session('reception_reservations')
            
    payment_methods = load_payment_methods()
    payment_methods = [m for m in payment_methods if 'caixa_reservas' in m.get('available_in', []) or 'reservas' in m.get('available_in', []) or 'reservations' in m.get('available_in', [])]

    if request.method == 'POST':
        action = request.form.get('action')
        logging.warning(f"DEBUG: RESERVATIONS POST action={action}, form={request.form}")
        
        if action == 'open_cashier':
            try:
                initial_balance = float(request.form.get('opening_balance', 0))
            except ValueError:
                initial_balance = 0.0
            
            try:
                CashierService.open_session('reception_reservations', current_user, initial_balance)
                log_system_action('Caixa Aberto', f'Caixa Reservas aberto por {current_user} com R$ {initial_balance:.2f}', department='Recepção')
                flash('Caixa de Reservas aberto com sucesso.')
            except ValueError as e:
                flash(str(e))
            except Exception as e:
                flash(f'Erro ao abrir caixa: {str(e)}')
            
            return redirect(url_for('reception.reception_reservations_cashier'))
                
        elif action == 'close_cashier':
            if not current_session:
                flash('Não há caixa de reservas aberto para fechar.')
            else:
                try:
                    CashierService.close_session(session_id=current_session['id'], user=current_user)
                    log_system_action('Caixa Fechado', f'Caixa Reservas fechado por {current_user}', department='Recepção')
                    flash('Caixa de Reservas fechado com sucesso.')
                except Exception as e:
                    flash(f'Erro ao fechar caixa: {str(e)}')
                    
                return redirect(url_for('reception.reception_reservations_cashier'))

        elif action == 'add_transaction':
            if not current_session:
                flash('É necessário abrir o caixa de reservas antes de realizar movimentações.')
                return redirect(url_for('reception.reception_reservations_cashier'))
                
            trans_type = request.form.get('type') 
            description = request.form.get('description')
            try:
                amount = float(request.form.get('amount', 0))
            except ValueError:
                amount = 0.0
            
            if amount > 0 and description:
                try:
                    if trans_type == 'transfer':
                        target_cashier = request.form.get('target_cashier')
                        CashierService.transfer_funds(
                            source_type='reception_reservations',
                            target_type=target_cashier,
                            amount=amount,
                            description=description,
                            user=current_user
                        )
                        flash('Transferência realizada com sucesso.')
                        log_system_action('Transferência Caixa', f'Reservas -> {target_cashier}: R$ {amount:.2f}', department='Recepção')

                    elif trans_type == 'sale':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_reservations_cashier'))

                        payment_list_json = request.form.get('payment_list_json')
                        
                        if payment_list_json:
                            # Multi-payment logic
                            try:
                                payment_list = json.loads(payment_list_json)
                                logging.warning(f"DEBUG: Payment List received: {payment_list}")
                                if not payment_list:
                                    raise ValueError("Lista de pagamentos vazia.")
                                
                                # Validate total
                                total_payments = sum(float(p.get('amount', 0)) for p in payment_list)
                                logging.warning(f"DEBUG: Total payments: {total_payments}, Expected: {amount}")
                                if abs(total_payments - amount) > 0.05: # 5 cent tolerance
                                    raise ValueError(f"Soma dos pagamentos (R$ {total_payments:.2f}) difere do valor total (R$ {amount:.2f})")
                                
                                group_id = str(uuid.uuid4())
                                
                                for p in payment_list:
                                    p_amount = float(p.get('amount', 0))
                                    p_method_id = p.get('id')
                                    p_method_name = p.get('name', 'Desconhecido')
                                    
                                    # Ensure method name is correct if ID is provided
                                    if p_method_id:
                                        found_name = next((m['name'] for m in payment_methods if m['id'] == p_method_id), None)
                                        if found_name:
                                            p_method_name = found_name
                                        else:
                                            logging.warning(f"DEBUG: Payment method ID {p_method_id} not found in {payment_methods}")

                                    CashierService.add_transaction(
                                        cashier_type='reception_reservations',
                                        amount=p_amount,
                                        description=description,
                                        payment_method=p_method_name,
                                        user=current_user,
                                        transaction_type='sale',
                                        is_withdrawal=False,
                                        payment_group_id=group_id,
                                        details={'idempotency_key': idempotency_key} if idempotency_key else None
                                    )
                                    logging.warning(f"DEBUG: Added transaction for {p_method_name}: {p_amount}")
                                    
                                log_system_action('Transação Caixa', f'Reservas: Recebimento Múltiplo de R$ {amount:.2f} - {description}', department='Recepção')
                                
                                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                    return jsonify({'success': True, 'message': 'Recebimento múltiplo registrado com sucesso.'})

                                flash('Recebimento múltiplo registrado com sucesso.')

                            except json.JSONDecodeError:
                                logging.warning("DEBUG: JSON Decode Error")
                                flash('Erro ao processar lista de pagamentos.')
                            except ValueError as ve:
                                logging.warning(f"DEBUG: Value Error: {ve}")
                                flash(f'Erro de validação: {str(ve)}')
                        
                        else:
                            # Single payment logic (Legacy/Default)
                            method_id = request.form.get('payment_method')
                            method_name = next((m['name'] for m in payment_methods if m['id'] == method_id), method_id)
                            
                            CashierService.add_transaction(
                                cashier_type='reception_reservations',
                                amount=amount,
                                description=description,
                                payment_method=method_name,
                                user=current_user,
                                transaction_type='sale',
                                is_withdrawal=False,
                                details={'idempotency_key': idempotency_key} if idempotency_key else None
                            )
                            log_system_action('Transação Caixa', f'Reservas: Recebimento de R$ {amount:.2f} - {description}', department='Recepção')
                            
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                return jsonify({'success': True, 'message': 'Recebimento registrado com sucesso.'})

                            flash('Recebimento registrado com sucesso.')

                    elif trans_type == 'deposit':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_reservations_cashier'))

                        CashierService.add_transaction(
                            cashier_type='reception_reservations',
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='deposit',
                            is_withdrawal=False,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                        log_system_action('Transação Caixa', f'Reservas: Suprimento de R$ {amount:.2f} - {description}')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Suprimento registrado com sucesso.'})

                        flash('Suprimento registrado com sucesso.')
                        
                    elif trans_type == 'withdrawal':
                        CashierService.add_transaction(
                            cashier_type='reception_reservations',
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='withdrawal',
                            is_withdrawal=True
                        )
                        log_system_action('Transação Caixa', f'Reservas: Sangria de R$ {amount:.2f} - {description}')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Sangria registrada com sucesso.'})

                        flash('Sangria registrada com sucesso.')
                
                except ValueError as e:
                    flash(f'Erro: {str(e)}')
                except Exception as e:
                    flash(f'Erro inesperado: {str(e)}')
            else:
                flash('Valor inválido ou descrição ausente.')
            
            return redirect(url_for('reception.reception_reservations_cashier'))

    total_in = 0
    total_out = 0
    balance = 0
    current_totals = {}

    if current_session:
        total_in = sum(t['amount'] for t in current_session['transactions'] if t.get('type') in ['in', 'sale', 'deposit', 'suprimento'])
        total_out = sum(t['amount'] for t in current_session['transactions'] if t.get('type') in ['out', 'withdrawal', 'sangria'])
        
        initial_balance = float(current_session.get('initial_balance') or current_session.get('opening_balance') or 0.0)
        balance = initial_balance + total_in - total_out
        
        for t in current_session['transactions']:
            if t.get('type') in ['in', 'sale', 'deposit', 'suprimento']:
                method = t.get('payment_method', 'Outros')
                current_totals[method] = current_totals.get(method, 0.0) + float(t.get('amount', 0))
        
        if 'opening_balance' not in current_session:
            current_session['opening_balance'] = initial_balance

    # Pagination
    try:
        current_page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
    except ValueError:
        current_page = 1
        per_page = 20

    displayed_transactions = []
    has_more = False
    
    if current_session:
        displayed_transactions, has_more = CashierService.get_paginated_transactions(current_session.get('id'), page=current_page, per_page=per_page)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
            return jsonify({
                'transactions': displayed_transactions,
                'has_more': has_more,
                'current_page': current_page
            })

    return render_template('reception_reservations_cashier.html', 
                         cashier=current_session, 
                         displayed_transactions=displayed_transactions,
                         has_more=has_more,
                         current_page=current_page,
                         payment_methods=payment_methods,
                         total_in=total_in,
                         total_out=total_out,
                         balance=balance,
                         total_balance=balance,
                         current_totals=current_totals)

@reception_bp.route('/reception/waiting-list')
@login_required
def reception_waiting_list():
    user_dept = session.get('department')
    user_role = session.get('role')
    
    allowed = user_role == 'admin' or user_role == 'gerente' or user_dept == 'Recepção' or user_dept == 'Restaurante'
    if not allowed:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    queue = waiting_list_service.get_waiting_list()
    settings = waiting_list_service.get_settings()
    metrics = waiting_list_service.get_queue_metrics()
    
    now = datetime.now()
    for item in queue:
        entry_time = datetime.fromisoformat(item['entry_time'])
        item['wait_minutes'] = int((now - entry_time).total_seconds() / 60)
        item['entry_time_fmt'] = entry_time.strftime('%H:%M')
        item['phone_clean'] = re.sub(r'\D', '', item['phone'])
        
    return render_template('waiting_list_admin.html', queue=queue, settings=settings, metrics=metrics)

@reception_bp.route('/reception/waiting-list/update/<id>/<status>')
@login_required
def update_queue_status(id, status):
    reason = request.args.get('reason')
    user = session.get('user')
    waiting_list_service.update_customer_status(id, status, reason=reason, user=user)
    flash(f'Status atualizado para {status}.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/settings', methods=['POST'])
@login_required
def update_queue_settings():
    avg_wait = int(request.form.get('avg_wait', 15))
    max_size = int(request.form.get('max_size', 50))
    whatsapp_token = request.form.get('whatsapp_token', '').strip()
    whatsapp_phone_id = request.form.get('whatsapp_phone_id', '').strip()
    
    settings_update = {
        'average_wait_per_party': avg_wait,
        'max_queue_size': max_size
    }
    
    if whatsapp_token:
        settings_update['whatsapp_api_token'] = whatsapp_token
    if whatsapp_phone_id:
        settings_update['whatsapp_phone_id'] = whatsapp_phone_id
        
    waiting_list_service.update_settings(settings_update)
    flash('Configurações atualizadas.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/toggle')
@login_required
def toggle_queue_status():
    settings = waiting_list_service.get_settings()
    new_status = not settings['is_open']
    waiting_list_service.update_settings({'is_open': new_status})
    flash(f"Fila {'aberta' if new_status else 'fechada'}.")
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/api/queue/log-notification', methods=['POST'])
@login_required
def log_queue_notification():
    data = request.json
    customer_id = data.get('id')
    if customer_id:
        waiting_list_service.log_notification(customer_id, 'whatsapp_call', user=session.get('user'))
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@reception_bp.route('/api/queue/send-notification', methods=['POST'])
@login_required
def send_queue_notification():
    data = request.json
    customer_id = data.get('id')
    if not customer_id:
        return jsonify({'success': False, 'message': 'ID required'}), 400
        
    success, message = waiting_list_service.send_notification(
        customer_id, 
        message_type="table_ready", 
        user=session.get('user')
    )
    
    return jsonify({
        'success': success, 
        'message': message,
        'code': message if not success else 'sent'
    })

@reception_bp.route('/reception/chat')
@login_required
def reception_chat():
    if session.get('role') not in ['admin', 'recepcao', 'gerente']:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    return render_template('whatsapp_chat.html')

@reception_bp.route('/api/chat/conversations')
@login_required
def api_chat_conversations():
    conversations = chat_service.get_all_conversations()
    return jsonify(conversations)

@reception_bp.route('/api/chat/history/<path:phone>')
@login_required
def api_chat_history(phone):
    messages = chat_service.get_messages(phone)
    return jsonify(messages)

@reception_bp.route('/api/chat/send', methods=['POST'])
@login_required
def api_chat_send():
    data = request.json
    phone = data.get('phone')
    message = data.get('message')
    
    if not phone or not message:
        return jsonify({'success': False, 'message': 'Phone and message required'}), 400
        
    settings = waiting_list_service.get_settings()
    token = settings.get('whatsapp_api_token')
    phone_id = settings.get('whatsapp_phone_id')
    
    if not token or not phone_id:
        return jsonify({'success': False, 'message': 'WhatsApp API not configured'}), 500
        
    wa_service = WhatsAppService(token, phone_id)
    result = wa_service.send_message(phone, message)
    
    if result:
        msg_data = {
            'type': 'sent',
            'content': message,
            'timestamp': datetime.now().isoformat(),
            'status': 'sent',
            'via': 'api',
            'user': session.get('user')
        }
        chat_service.add_message(phone, msg_data)
        return jsonify({'success': True, 'data': result})
    else:
        return jsonify({'success': False, 'message': 'Failed to send via WhatsApp API'}), 500

@reception_bp.route('/api/chat/tags/<path:phone>', methods=['GET'])
@login_required
def api_chat_get_tags(phone):
    tags = chat_service.get_tags(phone)
    name = chat_service.get_contact_name(phone)
    return jsonify({'tags': tags, 'name': name})

@reception_bp.route('/api/chat/tags', methods=['POST'])
@login_required
def api_chat_update_tags():
    data = request.json
    phone = data.get('phone')
    tags = data.get('tags', [])
    
    if not phone:
        return jsonify({'success': False, 'message': 'Phone required'}), 400
        
    success = chat_service.update_tags(phone, tags)
    return jsonify({'success': success})

@reception_bp.route('/api/chat/tags_config', methods=['GET', 'POST'])
@login_required
def api_chat_tags_config():
    if request.method == 'POST':
        if session.get('role') not in ['admin', 'gerente', 'supervisor']:
             return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        tags = request.json.get('tags', [])
        success = chat_service.save_tags_config(tags)
        return jsonify({'success': success})
    else:
        tags = chat_service.get_tags_config()
        return jsonify({'tags': tags})

@reception_bp.route('/api/chat/name', methods=['POST'])
@login_required
def api_chat_update_name():
    data = request.json
    phone = data.get('phone')
    name = data.get('name', '')
    
    if not phone:
        return jsonify({'success': False, 'message': 'Phone required'}), 400
        
    success = chat_service.update_contact_name(phone, name)
    return jsonify({'success': success})

@reception_bp.route('/api/chat/improve_text', methods=['POST'])
@login_required
def api_chat_improve_text():
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({'success': False, 'text': ''})
    
    improved = text[0].upper() + text[1:] if len(text) > 0 else text
    
    if improved and improved[-1] not in ['.', '!', '?']:
        improved += '.'
        
    corrections = {
        r'\bvc\b': 'você',
        r'\btbm\b': 'também',
        r'\bq\b': 'que',
        r'\bnao\b': 'não',
        r'\beh\b': 'é',
        r'\bta\b': 'está'
    }
    for slang, formal in corrections.items():
        improved = re.sub(slang, formal, improved, flags=re.IGNORECASE)
        
    return jsonify({'success': True, 'text': improved})

@reception_bp.route('/reception/room_consumption_report/<room_num>')
@reception_bp.route('/reception/room_consumption_report/<room_num>/')
@login_required
def get_room_consumption_report(room_num):
    try:
        # Permission Check
        user_role = session.get('role')
        user_perms = session.get('permissions', [])
        if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
            return "Acesso não autorizado", 403

        room_charges = load_room_charges()
        room_occupancy = load_room_occupancy()
        
        # Get guest info
        room_num_str = str(room_num)
        
        target_room_norm = normalize_room_simple(room_num_str)

        
        # Guest info lookup
        guest_info = {}
        # Try exact match, formatted, and normalized
        keys_to_try = [room_num_str]
        if room_num_str.isdigit():
            keys_to_try.append(f"{int(room_num_str):02d}")
        keys_to_try.append(target_room_norm)
        
        for key in keys_to_try:
             if key in room_occupancy:
                 guest_info = room_occupancy[key]
                 break
        
        guest_name = guest_info.get('guest_name', 'Hóspede não identificado')
        
        # Filter charges
        if not isinstance(room_charges, list):
            room_charges = []
            
        target_charges = []
        for c in room_charges:
            if not isinstance(c, dict):
                continue
            
            c_room = c.get('room_number')
            c_room_norm = normalize_room_simple(c_room)
            
            # Match by normalized room number
            if c.get('status') == 'pending' and c_room_norm == target_room_norm:
                target_charges.append(c)
        
        processed_charges = []
        total_amount = 0.0
        
        for charge in target_charges:
            date_raw = charge.get('date', '')
            time_str = charge.get('time', '')
            date = date_raw
            if isinstance(date_raw, str):
                try:
                    dt = datetime.strptime(date_raw, '%d/%m/%Y %H:%M')
                    date = dt.strftime('%d/%m/%Y')
                    if not time_str:
                        time_str = dt.strftime('%H:%M')
                except:
                    pass
            
            # If time is missing, try to parse from created_at if available
            if not time_str and 'created_at' in charge:
                try:
                    dt = datetime.strptime(charge['created_at'], '%d/%m/%Y %H:%M')
                    time_str = dt.strftime('%H:%M')
                except:
                    pass
            
            items_list = charge.get('items')
            if isinstance(items_list, str):
                try:
                    items_list = json.loads(items_list)
                except:
                    items_list = []
            elif items_list is None:
                items_list = []

            source = charge.get('source')
            if not source:
                charge_type = charge.get('type')
                if charge_type == 'minibar':
                    source = 'minibar'
                else:
                    has_minibar = any(
                        (isinstance(item, dict) and (item.get('category') == 'Frigobar' or item.get('source') == 'minibar'))
                        for item in (items_list or [])
                    )
                    source = 'minibar' if has_minibar else 'restaurant'
            
            charge_items = []
            charge_subtotal = 0.0
            taxable_total = 0.0
            
            # Debug: Trace item processing
            print(f"DEBUG: Processing charge {charge.get('id')} items. Count: {len(items_list)}")
                
            for item in items_list:
                try:
                    if not isinstance(item, dict):
                        print(f"DEBUG: Skipping non-dict item: {item}")
                        continue
                        
                    qty = float(item.get('qty', 1) or 1)
                    if qty.is_integer():
                        qty = int(qty)
                    base_price = float(item.get('price', 0) or 0)
                    
                    item_name = item.get('name', 'Item sem nome')
                    print(f"DEBUG: Processing item: {item_name}, qty: {qty}, price: {base_price}")

                    complements_total = 0.0
                    complements = item.get('complements') or []
                    if isinstance(complements, str):
                        try:
                            complements = json.loads(complements)
                        except:
                            complements = []
                    if isinstance(complements, list):
                        for c in complements:
                            if isinstance(c, dict):
                                try:
                                    complements_total += float(c.get('price', 0) or 0)
                                except:
                                    pass

                    accompaniments_total = 0.0
                    accompaniments = item.get('accompaniments') or []
                    if isinstance(accompaniments, str):
                        try:
                            accompaniments = json.loads(accompaniments)
                        except:
                            accompaniments = []
                    if isinstance(accompaniments, list):
                        for a in accompaniments:
                            if isinstance(a, dict):
                                try:
                                    accompaniments_total += float(a.get('price', 0) or 0)
                                except:
                                    pass

                    unit_price = base_price + complements_total + accompaniments_total
                    item_total = qty * unit_price
                    
                    charge_items.append({
                        'name': item.get('name', 'Item sem nome'),
                        'qty': qty,
                        'unit_price': unit_price,
                        'total': item_total
                    })
                    charge_subtotal += item_total
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += item_total
                except (ValueError, TypeError) as e:
                    print(f"Error processing item in room report: {e}")
                    continue
            
            if charge_items:
                service_fee = charge.get('service_fee')
                try:
                    service_fee = float(service_fee) if service_fee is not None else None
                except:
                    service_fee = None
                if service_fee is None:
                    service_fee = taxable_total * 0.10
                
                stored_total = charge.get('total')
                charge_total = charge_subtotal + service_fee
                if stored_total is not None:
                    try:
                        stored_total_f = float(stored_total)
                    except:
                        stored_total_f = None
                    if stored_total_f is not None:
                        if abs(stored_total_f - charge_total) <= 0.05:
                            charge_total = stored_total_f
                        elif abs(stored_total_f - charge_subtotal) <= 0.05:
                            charge_total = charge_subtotal + service_fee
                        else:
                            charge_total = stored_total_f

                processed_charges.append({
                    'id': charge.get('id'),
                    'date': date,
                    'time': time_str,
                    'source': source,
                    'line_items': charge_items,
                    'service_fee': service_fee,
                    'total': charge_total
                })
                total_amount += charge_total
        
        # Sort charges by date/time
        def sort_key(c):
            try:
                d = datetime.strptime(c['date'], '%d/%m/%Y')
                # Try to add time if available
                if c['time']:
                    try:
                        t = datetime.strptime(c['time'], '%H:%M').time()
                        d = datetime.combine(d.date(), t)
                    except: pass
                return d
            except:
                return datetime.min

        processed_charges.sort(key=sort_key)
        
        # total_amount already accumulated to include service fee consistently
        
        return render_template('consumption_report.html',
                            room_number=room_num_str,
                            guest_name=guest_name,
                            generation_date=datetime.now().strftime('%d/%m/%Y %H:%M'),
                            charges=processed_charges,
                            total_amount=total_amount)
    except Exception as e:
        traceback.print_exc()
        return f"Erro ao gerar relatório: {str(e)}", 500

@reception_bp.route('/debug/report_calc/<room_num>')
def debug_report_calc_route(room_num):
    try:
        room_charges = load_room_charges()
        # Normalize room number (handle 02 vs 2)
        target_charges = []
        for c in room_charges:
            r = str(c.get('room_number'))
            if r == str(room_num) or r == f"{int(room_num):02d}" or r == str(int(room_num)):
                if c.get('status') == 'pending':
                    target_charges.append(c)
        
        details = []
        total_amount = 0.0
        
        for charge in target_charges:
            charge_items = charge.get('items', [])
            if isinstance(charge_items, str):
                charge_items = json.loads(charge_items)
            
            charge_subtotal = 0.0
            taxable_total = 0.0
            source = charge.get('source', 'restaurant')
            
            item_details = []
            for item in charge_items:
                try:
                    p = float(item.get('price', 0))
                    q = float(item.get('qty', 1))
                    val = p * q
                    charge_subtotal += val
                    
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += val
                    item_details.append({'name': item.get('name'), 'val': val, 'apply_fee': apply_fee})
                except: pass

            service_fee = charge.get('service_fee')
            stored_total = charge.get('total')
            
            # Logic simulation
            final_total = 0.0
            method = "unknown"
            
            if stored_total is not None:
                final_total = float(stored_total)
                method = "stored_total"
            else:
                try:
                    sf = float(service_fee) if service_fee is not None else (taxable_total * 0.10)
                except:
                    sf = taxable_total * 0.10
                final_total = charge_subtotal + sf
                method = "calculated"
            
            total_amount += final_total
            details.append({
                'id': charge.get('id'),
                'stored_total': stored_total,
                'service_fee': service_fee,
                'subtotal': charge_subtotal,
                'taxable': taxable_total,
                'final_total': final_total,
                'method': method
            })
            
        return jsonify({
            'room': room_num,
            'count': len(target_charges),
            'total_amount': total_amount,
            'details': details
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@reception_bp.route('/reception/close_account/<room_num>', methods=['POST'])
@login_required
def reception_close_account(room_num):
    # Permission Check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        return jsonify({'success': False, 'error': 'Permissão negada'}), 403

    try:
        data = request.get_json()
        print_receipt = data.get('print_receipt', False)
        payment_method = data.get('payment_method')
        
        if not payment_method:
            return jsonify({'success': False, 'error': 'Forma de pagamento é obrigatória'}), 400
        
        occupancy = load_room_occupancy()
        room_num = str(room_num)
        
        # Validation: Room must be occupied
        if room_num not in occupancy:
            return jsonify({'success': False, 'error': 'Quarto não está ocupado'}), 400
            
        guest_name = occupancy[room_num].get('guest_name', 'Hóspede')
        
        # Validation: Open Cashier Session
        user = session.get('user', 'Sistema')
        
        # Use CashierService to find active session
        current_session = CashierService.get_active_session('guest_consumption')
        if not current_session:
             # Fallback to check legacy type or auto-open if needed? 
             # For now strict check as per legacy behavior
             current_session = CashierService.get_active_session('reception_room_billing')

        if not current_session:
             return jsonify({'success': False, 'error': 'Nenhum caixa de Consumo de Hóspedes aberto.'}), 400
        
        room_charges = load_room_charges()
        pending_charges = [c for c in room_charges if str(c.get('room_number')) == room_num and c.get('status') == 'pending']
        
        if not pending_charges:
            return jsonify({'success': False, 'error': 'Não há consumo pendente para este quarto'}), 400
            
        # Calculate total and prepare receipt data
        total_amount = 0.0
        processed_charges = []
        now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        # Resolve Payment Method Name and Object
        payment_methods_list = load_payment_methods()
        pm_obj = next((m for m in payment_methods_list if m['id'] == payment_method), None)
        pm_name = pm_obj['name'] if pm_obj else payment_method
        is_fiscal = pm_obj.get('is_fiscal', False) if pm_obj else False

        # Aggregate waiter breakdown
        from collections import defaultdict
        aggregated_waiter_breakdown = defaultdict(float)
        
        for charge in pending_charges:
            # Update Status
            charge['status'] = 'paid'
            charge['paid_at'] = now_str
            charge['closed_by'] = user
            charge['payment_method'] = payment_method
            charge['notes'] = charge.get('notes', '') + f" [Baixa Total por {user} em {now_str}]"
            
            # Prepare data for receipt
            date = charge.get('date', '')
            time_str = charge.get('time', '')
            source = charge.get('source')
            if not source:
                has_minibar = any(item.get('category') == 'Frigobar' for item in (charge.get('items') or []))
                source = 'minibar' if has_minibar else 'Restaurante'
            
            if not time_str and 'created_at' in charge:
                try:
                    dt = datetime.strptime(charge['created_at'], '%d/%m/%Y %H:%M')
                    time_str = dt.strftime('%H:%M')
                except: pass
                
            items_list = charge.get('items')
            if isinstance(items_list, str):
                try: items_list = json.loads(items_list)
                except: items_list = []
            elif items_list is None:
                items_list = []

            # Add to Fiscal Pool (Individual Emission per Charge)
            try:
                fiscal_payments = [{
                    'method': pm_name,
                    'amount': float(charge.get('total', 0)),
                    'is_fiscal': is_fiscal
                }]
                
                FiscalPoolService.add_to_pool(
                    origin='reception_charge',
                    original_id=f"CHARGE_{charge['id']}",
                    total_amount=float(charge.get('total', 0)),
                    items=items_list,
                    payment_methods=fiscal_payments,
                    user=user,
                    customer_info={'room_number': room_num, 'guest_name': guest_name}
                )
            except Exception as e:
                print(f"Error adding charge {charge['id']} to fiscal pool: {e}")
                
            charge_items = []
            charge_subtotal = 0.0
            taxable_total = 0.0
            
            for item in items_list:
                try:
                    if not isinstance(item, dict): continue
                    qty = int(item.get('qty', 1))
                    unit_price = float(item.get('price', 0))
                    item_total = qty * unit_price
                    
                    charge_items.append({
                        'name': item.get('name', 'Item sem nome'),
                        'qty': qty,
                        'unit_price': unit_price,
                        'total': item_total
                    })
                    charge_subtotal += item_total
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += item_total
                except: continue
                
            if charge_items:
                service_fee = charge.get('service_fee')
                try:
                    service_fee = float(service_fee) if service_fee is not None else None
                except:
                    service_fee = None
                
                # Check if service fee was explicitly removed
                is_fee_removed = charge.get('service_fee_removed', False)
                
                if service_fee is None:
                    if is_fee_removed:
                        service_fee = 0.0
                    else:
                        service_fee = taxable_total * 0.10
                        
                charge_total = charge_subtotal + service_fee
                processed_charges.append({
                    'id': charge.get('id'),
                    'date': date,
                    'time': time_str,
                    'source': source,
                    'line_items': charge_items,
                    'service_fee': service_fee,
                    'total': charge_total
                })
                total_amount += charge_total
                
                # Waiter Commission Aggregation
                # Only add commission if service fee was NOT removed
                if not is_fee_removed:
                    wb = charge.get('waiter_breakdown')
                    if wb and isinstance(wb, dict):
                        for w, amt in wb.items():
                            try:
                                aggregated_waiter_breakdown[w] += float(amt)
                            except: pass
                    elif charge.get('waiter'):
                        # Fallback for legacy charges
                        try:
                            w_name = charge.get('waiter')
                            # Calculate proportional commission based on service fee
                            if service_fee > 0:
                                aggregated_waiter_breakdown[w_name] += service_fee
                        except: pass

        save_room_charges(room_charges)
        
        # Resolve Payment Method Name
        payment_methods_list = load_payment_methods()
        pm_name = next((m['name'] for m in payment_methods_list if m['id'] == payment_method), payment_method)

        # Log Transaction to Cashier Session
        if total_amount > 0:
            transaction_details = {
                'room_number': room_num, 
                'guest_name': guest_name, 
                'category': 'Baixa de Conta'
            }
            
            # Add waiter breakdown to details if exists
            if aggregated_waiter_breakdown:
                transaction_details['waiter_breakdown'] = dict(aggregated_waiter_breakdown)
            
            CashierService.add_transaction(
                cashier_type='guest_consumption',
                amount=float(total_amount),
                description=f"Fechamento Conta Quarto {room_num} - {guest_name}",
                payment_method=pm_name,
                user=user,
                details=transaction_details
            )
        
        log_action('Baixa de Conta', f'Conta do Quarto {room_num} fechada por {user}. Total: R$ {total_amount:.2f}', department='Recepção')
        
        receipt_html = None
        if print_receipt:
            # Sort charges
            def sort_key(c):
                try:
                    d = datetime.strptime(c['date'], '%d/%m/%Y')
                    if c['time']:
                        try:
                            t = datetime.strptime(c['time'], '%H:%M').time()
                            d = datetime.combine(d.date(), t)
                        except: pass
                    return d
                except: return datetime.min
            
            processed_charges.sort(key=sort_key)
            
            receipt_html = render_template('consumption_report.html',
                                room_number=room_num,
                                guest_name=guest_name,
                                generation_date=now_str,
                                charges=processed_charges,
                                total_amount=total_amount)

        # --- FISCAL POOL INTEGRATION REMOVED ---
        # Logic moved to individual charge loop to prevent grouping
        # ---------------------------------------

        return jsonify({'success': True, 'receipt_html': receipt_html})
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@reception_bp.route('/webhook/whatsapp', methods=['GET', 'POST'])
def webhook_whatsapp():
    # Verification Challenge
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        # You should configure this token in your settings or env
        # For now accepting 'almareia_webhook_token' or the one from settings if we decide to store it
        VERIFY_TOKEN = 'almareia_webhook_token'
        
        if mode and token:
            if mode == 'subscribe' and token == VERIFY_TOKEN:
                return challenge, 200
            else:
                return 'Forbidden', 403
        return 'Hello World', 200
        
    # Receive Message
    if request.method == 'POST':
        data = request.json
        # Log raw hook for debug
        # logger.info(f"Webhook received: {data}")
        
        try:
            entry = data['entry'][0]
            changes = entry['changes'][0]
            value = changes['value']
            
            if 'messages' in value:
                message = value['messages'][0]
                phone = message['from'] # This is the sender's phone ID/number
                msg_body = ""
                msg_type = message.get('type')
                
                if msg_type == 'text':
                    msg_body = message['text']['body']
                else:
                    msg_body = f"[{msg_type} message]"
                    
                msg_data = {
                    'type': 'received',
                    'content': msg_body,
                    'timestamp': datetime.now().isoformat(),
                    'id': message.get('id'),
                    'raw': message
                }
                
                chat_service.add_message(phone, msg_data)
                
            return 'EVENT_RECEIVED', 200
            
        except Exception as e:
            # logger.error(f"Webhook processing error: {e}")
            return 'EVENT_RECEIVED', 200 # Return 200 anyway to prevent retries loop

@reception_bp.route('/admin/consumption/cancel', methods=['POST'])
@login_required
def cancel_consumption():
    try:
        user_role = session.get('role')
        user_perms = session.get('permissions', [])
        
        # Allow Admin, Manager, Supervisor OR anyone with 'recepcao' permission
        if user_role not in ['admin', 'gerente', 'supervisor'] and 'recepcao' not in user_perms:
            return jsonify({'success': False, 'message': 'Acesso negado. Permissão insuficiente.'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400

        charge_id = data.get('charge_id')
        justification = data.get('justification')
        
        if not charge_id or not justification:
            return jsonify({'success': False, 'message': 'ID do consumo e justificativa são obrigatórios.'}), 400
            
        room_charges = load_room_charges()
        charge = next((c for c in room_charges if c.get('id') == charge_id), None)
        
        if not charge:
            return jsonify({'success': False, 'message': 'Consumo não encontrado.'}), 404
            
        if charge.get('status') == 'canceled':
            return jsonify({'success': False, 'message': 'Este consumo já foi cancelado.'}), 400
            
        # Update Status
        old_status = charge.get('status')
        charge['status'] = 'canceled'
        charge['canceled_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        charge['canceled_by'] = session.get('user')
        charge['cancellation_reason'] = justification
        
        save_room_charges(room_charges)
        
        # Audit Log
        logs = load_audit_logs()
        logs.append({
            'id': f"AUDIT_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}",
            'action': 'cancel_consumption',
            'target_id': charge_id,
            'target_details': {
                'room': charge.get('room_number'),
                'total': charge.get('total'),
                'date': charge.get('date'),
                'old_status': old_status
            },
            'user': session.get('user'),
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'justification': justification
        })
        save_audit_logs(logs)
        
        # Structured Logging (DB)
        LoggerService.log_acao(
            acao='Cancelar Consumo',
            entidade='Consumo',
            detalhes={
                'charge_id': charge_id,
                'room_number': charge.get('room_number'),
                'total': charge.get('total'),
                'old_status': old_status,
                'justification': justification
            },
            nivel_severidade='ALERTA',
            departamento_id='Recepção',
            colaborador_id=session.get('user', 'Sistema')
        )
        
        # Notify Guest
        try:
            room_num = str(charge.get('room_number'))
            room_occupancy = load_room_occupancy()
            guest_info = room_occupancy.get(room_num, {})
            guest_name = guest_info.get('guest_name', 'Hóspede')
            guest_phone = guest_info.get('guest_phone')
            
            if guest_phone:
                msg = f"Olá {guest_name}, o consumo de R$ {charge.get('total', 0):.2f} no quarto {room_num} foi cancelado/estornado. Motivo: {justification}."
                chat_service.send_message(guest_phone, msg)
        except:
            pass
            
        return jsonify({'success': True, 'message': 'Consumo cancelado com sucesso.'})
        
    except Exception as e:
        print(f"Error cancelling consumption: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/api/guest/details/<reservation_id>')
@login_required
def api_guest_details(reservation_id):
    try:
        service = ReservationService()
        
        # 1. Get Basic Info
        res = service.get_reservation_by_id(reservation_id)
        if not res:
            res = {}
        else:
            res = service.merge_overrides_into_reservation(reservation_id, res)

        # 2. Get Extended Info
        details = service.get_guest_details(reservation_id)
        
        return jsonify({
            'success': True,
            'data': {
                'guest': details,
                'reservation': res
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/update', methods=['POST'])
@login_required
def api_guest_update():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        if not res_id:
            return jsonify({'success': False, 'error': 'ID da reserva necessário'}), 400
            
        service = ReservationService()
        service.update_guest_details(res_id, data)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/update_reservation_financials', methods=['POST'])
@login_required
def api_update_reservation_financials():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        if not res_id:
            return jsonify({'success': False, 'error': 'ID da reserva necessário'}), 400
        # Normalize numeric strings
        for k in ['amount', 'paid_amount', 'to_receive']:
            if k in data and isinstance(data.get(k), (int, float)):
                data[k] = f"{float(data[k]):.2f}"
        service = ReservationService()
        fin = service.update_financial_overrides(res_id, data)
        # Return merged details
        res = service.get_reservation_by_id(res_id) or {}
        res = service.merge_overrides_into_reservation(res_id, res)
        return jsonify({'success': True, 'financial': fin, 'reservation': res})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/upload_document', methods=['POST'])
@login_required
def api_guest_upload_document():
    try:
        res_id = request.form.get('reservation_id')
        file = request.files.get('document_photo')
        
        if not res_id or not file:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        filename = f"doc_{res_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        target_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'documents')
        os.makedirs(target_dir, exist_ok=True)
        
        path = os.path.join(target_dir, filename)
        file.save(path)
        final_filename = filename
        try:
            from PIL import Image, ImageOps
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)
            max_size = (1280, 1280)
            img.thumbnail(max_size)
            if img.mode in ('RGBA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = bg
            out_name = os.path.splitext(filename)[0] + '.jpg'
            out_path = os.path.join(target_dir, out_name)
            img.save(out_path, format='JPEG', quality=80, optimize=True, progressive=True)
            try:
                if os.path.exists(path) and path != out_path:
                    os.remove(path)
            except:
                pass
            final_filename = out_name
        except Exception:
            final_filename = filename
        
        # Update details with path (support up to 3 documents per reservation)
        service = ReservationService()
        details = service.get_guest_details(res_id)
        if 'personal_info' not in details:
            details['personal_info'] = {}
        pi = details['personal_info']
        photos = pi.get('document_photos')
        if not isinstance(photos, list):
            photos = []
            legacy = pi.get('document_photo_path')
            if legacy:
                photos.append(legacy)
        photos.append(final_filename)
        # keep only last 4
        photos = photos[-4:]
        pi['document_photos'] = photos
        # keep legacy key pointing to the latest for backward compatibility
        pi['document_photo_path'] = photos[-1] if photos else final_filename
        service.update_guest_details(res_id, {'personal_info': pi})
        
        return jsonify({'success': True, 'filename': final_filename, 'count': len(photos)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/upload_signature', methods=['POST'])
@login_required
def api_guest_upload_signature():
    try:
        res_id = request.form.get('reservation_id')
        file = request.files.get('signature')
        if not res_id or not file:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
        target_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures')
        os.makedirs(target_dir, exist_ok=True)
        filename = f"sign_{res_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        path = os.path.join(target_dir, filename)
        file.save(path)
        service = ReservationService()
        details = service.get_guest_details(res_id)
        if 'personal_info' not in details:
            details['personal_info'] = {}
        details['personal_info']['signature_path'] = filename
        service.update_guest_details(res_id, {'personal_info': details['personal_info']})
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/fnrh/<reservation_id>')
@login_required
def reception_fnrh(reservation_id):
    try:
        service = ReservationService()
        res = service.get_reservation_by_id(reservation_id) or {}
        details = service.get_guest_details(reservation_id) or {}
        return render_template('fnrh.html', reservation=res, details=details, reservation_id=reservation_id)
    except Exception as e:
        return f"Erro: {str(e)}", 500

@reception_bp.route('/api/utils/cep')
@login_required
def api_utils_cep():
    try:
        cep = request.args.get('cep', '').strip()
        import re
        cep_digits = re.sub(r'\D', '', cep or '')
        if len(cep_digits) != 8:
            return jsonify({'success': False, 'error': 'CEP inválido'}), 200
        import requests
        url = f'https://viacep.com.br/ws/{cep_digits}/json/'
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('erro'):
            return jsonify({'success': False, 'error': 'CEP não encontrado'}), 200
        logradouro = (data.get('logradouro') or '').strip()
        bairro = (data.get('bairro') or '').strip()
        localidade = (data.get('localidade') or '').strip()
        uf = (data.get('uf') or '').strip()
        address = ', '.join([p for p in [logradouro, bairro] if p])
        municipality = ' - '.join([p for p in [localidade, uf] if p])
        return jsonify({'success': True, 'address': address, 'municipality': municipality})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/utils/cpf')
@login_required
def api_utils_cpf():
    try:
        cpf = request.args.get('cpf', '').strip()
        import re, os
        cpf_digits = re.sub(r'\D', '', cpf or '')
        if len(cpf_digits) != 11:
            return jsonify({'success': False, 'error': 'CPF inválido'}), 200
        # Allow configuration via environment or system_config.json
        try:
            from app.services.system_config_manager import get_config_value
        except Exception:
            get_config_value = None
        ab_base = os.environ.get('APIBRASIL_CPF_BASE') or (get_config_value('apibrasil_cpf_base') if get_config_value else None)
        ab_token = os.environ.get('APIBRASIL_TOKEN') or (get_config_value('apibrasil_token') if get_config_value else None)
        base = os.environ.get('CPF_API_BASE') or (get_config_value('cpf_api_base') if get_config_value else None)
        token = os.environ.get('CPF_API_TOKEN') or (get_config_value('cpf_api_token') if get_config_value else None)
        use_base = None
        use_token = None
        if ab_base and ab_token:
            use_base = ab_base
            use_token = ab_token
        elif base and token:
            use_base = base
            use_token = token
        if not use_base or not use_token:
            return jsonify({'success': False, 'error': 'API de CPF não configurada'}), 200
        import requests
        headers = {'Authorization': f'Bearer {use_token}'}
        # Generic pattern: base may require path/params; we try fallback query param
        url = use_base
        if '{cpf}' in url:
            url = url.replace('{cpf}', cpf_digits)
            r = requests.get(url, headers=headers, timeout=7)
        else:
            r = requests.get(url, headers=headers, params={'cpf': cpf_digits}, timeout=7)
        data = {}
        try:
            data = r.json()
        except Exception:
            return jsonify({'success': False, 'error': 'Resposta inválida da API de CPF'}), 200
        # Best-effort extraction
        name = data.get('nome') or data.get('name') or data.get('full_name')
        birth = data.get('nascimento') or data.get('birthdate') or data.get('data_nascimento')
        address = None
        # Try common address structures
        endereco = data.get('endereco') or data.get('address') or {}
        if isinstance(endereco, dict):
            log = endereco.get('logradouro') or endereco.get('street')
            num = endereco.get('numero') or endereco.get('number')
            bai = endereco.get('bairro') or endereco.get('neighborhood')
            cid = endereco.get('cidade') or endereco.get('city')
            uf = endereco.get('uf') or endereco.get('state') or endereco.get('estado')
            parts = [p for p in [log, num if num else None, bai] if p]
            if parts:
                address = ', '.join([str(x) for x in parts])
        elif isinstance(endereco, str):
            address = endereco
        municipality = None
        if isinstance(endereco, dict):
            cid = endereco.get('cidade') or endereco.get('city')
            uf = endereco.get('uf') or endereco.get('state') or endereco.get('estado')
            if cid or uf:
                municipality = ' - '.join([p for p in [cid, uf] if p])
        return jsonify({'success': True, 'name': name, 'birthdate': birth, 'address': address, 'municipality': municipality})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/generate_pre_checkin', methods=['POST'])
@login_required
def api_generate_pre_checkin():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        guest_name = data.get('guest_name')
        send_wa = data.get('send_whatsapp')
        
        # Generate Link (Placeholder)
        # In a real app, this would generate a unique token
        token = f"{res_id}" # Simple for now
        # Check if 'public' blueprint exists, otherwise use absolute string
        try:
            link = url_for('public.pre_checkin', token=token, _external=True)
        except:
            link = f"http://{request.host}/pre-checkin/{token}"
        
        wa_result = None
        if send_wa:
            # Send WA logic
            pass
            
        return jsonify({'success': True, 'link': link, 'whatsapp_result': wa_result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/print_individual_bills', methods=['POST'])
@login_required
def print_individual_bills_route():
    try:
        data = request.get_json()
        room_num = data.get('room_number')
        guest_name = data.get('guest_name', 'Hóspede')
        printer_id = data.get('printer_id')
        selected_ids = data.get('selected_charge_ids', [])
        
        if not room_num or not printer_id:
            return jsonify({'success': False, 'message': 'Dados incompletos'}), 400
            
        room_charges = load_room_charges()
        
        # Filter selected charges
        charges_to_print = []
        total_amount = 0.0
        
        for c in room_charges:
            if c.get('id') in selected_ids:
                charges_to_print.append(c)
                total_amount += float(c.get('total', 0))
        
        if not charges_to_print:
            return jsonify({'success': False, 'message': 'Nenhuma conta encontrada'}), 404
            
        success, error = print_individual_bills_thermal(printer_id, room_num, guest_name, charges_to_print, total_amount)
        
        if success:
            return jsonify({'success': True, 'message': 'Enviado para impressão.'})
        else:
            return jsonify({'success': False, 'message': f'Erro na impressão: {error}'})
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
