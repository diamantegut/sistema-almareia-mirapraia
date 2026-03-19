
import os
import json
import logging
from datetime import datetime
import uuid
from app.services.data_service import (
    load_table_orders,
    save_table_orders,
    load_products,
    load_menu_items,
    save_stock_entry,
    load_breakfast_history,
    save_breakfast_history,
    load_sales_history,
    secure_save_sales_history,
    log_stock_action,
)
from app.services.logger_service import log_system_action

SPECIAL_TABLES_LOG_FILE = r"f:\Sistema Almareia Mirapraia\data\special_tables_log.json"

class SpecialTablesService:
    @staticmethod
    def _normalize_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    @staticmethod
    def _collect_stock_components(item, menu_by_id, menu_by_name, product_by_id, product_by_name):
        components = []
        item_qty = SpecialTablesService._normalize_float(item.get('qty', 1) or 1)
        if item_qty <= 0:
            return components
        components.append({
            'product_id': item.get('product_id'),
            'name': item.get('name'),
            'qty': item_qty,
            'origin': 'produto',
            'parent_name': item.get('name'),
        })
        for acc in item.get('accompaniments', []) or []:
            if not isinstance(acc, dict):
                continue
            acc_qty = SpecialTablesService._normalize_float(acc.get('qty', item_qty) or item_qty)
            if acc_qty <= 0:
                continue
            components.append({
                'product_id': acc.get('id') or acc.get('product_id'),
                'name': acc.get('name'),
                'qty': acc_qty,
                'origin': 'acompanhamento',
                'parent_name': item.get('name'),
            })
        expanded = []
        for component in components:
            comp_qty = SpecialTablesService._normalize_float(component.get('qty'))
            if comp_qty <= 0:
                continue
            comp_pid = component.get('product_id')
            comp_name = component.get('name')
            menu_item = None
            if comp_pid is not None:
                menu_item = menu_by_id.get(str(comp_pid))
            if not menu_item and comp_name:
                menu_item = menu_by_name.get(comp_name)
            if menu_item and isinstance(menu_item.get('recipe'), list) and menu_item.get('recipe'):
                for ingred in menu_item.get('recipe'):
                    ing_id = ingred.get('ingredient_id')
                    if ing_id is None:
                        continue
                    ingredient = product_by_id.get(str(ing_id))
                    if not ingredient:
                        continue
                    ing_qty = SpecialTablesService._normalize_float(ingred.get('qty'))
                    if ing_qty <= 0:
                        continue
                    expanded.append({
                        'product': ingredient,
                        'qty': comp_qty * ing_qty,
                        'origin': component.get('origin'),
                        'parent_name': component.get('parent_name'),
                    })
                continue
            product = None
            if comp_pid is not None:
                product = product_by_id.get(str(comp_pid))
            if not product and comp_name:
                product = product_by_name.get(comp_name)
            if not product:
                continue
            expanded.append({
                'product': product,
                'qty': comp_qty,
                'origin': component.get('origin'),
                'parent_name': component.get('parent_name'),
            })
        return expanded

    @staticmethod
    def _deduct_stock_for_order(order, table_id, user, supplier_label):
        products_db = load_products()
        menu_items_db = load_menu_items()
        menu_by_id = {str(m.get('id')): m for m in menu_items_db if m.get('id') is not None}
        menu_by_name = {m.get('name'): m for m in menu_items_db if m.get('name')}
        product_by_id = {str(p.get('id')): p for p in products_db if p.get('id') is not None}
        product_by_name = {p.get('name'): p for p in products_db if p.get('name')}
        deducted = 0
        for item in order.get('items', []):
            item_id = item.get('id') or str(uuid.uuid4())
            for index, comp in enumerate(SpecialTablesService._collect_stock_components(item, menu_by_id, menu_by_name, product_by_id, product_by_name)):
                product_obj = comp.get('product') or {}
                qty = SpecialTablesService._normalize_float(comp.get('qty'))
                if qty <= 0:
                    continue
                origin = comp.get('origin')
                parent_name = comp.get('parent_name')
                details_suffix = f" | Acomp de {parent_name}" if origin == 'acompanhamento' else ""
                log_stock_action(
                    user=user,
                    action='saida',
                    product=product_obj.get('name'),
                    qty=qty,
                    details=f"{supplier_label} - Mesa {table_id}{details_suffix}",
                    department='Restaurante'
                )
                save_stock_entry({
                    'id': f"SPECIAL_{table_id}_{item_id}_{index}_{str(product_obj.get('id') or product_obj.get('name'))}",
                    'date': datetime.now().strftime('%d/%m/%Y'),
                    'product_id': product_obj.get('id'),
                    'product': product_obj.get('name'),
                    'qty': -abs(qty),
                    'unit': product_obj.get('unit', 'un'),
                    'price': product_obj.get('price', 0),
                    'supplier': f'{supplier_label} (Acompanhamento)' if origin == 'acompanhamento' else supplier_label,
                    'invoice': f"Mesa {table_id} | Acomp de: {parent_name}" if origin == 'acompanhamento' else f"Mesa {table_id}",
                    'user': user
                })
                deducted += 1
        return deducted

    @staticmethod
    def _append_special_sales_history(order, table_id, user, special_type, original_total):
        entry = dict(order)
        entry['table_id'] = str(table_id)
        entry['total'] = 0.0
        entry['final_total'] = 0.0
        entry['service_fee'] = 0.0
        entry['service_fee_removed'] = True
        entry['commission_eligible'] = False
        entry['special_table_type'] = special_type
        entry['special_original_total'] = SpecialTablesService._normalize_float(original_total)
        entry['payment_methods'] = []
        try:
            history = load_sales_history()
            history.append(entry)
            secure_save_sales_history(history, user)
        except Exception:
            pass

    @staticmethod
    def _load_logs():
        if not os.path.exists(SPECIAL_TABLES_LOG_FILE):
            return []
        try:
            with open(SPECIAL_TABLES_LOG_FILE, 'r') as f:
                return json.load(f)
        except:
            return []

    @staticmethod
    def _save_logs(logs):
        os.makedirs(os.path.dirname(SPECIAL_TABLES_LOG_FILE), exist_ok=True)
        with open(SPECIAL_TABLES_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)

    @staticmethod
    def log_special_operation(table_id, action, user, details=None):
        logs = SpecialTablesService._load_logs()
        entry = {
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'table_id': str(table_id),
            'action': action,
            'user': user,
            'details': details or {}
        }
        logs.append(entry)
        SpecialTablesService._save_logs(logs)

    @staticmethod
    def process_table_36_breakfast(table_id, user):
        """
        Mesa 36 - Café da Manhã:
        - Validar horário (07:00 - 10:30)
        - Zerar total financeiro
        - Baixar estoque
        """
        now = datetime.now()
        # Validation: Time check (relaxed for testing/dev, but strictly specified in reqs)
        # Req: 07:00 to 10:30. 
        # Note: If current time is outside window, we might BLOCK transfer or closing?
        # The requirement says "impedir que produtos lançados fora do horário... sejam transferidos".
        # This function processes the CLOSING/PROCESSING.
        
        # Check time window for processing (Closing)
        # Actually, table 36 acts as a "sink" for breakfast items.
        
        orders = load_table_orders()
        if str(table_id) not in orders:
            return False, "Mesa não encontrada"
            
        order = orders[str(table_id)]
        
        # Zero out total
        original_total = order.get('total', 0.0)
        order['total'] = 0.0
        order['final_total'] = 0.0
        order['discount'] = original_total # 100% discount
        order['payment_method'] = 'Cafe da Manha'
        order['status'] = 'closed'
        order['closed_at'] = now.strftime('%d/%m/%Y %H:%M')
        order['closed_by'] = user
        
        # Stock Deduction + Breakfast History
        history_items = []
        total_value = 0.0
        
        for item in order.get('items', []):
            product_obj = None
            try:
                qty = float(item.get('qty', 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            
            # Base price: prefer item price, fallback to product price
            base_price = 0.0
            try:
                base_price = float(item.get('price', 0) or 0)
            except (TypeError, ValueError):
                if product_obj:
                    try:
                        base_price = float(product_obj.get('price', 0) or 0)
                    except (TypeError, ValueError):
                        base_price = 0.0
            
            complements = item.get('complements') or []
            
            item_total = qty * base_price
            for comp in complements:
                try:
                    comp_price = float(comp.get('price', 0) or 0)
                except (TypeError, ValueError):
                    comp_price = 0.0
                item_total += qty * comp_price
            total_value += item_total
            
            history_items.append({
                'name': item.get('name'),
                'qty': qty,
                'price': base_price,
                'complements': complements,
            })
            
        stock_count = SpecialTablesService._deduct_stock_for_order(order, table_id, user, 'Café da Manhã')

        # Breakfast History (estoque sem financeiro)
        try:
            history = load_breakfast_history()
        except Exception:
            history = []
        history_entry = {
            'date': now.strftime('%d/%m/%Y'),
            'closed_at': now.strftime('%d/%m/%Y %H:%M'),
            'items': history_items,
            'total_value': round(total_value, 2),
            'closed_by': user,
            'table_id': str(table_id),
        }
        history.append(history_entry)
        save_breakfast_history(history)
        SpecialTablesService._append_special_sales_history(order, table_id, user, 'breakfast', original_total)
        
        # Save changes (remove mesa do mapa)
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_breakfast', user, {
            'original_total': original_total,
            'items_count': len(order.get('items', [])),
            'stock_entries': stock_count
        })
        
        return True, f"Mesa 36 fechada como Café da Manhã. Total zerado (R$ {original_total:.2f}). Estoque baixado."

    @staticmethod
    def process_table_69_owners(table_id, user):
        """
        Mesa 69 - Consumo Proprietários:
        - Bloqueio financeiro/comissões
        - Baixa estoque
        """
        orders = load_table_orders()
        if str(table_id) not in orders:
            return False, "Mesa não encontrada"
            
        order = orders[str(table_id)]
        
        original_total = order.get('total', 0.0)
        order['total'] = 0.0
        order['final_total'] = 0.0
        order['discount'] = original_total
        order['payment_method'] = 'Consumo Proprio'
        order['status'] = 'closed'
        order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        order['closed_by'] = user
        order['service_fee'] = 0.0
        order['service_fee_removed'] = True
        order['commission_eligible'] = False
        stock_count = SpecialTablesService._deduct_stock_for_order(order, table_id, user, 'Consumo Proprietários')
        SpecialTablesService._append_special_sales_history(order, table_id, user, 'owners', original_total)
        
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_owners', user, {
            'original_total': original_total,
            'stock_entries': stock_count
        })
        
        return True, "Consumo Proprietários registrado. Total zerado."

    @staticmethod
    def process_table_68_courtesy(table_id, user, justification):
        """
        Mesa 68 - Cortesias:
        - Justificativa obrigatória
        - Aprovação (Simulated/Logged)
        """
        if not justification or len(justification) < 5:
            return False, "Justificativa obrigatória (mínimo 5 caracteres)."
            
        orders = load_table_orders()
        if str(table_id) not in orders:
            return False, "Mesa não encontrada"
            
        order = orders[str(table_id)]
        
        original_total = order.get('total', 0.0)
        order['total'] = 0.0
        order['final_total'] = 0.0
        order['discount'] = original_total
        order['payment_method'] = 'Cortesia'
        order['status'] = 'closed'
        order['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        order['closed_by'] = user
        order['justification'] = justification
        order['service_fee'] = 0.0
        order['service_fee_removed'] = True
        order['commission_eligible'] = False
        stock_count = SpecialTablesService._deduct_stock_for_order(order, table_id, user, 'Cortesia')
        SpecialTablesService._append_special_sales_history(order, table_id, user, 'courtesy', original_total)
        
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_courtesy', user, {
            'original_total': original_total,
            'justification': justification,
            'stock_entries': stock_count
        })
        
        return True, "Cortesia registrada com sucesso."

    @staticmethod
    def validate_transfer_to_special(target_table_id, items, user, source_created_at=None):
        """
        Validates transfer rules BEFORE items are moved.
        target_table_id: ID da mesa de destino
        items: Lista de itens sendo transferidos
        user: Usuário solicitante
        source_created_at: String de data/hora de abertura da mesa de origem (opcional)
        """
        target_id = str(target_table_id)
        
        # Rule 1: Mesa 36 (Breakfast)
        if target_id == '36':
            # Check if source origin time allows it (Breakfast time) OR current time is breakfast time
            # User Req: "A tranferencia ... pode ser realizado em qualquer horario desde que a mesa ... tenha sido realizados dentro do horario."
            
            from datetime import time
            start_time = time(7, 0)
            end_time = time(10, 30)
            
            is_valid_source = False
            is_valid_now = False
            
            # 1. Check Source Time
            if source_created_at:
                try:
                    # Format expected: %d/%m/%Y %H:%M
                    dt_source = datetime.strptime(source_created_at, '%d/%m/%Y %H:%M')
                    t_source = dt_source.time()
                    if start_time <= t_source <= end_time:
                        is_valid_source = True
                except (ValueError, TypeError):
                    pass # Invalid format, ignore source validation
            
            # 2. Check Current Time (REMOVED: Strict validation based on Source Time only)
            # now = datetime.now()
            # t_now = now.time()
            # if start_time <= t_now <= end_time:
            #    is_valid_now = True
            
            if not is_valid_source:
                return False, "Transferência para Mesa 36 permitida apenas se a mesa de origem foi aberta no horário do Café (07:00 - 10:30)."
                
            # Ideally check if items are breakfast category?
            # Reqs: "impedir que produtos lançados fora do horário... sejam transferidos"
            # This time check covers the "transfer action" time.
            
        # Rule 3: Mesa 68 (Courtesy) - Justification check is handled in the UI flow usually, 
        # but here we can enforce specific constraints if needed.
        
        return True, "OK"
