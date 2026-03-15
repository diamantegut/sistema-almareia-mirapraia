
import json
import os
import uuid
import copy
from datetime import datetime
from app.services.logger_service import LoggerService
from app.services.system_config_manager import get_data_path
from app.services.data_service import (
    load_sales_history, save_sales_history,
    load_products, load_menu_items, save_stock_entry, log_stock_action
)
from app.services.cashier_service import CashierService

# Helper for file locking (simple version)
import time
from contextlib import contextmanager


@contextmanager
def file_lock(lock_file):
    lock_path = lock_file + '.lock'
    timeout = 5
    start_time = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Could not acquire lock for {lock_file}")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def log_action(action_type, details, user=None, department=None):
    try:
        LoggerService.log_acao(
            acao=action_type,
            entidade='Transferência',
            detalhes=details,
            colaborador_id=user,
            departamento_id=department or 'Sistema'
        )
    except Exception:
        pass

def load_json(filename, default=None):
    path = get_data_path(filename)
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return default if default is not None else {}

def save_json(filename, data):
    path = get_data_path(filename)
    try:
        # Atomic write: write to temp then rename
        temp_path = path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        # Windows replace can be tricky, but os.replace is atomic on POSIX and mostly atomic on Windows (Python 3.3+)
        if os.path.exists(path):
             os.replace(temp_path, path)
        else:
             os.rename(temp_path, path)
        return True
    except Exception as e:
        print(f"Error saving {filename}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return False

def normalize_room_key(raw_input, valid_keys):
    raw_input = str(raw_input).strip()
    if raw_input in valid_keys:
        return raw_input
    variations = [
        raw_input.zfill(2),
        raw_input.zfill(3),
        raw_input.lstrip('0')
    ]
    
    for var in variations:
        if var in valid_keys:
            return var
            
    return None

def resolve_stock_product_for_order_item(order_item, menu_items_db, products_db):
    menu_item = None
    raw_product_id = order_item.get('product_id')
    if raw_product_id is not None:
        menu_item = next((m for m in menu_items_db if str(m.get('id')) == str(raw_product_id)), None)

    if not menu_item:
        item_name = order_item.get('name')
        if item_name:
            menu_item = next((m for m in menu_items_db if m.get('name') == item_name), None)

    if menu_item and menu_item.get('recipe'):
        return None

    if menu_item:
        linked_stock_id = menu_item.get('stock_product_id') or menu_item.get('inventory_product_id')
        if linked_stock_id is not None:
            linked_product = next((p for p in products_db if str(p.get('id')) == str(linked_stock_id)), None)
            if linked_product:
                return linked_product

        menu_name = menu_item.get('name')
        if menu_name:
            by_name = next((p for p in products_db if p.get('name') == menu_name), None)
            if by_name:
                return by_name

    item_name = order_item.get('name')
    if item_name:
        return next((p for p in products_db if p.get('name') == item_name), None)
    return None

def normalize_order_item_accompaniments(accompaniments):
    normalized = []
    if not isinstance(accompaniments, list):
        return normalized
    for acc in accompaniments:
        if isinstance(acc, dict):
            acc_id = acc.get('id')
            acc_name = acc.get('name')
        else:
            acc_id = None
            acc_name = str(acc)
        normalized.append({
            'id': str(acc_id) if acc_id is not None else None,
            'name': acc_name
        })
    return normalized

def expand_order_item_stock_components(order_item):
    components = []
    try:
        base_qty = float(order_item.get('qty', 0) or 0)
    except Exception:
        base_qty = 0.0
    components.append({
        'product_id': order_item.get('product_id'),
        'name': order_item.get('name'),
        'qty': base_qty,
        'origin': 'produto',
        'parent_name': order_item.get('name')
    })
    for acc in normalize_order_item_accompaniments(order_item.get('accompaniments', [])):
        components.append({
            'product_id': acc.get('id'),
            'name': acc.get('name'),
            'qty': base_qty,
            'origin': 'acompanhamento',
            'parent_name': order_item.get('name')
        })
    return components

class TransferError(Exception):
    pass

class TableOccupiedError(TransferError):
    def __init__(self, message, free_tables=None):
        super().__init__(message)
        self.free_tables = free_tables or []

def _compute_free_tables_for_return(orders, room_charges):
    table_settings = load_json('restaurant_table_settings.json', {})
    disabled_raw = table_settings.get('disabled_tables') or []
    disabled_tables = set()
    for raw in disabled_raw:
        try:
            disabled_tables.add(str(int(raw)))
        except Exception:
            continue

    known_numeric_tables = set()
    for key in (orders or {}).keys():
        try:
            known_numeric_tables.add(int(str(key)))
        except Exception:
            continue
    for c in (room_charges or []):
        try:
            known_numeric_tables.add(int(str(c.get('table_id') or '')))
        except Exception:
            continue
    for raw in disabled_raw:
        try:
            known_numeric_tables.add(int(raw))
        except Exception:
            continue

    max_table = max(120, max(known_numeric_tables) if known_numeric_tables else 0)
    free_tables = []
    for i in range(1, max_table + 1):
        t_key = str(i)
        if t_key in disabled_tables:
            continue
        if t_key not in orders:
            free_tables.append(t_key)
            continue
        t = orders[t_key]
        has_items = bool(t.get('items')) and len(t.get('items')) > 0
        has_total = float(t.get('total', 0) or 0) > 0
        if not has_items and not has_total:
            free_tables.append(t_key)
    return free_tables

def transfer_table_to_room(table_id, raw_room_number, user_name, mode='restaurant'):
    str_table_id = str(table_id)
    
    # Acquire locks for both files to ensure consistency
    # Note: Global lock might be better, but per-resource is okay for now.
    # We'll use a conceptual "transfer" lock to avoid complex deadlocks
    
    lock_file = get_data_path('transfer_lock')
    
    try:
        with file_lock(lock_file):
            # Reload data inside lock
            orders = load_json('table_orders.json', {})
            room_occupancy = load_json('room_occupancy.json', {})
            room_charges = load_json('room_charges.json', [])
            
            # 1. Validate Order
            if str_table_id not in orders:
                raise TransferError(f"Mesa {table_id} não encontrada ou já fechada.")
                
            order = orders[str_table_id]
            if not order.get('items'):
                raise TransferError("Mesa sem itens para transferir.")
                
            # 2. Validate Room
            target_key = normalize_room_key(raw_room_number, room_occupancy.keys())
            if not target_key:
                # Debug info
                available = sorted(list(room_occupancy.keys()))
                raise TransferError(f"Quarto '{raw_room_number}' não encontrado. Disponíveis: {available[:5]}...")
                
            room_data = room_occupancy[target_key]
            # Flexible status check: if 'status' field exists, it must be 'occupied'. 
            # If missing, assume legacy/occupied.
            if room_data.get('status') and room_data.get('status') != 'occupied':
                raise TransferError(f"Quarto {target_key} não está ocupado (Status: {room_data.get('status')}).")
            
            # 3. Prepare Transfer Data
            items = order['items']
            
            # Separate items
            minibar_items = []
            restaurant_items = []
            
            for item in items:
                is_minibar = item.get('source') == 'minibar' or item.get('category') == 'Frigobar'
                if is_minibar:
                    minibar_items.append(item)
                else:
                    restaurant_items.append(item)
            
            transferred_any = False
            
            service_fee_removed = order.get('service_fee_removed', False)
            discount_amount = float(order.get('discount_amount', 0) or 0)
            discount_remaining = discount_amount
            
            new_charges = []
            
            # 3a. Restaurant Portion
            if restaurant_items:
                cover_items_total = 0.0
                noncover_items_total = 0.0
                restaurant_items_total = 0.0
                
                for item in restaurant_items:
                    try:
                        qty_sf = float(item.get('qty', 1) or 1)
                    except Exception:
                        qty_sf = 1.0
                    try:
                        price_sf = float(item.get('price', 0) or 0)
                    except Exception:
                        price_sf = 0.0
                    
                    complements_total_sf = 0.0
                    for c in item.get('complements', []) or []:
                        try:
                            complements_total_sf += float(c.get('price', 0) or 0)
                        except Exception:
                            continue
                    
                    item_val_sf = qty_sf * (price_sf + complements_total_sf)
                    restaurant_items_total += item_val_sf
                    
                    name_sf = (item.get('name') or '').lower()
                    is_auto_cover_sf = item.get('source') == 'auto_cover_activation'
                    is_cover_name_sf = 'couvert artistico' in name_sf
                    is_cover_item_sf = is_auto_cover_sf or is_cover_name_sf
                    
                    if is_cover_item_sf:
                        cover_items_total += item_val_sf
                    else:
                        noncover_items_total += item_val_sf
                
                rest_taxable = sum(i['qty'] * i['price'] for i in restaurant_items if not i.get('service_fee_exempt', False))
                rest_service = 0 if service_fee_removed else rest_taxable * 0.10
                
                rest_total_base = restaurant_items_total
                
                current_discount = 0
                if discount_remaining > 0:
                    current_discount = min(discount_remaining, rest_total_base + rest_service)
                    discount_remaining -= current_discount
                
                rest_grand_total = rest_total_base + rest_service - current_discount
                
                flags = []
                if service_fee_removed:
                    flags.append({'type': 'service_removed', 'value': rest_taxable * 0.10})
                if current_discount > 0:
                    flags.append({'type': 'discount_applied', 'value': current_discount})

                waiter_totals = {}
                total_item_value_for_breakdown = 0.0

                for item in restaurant_items:
                    try:
                        qty = float(item.get('qty', 1) or 1)
                    except Exception:
                        qty = 1.0
                    try:
                        price = float(item.get('price', 0) or 0)
                    except Exception:
                        price = 0.0

                    complements_total = 0.0
                    for c in item.get('complements', []) or []:
                        try:
                            complements_total += float(c.get('price', 0) or 0)
                        except Exception:
                            continue

                    item_val = qty * (price + complements_total)

                    name = (item.get('name') or '').lower()
                    is_auto_cover = item.get('source') == 'auto_cover_activation'
                    is_cover_name = 'couvert artistico' in name
                    is_cover_item = is_auto_cover or is_cover_name

                    if not is_cover_item:
                        w = item.get('waiter') or order.get('waiter') or 'Garçom'
                        waiter_totals[w] = waiter_totals.get(w, 0.0) + item_val
                        total_item_value_for_breakdown += item_val

                if total_item_value_for_breakdown > 0:
                    waiter_shares = {w: amt / total_item_value_for_breakdown for w, amt in waiter_totals.items()}
                else:
                    waiter_shares = {order.get('waiter') or 'Garçom': 1.0}

                if restaurant_items_total > 0:
                    noncover_share_of_check = noncover_items_total / restaurant_items_total
                else:
                    noncover_share_of_check = 1.0

                commissionable_total = rest_grand_total * noncover_share_of_check

                waiter_breakdown = {w: commissionable_total * share for w, share in waiter_shares.items()}
                main_waiter = None
                if waiter_breakdown:
                    main_waiter = max(waiter_breakdown.items(), key=lambda x: x[1])[0]
                
                charge_entry = {
                    'id': f"CHARGE_{str_table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}_REST",
                    'room_number': target_key,
                    'table_id': str_table_id,
                    'total': rest_grand_total,
                    'items': restaurant_items,
                    'service_fee': rest_service,
                    'discount': current_discount,
                    'flags': flags,
                    'waiter': main_waiter or order.get('waiter'),
                    'opened_by': order.get('opened_by') or order.get('waiter') or user_name,
                    'waiter_breakdown': waiter_breakdown,
                    'service_fee_removed': service_fee_removed,
                    'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'status': 'pending',
                    'type': 'restaurant'
                }
                new_charges.append(charge_entry)
                
                LoggerService.log_acao(
                    acao='Transferência de Mesa',
                    entidade='Mesas',
                    detalhes={
                        'source_table': str_table_id,
                        'target_room': target_key,
                        'total': rest_grand_total,
                        'items_count': len(restaurant_items),
                        'items': restaurant_items
                    },
                    departamento_id='Restaurante',
                    colaborador_id=user_name
                )
                
                transferred_any = True

            # 3b. Minibar Portion
            if minibar_items:
                mini_total = sum(i['qty'] * (i['price'] + sum(c['price'] for c in i.get('complements', []))) for i in minibar_items)
                
                current_discount = 0
                if discount_remaining > 0:
                    current_discount = min(discount_remaining, mini_total)
                    discount_remaining -= current_discount
                
                mini_grand_total = mini_total - current_discount
                
                flags = []
                if current_discount > 0:
                    flags.append({'type': 'discount_applied', 'value': current_discount})
                
                charge_entry = {
                    'id': f"CHARGE_{str_table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}_BAR",
                    'room_number': target_key,
                    'table_id': str_table_id,
                    'total': mini_grand_total,
                    'items': minibar_items,
                    'service_fee': 0,
                    'discount': current_discount,
                    'flags': flags,
                    'waiter': None,
                    'opened_by': order.get('opened_by') or order.get('waiter') or user_name,
                    'waiter_breakdown': None,
                    'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'status': 'pending',
                    'type': 'minibar'
                }
                new_charges.append(charge_entry)
                transferred_any = True

            if not transferred_any:
                raise TransferError("Nenhum item válido para transferência.")

            # 4. Commit Changes (Atomic-ish)
            # We append charges first, then clear/close table.
            # If charges save fails, table is untouched (user tries again).
            # If table save fails, we might have duplicate charges (risk).
            # Ideally we'd rollback charges, but let's just try to be safe.
            
            room_charges = new_charges + room_charges
            if not save_json('room_charges.json', room_charges):
                raise TransferError("Falha ao salvar cobranças no quarto. Tente novamente.")
            
            # --- Archive to Sales History & Deduct Stock ---
            try:
                sales_history = load_sales_history()
                if not isinstance(sales_history, list):
                    sales_history = []
                
                order_to_archive = copy.deepcopy(order)
                order_to_archive['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                order_to_archive['status'] = 'closed'
                order_to_archive['payment_method'] = 'Room Charge'
                order_to_archive['room_charge'] = target_key
                order_to_archive['final_total'] = sum(c['total'] for c in new_charges) # Total transferred
                
                sales_history.append(order_to_archive)
                save_sales_history(sales_history)
                
                # Deduct Stock
                products_db = load_products()
                menu_items_db = load_menu_items()
                menu_items_by_id = {str(m.get('id')): m for m in menu_items_db if m.get('id') is not None}
                menu_items_by_name = {m.get('name'): m for m in menu_items_db if m.get('name')}
                insumo_map = {str(p.get('id')): p for p in products_db if p.get('id') is not None}
                for item in order['items']:
                    item_uuid = item.get('id') or str(uuid.uuid4())
                    deducted_acc_ids = set(str(x) for x in item.get('accompaniments_deducted_ids', []) if x is not None)
                    for component in expand_order_item_stock_components(item):
                        qty = float(component.get('qty', 0) or 0)
                        if qty <= 0:
                            continue
                        component_pid = component.get('product_id')
                        component_name = component.get('name')
                        origin = component.get('origin')
                        parent_name = component.get('parent_name')
                        if origin == 'acompanhamento' and component_pid is not None and str(component_pid) in deducted_acc_ids:
                            continue

                        menu_item_match = None
                        if component_pid is not None:
                            menu_item_match = menu_items_by_id.get(str(component_pid))
                        if not menu_item_match and component_name:
                            menu_item_match = menu_items_by_name.get(component_name)

                        if menu_item_match and menu_item_match.get('recipe'):
                            if origin == 'produto':
                                continue
                            for ingred in menu_item_match.get('recipe', []):
                                ing_id = ingred.get('ingredient_id')
                                if ing_id is None:
                                    continue
                                insumo_data = insumo_map.get(str(ing_id))
                                if not insumo_data:
                                    continue
                                try:
                                    ing_qty = float(ingred.get('qty', 0) or 0)
                                except Exception:
                                    continue
                                if ing_qty <= 0:
                                    continue
                                total_needed = ing_qty * qty
                                save_stock_entry({
                                    'id': f"ROOM_ACC_RECIPE_{item_uuid}_{str(component_pid or component_name)}_{str(ing_id)}",
                                    'date': datetime.now().strftime('%d/%m/%Y'),
                                    'product_id': insumo_data.get('id'),
                                    'product': insumo_data['name'],
                                    'qty': -abs(total_needed),
                                    'unit': insumo_data.get('unit', 'un'),
                                    'price': insumo_data.get('price', 0),
                                    'supplier': 'Venda (Acompanhamento)',
                                    'invoice': f"Quarto {target_key} | Acomp de: {parent_name}",
                                    'user': user_name
                                })
                            continue

                        product_obj = resolve_stock_product_for_order_item(
                            {'product_id': component_pid, 'name': component_name},
                            menu_items_db,
                            products_db
                        )
                        if not product_obj:
                            continue
                        details_suffix = f" | Acomp de {parent_name}" if origin == 'acompanhamento' else ""
                        log_stock_action(
                            user=user_name,
                            action='saida',
                            product=product_obj['name'],
                            qty=qty,
                            details=f"Transferência Quarto {target_key}{details_suffix}",
                            department='Restaurante'
                        )
                        save_stock_entry({
                            'id': f"ROOM_{item_uuid}_{str(component_pid or component_name)}",
                            'date': datetime.now().strftime('%d/%m/%Y'),
                            'product_id': product_obj.get('id'),
                            'product': product_obj['name'],
                            'qty': -abs(qty),
                            'unit': product_obj.get('unit', 'un'),
                            'price': product_obj.get('price', 0),
                            'supplier': 'Venda (Acompanhamento)' if origin == 'acompanhamento' else 'Venda',
                            'invoice': f"Quarto {target_key} | Acomp de: {parent_name}" if origin == 'acompanhamento' else f"Quarto {target_key}",
                            'user': user_name
                        })
            except Exception as e:
                # Log but don't fail the transfer? 
                # Or fail and revert?
                # Failing here is safer to avoid data inconsistency.
                LoggerService.log_acao(
                    acao='Erro Transferência', 
                    entidade='Sistema', 
                    detalhes={'error': str(e), 'context': 'Stock/History update'},
                    departamento_id='Restaurante',
                    colaborador_id=user_name
                )
                # We proceed, or raise? 
                # If we raise, we need to revert room_charges.
                # Let's raise to trigger the revert block below.
                raise e

            # Now update table
            try:
                # Determine if we should close or clear based on ID logic
                # Legacy logic: tables <= 35 stay open but empty
                is_permanent_table = False
                try:
                    if int(str_table_id) <= 35:
                        is_permanent_table = True
                except:
                    pass
                
                if is_permanent_table:
                    orders[str_table_id]['items'] = []
                    orders[str_table_id]['total'] = 0
                else:
                    del orders[str_table_id]
                
                if not save_json('table_orders.json', orders):
                    raise TransferError("Falha ao gravar arquivo de mesas")
                    
            except Exception as e:
                # Revert charges if table update failed
                added_ids = {c['id'] for c in new_charges}
                room_charges = [c for c in room_charges if c['id'] not in added_ids]
                save_json('room_charges.json', room_charges)
                raise TransferError(f"Falha ao atualizar mesa. Operação revertida. Detalhe: {e}")

            return True, f"Transferência realizada com sucesso para o quarto {target_key}."

    except TimeoutError:
        raise TransferError("Sistema ocupado. Tente novamente em instantes.")
    except TransferError:
        raise
    except Exception as e:
        # Unexpected error
        raise TransferError(f"Erro inesperado: {str(e)}")

def return_charge_to_restaurant(charge_id, user_name, target_table_id=None):
    """
    Returns a charge from room back to restaurant table.
    """
    # Validate Cashier Status (Business Rule)
    try:
        CashierService.validate_transfer_eligibility('guest_consumption', 'restaurant', user_name)
    except ValueError as e:
        raise TransferError(str(e))

    lock_file = get_data_path('transfer_lock')
    
    try:
        with file_lock(lock_file):
            room_charges = load_json('room_charges.json', [])
            orders = load_json('table_orders.json', {})
            
            # 1. Find Charge
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            if not charge:
                raise TransferError("Conta não encontrada.")
            
            if charge.get('status') != 'pending':
                raise TransferError("Apenas contas pendentes podem ser devolvidas.")
                
            original_table_id = charge.get('table_id')
            
            # Determine destination table
            dest_table_id = str(target_table_id).strip() if target_table_id else str(original_table_id)
            
            if not dest_table_id or dest_table_id == 'None':
                 raise TransferError("Esta conta não possui mesa de origem vinculada.")
            
            # Check Occupancy
            if dest_table_id in orders:
                table_data = orders[dest_table_id]
                is_occupied = False
                
                # Criteria for occupancy: has items OR total > 0
                if table_data.get('items') and len(table_data.get('items')) > 0:
                    is_occupied = True
                elif float(table_data.get('total', 0)) > 0:
                    is_occupied = True
                
                if is_occupied:
                    free_tables = _compute_free_tables_for_return(orders, room_charges)
                    raise TableOccupiedError(f"A Mesa {dest_table_id} está ocupada.", free_tables=free_tables)

            # 2. Restore to Table
            items_total = sum(i['qty'] * i['price'] for i in charge.get('items', []))
            
            if dest_table_id in orders:
                # Table exists, append items
                existing_items = orders[dest_table_id].get('items', [])
                existing_items.extend(charge.get('items', []))
                orders[dest_table_id]['items'] = existing_items
                
                # Recalculate total (sum of all items)
                orders[dest_table_id]['total'] = sum(i['qty'] * i['price'] for i in existing_items)
                
                # Ensure status is open
                orders[dest_table_id]['status'] = 'open'
                if not orders[dest_table_id].get('opened_by'):
                    orders[dest_table_id]['opened_by'] = charge.get('opened_by') or charge.get('waiter') or user_name
                
                if not orders[dest_table_id].get('opened_at'):
                    orders[dest_table_id]['opened_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
            else:
                # Table doesn't exist (deleted), recreate it
                new_order = {
                    'items': charge.get('items', []),
                    'total': items_total,
                    'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'status': 'open',
                    'waiter': charge.get('waiter'),
                    'opened_by': charge.get('opened_by') or charge.get('waiter') or user_name,
                    'customer_type': 'hospede',
                    'room_number': charge.get('room_number')
                }
                orders[dest_table_id] = new_order
                
            # 3. Remove from Room Charges
            room_charges = [c for c in room_charges if c['id'] != charge_id]
            
            # 4. Save
            if not save_json('table_orders.json', orders):
                raise TransferError("Falha ao restaurar mesa.")
                
            if not save_json('room_charges.json', room_charges):
                raise TransferError("Falha ao remover cobrança do quarto.")
                
            # Log
            log_data = {
                'charge_id': charge_id,
                'source_room': charge.get('room_number'),
                'target_table': dest_table_id,
                'original_table': original_table_id,
                'total': charge.get('total'),
                'user': user_name
            }
            LoggerService.log_acao(
                acao='Devolução ao Restaurante',
                entidade='Mesas',
                detalhes=log_data,
                departamento_id='Restaurante',
                colaborador_id=user_name
            )
            
            return True, f"Conta devolvida para a Mesa {dest_table_id}."

    except TimeoutError:
        raise TransferError("Sistema ocupado. Tente novamente.")
    except TransferError:
        raise
    except Exception as e:
        raise TransferError(f"Erro: {str(e)}")
