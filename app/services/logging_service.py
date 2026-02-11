from datetime import datetime
from app.services.logger_service import LoggerService
import re
from app.services.system_config_manager import BASE_DIR, get_log_path, get_data_path

LOGS_DIR = get_log_path('')
DATA_DIR = get_data_path('')

def log_order_action(order_data, action="create", user="Sistema"):
    """
    Logs order-related actions using centralized LoggerService.
    order_data: dict containing order details (id, table, items, etc.)
    """
    details = {
        'order_id': order_data.get('id'),
        'table': str(order_data.get('table_id', '')),
        'waiter': order_data.get('waiter_name', user),
        'items': order_data.get('items', []),
        'total': order_data.get('total', 0),
        'status': order_data.get('status', 'unknown'),
        'timestamp_iso': datetime.now().isoformat()
    }
    
    LoggerService.log_acao(
        acao=f"Order {action}",
        entidade='Order',
        detalhes=details,
        departamento_id='Restaurante',
        colaborador_id=user
    )
    return True

def log_system_action(action, message=None, user="Sistema", category="Geral", details=None):
    """
    Logs system actions using centralized LoggerService.
    """
    entry_details = {}
    if details is not None and message is not None:
        entry_details = {
            'message': message,
            'details': details
        }
    elif details is not None:
        entry_details = details
    elif message is not None:
        entry_details = {'message': message}

    LoggerService.log_acao(
        acao=action,
        entidade='System',
        detalhes=entry_details,
        departamento_id=category,
        colaborador_id=user
    )
    return True

def list_log_files():
    """
    Returns available log categories/departments.
    Legacy compatibility.
    """
    return ['System', 'Restaurante', 'Recepcao', 'Fiscal', 'Geral', 'Cardápio']

def get_logs(log_type, date_str):
    """
    Retrieves logs for a specific type/department and date.
    Adapter for LoggerService.
    """
    try:
        start_date = datetime.strptime(date_str, '%Y-%m-%d')
        end_date = start_date.replace(hour=23, minute=59, second=59)
        
        dept = None
        if log_type and log_type.lower() != 'all':
            dept = log_type
            
        result = LoggerService.get_logs(
            departamento_id=dept,
            start_date=start_date,
            end_date=end_date,
            per_page=500
        )
        return result['items']
    except Exception as e:
        print(f"Error in get_logs adapter: {e}")
        return []

def export_logs_to_csv(log_type, date_str):
    """
    Exports logs to CSV format.
    """
    logs = get_logs(log_type, date_str)
    import io
    import csv
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data/Hora', 'Usuário', 'Ação', 'Entidade', 'Detalhes'])
    
    for log in logs:
        writer.writerow([
            log.get('timestamp'), 
            log.get('colaborador_id'), 
            log.get('acao'), 
            log.get('entidade'),
            log.get('detalhes')
        ])
        
    return output.getvalue()
