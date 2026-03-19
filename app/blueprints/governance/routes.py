from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, flash, current_app
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from PIL import Image
from werkzeug.utils import secure_filename

from . import governance_bp
from app.utils.decorators import login_required
from app.services.data_service import (
    load_products,
    load_room_charges, save_room_charges, 
    load_room_occupancy, load_menu_items,
    load_settings, load_cleaning_status, save_cleaning_status
)
from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    LAUNDRY_DATA_DIR, CLEANING_STATUS_FILE, CLEANING_LOGS_FILE
)
from app.services.governance_auto_deduct_service import (
    EVENT_TYPES,
    load_auto_deduct_config,
    load_auto_deduct_audit,
    upsert_auto_rule,
    remove_auto_rule,
    list_governance_candidate_products,
    low_stock_alerts_for_auto_deduct,
    apply_auto_deduction,
    apply_manual_stock_movement
)

# --- Helpers ---

def get_laundry_db_path():
    os.makedirs(LAUNDRY_DATA_DIR, exist_ok=True)
    return os.path.join(LAUNDRY_DATA_DIR, "laundry.json")

def _read_json_file(path, default):
    file_path = Path(path)
    if not file_path.exists():
        return default
    try:
        raw = file_path.read_text(encoding='utf-8')
        return json.loads(raw)
    except Exception:
        return default

def _write_json_file_atomic(path, payload):
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_name(f"{file_path.name}.tmp.{uuid.uuid4().hex}")
    raw = json.dumps(payload, indent=4, ensure_ascii=False)
    temp_path.write_text(raw, encoding='utf-8')
    os.replace(str(temp_path), str(file_path))
    return True

def load_cleaning_logs():
    logs = _read_json_file(CLEANING_LOGS_FILE, [])
    if isinstance(logs, list):
        return logs
    return []

def save_cleaning_log(log_entry):
    logs = load_cleaning_logs()
    logs.append(log_entry)
    return _write_json_file_atomic(CLEANING_LOGS_FILE, logs)


def _ensure_governance_access(json_mode=False):
    if session.get('role') in ['admin', 'gerente', 'supervisor'] or session.get('department') == 'Governança':
        return None
    if json_mode:
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403
    flash('Acesso restrito à Governança.')
    return redirect(url_for('main.index'))


def _can_manage_auto_deduct_rules():
    return session.get('role') in ['admin', 'gerente', 'supervisor']

# --- Routes ---

@governance_bp.route('/api/laundry/data', methods=['GET'])
@login_required
def get_laundry_data():
    path = get_laundry_db_path()
    data = _read_json_file(path, None)
    if data is None:
        return jsonify(None)
    return jsonify(data)

@governance_bp.route('/api/laundry/data', methods=['POST'])
@login_required
def save_laundry_data():
    path = get_laundry_db_path()
    
    try:
        data = request.json
        _write_json_file_atomic(path, data)
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

        movement = apply_manual_stock_movement(
            room_number=room_num,
            triggered_by=session.get('user', 'Governança'),
            source='governance_deduct_coffee',
            movement_type='coffee_capsule_deduction',
            items=[{
                'product_id': target_product.get('id'),
                'product_name': target_product.get('name'),
                'qty': -2
            }],
            metadata={'invoice': 'Consumo Hóspede'}
        )
        if movement.get('applied_count', 0) <= 0:
            first = (movement.get('insufficient') or [{}])[0]
            current_balance = first.get('balance')
            LoggerService.log_acao(
                acao='Erro Dedução Estoque',
                entidade='Governança',
                detalhes={'error': f"Estoque insuficiente ({current_balance})", 'room': room_num},
                departamento_id='Governança',
                colaborador_id=session.get('user')
            )
            return jsonify({'success': False, 'error': f"Estoque insuficiente. Disponível: {current_balance if current_balance is not None else 0}"}), 400
        
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

        movement = apply_manual_stock_movement(
            room_number=room_num,
            triggered_by=session.get('user', 'Governança'),
            source='governance_undo_deduct_coffee',
            movement_type='coffee_capsule_reversal',
            items=[{
                'product_id': target_product.get('id'),
                'product_name': target_product.get('name'),
                'qty': 2
            }],
            metadata={'invoice': 'Estorno Consumo'}
        )
        if movement.get('applied_count', 0) <= 0:
            return jsonify({'success': False, 'error': 'Falha ao registrar estorno no estoque.'}), 500
        
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
        denied = _ensure_governance_access()
        if denied is not None:
            return denied
        occupancy = load_room_occupancy()
        cleaning_status = load_cleaning_status()
        auto_deduct_config = load_auto_deduct_config()
        governance_products = list_governance_candidate_products()
        low_stock_alerts = low_stock_alerts_for_auto_deduct()
        auto_deduct_audit = load_auto_deduct_audit()
        
        if not isinstance(cleaning_status, dict):
            cleaning_status = {}
        
        if request.method == 'POST':
            action = request.form.get('action')
            if action in ['auto_rule_add', 'auto_rule_remove']:
                if not _can_manage_auto_deduct_rules():
                    flash('Apenas supervisão/gerência pode alterar regras de baixa automática.')
                    return redirect(url_for('governance.governance_rooms'))
                event_type = str(request.form.get('event_type') or '').strip()
                product_id = str(request.form.get('product_id') or '').strip()
                qty_raw = request.form.get('qty')
                if action == 'auto_rule_add':
                    ok, msg = upsert_auto_rule(event_type, product_id, qty_raw, active=True)
                    if ok:
                        flash('Regra automática salva com sucesso.')
                    else:
                        flash(msg or 'Falha ao salvar regra automática.')
                else:
                    ok, msg = remove_auto_rule(event_type, product_id)
                    if ok:
                        flash('Regra automática removida.')
                    else:
                        flash(msg or 'Falha ao remover regra automática.')
                return redirect(url_for('governance.governance_rooms'))
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
                    'cleaning_cycle_ref': current_time.strftime('%Y%m%d%H%M%S%f'),
                    'last_update': current_time.strftime('%d/%m/%Y %H:%M'),
                    'pending_note': current_data.get('pending_note')
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
                        'last_cleaned_at': current_time.strftime('%d/%m/%Y %H:%M'),
                        'pending_note': status.get('pending_note')
                    }
                    save_cleaning_status(cleaning_status)
                    flash(f"Limpeza finalizada no Quarto {room_num}. Tempo: {duration_minutes} min")
                    auto_event_type = 'checkout_cleaning' if prev_status == 'dirty_checkout' else 'daily_cleaning'
                    deduction = apply_auto_deduction(
                        event_type=auto_event_type,
                        room_number=room_num,
                        triggered_by=session.get('user') or 'Governança',
                        source='governance_rooms.finish_cleaning',
                        event_ref=current_time.strftime('%Y-%m-%d'),
                        event_context={'cleaning_cycle_ref': status.get('cleaning_cycle_ref')}
                    )
                    if deduction.get('duplicate'):
                        flash(f"Baixa automática já registrada para este ciclo de limpeza ({auto_event_type}).")
                    if deduction.get('applied_count', 0) > 0:
                        flash(f"Baixa automática aplicada: {deduction.get('applied_count')} item(ns) ({auto_event_type}).")
                    for warning in (deduction.get('warnings') or []):
                        flash(f"Aviso de estoque automático: {warning}")
                    
                    if request.form.get('redirect_minibar') == 'true':
                        return redirect(url_for('restaurant.restaurant_table_order', table_id=int(room_num), mode='minibar'))
                else:
                    flash('Erro: Limpeza não estava em andamento.')
                    
            elif action == 'inspect':
                cleaning_status[room_num] = {
                    'status': 'inspected',
                    'inspected_by': session.get('user'),
                    'inspected_at': current_time.strftime('%d/%m/%Y %H:%M'),
                    'pending_note': (cleaning_status.get(room_num, {}) or {}).get('pending_note')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Quarto {room_num} inspecionado e liberado.")
                
            elif action == 'reject':
                cleaning_status[room_num] = {
                    'status': 'rejected',
                    'rejected_by': session.get('user'),
                    'rejected_at': current_time.strftime('%d/%m/%Y %H:%M'),
                    'reason': request.form.get('reason', 'Retorno de inspeção'),
                    'rejection_reason': request.form.get('reason', 'Retorno de inspeção'),
                    'pending_note': (cleaning_status.get(room_num, {}) or {}).get('pending_note')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Quarto {room_num} rejeitado na inspeção.")
            elif action == 'mark_dirty':
                current_data = cleaning_status.get(room_num, {}) if isinstance(cleaning_status.get(room_num, {}), dict) else {}
                cleaning_status[room_num] = {
                    'status': 'dirty',
                    'marked_by': session.get('user'),
                    'marked_at': current_time.strftime('%d/%m/%Y %H:%M'),
                    'pending_note': current_data.get('pending_note')
                }
                save_cleaning_status(cleaning_status)
                flash(f"Quarto {room_num} marcado como sujo.")
            elif action == 'add_note':
                note = str(request.form.get('note') or '').strip()
                current_data = cleaning_status.get(room_num, {}) if isinstance(cleaning_status.get(room_num, {}), dict) else {}
                current_data['status'] = current_data.get('status', 'dirty')
                current_data['pending_note'] = note
                current_data['note_updated_by'] = session.get('user')
                current_data['note_updated_at'] = current_time.strftime('%d/%m/%Y %H:%M')
                cleaning_status[room_num] = current_data
                save_cleaning_status(cleaning_status)
                flash(f"Pendência atualizada no quarto {room_num}.")
                
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
        
        auto_deduct_config = load_auto_deduct_config()
        governance_products = list_governance_candidate_products()
        low_stock_alerts = low_stock_alerts_for_auto_deduct()
        auto_deduct_audit = load_auto_deduct_audit()
        return render_template(
            'governance_rooms.html',
            occupancy=occupancy,
            cleaning_status=cleaning_status,
            month_stats=month_stats,
            year_stats=year_stats,
            auto_deduct_config=auto_deduct_config,
            governance_products=governance_products,
            auto_event_types=EVENT_TYPES,
            low_stock_alerts=low_stock_alerts,
            can_manage_auto_rules=_can_manage_auto_deduct_rules(),
            auto_deduct_audit=list(reversed(auto_deduct_audit[-20:]))
        )
        
    except Exception as e:
        print(f"Error in governance_rooms: {e}")
        return render_template('error.html', error=str(e)), 500

@governance_bp.route('/api/frigobar/items', methods=['GET'])
@login_required
def api_frigobar_items():
    try:
        denied = _ensure_governance_access(json_mode=True)
        if denied is not None:
            return denied
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
        denied = _ensure_governance_access(json_mode=True)
        if denied is not None:
            return denied
        data = request.get_json() or {}
        room_num = str(data.get('room_number') or '').strip()
        items = data.get('items', [])
        
        if not room_num or not isinstance(items, list) or not items:
            return jsonify({'success': False, 'error': 'Dados inválidos.'}), 400

        occupancy = load_room_occupancy()
        cleaning_status = load_cleaning_status()
        room_status = ''
        if isinstance(cleaning_status, dict):
            room_status = str((cleaning_status.get(room_num, {}) or {}).get('status') or '').strip()
        room_is_occupied = room_num in occupancy
        allowed_unoccupied_statuses = {'dirty_checkout', 'in_progress'}
        if not room_is_occupied and room_status not in allowed_unoccupied_statuses:
            return jsonify({
                'success': False,
                'error': 'Quarto fora de contexto operacional para lançamento de frigobar.',
                'details': {
                    'room_number': room_num,
                    'occupied': room_is_occupied,
                    'cleaning_status': room_status
                }
            }), 400
            
        menu_items = load_menu_items()
        product_map = {str(p['id']): p for p in menu_items}
        products_insumos = load_products()
        insumo_map = {str(i.get('id')): i for i in products_insumos if i.get('id') is not None}
        
        room_charges = load_room_charges()
        
        items_to_charge = []
        stock_movements = []
        total = 0
        missing_recipe = []
        missing_ingredients = []
        invalid_items = []
        invalid_category = []
        
        items_added_names = []
        for item in items:
            p_id = str(item.get('id') or '').strip()
            try:
                qty = float(item.get('qty') or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty <= 0:
                continue
            product = product_map.get(p_id)
            if not product:
                invalid_items.append(p_id)
                continue
            if str(product.get('category') or '') != 'Frigobar':
                invalid_category.append(str(product.get('name') or p_id))
                continue
            recipe = product.get('recipe')
            if not isinstance(recipe, list) or not recipe:
                missing_recipe.append(str(product.get('name') or p_id))
                continue
            
            price = float(product['price'])
            item_total = qty * price

            try:
                for ingred in recipe:
                    raw_ing_id = ingred.get('ingredient_id')
                    insumo_data = None
                    ing_key = None

                    if raw_ing_id is not None:
                        ing_key = str(raw_ing_id)
                        insumo_data = insumo_map.get(ing_key)
                    else:
                        ing_name = ingred.get('ingredient')
                        if ing_name:
                            insumo_data = next((i for i in products_insumos if i.get('name') == ing_name), None)
                            if insumo_data and insumo_data.get('id') is not None:
                                ing_key = str(insumo_data.get('id'))
                            else:
                                ing_key = ing_name

                    if not insumo_data:
                        missing_ingredients.append(f"{product.get('name')}::{ing_key or ingred.get('ingredient') or 'ingrediente'}")
                        continue

                    try:
                        ing_qty = float(ingred.get('qty', 0))
                    except (TypeError, ValueError):
                        ing_qty = 0
                    if ing_qty <= 0:
                        missing_ingredients.append(f"{product.get('name')}::{insumo_data.get('name')} (quantidade inválida)")
                        continue

                    total_needed = ing_qty * qty

                    entry_data = {
                        'product_id': insumo_data.get('id'),
                        'product_name': insumo_data['name'],
                        'qty': -total_needed
                    }
                    stock_movements.append(entry_data)
            except Exception as e:
                current_app.logger.error(f"Stock deduction error (Governance Frigobar): {e}")
                return jsonify({'success': False, 'error': f'Erro ao processar ficha técnica do item {product.get("name")}.'}), 500

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

        if invalid_items:
            return jsonify({'success': False, 'error': 'Existem itens inválidos no lançamento.', 'details': {'invalid_items': invalid_items}}), 400
        if invalid_category:
            return jsonify({'success': False, 'error': 'Existem itens fora da categoria Frigobar.', 'details': {'invalid_category': invalid_category}}), 400
        if missing_recipe:
            return jsonify({'success': False, 'error': 'Existem itens de frigobar sem ficha técnica de estoque.', 'details': {'missing_recipe': missing_recipe}}), 400
        if missing_ingredients:
            return jsonify({'success': False, 'error': 'Ficha técnica incompleta ou inválida para itens selecionados.', 'details': {'missing_ingredients': missing_ingredients}}), 400
        if not items_to_charge:
             return jsonify({'success': False, 'error': 'Nenhum item válido encontrado.'}), 400
        if not stock_movements:
            return jsonify({'success': False, 'error': 'Não foi possível gerar movimentos de estoque para os itens selecionados.'}), 400

        charge_id = f"CHARGE_GOV_{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        movement = apply_manual_stock_movement(
            room_number=room_num,
            triggered_by=session.get('user', 'Governança'),
            source='governance_launch_frigobar',
            movement_type='frigobar_sale',
            items=stock_movements,
            event_ref=charge_id,
            metadata={'invoice': 'Frigobar Governança'},
            allow_negative_stock=True
        )
        if not movement.get('success'):
            return jsonify({
                'success': False,
                'error': movement.get('error') or 'Falha ao registrar movimentação de estoque do frigobar.',
                'details': {
                    'warnings': movement.get('warnings', []),
                    'insufficient': movement.get('insufficient', [])
                }
            }), 400

        charge = {
            'id': charge_id,
            'room_number': room_num,
            'table_id': 'GOV', 
            'total': total,
            'items': items_to_charge,
            'service_fee': 0, 
            'discount': 0,
            'flags': [],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'status': 'pending',
            'type': 'minibar',
            'source': 'minibar'
        }

        try:
            room_charges.append(charge)
            save_room_charges(room_charges)
        except Exception as save_error:
            rollback_items = []
            for moved in (movement.get('applied_items') or []):
                try:
                    rollback_qty = abs(float(moved.get('qty') or 0))
                except Exception:
                    rollback_qty = 0
                if rollback_qty <= 0:
                    continue
                rollback_items.append({
                    'product_id': moved.get('product_id'),
                    'product_name': moved.get('product_name'),
                    'qty': rollback_qty
                })
            if rollback_items:
                apply_manual_stock_movement(
                    room_number=room_num,
                    triggered_by=session.get('user', 'Governança'),
                    source='governance_launch_frigobar.rollback',
                    movement_type='frigobar_sale_rollback',
                    items=rollback_items,
                    event_ref=charge_id,
                    metadata={'invoice': 'Rollback Frigobar Governança'}
                )
            current_app.logger.error(f"Erro ao salvar cobrança de frigobar, rollback executado: {save_error}")
            return jsonify({'success': False, 'error': 'Falha ao registrar cobrança de frigobar.'}), 500
        
        if items_added_names:
            log_msg = f"Lançamento de Frigobar no Quarto {room_num}: {', '.join(items_added_names)}"
            LoggerService.log_acao(
                acao='Frigobar Governança', 
                entidade='Governança',
                detalhes={'msg': log_msg},
                departamento_id='Governança',
                colaborador_id=session.get('user')
            )

        for warning in (movement.get('warnings') or []):
            current_app.logger.warning(f"Frigobar warning ({room_num}): {warning}")
            
        return jsonify({
            'success': True,
            'charge_id': charge_id,
            'warnings': movement.get('warnings', []),
            'stock_warning': bool(movement.get('warnings'))
        })
        
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
