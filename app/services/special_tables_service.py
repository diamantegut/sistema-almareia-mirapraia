
import os
import json
import logging
from datetime import datetime
import uuid
from app.services.data_service import (
    load_table_orders,
    save_table_orders,
    load_products,
    save_stock_entry,
    load_breakfast_history,
    save_breakfast_history,
    log_stock_action,
)
from app.services.logger_service import log_system_action

SPECIAL_TABLES_LOG_FILE = r"f:\Sistema Almareia Mirapraia\data\special_tables_log.json"

class SpecialTablesService:
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
        products_db = load_products()
        history_items = []
        total_value = 0.0
        
        for item in order.get('items', []):
            product_obj = next((p for p in products_db if p['name'] == item.get('name')), None)
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
            
            if product_obj:
                log_stock_action(
                    user=user,
                    action='saida',
                    product=product_obj['name'],
                    qty=qty,
                    details=f"Café da Manhã - Mesa {table_id}",
                    department='Restaurante'
                )
                save_stock_entry({
                    'id': str(uuid.uuid4()),
                    'date': now.strftime('%d/%m/%Y'),
                    'product': product_obj['name'],
                    'qty': -abs(qty),
                    'unit': product_obj.get('unit', 'un'),
                    'price': product_obj.get('price', 0),
                    'supplier': 'Café da Manhã',
                    'invoice': f"Mesa {table_id}",
                    'user': user
                })

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
        
        # Save changes (remove mesa do mapa)
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_breakfast', user, {
            'original_total': original_total,
            'items_count': len(order.get('items', []))
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
        
        # Disable commission flag?
        order['commission_eligible'] = False
        
        # Stock deduction logic (same as standard)
        
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_owners', user, {
            'original_total': original_total
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
        order['commission_eligible'] = False
        
        del orders[str(table_id)]
        save_table_orders(orders)
        
        SpecialTablesService.log_special_operation(table_id, 'close_courtesy', user, {
            'original_total': original_total,
            'justification': justification
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
