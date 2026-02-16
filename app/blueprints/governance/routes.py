from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, flash, current_app
import os
import json
import uuid
from datetime import datetime
from PIL import Image
from werkzeug.utils import secure_filename

from . import governance_bp
from app.utils.decorators import login_required
from app.services.stock_service import get_product_balances, calculate_inventory
from app.services.data_service import (
    load_products, load_stock_entries, load_stock_requests, 
    load_stock_transfers, save_stock_entry, 
    load_room_charges, save_room_charges, 
    load_room_occupancy, load_menu_items,
    load_settings
)
from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    LAUNDRY_DATA_DIR, CLEANING_STATUS_FILE, CLEANING_LOGS_FILE
)

# --- Helpers ---

def get_laundry_db_path():
    # Ensure directory exists
    if not os.path.exists(LAUNDRY_DATA_DIR):
        os.makedirs(LAUNDRY_DATA_DIR)
    return os.path.join(LAUNDRY_DATA_DIR, "laundry.json")

def load_cleaning_status():
    if not os.path.exists(CLEANING_STATUS_FILE):
        return {}
    try:
        with open(CLEANING_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_cleaning_status(data):
    with open(CLEANING_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_cleaning_logs():
    if not os.path.exists(CLEANING_LOGS_FILE):
        return []
    try:
        with open(CLEANING_LOGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_cleaning_log(log_entry):
    logs = load_cleaning_logs()
    logs.append(log_entry)
    with open(CLEANING_LOGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=4, ensure_ascii=False)

# --- Routes ---

@governance_bp.route('/api/laundry/data', methods=['GET'])
@login_required
def get_laundry_data():
    path = get_laundry_db_path()
    
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return jsonify(data)
            except json.JSONDecodeError:
                return jsonify(None)
    else:
        return jsonify(None)

@governance_bp.route('/api/laundry/data', methods=['POST'])
@login_required
def save_laundry_data():
    path = get_laundry_db_path()
    
    try:
        data = request.json
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@governance_bp.route('/laundry_management')
@login_required
def laundry_management():
    return render_template('laundry_management.html')

@governance_bp.route('/governance/deduct_coffee', methods=['POST'])
@login_required
def governance_deduct_coffee():
    # Only Governance or Admin
    if session.get('role') not in ['admin', 'gerente', 'supervisor'] and session.get('department') != 'Governança':
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403

    try:
        data = request.json
        room_num = data.get('room_number')
        
        if not room_num:
            return jsonify({'success': False, 'error': 'Número do quarto inválido.'}), 400
            
        # Find Product ID 492 (Café Capsula (GOVERNANÇA))
        products = load_products()
        target_product = next((p for p in products if str(p.get('id')) == '492'), None)
        
        if not target_product:
            # Fallback search by name if ID changed
            target_product = next((p for p in products if 'Café Capsula' in p['name'] and 'GOVERNANÇA' in p['name']), None)
            
        if not target_product:
             return jsonify({'success': False, 'error': 'Produto "Café Capsula (GOVERNANÇA)" não encontrado.'}), 404

        # Validate Stock Availability
        entries = load_stock_entries()
        stock_reqs = load_stock_requests()
        transfers = load_stock_transfers()
        
        # Calculate Global Inventory to get current balance
        inventory_data = calculate_inventory(products, entries, stock_reqs, transfers, target_dept='Geral')
        
        product_name = target_product['name']
        current_balance = 0.0
        
        if product_name in inventory_data:
             current_balance = inventory_data[product_name].get('balance', 0.0)
             
        if current_balance < 2:
             # Log the failed attempt
             LoggerService.log_acao(
                 acao='Erro Dedução Estoque', 
                 entidade='Governança',
                 detalhes={'error': f"Estoque insuficiente ({current_balance})", 'room': room_num},
                 departamento_id='Governança',
                 colaborador_id=session.get('user')
             )
             return jsonify({'success': False, 'error': f'Estoque insuficiente. Disponível: {current_balance}'}), 400
             
        # Create Stock Deduction
        entry = {
            'id': f"DEDUCT_{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'user': session.get('user', 'Governança'),
            'product': target_product['name'],
            'supplier': f"Consumo: Quarto {room_num}",
            'qty': -2,
            'price': target_product.get('price', 0),
            'date': datetime.now().strftime('%d/%m/%Y'),
            'invoice': 'Consumo Hóspede'
        }
        
        save_stock_entry(entry)
        
        # Log Action
        LoggerService.log_acao(
            acao='Dedução de Estoque', 
            entidade='Governança',
            detalhes={'msg': f"Dedução automática de 2 cápsulas para Quarto {room_num}"},
            departamento_id='Governança',
            colaborador_id=session.get('user')
        )
                   
        return jsonify({
            'success': True,
            'receipt': {
                'date': datetime.now().strftime('%d/%m/%Y'),
                'time': datetime.now().strftime('%H:%M'),
                'room': room_num,
                'staff': session.get('user', 'Governança'),
                'item': target_product['name'],
                'qty': 2
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@governance_bp.route('/governance/undo_deduct_coffee', methods=['POST'])
@login_required
def governance_undo_deduct_coffee():
    # Only Governance or Admin
    if session.get('role') not in ['admin', 'gerente', 'supervisor'] and session.get('department') != 'Governança':
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403

    try:
        data = request.json
        room_num = data.get('room_number')
        
        if not room_num:
            return jsonify({'success': False, 'error': 'Número do quarto inválido.'}), 400
            
        # Find Product ID 492
        products = load_products()
        target_product = next((p for p in products if str(p.get('id')) == '492'), None)
        
        if not target_product:
            target_product = next((p for p in products if 'Café Capsula' in p['name'] and 'GOVERNANÇA' in p['name']), None)
            
        if not target_product:
             return jsonify({'success': False, 'error': 'Produto não encontrado.'}), 404

        # Create Stock Entry (Reversal)
        entry = {
            'id': f"UNDO_DEDUCT_{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'user': session.get('user', 'Governança'),
            'product': target_product['name'],
            'supplier': f"Estorno Consumo: Quarto {room_num}",
            'qty': 2, # Positive to add back
            'price': target_product.get('price', 0),
            'date': datetime.now().strftime('%d/%m/%Y'),
            'invoice': 'Estorno Consumo'
        }
        
        save_stock_entry(entry)
        
        LoggerService.log_acao(
            acao='Estorno Dedução', 
            entidade='Governança',
            detalhes={'msg': f"Estorno de 2 cápsulas para Quarto {room_num}"},
            departamento_id='Governança',
            colaborador_id=session.get('user')
        )
                   
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@governance_bp.route('/governance/rooms', methods=['GET', 'POST'])
@login_required
def governance_rooms():
    try:
        occupancy = load_room_occupancy()
        cleaning_status = load_cleaning_status()
        
        if not isinstance(cleaning_status, dict):
            cleaning_status = {}
        
        if request.method == 'POST':
            action = request.form.get('action')
            room_num = request.form.get('room_number')
            
            if not room_num:
                flash("Erro: Número do quarto não identificado.")
                return redirect(url_for('governance.governance_rooms'))

            current_time = datetime.now()
            
            if action == 'start_cleaning':
                current_data = cleaning_status.get(room_num, {})
                previous_status = current_data.get('status', 'dirty')
                
                if previous_status == 'in_progress':
                    previous_status = current_data.get('previous_status', 'dirty')
                
                cleaning_status[room_num] = {
                    'status': 'in_progress',
                    'previous_status': previous_status,
                    'maid': session.get('user', 'Desconhecido'),
                    'start_time': current_time.strftime('%d/%m/%Y %H:%M:%S'),
                    'last_update': current_time.strftime('%d/%m/%Y %H:%M')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Limpeza iniciada no Quarto {room_num}")
                
            elif action == 'finish_cleaning':
                status = cleaning_status.get(room_num, {})
                if status.get('status') == 'in_progress':
                    start_time_str = status.get('start_time')
                    try:
                        start_time = datetime.strptime(start_time_str, '%d/%m/%Y %H:%M:%S')
                    except ValueError:
                        start_time = current_time
                        
                    duration_seconds = (current_time - start_time).total_seconds()
                    duration_minutes = round(duration_seconds / 60, 2)
                    
                    prev_status = status.get('previous_status', 'dirty')
                    
                    cleaning_type = 'normal'
                    if prev_status in ['dirty_checkout', 'rejected']:
                        new_status = 'clean' # Needs Inspection
                        if prev_status == 'dirty_checkout':
                             cleaning_type = 'checkout'
                    else:
                        new_status = 'inspected' # Ready for guest (Skip inspection)
                    
                    log_entry = {
                        'room': room_num,
                        'maid': status.get('maid'),
                        'start_time': status.get('last_update'),
                        'end_time': current_time.strftime('%d/%m/%Y %H:%M'),
                        'duration_minutes': duration_minutes,
                        'type': cleaning_type,
                        'timestamp': current_time.timestamp()
                    }
                    
                    if duration_minutes >= 1.0:
                        save_cleaning_log(log_entry)
                    
                    cleaning_status[room_num] = {
                        'status': new_status,
                        'last_cleaned_by': status.get('maid'),
                        'last_cleaned_at': current_time.strftime('%d/%m/%Y %H:%M')
                    }
                    save_cleaning_status(cleaning_status)
                    flash(f"Limpeza finalizada no Quarto {room_num}. Tempo: {duration_minutes} min")
                    
                    if request.form.get('redirect_minibar') == 'true':
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=int(room_num), mode='minibar'))
                else:
                    flash('Erro: Limpeza não estava em andamento.')
                    
            elif action == 'inspect':
                cleaning_status[room_num] = {
                    'status': 'inspected',
                    'inspected_by': session.get('user'),
                    'inspected_at': current_time.strftime('%d/%m/%Y %H:%M')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Quarto {room_num} inspecionado e liberado.")
                
            elif action == 'reject':
                cleaning_status[room_num] = {
                    'status': 'rejected',
                    'rejected_by': session.get('user'),
                    'rejected_at': current_time.strftime('%d/%m/%Y %H:%M'),
                    'reason': request.form.get('reason', 'Retorno de inspeção')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Quarto {room_num} rejeitado na inspeção.")
                
            return redirect(url_for('governance.governance_rooms'))
            
        # Mock month_stats for template compatibility
        current_month_name = datetime.now().strftime('%B')
        month_stats = {
            'name': current_month_name,
            'avg_time': 0,
            'total_cleaned': 0
        }
        
        year_stats = {
            'name': datetime.now().year,
            'avg_time': 0,
            'total_cleaned': 0
        }
        
        return render_template('governance_rooms.html', occupancy=occupancy, cleaning_status=cleaning_status, month_stats=month_stats, year_stats=year_stats)
        
    except Exception as e:
        print(f"Error in governance_rooms: {e}")
        return render_template('error.html', error=str(e)), 500

@governance_bp.route('/api/frigobar/items', methods=['GET'])
@login_required
def api_frigobar_items():
    try:
        items = load_menu_items()
        frigobar_items = [p for p in items if p.get('category') == 'Frigobar']
        simplified = []
        for p in frigobar_items:
            simplified.append(
                {
                    "id": str(p.get("id")),
                    "name": p.get("name"),
                    "price": float(p.get("price", 0)),
                }
            )
        return jsonify({"items": simplified})
    except Exception as e:
        print(f"Error loading frigobar items: {e}")
        return jsonify({'error': 'Erro ao carregar itens do servidor.'}), 500

@governance_bp.route('/governance/launch_frigobar', methods=['POST'])
@login_required
def governance_launch_frigobar():
    try:
        data = request.get_json()
        room_num = str(data.get('room_number'))
        items = data.get('items', []) # List of {id, qty}
        
        if not room_num or not items:
            return jsonify({'success': False, 'error': 'Dados inválidos.'}), 400
            
        menu_items = load_menu_items()
        product_map = {str(p['id']): p for p in menu_items}
        
        room_charges = load_room_charges()
        
        items_to_charge = []
        total = 0
        
        items_added_names = []
        for item in items:
            p_id = str(item['id'])
            qty = float(item['qty'])
            
            if qty > 0 and p_id in product_map:
                product = product_map[p_id]
                price = float(product['price'])
                item_total = qty * price
                
                order_item = {
                    'id': p_id,
                    'name': product['name'],
                    'price': price,
                    'qty': qty,
                    'category': product.get('category', 'Frigobar'),
                    'added_at': datetime.now().strftime('%H:%M:%S'),
                    'added_by': session.get('user', 'Governança')
                }
                
                items_to_charge.append(order_item)
                items_added_names.append(f"{qty}x {product['name']}")
                total += item_total

        if not items_to_charge:
             return jsonify({'success': False, 'error': 'Nenhum item válido encontrado.'}), 400

        charge = {
            'id': f"CHARGE_GOV_{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
            'room_number': room_num,
            'table_id': 'GOV', 
            'total': total,
            'items': items_to_charge,
            'service_fee': 0, 
            'discount': 0,
            'flags': [],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'status': 'pending',
            'type': 'minibar'
        }
        
        room_charges.append(charge)
        save_room_charges(room_charges)
        
        if items_added_names:
            log_msg = f"Lançamento de Frigobar no Quarto {room_num}: {', '.join(items_added_names)}"
            LoggerService.log_acao(
                acao='Frigobar Governança', 
                entidade='Governança',
                detalhes={'msg': log_msg},
                departamento_id='Governança',
                colaborador_id=session.get('user')
            )
            
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

from app.services import checklist_service

@governance_bp.route('/checklist')
@login_required
def checklist_view():
    dept = request.args.get('department', 'Governança')
    daily_items = checklist_service.get_todays_checklist(department=dept)
    # Group items by category for display
    items_by_category = {}
    for item in daily_items.get('items', []):
        cat = item.get('category', 'Outros')
        if cat not in items_by_category:
            items_by_category[cat] = []
        items_by_category[cat].append(item)
    
    # Sort categories alphabetically
    sorted_items_by_category = dict(sorted(items_by_category.items()))
    
    settings = load_settings()
    
    # Filter catalog items for Department
    all_items = checklist_service.load_checklist_items()
    dept_items = [i for i in all_items if i.get('department', 'Governança') == dept]
    
    # Load Insumos for auto-complete
    insumos = load_products() 

    return render_template('checklist.html', 
                          daily_items=daily_items,
                          daily_items_by_category=sorted_items_by_category,
                          all_items=dept_items,
                          insumos=insumos,
                          settings=settings,
                          department=dept)

# --- Checklist API Routes ---

@governance_bp.route('/api/checklist/update_daily', methods=['POST'])
@login_required
def update_checklist_daily():
    data = request.json
    item_id = data.get('item_id')
    checked = data.get('checked')
    qty = data.get('qty')
    dept = data.get('department', 'Governança')
    
    today = datetime.now().strftime('%Y-%m-%d')
    success = checklist_service.update_checklist_item(today, item_id, checked, qty, department=dept)
    return jsonify({'success': success})

@governance_bp.route('/api/checklist/add_item', methods=['POST'])
@login_required
def add_checklist_item_api():
    data = request.json
    name = data.get('name')
    category = data.get('category')
    unit = data.get('unit')
    dept = data.get('department', 'Governança')
    
    if name:
        checklist_service.add_catalog_item(name, category, unit, department=dept)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Nome obrigatório'})

@governance_bp.route('/api/checklist/update_item', methods=['POST'])
@login_required
def update_checklist_item_api():
    data = request.json
    item_id = data.get('id')
    name = data.get('name')
    category = data.get('category')
    unit = data.get('unit')
    
    if item_id and name:
        checklist_service.update_catalog_item(item_id, name, category, unit)
        return jsonify({'success': True})
    return jsonify({'success': False})

@governance_bp.route('/api/checklist/delete_item', methods=['POST'])
@login_required
def delete_checklist_item_api():
    data = request.json
    item_id = data.get('id')
    if item_id:
        checklist_service.remove_catalog_item(item_id)
        return jsonify({'success': True})
    return jsonify({'success': False})

@governance_bp.route('/api/checklist/settings', methods=['POST'])
@login_required
def save_checklist_settings_api():
    data = request.json
    settings = checklist_service.load_checklist_settings()
    settings['whatsapp_number'] = data.get('whatsapp_number')
    checklist_service.save_checklist_settings(settings)
    return jsonify({'success': True})

@governance_bp.route('/api/checklist/preview', methods=['GET'])
@login_required
def preview_checklist_api():
    dept = request.args.get('department', 'Governança')
    checklist = checklist_service.get_todays_checklist(department=dept)
    
    lines = [f"*Checklist de Compras - {dept}*"]
    lines.append(f"Data: {datetime.now().strftime('%d/%m/%Y')}")
    lines.append("")
    
    items_by_cat = {}
    for item in checklist.get('items', []):
        if item.get('checked'):
            cat = item.get('category', 'Outros')
            if cat not in items_by_cat: items_by_cat[cat] = []
            items_by_cat[cat].append(item)
            
    if not items_by_cat:
        return jsonify({'success': True, 'text': "Nenhum item selecionado."})
        
    for cat in sorted(items_by_cat.keys()):
        lines.append(f"*{cat}*")
        for item in items_by_cat[cat]:
            qty = item.get('qty', '')
            unit = item.get('unit', '')
            lines.append(f"- {item['name']}: {qty} {unit}")
        lines.append("")
        
    return jsonify({'success': True, 'text': "\n".join(lines)})

@governance_bp.route('/api/checklist/send', methods=['POST'])
@login_required
def send_checklist_api():
    try:
        data = request.json or {}
        dept = data.get('department', 'Governança')
        
        settings = checklist_service.load_checklist_settings()
        phone = settings.get('whatsapp_number')
        
        if not phone:
            return jsonify({'success': False, 'error': 'Número WhatsApp não configurado.'})
            
        checklist = checklist_service.get_todays_checklist(department=dept)
        items_by_cat = {}
        for item in checklist.get('items', []):
            if item.get('checked'):
                cat = item.get('category', 'Outros')
                if cat not in items_by_cat:
                    items_by_cat[cat] = []
                items_by_cat[cat].append(item)
        
        if not items_by_cat:
            return jsonify({'success': False, 'error': 'Nenhum item selecionado.'})

        lines = [f"*Checklist de Compras - {dept}*"]
        lines.append(f"Data: {datetime.now().strftime('%d/%m/%Y')}")
        lines.append("")
        
        for cat in sorted(items_by_cat.keys()):
            lines.append(f"*{cat}*")
            for item in items_by_cat[cat]:
                qty = item.get('qty', '')
                unit = item.get('unit', '')
                lines.append(f"- {item['name']}: {qty} {unit}")
            lines.append("")
            
        message_text = "\n".join(lines)
        
        return jsonify({'success': True, 'phone': phone, 'text': message_text})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
