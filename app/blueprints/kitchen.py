import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.utils.decorators import login_required
import uuid
from app.services.data_service import (
    load_products, load_settings, save_settings, load_stock_entries,
    save_stock_entry, save_stock_entries, load_stock_logs, save_stock_logs, STOCK_LOGS_FILE, STOCK_ENTRIES_FILE,
    load_table_orders, save_table_orders, load_menu_items, load_printers, secure_save_products,
    load_suppliers
)
from app.services.logger_service import LoggerService
from app.services.kitchen_checklist_service import KitchenChecklistService
from app.services.data_service import load_products, load_menu_items, secure_save_menu_items
from app.services.system_config_manager import get_data_path, PRODUCT_PHOTOS_DIR, PRODUCTS_FILE
from werkzeug.utils import secure_filename
from app.services.printing_service import get_default_printer, print_portion_labels
from app.utils.lock import file_lock

kitchen_bp = Blueprint('kitchen', __name__)


def _normalize_station(value):
    if not value:
        return None
    v = str(value).strip().lower()
    if v in ['cozinha', 'kitchen']:
        return 'kitchen'
    if v in ['bar', 'balcao']:
        return 'bar'
    return None


def _classify_section(category):
    if not category:
        return 'Outros'
    c = str(category).strip().lower()
    if 'sobremesa' in c or 'doce' in c or 'dessert' in c:
        return 'Sobremesas'
    if 'entrada' in c or 'petisco' in c or 'porção' in c or 'porcao' in c:
        return 'Entradas'
    return 'Pratos Principais'


def _compute_order_wait_bucket(wait_minutes):
    try:
        minutes = float(wait_minutes)
    except Exception:
        minutes = 0
    if minutes >= 20:
        return 'critical'
    if minutes >= 10:
        return 'warning'
    return 'normal'


def _extract_origin_supplier(entry):
    supplier = str(entry.get('origin_supplier') or '').strip()
    if supplier:
        return supplier
    invoice_text = str(entry.get('invoice') or '')
    supplier_match = re.search(r'Fornecedor:\s*([^|]+)', invoice_text)
    if supplier_match:
        return supplier_match.group(1).strip()
    return ''


def _compute_avg_prep_seconds(orders):
    durations = []
    for order in (orders or {}).values():
        items = order.get('items') or []
        for item in items:
            try:
                sec = int(item.get('kds_preparing_duration_sec') or 0)
            except Exception:
                sec = 0
            if sec > 0:
                durations.append(sec)
    if not durations:
        return 20 * 60
    return int(sum(durations) / len(durations))


def _emit_server_done_sound():
    try:
        import winsound
        winsound.Beep(1500, 140)
        winsound.Beep(1800, 160)
        return
    except Exception:
        pass
    try:
        print('\a', end='', flush=True)
    except Exception:
        pass


def _build_kds_payload(station, now=None):
    if now is None:
        now = datetime.now()
    orders = load_table_orders()
    menu_items = load_menu_items()
    menu_map = {str(p.get('id')): p for p in menu_items}
    
    # Load SLA Settings
    settings = load_settings()
    kds_sla = settings.get('kds_sla', {})
    
    printers = load_printers()
    printers_map = {str(p.get('id')): p for p in printers}
    default_kitchen = get_default_printer('kitchen')
    result_orders = []
    sections_counter = {}
    avg_prep_seconds = _compute_avg_prep_seconds(orders)
    changed = False
    for table_id, order in orders.items():
        status = str(order.get('status', '')).lower()
        if status not in ['open', 'aberta', 'aberto']:
            continue
        items = order.get('items') or []
        table_items = []
        opened_raw = order.get('opened_at') or order.get('created_at')
        try:
            opened_at = datetime.strptime(opened_raw, '%d/%m/%Y %H:%M') if opened_raw else now
        except Exception:
            opened_at = now
            
        # Order-level SLA tracking
        order_max_wait_minutes = 0
        order_has_late_item = False
        
        for item in items:
            cat = item.get('category') or ''
            cat_norm = unicodedata.normalize('NFKD', str(cat)).encode('ASCII', 'ignore').decode('utf-8').strip().lower()
            is_beverage = cat_norm in [
                'vinhos',
                'drinks',
                'sucos e aguas',
                'sucos e agua',
                'refrigerante',
                'refrigerantes',
                'cervejas',
                'cerveja',
                'frigobar',
                'doses',
                'bebidas',
                'bebida'
            ]
            
            # Filter by station
            item_printer_id = item.get('printer_id')
            should_show = False
            
            # Determine Section (Printer Name or Category)
            printer_name = 'Cozinha'
            if item_printer_id:
                p_obj = printers_map.get(str(item_printer_id))
                if p_obj:
                    printer_name = p_obj.get('name', 'Cozinha')
            
            # If item has no printer, fallback logic
            if not item_printer_id:
                if is_beverage:
                    printer_name = 'Bar'
                else:
                    printer_name = 'Cozinha'

            section_name = printer_name

            # Station Filtering Logic
            if station == 'kitchen':
                # Show everything NOT bar (unless mixed)
                if not is_beverage:
                    should_show = True
                # If explicit kitchen printer
                if item_printer_id and 'bar' not in printer_name.lower():
                    should_show = True
            elif station == 'bar':
                if is_beverage or (item_printer_id and 'bar' in printer_name.lower()):
                    should_show = True
            elif station == 'all':
                should_show = True
            else:
                # Custom station logic (by printer ID match?)
                # For simplicity, if station name is in printer name
                if station.lower() in printer_name.lower():
                    should_show = True

            if not should_show:
                continue
            
            kds_status = item.get('kds_status') or 'pending'
            if kds_status == 'archived':
                continue

            # Calculate Wait Time
            # If pending: time since created_at
            # If preparing: time since kds_start_time + pending time? No, usually total time since order.
            
            item_created_at = None
            try:
                item_created_at = datetime.strptime(item.get('created_at'), '%d/%m/%Y %H:%M')
            except:
                item_created_at = opened_at
            
            wait_seconds = (now - item_created_at).total_seconds()
            wait_minutes = int(wait_seconds / 60)
            
            # Check SLA
            # Default SLA 20 min if not found
            sla_minutes = kds_sla.get(item.get('category'), 20)
            is_late = wait_minutes > sla_minutes
            
            if is_late:
                order_has_late_item = True
            
            if wait_minutes > order_max_wait_minutes:
                order_max_wait_minutes = wait_minutes

            if section_name not in sections_counter:
                sections_counter[section_name] = 0
            if kds_status == 'pending':
                sections_counter[section_name] += 1
            
            # Prepare Item Display
            item['wait_minutes'] = wait_minutes
            item['sla_minutes'] = sla_minutes
            item['is_late'] = is_late
            item['section'] = section_name
            
            # Format Notes
            observations = item.get('observations') or []
            if isinstance(observations, list):
                notes_parts = [str(o) for o in observations if o]
            else:
                notes_parts = [str(observations)] if observations else []
            accompaniments = item.get('accompaniments') or []
            if accompaniments:
                acc_names = []
                for a in accompaniments:
                    if isinstance(a, dict):
                        a_name = a.get('name')
                        if a_name:
                            acc_names.append(str(a_name))
                    else:
                        acc_names.append(str(a))
                acc_str = ', '.join(acc_names)
                notes_parts.append(acc_str)
            questions = item.get('questions_answers') or []
            if isinstance(questions, dict):
                for q, ans in questions.items():
                    if ans:
                        notes_parts.append(str(ans))
            elif isinstance(questions, list):
                for qa in questions:
                    if isinstance(qa, dict):
                        q_text = qa.get('question')
                        ans = qa.get('answer')
                        if ans:
                            notes_parts.append(str(ans))
                    else:
                        notes_parts.append(str(qa))
            notes = ' / '.join(notes_parts)
            flavor_text = item.get('flavor') or item.get('flavor_name')
            if flavor_text:
                flavor_str = str(flavor_text).strip()
                if flavor_str:
                    if notes:
                        notes = f"Sabor: {flavor_str} / {notes}"
                    else:
                        notes = f"Sabor: {flavor_str}"
            
            item['display_notes'] = notes
            
            start_time = item.get('kds_start_time')
            done_time = item.get('kds_done_time')
            
            table_items.append({
                'id': item.get('id'),
                'name': item.get('name'),
                'qty': item.get('qty', 1),
                'category': cat,
                'section': section_name,
                'status': kds_status,
                'order_time': item_created_at.isoformat(),
                'start_time': start_time,
                'done_time': done_time,
                'notes': notes,
                'is_late': is_late,
                'wait_minutes': wait_minutes,
                'sla_minutes': sla_minutes, # Pass SLA to frontend
                'wait_bucket': _compute_order_wait_bucket(wait_minutes),
                'is_over_avg': is_late # Override generic avg with SLA logic
            })

        if not table_items:
            continue

        # Sort items by status priority: pending > preparing > done
        status_priority = {'pending': 0, 'preparing': 1, 'done': 2}
        table_items.sort(key=lambda x: (status_priority.get(x.get('status', 'pending'), 0), x.get('name')))

        # Determine overall order status
        pending_count = sum(1 for i in table_items if i.get('status') == 'pending')
        preparing_count = sum(1 for i in table_items if i.get('status') == 'preparing')
        done_count = sum(1 for i in table_items if i.get('status') == 'done')
        
        overall_status = 'pending'
        if done_count == len(table_items):
            overall_status = 'done'
        elif preparing_count > 0 or done_count > 0:
            overall_status = 'preparing'
        
        # New "Late" logic for order card
        order_late = order_has_late_item
        
        active_items = [i for i in table_items if i.get('status') != 'done']
        basis_items = active_items if active_items else table_items
        
        order_wait_minutes = order_max_wait_minutes
        wait_bucket = _compute_order_wait_bucket(order_max_wait_minutes)
        is_over_avg = order_late # Use late flag for order highlighting too
        
        sections = {}
        for i in table_items:
            key = i['section']
            if key not in sections:
                sections[key] = []
            sections[key].append(i)
        sections_list = []
        for name, items_list in sections.items():
            sections_list.append({
                'name': name,
                'pending': sum(1 for i in items_list if i['status'] == 'pending'),
                'preparing': sum(1 for i in items_list if i['status'] == 'preparing'),
                'done': sum(1 for i in items_list if i['status'] == 'done'),
                'items': items_list
            })
        label = order.get('label')
        if not label:
            tid_str = str(table_id)
            staff_name = order.get('staff_name')
            if 'FUNC_' in tid_str and staff_name:
                label = staff_name
            else:
                label = f"Mesa {table_id}"
        result_orders.append({
            'table_id': table_id,
            'label': label,
            'waiter': order.get('waiter') or '',
            'status': overall_status,
            'is_late': order_late,
            'opened_at': opened_at.isoformat(),
            'wait_minutes': order_wait_minutes,
            'wait_bucket': wait_bucket,
            'is_over_avg': is_over_avg,
            'sections': sections_list,
            'totals': {
                'pending': pending_count,
                'preparing': preparing_count,
                'done': done_count
            }
        })
    sections_summary = []
    for name, count in sections_counter.items():
        sections_summary.append({'name': name, 'pending': count})
    payload = {
        'station': station,
        'generated_at': now.isoformat(),
        'avg_prep_seconds': avg_prep_seconds,
        'avg_prep_minutes': max(1, int(round(avg_prep_seconds / 60.0))),
        'orders': result_orders,
        'sections_summary': sections_summary
    }
    if changed:
        save_table_orders(orders)
    return payload


@kitchen_bp.route('/kitchen/kds')
@login_required
def kitchen_kds():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    reset = request.args.get('reset')
    if reset:
        session.pop('kds_station', None)
    station = _normalize_station(request.args.get('station')) or session.get('kds_station')
    station = _normalize_station(station)
    if not station:
        return render_template('kitchen_kds_select.html')
    session['kds_station'] = station
    return render_template('kitchen_kds.html', station=station)


@kitchen_bp.route('/kitchen/kds/data')
@login_required
def kitchen_kds_data():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    station = _normalize_station(request.args.get('station')) or session.get('kds_station')
    station = _normalize_station(station) or 'kitchen'
    payload = _build_kds_payload(station)
    return jsonify({'success': True, 'data': payload})


@kitchen_bp.route('/kitchen/kds/update_status', methods=['POST'])
@login_required
def kitchen_kds_update_status():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    table_id = str(data.get('table_id') or '')
    item_id = str(data.get('item_id') or '')
    new_status = str(data.get('status') or '')
    if not table_id or not item_id or new_status not in ['pending', 'preparing', 'done', 'archived']:
        return jsonify({'success': False, 'error': 'Parâmetros inválidos.'}), 400
    orders = load_table_orders()
    order = orders.get(table_id)
    if not order:
        return jsonify({'success': False, 'error': 'Mesa não encontrada.'}), 404
    items = order.get('items') or []
    target = None
    for item in items:
        if str(item.get('id')) == item_id:
            target = item
            break
    if not target:
        return jsonify({'success': False, 'error': 'Item não encontrado.'}), 404
    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    old_status = target.get('kds_status') or 'pending'
    if new_status == 'pending':
        target['kds_status'] = 'pending'
        target.pop('kds_start_time', None)
        target.pop('kds_done_time', None)
    elif new_status == 'preparing':
        # Calcula tempo de espera até início do preparo
        # Salva em segundos desde created_at até agora
        try:
            created_at = datetime.strptime(target.get('created_at'), '%d/%m/%Y %H:%M')
        except Exception:
            created_at = datetime.now()
        wait_sec = max(0, int((datetime.now() - created_at).total_seconds()))
        target['kds_pending_duration_sec'] = wait_sec
        if target.get('kds_status') != 'preparing':
            target['kds_status'] = 'preparing'
            target['kds_start_time'] = now_str
            target.pop('kds_done_time', None)
    elif new_status == 'done':
        target['kds_status'] = 'done'
        if 'kds_start_time' not in target:
            target['kds_start_time'] = now_str
        target['kds_done_time'] = now_str
        # Calcula tempo de preparo entre start e done
        try:
            t_start = datetime.strptime(target.get('kds_start_time'), '%d/%m/%Y %H:%M')
        except Exception:
            t_start = datetime.now()
        prep_sec = max(0, int((datetime.now() - t_start).total_seconds()))
        target['kds_preparing_duration_sec'] = prep_sec
    elif new_status == 'archived':
        target['kds_status'] = 'archived'
        target['kds_archived_time'] = now_str
    save_table_orders(orders)
    LoggerService.log_acao(
        acao='KDS status atualizado',
        entidade='Cozinha',
        detalhes={
            'table_id': table_id,
            'item_id': item_id,
            'old_status': old_status,
            'new_status': new_status,
            'item_name': target.get('name'),
            'station': data.get('station') or _normalize_station(session.get('kds_station')) or 'kitchen'
        },
        nivel_severidade='INFO'
    )
    if new_status == 'done' and old_status != 'done':
        _emit_server_done_sound()
        LoggerService.log_acao(
            acao='KDS alerta sonoro finalizado',
            entidade='Cozinha',
            detalhes={
                'table_id': table_id,
                'item_id': item_id,
                'item_name': target.get('name')
            },
            nivel_severidade='INFO'
        )
    return jsonify({'success': True})


@kitchen_bp.route('/kitchen/kds/mark_received', methods=['POST'])
@login_required
def kitchen_kds_mark_received():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    table_id = str(data.get('table_id') or '')
    item_ids = data.get('item_ids') or []
    if not table_id or not item_ids:
        return jsonify({'success': False, 'error': 'Parâmetros inválidos.'}), 400
    item_ids = [str(i) for i in item_ids]
    orders = load_table_orders()
    order = orders.get(table_id)
    if not order:
        return jsonify({'success': False, 'error': 'Mesa não encontrada.'}), 404
    items = order.get('items') or []
    for item in items:
        if str(item.get('id')) in item_ids:
            item['kds_status'] = 'archived'
    save_table_orders(orders)
    LoggerService.log_acao(
        acao='KDS itens recebidos',
        entidade='Cozinha',
        detalhes={
            'table_id': table_id,
            'item_ids': item_ids,
            'items_count': len(item_ids)
        },
        nivel_severidade='INFO'
    )
    return jsonify({'success': True})

@kitchen_bp.route('/kitchen/portion/settings', methods=['GET', 'POST'])
@login_required
def kitchen_portion_settings():
    # Permissões: Supervisor, Gerente e Admin
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
         flash('Acesso restrito.')
         return redirect(url_for('main.service_page', service_id='cozinha'))

    settings = load_settings()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if 'portioning_rules' not in settings:
            settings['portioning_rules'] = []
            
        if 'product_portioning_rules' not in settings:
            settings['product_portioning_rules'] = []

        if action == 'add':
            origin_cat = request.form.get('origin_category')
            dest_cats = request.form.getlist('destination_categories')
            
            if origin_cat and dest_cats:
                settings['portioning_rules'].append({
                    'origin': origin_cat,
                    'destinations': dest_cats
                })
                flash('Regra de categoria adicionada com sucesso.')
            else:
                flash('Selecione uma categoria de origem e pelo menos uma de destino.')
                
        elif action == 'add_product_rule':
            origin_prod = request.form.get('origin_product')
            dest_prods = request.form.getlist('destination_products')
            
            if origin_prod and dest_prods:
                # Remove existing rule for this product if any to avoid duplicates/conflicts
                settings['product_portioning_rules'] = [r for r in settings['product_portioning_rules'] if r['origin'] != origin_prod]
                
                settings['product_portioning_rules'].append({
                    'origin': origin_prod,
                    'destinations': dest_prods
                })
                flash('Regra de produto adicionada com sucesso.')
            else:
                flash('Selecione um produto de origem e pelo menos um de destino.')

        elif action == 'delete':
            try:
                index = int(request.form.get('rule_index'))
                if 0 <= index < len(settings['portioning_rules']):
                    settings['portioning_rules'].pop(index)
                    flash('Regra de categoria removida.')
            except (ValueError, TypeError):
                flash('Erro ao remover regra.')
                
        elif action == 'delete_product_rule':
            try:
                index = int(request.form.get('rule_index'))
                if 0 <= index < len(settings['product_portioning_rules']):
                    settings['product_portioning_rules'].pop(index)
                    flash('Regra de produto removida.')
            except (ValueError, TypeError):
                flash('Erro ao remover regra.')
        elif action == 'update':
            try:
                index = int(request.form.get('rule_index'))
                origin_cat = request.form.get('origin_category')
                dest_cats = request.form.getlist('destination_categories')
                if 0 <= index < len(settings['portioning_rules']) and origin_cat and dest_cats:
                    old_rule = settings['portioning_rules'][index]
                    settings['portioning_rules'][index] = {
                        'origin': origin_cat,
                        'destinations': dest_cats
                    }
                    LoggerService.log_acao(
                        acao='Regra de categoria editada',
                        entidade='Cozinha',
                        detalhes={
                            'old_rule': old_rule,
                            'new_rule': settings['portioning_rules'][index],
                            'index': index
                        },
                        nivel_severidade='INFO'
                    )
                    flash('Regra de categoria atualizada com sucesso.')
                else:
                    flash('Dados inválidos para editar regra de categoria.')
            except (ValueError, TypeError):
                flash('Erro ao editar regra de categoria.')
        elif action == 'update_product_rule':
            try:
                index = int(request.form.get('rule_index'))
                origin_prod = request.form.get('origin_product')
                dest_prods = request.form.getlist('destination_products')
                if 0 <= index < len(settings['product_portioning_rules']) and origin_prod and dest_prods:
                    old_rule = settings['product_portioning_rules'][index]
                    settings['product_portioning_rules'][index] = {
                        'origin': origin_prod,
                        'destinations': dest_prods
                    }
                    LoggerService.log_acao(
                        acao='Regra de produto editada',
                        entidade='Cozinha',
                        detalhes={
                            'old_rule': old_rule,
                            'new_rule': settings['product_portioning_rules'][index],
                            'index': index
                        },
                        nivel_severidade='INFO'
                    )
                    flash('Regra de produto atualizada com sucesso.')
                else:
                    flash('Dados inválidos para editar regra de produto.')
            except (ValueError, TypeError):
                flash('Erro ao editar regra de produto.')
        
        save_settings(settings)
        return redirect(url_for('kitchen.kitchen_portion_settings'))

    products = load_products()
    products.sort(key=lambda x: x['name']) # Sort for dropdowns
    all_categories = sorted(list(set(p.get('category', 'Sem Categoria') for p in products if p.get('category'))))
    
    current_rules = settings.get('portioning_rules', [])
    product_rules = settings.get('product_portioning_rules', [])
    
    return render_template('portion_settings.html', 
                         categories=all_categories, 
                         products=products,
                         rules=current_rules,
                         product_rules=product_rules)

@kitchen_bp.route('/kitchen/portion', methods=['GET', 'POST'])
@login_required
def kitchen_portion():
    # Permissões: Admin, Gerente, Supervisor ou Cozinha
    if session.get('role') not in ['admin', 'gerente', 'supervisor'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))

    products = load_products()
    products.sort(key=lambda x: x['name'])

    settings = load_settings()
    rules = settings.get('portioning_rules', [])
    product_rules = settings.get('product_portioning_rules', [])
    
    # Map Origin Category -> List of Destination Categories
    rules_map = {}
    for r in rules:
        origin = r.get('origin')
        dests = r.get('destinations', [])
        if origin:
            if origin not in rules_map:
                rules_map[origin] = []
            # Merge and unique
            rules_map[origin] = list(set(rules_map[origin] + dests))
    
    # Map Origin Product -> List of Destination Products (Names)
    product_rules_map = {}
    for r in product_rules:
        origin = r.get('origin')
        dests = r.get('destinations', []) # List of product names
        if origin:
            product_rules_map[origin] = dests

    origin_categories = list(rules_map.keys())
    origin_products_with_rules = list(product_rules_map.keys())
    
    origin_products = [p for p in products if p.get('category') in rules_map or p['name'] in origin_products_with_rules]
    # Remove duplicates
    origin_products = list({p['name']: p for p in origin_products}.values())
    origin_products.sort(key=lambda x: x['name'])
    
    destination_products = products 
    suppliers_raw = load_suppliers()
    supplier_names = sorted(list({
        str(s.get('name', '')).strip()
        for s in suppliers_raw
        if isinstance(s, dict)
        and str(s.get('name', '')).strip()
        and bool(s.get('active', True))
    }))

    if request.method == 'POST':
        origin_name = request.form.get('origin_product')
        origin_supplier = str(request.form.get('origin_supplier') or '').strip()
        frozen_weight = request.form.get('frozen_weight')
        thawed_weight = request.form.get('thawed_weight')
        trim_weight = request.form.get('trim_weight')
        discard_weight = request.form.get('discard_weight')
        cooked_weight = request.form.get('cooked_weight')
        component_names = request.form.getlist('component_product[]')
        component_weights = request.form.getlist('component_weight[]')
        
        # New Multi-destination handling
        dest_names = request.form.getlist('dest_product[]')
        final_qties = request.form.getlist('final_qty[]')
        dest_counts = request.form.getlist('dest_count[]')

        if not all([origin_name, frozen_weight, thawed_weight, trim_weight, discard_weight]) or not dest_names:
            flash('Preencha todos os campos.')
            return redirect(url_for('kitchen.kitchen_portion'))
        if origin_supplier and origin_supplier not in supplier_names:
            flash('Fornecedor inválido. Selecione um fornecedor cadastrado.')
            return redirect(url_for('kitchen.kitchen_portion'))

        # Validate against Portioning Rules (Server-side enforcement)
        origin_prod_data = next((p for p in products if p['name'] == origin_name), None)
        if origin_prod_data:
            allowed_prods = product_rules_map.get(origin_name)
            allowed_cats = rules_map.get(origin_prod_data.get('category'))
            
            use_prod_filter = allowed_prods is not None and len(allowed_prods) > 0
            use_cat_filter = not use_prod_filter and allowed_cats is not None and len(allowed_cats) > 0
            
            for d_name in dest_names:
                if not d_name: continue
                
                is_valid = False
                if use_prod_filter:
                    if d_name in allowed_prods:
                        is_valid = True
                elif use_cat_filter:
                    dest_prod_data = next((p for p in products if p['name'] == d_name), None)
                    if dest_prod_data and dest_prod_data.get('category') in allowed_cats:
                        is_valid = True
                else:
                    # If no rules, allow all? Or restrict? 
                    # Assuming restrict if rules exist elsewhere, but if no rules for this product/cat, maybe allow all?
                    # The JS logic suggests filtering happens only if rules exist.
                    # If no rules apply to origin, then any destination is valid?
                    # Let's assume yes for now, or improve logic.
                    is_valid = True 
                
                if not is_valid:
                     flash(f'Erro: O destino "{d_name}" não é permitido para a origem "{origin_name}" segundo as regras.')
                     return redirect(url_for('kitchen.kitchen_portion'))

        try:
            frozen_weight_g = float(frozen_weight)
            thawed_weight_g = float(thawed_weight)
            trim_weight_g = float(trim_weight)
            discard_weight_g = float(discard_weight)
            cooked_weight_g = float(cooked_weight) if cooked_weight else 0.0
            
            frozen_weight_kg = frozen_weight_g / 1000.0
            thawed_weight_kg = thawed_weight_g / 1000.0
            trim_weight_kg = trim_weight_g / 1000.0
            discard_weight_kg = discard_weight_g / 1000.0
            cooked_weight_kg = cooked_weight_g / 1000.0
            
            parsed_destinations = []
            total_output_weight_g = 0
            
            for i in range(len(dest_names)):
                d_name = dest_names[i]
                if i < len(final_qties):
                    d_qty_g = float(final_qties[i]) if final_qties[i] else 0.0
                else:
                    d_qty_g = 0.0
                    
                if i < len(dest_counts) and dest_counts[i]:
                    try:
                        d_count = float(dest_counts[i])
                    except ValueError:
                        d_count = 1.0
                else:
                    d_count = 1.0
                
                if d_name and d_name.strip() and d_qty_g > 0:
                    d_qty_kg = d_qty_g / 1000.0
                    parsed_destinations.append({
                        'name': d_name, 
                        'qty_kg': d_qty_kg, 
                        'qty_g': d_qty_g,
                        'count': d_count
                    })
                    total_output_weight_g += d_qty_g

            total_output_weight_kg = total_output_weight_g / 1000.0

        except ValueError:
            flash('Valores numéricos inválidos.')
            return redirect(url_for('kitchen.kitchen_portion'))

        if frozen_weight_g <= 0 or total_output_weight_g <= 0:
            flash('Quantidades de entrada e saída devem ser positivas.')
            return redirect(url_for('kitchen.kitchen_portion'))
        if thawed_weight_g > frozen_weight_g:
            flash('Peso descongelado não pode ser maior que o peso congelado.')
            return redirect(url_for('kitchen.kitchen_portion'))
        if thawed_weight_g < (trim_weight_g + discard_weight_g):
            flash('A soma de aparas e descarte não pode ser maior que o peso descongelado.')
            return redirect(url_for('kitchen.kitchen_portion'))
        if cooked_weight_g > 0 and cooked_weight_g > (thawed_weight_g - trim_weight_g - discard_weight_g):
            flash('Peso cozido não pode ser maior que o peso limpo após aparas e descarte.')
            return redirect(url_for('kitchen.kitchen_portion'))

        # Build optional multi-origin components
        components = []
        for i in range(len(component_names)):
            name = component_names[i].strip() if i < len(component_names) and component_names[i] else ''
            weight_str = component_weights[i] if i < len(component_weights) else ''
            if not name and not weight_str:
                continue
            try:
                weight_g = float(weight_str)
            except (TypeError, ValueError):
                weight_g = 0.0
            if name and weight_g > 0:
                components.append({'name': name, 'weight_g': weight_g})

        # Get product details for pricing
        origin_prod = next((p for p in products if p['name'] == origin_name), None)

        # Calculate Losses
        thaw_loss_kg = frozen_weight_kg - thawed_weight_kg
        trim_loss_kg = trim_weight_kg
        
        cooking_loss_kg = 0.0
        if cooked_weight_kg > 0:
            clean_weight_kg = thawed_weight_kg - trim_weight_kg - discard_weight_kg
            cooking_loss_kg = max(0.0, clean_weight_kg - cooked_weight_kg)

        labels = []

        # 1. Register Exit for Origin Product(s)
        total_origin_cost = 0
        
        supplier_info = f"Fornecedor: {origin_supplier}" if origin_supplier else "Fornecedor: Não informado"
        loss_info = f"Degelo: {thaw_loss_kg:.3f}kg | Aparas: {trim_loss_kg:.3f}kg | Descarte: {discard_weight_kg:.3f}kg"
        if cooking_loss_kg > 0:
            loss_info += f" | Cocção: {cooking_loss_kg:.3f}kg"

        average_origin_cost_per_kg = 0.0
        if components:
            for comp in components:
                comp_prod = next((p for p in products if p['name'] == comp['name']), None)
                comp_weight_kg = comp['weight_g'] / 1000.0
                price = float(comp_prod.get('price', 0)) if comp_prod and comp_prod.get('price') else 0
                total_origin_cost += comp_weight_kg * price

                exit_entry = {
                    'id': datetime.now().strftime('%Y%m%d%H%M%S') + f"_PORT_OUT_{comp['name']}",
                    'user': session['user'],
                    'product': comp['name'],
                    'supplier': "PORCIONAMENTO (SAÍDA)",
                    'qty': -comp_weight_kg,
                    'price': price,
                    'invoice': f"{supplier_info} | Transf: {', '.join([d['name'] for d in parsed_destinations])} | {loss_info}",
                    'origin_supplier': origin_supplier,
                    'date': datetime.now().strftime('%d/%m/%Y'),
                    'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                }
                save_stock_entry(exit_entry)
            if frozen_weight_kg > 0:
                average_origin_cost_per_kg = total_origin_cost / frozen_weight_kg
        else:
            origin_price = float(origin_prod.get('price', 0) or 0) if origin_prod else 0.0
            exit_entry = {
                'id': datetime.now().strftime('%Y%m%d%H%M%S') + "_PORT_OUT",
                'user': session['user'],
                'product': origin_name,
                'supplier': "PORCIONAMENTO (SAÍDA)",
                'qty': -frozen_weight_kg,
                'price': origin_price,
                'invoice': f"{supplier_info} | Transf: {', '.join([d['name'] for d in parsed_destinations])} | {loss_info}",
                'origin_supplier': origin_supplier,
                'date': datetime.now().strftime('%d/%m/%Y'),
                'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
            save_stock_entry(exit_entry)

            total_origin_cost = frozen_weight_kg * origin_price
            average_origin_cost_per_kg = origin_price

        aparas_return_cost = trim_weight_kg * average_origin_cost_per_kg
        total_portion_cost = max(0.0, total_origin_cost - aparas_return_cost)

        if trim_weight_kg > 0:
            trim_return_entry = {
                'id': datetime.now().strftime('%Y%m%d%H%M%S') + "_PORT_TRIM_RETURN",
                'user': session['user'],
                'product': origin_name,
                'supplier': "PORCIONAMENTO (RETORNO APARAS)",
                'qty': trim_weight_kg,
                'price': average_origin_cost_per_kg,
                'invoice': f"{supplier_info} | Retorno de aparas ao bruto | Origem: {origin_name} | Aparas: {trim_weight_kg:.3f}kg",
                'origin_supplier': origin_supplier,
                'date': datetime.now().strftime('%d/%m/%Y'),
                'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
            save_stock_entry(trim_return_entry)
        
        for dest in parsed_destinations:
            allocation_ratio = dest['qty_kg'] / total_output_weight_kg if total_output_weight_kg > 0 else 0
            total_dest_cost = total_portion_cost * allocation_ratio

            final_qty = dest['count']
            final_price = total_dest_cost / final_qty if final_qty > 0 else 0
            dest['final_price'] = final_price
            
            entry_entry = {
                'id': datetime.now().strftime('%Y%m%d%H%M%S') + f"_PORT_IN_{dest['name']}",
                'user': session['user'],
                'product': dest['name'],
                'supplier': "PORCIONAMENTO (ENTRADA)",
                'qty': final_qty,
                'price': final_price,
                'invoice': f"{supplier_info} | Origem: {origin_name} | Qtd: {dest['count']} | Rateio Custo: {((dest['qty_kg']/total_output_weight_kg)*100):.1f}% | Méd: {(dest['qty_g']/dest['count']):.1f}g",
                'origin_supplier': origin_supplier,
                'date': datetime.now().strftime('%d/%m/%Y'),
                'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
            save_stock_entry(entry_entry)

            avg_weight = None
            if dest['count'] > 0:
                avg_g = dest['qty_g'] / dest['count']
                avg_weight = f"{avg_g:.0f} g"
            else:
                avg_weight = f"{dest['qty_g']:.0f} g"

            label_data = {
                'name': dest['name'],
                'avg_weight': avg_weight,
                'date': datetime.now().strftime('%d/%m/%Y'),
                'expiry': (datetime.now() + timedelta(days=90)).strftime('%d/%m/%Y'),
                'user': session.get('user', '')
            }

            copies = int(dest['count']) if dest['count'] and dest['count'] > 0 else 1
            for _ in range(copies):
                labels.append(label_data)

        updated_products = []
        try:
            with file_lock(PRODUCTS_FILE):
                current_products = load_products()
                for dest in parsed_destinations:
                    dest_name = dest.get('name')
                    dest_price = float(dest.get('final_price', 0) or 0)
                    product_data = next((p for p in current_products if p.get('name') == dest_name), None)
                    if not product_data:
                        continue
                    old_price = float(product_data.get('price', 0) or 0)
                    if abs(old_price - dest_price) < 0.000001:
                        continue
                    product_data['price'] = round(dest_price, 6)
                    updated_products.append({
                        'product': dest_name,
                        'old_price': old_price,
                        'new_price': round(dest_price, 6)
                    })
                if updated_products:
                    secure_save_products(current_products, user_id=session.get('user', 'Sistema'))
                    LoggerService.log_acao(
                        acao='Preço unitário atualizado por porcionamento',
                        entidade='Estoque',
                        detalhes={
                            'origin_product': origin_name,
                            'updated_products': updated_products
                        },
                        nivel_severidade='INFO'
                    )
        except Exception as e:
            LoggerService.log_acao(
                acao='Falha ao atualizar preço unitário no porcionamento',
                entidade='Estoque',
                detalhes={'origin_product': origin_name, 'erro': str(e)},
                nivel_severidade='ERRO'
            )
            flash('Porcionamento salvo, mas houve falha ao atualizar preço unitário dos produtos.')

        if labels:
            try:
                print_portion_labels(labels)
            except Exception as e:
                print(f"Error printing portion labels: {e}")

        flash(f'Porcionamento realizado com sucesso! Rendimento Global: {((total_output_weight_kg/frozen_weight_kg)*100):.1f}%')
        return redirect(url_for('main.service_page', service_id='cozinha'))

    return render_template('portion_item.html', origin_products=origin_products, destination_products=destination_products, rules_map=rules_map, product_rules_map=product_rules_map, usage_ranking={}, suppliers=supplier_names)

@kitchen_bp.route('/kitchen/reports', methods=['GET', 'POST'])
@login_required
def kitchen_reports():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
         flash('Acesso não autorizado.')
         return redirect(url_for('main.service_page', service_id='cozinha'))

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    product_filters = request.args.getlist('products[]') or request.args.getlist('products')
    staff_filters = request.args.getlist('staff[]') or request.args.getlist('staff')
    supplier_filters = request.args.getlist('suppliers[]') or request.args.getlist('suppliers')
    supplier_missing_only = str(request.args.get('supplier_missing_only', '')).lower() in ['1', 'true', 'on', 'yes']
    page = int(request.args.get('page', 1))
    per_page = 20
    
    products = load_products()
    all_products = products
    
    d_start = datetime.min
    d_end = datetime.max
    
    if start_date:
        try:
            d_start = datetime.strptime(start_date, '%d/%m/%Y')
        except ValueError:
            pass
            
    if end_date:
        try:
            d_end = datetime.strptime(end_date, '%d/%m/%Y')
            d_end = d_end.replace(hour=23, minute=59, second=59)
        except ValueError:
            pass
            
    entries = load_stock_entries()
    
    filtered_data = []
    staff_set = set()
    supplier_set = {'Não informado'}
    
    for entry in entries:
        if not ("_PORT_OUT" in entry['id'] or "PORCIONAMENTO (SAÍDA)" in str(entry.get('supplier', ''))):
            continue
            
        try:
            e_date = datetime.strptime(entry.get('entry_date', entry['date']), '%d/%m/%Y %H:%M')
        except (ValueError, TypeError):
             try:
                 e_date = datetime.strptime(entry['date'], '%d/%m/%Y')
             except ValueError:
                 continue
                 
        if not (d_start <= e_date <= d_end):
            continue
            
        if product_filters and entry['product'] not in product_filters:
            continue

        staff_name = entry.get('user', 'N/A')
        if staff_name:
            staff_set.add(staff_name)
        if staff_filters and staff_name not in staff_filters:
            continue

        supplier_name = _extract_origin_supplier(entry)
        supplier_display = supplier_name if supplier_name else 'Não informado'
        supplier_set.add(supplier_display)
        if supplier_missing_only and supplier_display != 'Não informado':
            continue
        if supplier_filters and supplier_display not in supplier_filters:
            continue

        invoice_text = entry.get('invoice', '')
        degelo = 0.0
        aparas = 0.0
        descarte = 0.0
        cooking_loss = 0.0
        
        degelo_match = re.search(r'Degelo:\s*([\d\.]+)kg', invoice_text)
        if degelo_match:
            degelo = float(degelo_match.group(1))
            
        aparas_match = re.search(r'Aparas:\s*([\d\.]+)kg', invoice_text)
        if aparas_match:
            aparas = float(aparas_match.group(1))

        descarte_match = re.search(r'Descarte:\s*([\d\.]+)kg', invoice_text)
        if descarte_match:
            descarte = float(descarte_match.group(1))
            
        cooking_match = re.search(r'Cocção:\s*([\d\.]+)kg', invoice_text)
        if cooking_match:
            cooking_loss = float(cooking_match.group(1))
        
        input_weight_kg = abs(float(entry['qty']))

        useful_weight_kg = input_weight_kg - degelo - aparas - descarte - cooking_loss
        degelo_percent = (degelo / input_weight_kg * 100) if input_weight_kg > 0 else 0
        waste_percent = ((degelo + descarte + cooking_loss) / input_weight_kg * 100) if input_weight_kg > 0 else 0
        yield_percent = (useful_weight_kg / input_weight_kg * 100) if input_weight_kg > 0 else 0

        total_cost_bruto = input_weight_kg * float(entry.get('price', 0))
        batch_prefix = str(entry.get('id', '')).split('_PORT_')[0]
        related_aparas_return_entries = [
            e for e in entries
            if str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_TRIM_RETURN")
            or (
                str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_")
                and "PORCIONAMENTO (RETORNO APARAS)" in str(e.get('supplier', ''))
            )
        ]
        aparas_return_cost = 0.0
        for return_entry in related_aparas_return_entries:
            try:
                return_qty = abs(float(return_entry.get('qty', 0) or 0))
                return_price = float(return_entry.get('price', 0) or 0)
                aparas_return_cost += (return_qty * return_price)
            except (TypeError, ValueError):
                continue
        total_cost = max(0.0, total_cost_bruto - aparas_return_cost)
        cost_per_useful_kg = (total_cost / useful_weight_kg) if useful_weight_kg > 0 else 0.0
        related_portioned_entries = [
            e for e in entries
            if str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_IN_")
            and "PORCIONAMENTO (ENTRADA)" in str(e.get('supplier', ''))
        ]
        portioned_items = []
        for related_entry in related_portioned_entries:
            product_name = str(related_entry.get('product', '')).strip()
            if not product_name:
                continue
            try:
                unit_price = float(related_entry.get('price', 0) or 0)
            except (TypeError, ValueError):
                unit_price = 0.0
            portioned_items.append({
                'product': product_name,
                'unit_price': unit_price
            })
        portioned_items.sort(key=lambda x: x['product'])
        portioned_items_unit_prices = ' | '.join(
            f"{item['product']}: R$ {item['unit_price']:.2f}" for item in portioned_items
        ) if portioned_items else '-'
        
        filtered_data.append({
            'id': entry['id'],
            'date_obj': e_date,
            'date': e_date.strftime('%d/%m/%Y %H:%M'),
            'product': entry['product'],
            'qty_kg': input_weight_kg,
            'staff': staff_name,
            'supplier': supplier_display,
            'price_gross': float(entry.get('price', 0)),
            'ice_loss_pct': degelo_percent,
            'waste_pct': waste_percent,
            'yield_pct': yield_percent,
            'degelo_kg': degelo,
            'aparas_kg': aparas,
            'descarte_kg': descarte,
            'cooking_loss_kg': cooking_loss,
            'useful_kg': useful_weight_kg,
            'total_cost_liquid': total_cost,
            'cost_per_useful_kg': cost_per_useful_kg,
            'portioned_items_unit_prices': portioned_items_unit_prices,
            'details': invoice_text
        })
        
    # Sort by date desc
    filtered_data.sort(key=lambda x: x['date_obj'], reverse=True)
    
    stats = {
        'total_kg': sum(d['qty_kg'] for d in filtered_data),
        'total_value': sum(d['total_cost_liquid'] for d in filtered_data),
        'count': len(filtered_data),
        'avg_yield_pct': (sum(d['yield_pct'] for d in filtered_data) / len(filtered_data)) if filtered_data else 0.0,
        'avg_waste_pct': (sum(d['waste_pct'] for d in filtered_data) / len(filtered_data)) if filtered_data else 0.0
    }
    
    total_items = len(filtered_data)
    total_pages = (total_items + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_data = filtered_data[start_idx:end_idx]
    
    return render_template('kitchen_reports.html',
                         data=paginated_data,
                         stats=stats,
                         page=page,
                         total_pages=total_pages,
                         all_products=all_products,
                         start_date=start_date,
                         end_date=end_date,
                         selected_products=product_filters,
                         staff_options=sorted(staff_set),
                         selected_staff=staff_filters,
                         supplier_options=sorted(supplier_set),
                         selected_suppliers=supplier_filters,
                         selected_supplier_missing_only=supplier_missing_only)

@kitchen_bp.route('/kitchen/reports/export')
@login_required
def kitchen_reports_export():
    import csv
    import io
    from flask import make_response
    
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    product_filters = request.args.getlist('products[]') or request.args.getlist('products')
    staff_filters = request.args.getlist('staff[]') or request.args.getlist('staff')
    supplier_filters = request.args.getlist('suppliers[]') or request.args.getlist('suppliers')
    supplier_missing_only = str(request.args.get('supplier_missing_only', '')).lower() in ['1', 'true', 'on', 'yes']
    fmt = request.args.get('format', 'csv')
    
    entries = load_stock_entries()
    d_start = datetime.min
    d_end = datetime.max
    if start_date: 
        try: d_start = datetime.strptime(start_date, '%d/%m/%Y')
        except: pass
    if end_date:
        try: 
            d_end = datetime.strptime(end_date, '%d/%m/%Y')
            d_end = d_end.replace(hour=23, minute=59, second=59)
        except: pass
        
    filtered_data = []
    for entry in entries:
        if not ("_PORT_OUT" in entry['id'] or "PORCIONAMENTO (SAÍDA)" in str(entry.get('supplier', ''))): continue
        try: e_date = datetime.strptime(entry.get('entry_date', entry['date']), '%d/%m/%Y %H:%M')
        except: 
             try: e_date = datetime.strptime(entry['date'], '%d/%m/%Y')
             except: continue
        if not (d_start <= e_date <= d_end): continue
        if product_filters and entry['product'] not in product_filters:
            continue

        staff_name = entry.get('user', 'N/A')
        if staff_filters and staff_name not in staff_filters:
            continue
        supplier_name = _extract_origin_supplier(entry)
        supplier_display = supplier_name if supplier_name else 'Não informado'
        if supplier_missing_only and supplier_display != 'Não informado':
            continue
        if supplier_filters and supplier_display not in supplier_filters:
            continue

        invoice_text = entry.get('invoice', '')
        degelo = 0.0
        aparas = 0.0
        descarte = 0.0
        cooking_loss = 0.0

        degelo_match = re.search(r'Degelo:\s*([\d\.]+)kg', invoice_text)
        if degelo_match:
            degelo = float(degelo_match.group(1))

        aparas_match = re.search(r'Aparas:\s*([\d\.]+)kg', invoice_text)
        if aparas_match:
            aparas = float(aparas_match.group(1))

        descarte_match = re.search(r'Descarte:\s*([\d\.]+)kg', invoice_text)
        if descarte_match:
            descarte = float(descarte_match.group(1))

        cooking_match = re.search(r'Cocção:\s*([\d\.]+)kg', invoice_text)
        if cooking_match:
            cooking_loss = float(cooking_match.group(1))

        input_weight_kg = abs(float(entry['qty']))
        useful_kg = input_weight_kg - degelo - aparas - descarte - cooking_loss

        degelo_percent = (degelo / input_weight_kg * 100) if input_weight_kg > 0 else 0
        waste_percent = ((degelo + descarte + cooking_loss) / input_weight_kg * 100) if input_weight_kg > 0 else 0
        yield_percent = (useful_kg / input_weight_kg * 100) if input_weight_kg > 0 else 0

        total_cost_bruto = input_weight_kg * float(entry.get('price', 0))
        batch_prefix = str(entry.get('id', '')).split('_PORT_')[0]
        related_aparas_return_entries = [
            e for e in entries
            if str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_TRIM_RETURN")
            or (
                str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_")
                and "PORCIONAMENTO (RETORNO APARAS)" in str(e.get('supplier', ''))
            )
        ]
        aparas_return_cost = 0.0
        for return_entry in related_aparas_return_entries:
            try:
                return_qty = abs(float(return_entry.get('qty', 0) or 0))
                return_price = float(return_entry.get('price', 0) or 0)
                aparas_return_cost += (return_qty * return_price)
            except (TypeError, ValueError):
                continue
        total_cost = max(0.0, total_cost_bruto - aparas_return_cost)
        cost_per_useful_kg = (total_cost / useful_kg) if useful_kg > 0 else 0.0
        related_portioned_entries = [
            e for e in entries
            if str(e.get('id', '')).startswith(f"{batch_prefix}_PORT_IN_")
            and "PORCIONAMENTO (ENTRADA)" in str(e.get('supplier', ''))
        ]
        portioned_items = []
        for related_entry in related_portioned_entries:
            product_name = str(related_entry.get('product', '')).strip()
            if not product_name:
                continue
            try:
                unit_price = float(related_entry.get('price', 0) or 0)
            except (TypeError, ValueError):
                unit_price = 0.0
            portioned_items.append({
                'product': product_name,
                'unit_price': unit_price
            })
        portioned_items.sort(key=lambda x: x['product'])
        portioned_items_unit_prices = ' | '.join(
            f"{item['product']}: R$ {item['unit_price']:.2f}" for item in portioned_items
        ) if portioned_items else '-'

        filtered_data.append({
            'date': e_date.strftime('%d/%m/%Y %H:%M'),
            'product': entry['product'],
            'qty_kg': input_weight_kg,
            'staff': staff_name,
            'supplier': supplier_display,
            'price_gross': float(entry.get('price', 0)),
            'ice_loss_pct': degelo_percent,
            'waste_pct': waste_percent,
            'yield_pct': yield_percent,
            'degelo_kg': degelo,
            'aparas_kg': aparas,
            'descarte_kg': descarte,
            'cooking_loss_kg': cooking_loss,
            'useful_kg': useful_kg,
            'total_cost': total_cost,
            'cost_per_useful_kg': cost_per_useful_kg,
            'portioned_items_unit_prices': portioned_items_unit_prices
        })
    
    if fmt == 'csv':
        si = io.StringIO()
        cw = csv.writer(si, delimiter=';') # Excel friendly
        cw.writerow([
            'Data/Hora',
            'Produto',
            'Qtd Bruta (Kg)',
            'Kg Degelo',
            'Kg Aparas',
            'Kg Descarte',
            'Kg Cocção',
            'Kg Útil',
            'Rendimento %',
            'Perda Total %',
            'Funcionario',
            'Fornecedor',
            'Preco Bruto/Kg',
            'Perda Gelo %',
            'Custo/ Kg Útil',
            'Custo Total',
            'Preço Unitário Final (Itens Porcionados)'
        ])
        for row in filtered_data:
            cw.writerow([
                row['date'],
                row['product'],
                f"{row['qty_kg']:.3f}".replace('.', ','),
                f"{row['degelo_kg']:.3f}".replace('.', ','),
                f"{row['aparas_kg']:.3f}".replace('.', ','),
                f"{row['descarte_kg']:.3f}".replace('.', ','),
                f"{row['cooking_loss_kg']:.3f}".replace('.', ','),
                f"{row['useful_kg']:.3f}".replace('.', ','),
                f"{row['yield_pct']:.1f}".replace('.', ','),
                f"{row['waste_pct']:.1f}".replace('.', ','),
                row['staff'],
                row['supplier'],
                f"{row['price_gross']:.2f}".replace('.', ','),
                f"{row['ice_loss_pct']:.1f}".replace('.', ','),
                f"{row['cost_per_useful_kg']:.2f}".replace('.', ','),
                f"{row['total_cost']:.2f}".replace('.', ','),
                row['portioned_items_unit_prices']
            ])
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=relatorio_porcionamento_{datetime.now().strftime('%Y%m%d')}.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    else:
        # PDF Fallback or implementation
        # For simplicity in this environment, return CSV or a simple HTML print view?
        # User requested PDF. I'll generate a simple HTML page that auto-prints.
        return render_template('kitchen_reports_print.html', data=filtered_data, date=datetime.now().strftime('%d/%m/%Y'))

@kitchen_bp.route('/kitchen/low-stock/ack', methods=['POST'])
@login_required
def acknowledge_low_stock():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso não autorizado.')
        return redirect(url_for('kitchen.kitchen_reports'))
    
    product_name = request.form.get('product')
    if not product_name:
        flash('Produto inválido.')
        return redirect(url_for('kitchen.kitchen_reports'))
    
    logs = load_stock_logs()
    ack_until = datetime.now() + timedelta(days=3)
    ack_until_str = ack_until.strftime('%d/%m/%Y %H:%M')
    updated = False
    
    for entry in logs:
        if entry.get('action') == 'Estoque Baixo' and entry.get('department') == 'Cozinha' and entry.get('product') == product_name:
            entry['ack_until'] = ack_until_str
            updated = True
    
    if updated:
        try:
            save_stock_logs(logs)
            flash(f'Aviso de estoque baixo para {product_name} marcado como ciente por 3 dias.')
        except Exception:
            flash('Erro ao atualizar avisos de estoque.')
    else:
        flash('Nenhum aviso de estoque baixo encontrado para este produto.')
    
    return redirect(url_for('kitchen.kitchen_reports'))

@kitchen_bp.route('/kitchen/reports/delete/<entry_id>', methods=['POST'])
@login_required
def delete_portion_entry(entry_id):
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso não autorizado.')
        return redirect(url_for('kitchen.kitchen_reports'))
    
    entries = load_stock_entries()
    
    try:
        timestamp_prefix = entry_id.split('_')[0]
        if len(timestamp_prefix) != 14: 
            raise ValueError("Invalid ID format")
            
        related_entries = [e for e in entries if e['id'].startswith(timestamp_prefix + '_PORT_')]
        
        if not related_entries:
            flash('Registro não encontrado.')
            return redirect(url_for('kitchen.kitchen_reports'))

        initial_count = len(entries)
        entries = [e for e in entries if not e['id'].startswith(timestamp_prefix + '_PORT_')]
        final_count = len(entries)
        
        deleted_count = initial_count - final_count
        
        if deleted_count > 0:
            save_stock_entries(entries)
            flash(f'Porcionamento excluído com sucesso ({deleted_count} registros removidos).')
        else:
            flash('Nenhum registro removido.')

    except Exception as e:
        print(f"Error deleting portion: {e}")
        flash('Erro ao excluir porcionamento.')
        
    return redirect(url_for('kitchen.kitchen_reports'))

# --- Kitchen Checklist Routes ---

def _kitchen_checklist_access_allowed():
    return session.get('role') in ['admin', 'gerente'] or session.get('department') == 'Cozinha'


@kitchen_bp.route('/kitchen/checklist')
@login_required
def kitchen_checklist_manage():
    if not _kitchen_checklist_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    overview = KitchenChecklistService.get_overview()
    period_summary = KitchenChecklistService.build_period_summary(start_date=start_date, end_date=end_date)
    return render_template(
        'kitchen_checklist_manage.html',
        lists=overview.get('lists', []),
        templates=overview.get('templates', []),
        shopping_lists=overview.get('shopping_lists', []),
        history=period_summary.get('rows', []),
        dashboard=overview.get('dashboard', {}),
        period_summary=period_summary,
        executions=overview.get('executions', []),
        insumos=overview.get('insumos', []),
        active_tab=request.args.get('tab') or 'minhas-listas',
    )


@kitchen_bp.route('/kitchen/checklist/create', methods=['GET', 'POST'])
@login_required
def kitchen_checklist_create():
    if not _kitchen_checklist_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        list_type = request.form.get('type') or 'conferencia'
        item_names = request.form.getlist('item_name[]')
        item_units = request.form.getlist('item_unit[]')
        items = []
        for i, item_name in enumerate(item_names):
            if (item_name or '').strip():
                items.append({
                    'id': str(uuid.uuid4()),
                    'name': item_name.strip(),
                    'unit': item_units[i] if i < len(item_units) else ''
                })
        created = KitchenChecklistService.create_list(
            name=name,
            list_type=list_type,
            items=items,
            responsible=(request.form.get('responsible') or '').strip(),
            periodicity=request.form.get('periodicity') or 'sob_demanda',
            base_template_id=request.form.get('base_template_id') or None,
            user=session.get('user') or 'Sistema',
        )
        if created:
            flash('Lista criada com sucesso.')
            return redirect(url_for('kitchen.kitchen_checklist_manage'))
        flash('Preencha nome, tipo e pelo menos um item.')
    return redirect(url_for('kitchen.kitchen_checklist_manage', tab='minhas-listas'))


@kitchen_bp.route('/kitchen/checklist/edit/<list_id>', methods=['GET', 'POST'])
@login_required
def kitchen_checklist_edit(list_id):
    if not _kitchen_checklist_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    target_list = KitchenChecklistService.get_list(list_id)
    if not target_list:
        flash('Lista não encontrada.')
        return redirect(url_for('kitchen.kitchen_checklist_manage'))
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        list_type = request.form.get('type') or target_list.get('list_type', 'conferencia')
        item_names = request.form.getlist('item_name[]')
        item_units = request.form.getlist('item_unit[]')
        items = []
        for i, item_name in enumerate(item_names):
            if (item_name or '').strip():
                items.append({
                    'id': str(uuid.uuid4()),
                    'name': item_name.strip(),
                    'unit': item_units[i] if i < len(item_units) else ''
                })
        updated = KitchenChecklistService.update_list(list_id, {
                'name': name,
                'list_type': list_type,
                'base_template_id': request.form.get('base_template_id') or target_list.get('base_template_id'),
                'responsible': request.form.get('responsible') or target_list.get('responsible', ''),
                'periodicity': request.form.get('periodicity') or target_list.get('periodicity', 'sob_demanda'),
                'items': items
            }, user=session.get('user') or 'Sistema')
        if updated:
            flash('Lista atualizada com sucesso.')
            return redirect(url_for('kitchen.kitchen_checklist_manage'))
        flash('Preencha nome, tipo e pelo menos um item.')
    return redirect(url_for('kitchen.kitchen_checklist_manage', tab='minhas-listas'))


@kitchen_bp.route('/kitchen/checklist/delete/<list_id>', methods=['POST'])
@login_required
def kitchen_checklist_delete(list_id):
    if not _kitchen_checklist_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    if KitchenChecklistService.delete_list(list_id):
        flash('Lista removida.')
    else:
        flash('Erro ao remover lista.')
    return redirect(url_for('kitchen.kitchen_checklist_manage'))


@kitchen_bp.route('/kitchen/checklist/use/<list_id>')
@login_required
def kitchen_checklist_use(list_id):
    if not _kitchen_checklist_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    target_list = KitchenChecklistService.get_list(list_id)
    if not target_list:
        flash('Lista não encontrada.')
        return redirect(url_for('kitchen.kitchen_checklist_manage'))
    return redirect(url_for('kitchen.kitchen_checklist_manage', tab='pendentes-hoje', use=list_id))


@kitchen_bp.route('/api/kitchen/checklist/overview')
@login_required
def kitchen_checklist_overview_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    return jsonify({'success': True, 'data': KitchenChecklistService.get_overview()})


@kitchen_bp.route('/api/kitchen/checklist/list', methods=['POST'])
@login_required
def kitchen_checklist_create_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    created = KitchenChecklistService.create_list(
        name=payload.get('name'),
        list_type=payload.get('list_type'),
        items=payload.get('items') or [],
        responsible=payload.get('responsible') or '',
        periodicity=payload.get('periodicity') or 'sob_demanda',
        base_template_id=payload.get('base_template_id'),
        user=session.get('user') or 'Sistema',
    )
    if not created:
        return jsonify({'success': False, 'error': 'Dados inválidos para criar lista.'}), 400
    return jsonify({'success': True, 'data': created})


@kitchen_bp.route('/api/kitchen/checklist/list/<list_id>', methods=['PUT'])
@login_required
def kitchen_checklist_update_api(list_id):
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    updated = KitchenChecklistService.update_list(
        list_id,
        payload,
        user=session.get('user') or 'Sistema',
    )
    if not updated:
        return jsonify({'success': False, 'error': 'Lista inválida ou não encontrada.'}), 404
    return jsonify({'success': True, 'data': updated})


@kitchen_bp.route('/api/kitchen/checklist/list/<list_id>', methods=['DELETE'])
@login_required
def kitchen_checklist_delete_api(list_id):
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    if not KitchenChecklistService.delete_list(list_id):
        return jsonify({'success': False, 'error': 'Lista não encontrada.'}), 404
    return jsonify({'success': True})


@kitchen_bp.route('/api/kitchen/checklist/template', methods=['POST'])
@login_required
def kitchen_checklist_create_template_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    created = KitchenChecklistService.create_template(
        name=payload.get('name'),
        list_type=payload.get('list_type'),
        items=payload.get('items') or [],
        user=session.get('user') or 'Sistema',
    )
    if not created:
        return jsonify({'success': False, 'error': 'Dados inválidos para criar modelo.'}), 400
    return jsonify({'success': True, 'data': created})


@kitchen_bp.route('/api/kitchen/checklist/template/<template_id>', methods=['PUT'])
@login_required
def kitchen_checklist_update_template_api(template_id):
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    updated = KitchenChecklistService.update_template(
        template_id=template_id,
        data=payload,
        user=session.get('user') or 'Sistema',
    )
    if not updated:
        return jsonify({'success': False, 'error': 'Modelo inválido ou não encontrado.'}), 404
    return jsonify({'success': True, 'data': updated})


@kitchen_bp.route('/api/kitchen/checklist/template/<template_id>', methods=['DELETE'])
@login_required
def kitchen_checklist_delete_template_api(template_id):
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    if not KitchenChecklistService.delete_template(template_id):
        return jsonify({'success': False, 'error': 'Modelo não encontrado.'}), 404
    return jsonify({'success': True})


@kitchen_bp.route('/api/kitchen/checklist/execute/start', methods=['POST'])
@login_required
def kitchen_checklist_start_execution_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    execution = KitchenChecklistService.start_execution(
        list_id=payload.get('list_id'),
        user=session.get('user') or 'Sistema',
    )
    if not execution:
        return jsonify({'success': False, 'error': 'Lista não encontrada.'}), 404
    return jsonify({'success': True, 'data': execution})


@kitchen_bp.route('/api/kitchen/checklist/execute/finish', methods=['POST'])
@login_required
def kitchen_checklist_finish_execution_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    result = KitchenChecklistService.finish_execution(
        execution_id=payload.get('execution_id'),
        item_results=payload.get('item_results') or [],
        add_to_today_purchase=bool(payload.get('add_to_today_purchase')),
        user=session.get('user') or 'Sistema',
    )
    if not result:
        return jsonify({'success': False, 'error': 'Execução não encontrada.'}), 404
    return jsonify({'success': True, 'data': result})


@kitchen_bp.route('/api/kitchen/checklist/shopping', methods=['POST'])
@login_required
def kitchen_checklist_create_shopping_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    payload = request.get_json(force=True) or {}
    created = KitchenChecklistService.create_shopping_list(
        name=payload.get('name'),
        items=payload.get('items') or [],
        observation=payload.get('observation') or '',
        source=payload.get('source') or 'manual',
        base_template_id=payload.get('base_template_id'),
        user=session.get('user') or 'Sistema',
    )
    if not created:
        return jsonify({'success': False, 'error': 'Dados inválidos para lista de compras.'}), 400
    return jsonify({'success': True, 'data': created})


@kitchen_bp.route('/api/kitchen/checklist/shopping/duplicate', methods=['POST'])
@login_required
def kitchen_checklist_duplicate_shopping_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    duplicated = KitchenChecklistService.duplicate_previous_shopping_list(user=session.get('user') or 'Sistema')
    if not duplicated:
        return jsonify({'success': False, 'error': 'Nenhuma lista concluída para duplicar.'}), 404
    return jsonify({'success': True, 'data': duplicated})


@kitchen_bp.route('/api/kitchen/checklist/send', methods=['POST'])
@login_required
def kitchen_checklist_send_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    try:
        data = request.json or {}
        list_name = data.get('list_name') or 'Lista da cozinha'
        items = data.get('items', [])
        if not items:
            return jsonify({'success': False, 'error': 'Nenhum item selecionado.'})
        message_text = KitchenChecklistService.build_whatsapp_message(
            title=list_name,
            items=items,
            observation=data.get('observation') or '',
        )
        return jsonify({
            'success': True,
            'text': message_text
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@kitchen_bp.route('/api/kitchen/checklist/history/summary')
@login_required
def kitchen_checklist_history_summary_api():
    if not _kitchen_checklist_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    format_type = (request.args.get('format') or 'json').lower()
    summary = KitchenChecklistService.build_period_summary(start_date=start_date, end_date=end_date)
    if format_type == 'csv':
        csv_content = KitchenChecklistService.build_summary_csv(summary)
        return jsonify({'success': True, 'csv': csv_content, 'summary': summary})
    return jsonify({'success': True, 'data': summary})


# --- Kitchen Recipes ---
RECIPES_FILE = get_data_path('kitchen_recipes.json')


def load_kitchen_recipes():
    recipes_path = Path(RECIPES_FILE)
    if not recipes_path.exists():
        return []
    try:
        raw = recipes_path.read_text(encoding='utf-8')
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception:
        return []


def save_kitchen_recipes(recipes):
    recipes_path = Path(RECIPES_FILE)
    recipes_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = recipes_path.with_name(f"{recipes_path.name}.tmp.{uuid.uuid4().hex}")
    temp_path.write_text(json.dumps(recipes, indent=4, ensure_ascii=False), encoding='utf-8')
    os.replace(str(temp_path), str(recipes_path))
    return True


@kitchen_bp.route('/kitchen/recipes')
@login_required
def kitchen_recipes():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    recipes = load_kitchen_recipes()
    for r in recipes:
        if 'created_at' not in r:
            r['created_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    insumos = load_products()
    insumos_simple = [{'name': p.get('name'), 'unit': p.get('unit')} for p in insumos]
    menu_items = load_menu_items()
    menu_products_pending = []
    menu_products_simple = []
    for it in menu_items:
        rec = it.get('recipe')
        menu_products_simple.append({
            'id': it.get('id'),
            'name': it.get('name'),
            'image_url': it.get('image_url') or '',
            'recipe': rec or {}
        })
        # Itens marcados como "sem receita" não entram na lista pendente
        if it.get('no_preparation'):
            continue
        include = False
        if not rec:
            include = True
        elif isinstance(rec, dict):
            ings = rec.get('ingredients') or []
            instr = (rec.get('instructions') or '').strip()
            # Apenas listar pendentes se não há insumos e não há preparo
            if len(ings) == 0 and not instr:
                include = True
        else:
            # Se for lista (insumos legados), não incluir segundo regra do usuário
            include = False
        if include:
            menu_products_pending.append({
                'id': it.get('id'),
                'name': it.get('name'),
                'image_url': it.get('image_url') or ''
            })
    return render_template('kitchen_recipes.html',
                           recipes=recipes,
                           insumos=insumos_simple,
                           menu_products=menu_products_simple,
                           menu_products_pending=menu_products_pending)


@kitchen_bp.route('/kitchen/recipes/save', methods=['POST'])
@login_required
def kitchen_recipe_save():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    recipe_id = request.form.get('recipe_id') or str(uuid.uuid4())
    menu_product_id = (request.form.get('menu_product_id') or '').strip()
    name = (request.form.get('name') or '').strip()
    instructions = (request.form.get('instructions') or '').strip()
    ingredient_names = request.form.getlist('ingredient_name[]')
    ingredient_qty = request.form.getlist('ingredient_qty[]')
    ingredient_unit = request.form.getlist('ingredient_unit[]')
    if not name:
        flash('Nome da receita é obrigatório.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    ingredients = []
    for i, n in enumerate(ingredient_names):
        n = (n or '').strip()
        if not n:
            continue
        qty = ingredient_qty[i] if i < len(ingredient_qty) else ''
        unit = ingredient_unit[i] if i < len(ingredient_unit) else ''
        ingredients.append({'name': n, 'qty': qty, 'unit': unit})
    if not ingredients:
        flash('Inclua pelo menos um insumo na receita.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    image_file = request.files.get('image')
    image_filename = None
    image_url = None
    if image_file and image_file.filename:
        try:
            os.makedirs(PRODUCT_PHOTOS_DIR, exist_ok=True)
            base_name = secure_filename(f"{recipe_id}_{image_file.filename}")
            target_path = os.path.join(PRODUCT_PHOTOS_DIR, base_name)
            try:
                from PIL import Image, ImageOps
                img = Image.open(image_file.stream)
                img = ImageOps.exif_transpose(img)
                max_size = (800, 800)
                img.thumbnail(max_size)
                if img.mode in ('RGBA', 'P'):
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = bg
                # Preserve extension if present, default to .jpg
                root, ext = os.path.splitext(base_name)
                if not ext:
                    ext = '.jpg'
                final_name = root + ext
                final_path = os.path.join(PRODUCT_PHOTOS_DIR, final_name)
                img.save(final_path, quality=85, optimize=True)
                image_filename = final_name
            except Exception:
                # Fallback: save original upload without processing
                image_file.save(target_path)
                image_filename = base_name
            if image_filename:
                image_url = f"/Produtos/Fotos/{image_filename}"
        except Exception:
            image_filename = None
            image_url = None
    # Se estiver editando diretamente um produto do menu
    if menu_product_id:
        items = load_menu_items()
        target = None
        for it in items:
            if str(it.get('id')) == menu_product_id:
                target = it
                break
        if not target:
            flash('Produto do cardápio não encontrado.')
            return redirect(url_for('kitchen.kitchen_recipes'))
        target['recipe'] = {
            'ingredients': ingredients,
            'instructions': instructions
        }
        if image_filename:
            target['image'] = image_filename
            target['image_url'] = image_url or ''
        secure_save_menu_items(items, session.get('user', 'Sistema'))
        flash('Ficha técnica atualizada no produto do cardápio.')
        return redirect(url_for('kitchen.kitchen_recipes'))

    recipes = load_kitchen_recipes()
    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    found = False
    for r in recipes:
        if r.get('id') == recipe_id:
            r.update({
                'name': name,
                'instructions': instructions,
                'ingredients': ingredients,
            })
            if image_url:
                r['image'] = image_filename
                r['image_url'] = image_url
            if 'created_at' not in r:
                r['created_at'] = now_str
            found = True
            break
    if not found:
        recipes.append({
            'id': recipe_id,
            'name': name,
            'instructions': instructions,
            'ingredients': ingredients,
            'created_at': now_str,
            'image': image_filename,
            'image_url': image_url,
            'menu_product_id': None
        })
    save_kitchen_recipes(recipes)
    flash('Receita salva com sucesso.')
    return redirect(url_for('kitchen.kitchen_recipes'))


@kitchen_bp.route('/kitchen/recipes/mark_no_recipe', methods=['POST'])
@login_required
def kitchen_recipe_mark_no_recipe():
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    menu_product_id = (request.form.get('menu_product_id') or '').strip()
    if not menu_product_id:
        flash('Produto inválido.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    items = load_menu_items()
    target = None
    for it in items:
        if str(it.get('id')) == menu_product_id:
            target = it
            break
    if not target:
        flash('Produto do cardápio não encontrado.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    target['no_preparation'] = True
    secure_save_menu_items(items, session.get('user', 'Sistema'))
    flash('Produto marcado como "não possui receita". Ele não aparecerá mais na lista de pendentes.')
    return redirect(url_for('kitchen.kitchen_recipes'))


@kitchen_bp.route('/kitchen/recipes/publish/<recipe_id>', methods=['POST'])
@login_required
def kitchen_recipe_publish(recipe_id):
    if session.get('role') not in ['admin', 'gerente'] and session.get('department') != 'Cozinha':
        flash('Acesso restrito.')
        return redirect(url_for('main.service_page', service_id='cozinha'))
    recipes = load_kitchen_recipes()
    target = next((r for r in recipes if r.get('id') == recipe_id), None)
    if not target:
        flash('Receita não encontrada.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    if target.get('menu_product_id'):
        flash('Receita já vinculada ao cardápio.')
        return redirect(url_for('kitchen.kitchen_recipes'))
    menu_items = load_menu_items()
    new_id = str(uuid.uuid4())
    ingredients = target.get('ingredients') or []
    recipe_payload = {
        'ingredients': ingredients,
        'instructions': target.get('instructions') or ''
    }
    new_item = {
        'id': new_id,
        'name': target.get('name'),
        'category': 'Cozinha',
        'price': 0.0,
        'cost_price': 0.0,
        'printer_id': None,
        'should_print': True,
        'description': '',
        'image': target.get('image'),
        'image_url': target.get('image_url') or '',
        'service_fee_exempt': False,
        'visible_virtual_menu': False,
        'highlight': False,
        'active': True,
        'recipe': recipe_payload,
        'mandatory_questions': [],
        'flavor_group_id': None,
        'flavor_multiplier': 1.0,
        'product_type': 'standard',
        'has_accompaniments': False,
        'allowed_accompaniments': [],
        'ncm': '',
        'cest': '',
        'transparency_tax': '',
        'fiscal_benefit_code': '',
        'cfop': '',
        'origin': '',
        'tax_situation': '',
        'icms_rate': 0.0,
        'icms_base_reduction': 0.0,
        'fcp_rate': 0.0,
        'pis_cst': '',
        'pis_rate': 0.0,
        'cofins_cst': '',
        'cofins_rate': 0.0,
        'paused': False,
        'pause_reason': ''
    }
    menu_items.append(new_item)
    secure_save_menu_items(menu_items, session.get('user', 'Sistema'))
    for r in recipes:
        if r.get('id') == recipe_id:
            r['menu_product_id'] = new_id
            break
    save_kitchen_recipes(recipes)
    flash('Produto criado no cardápio a partir da receita. Complete os dados em /menu/management.')
    return redirect(url_for('kitchen.kitchen_recipes'))
