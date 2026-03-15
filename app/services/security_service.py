import json
import os
from datetime import datetime, timedelta
import uuid
from app.services.system_config_manager import get_data_path

# File Paths
ALERTS_FILE = get_data_path('security_alerts.json')
SETTINGS_FILE = get_data_path('security_settings.json')

# Default Settings
DEFAULT_SETTINGS = {
    'max_discount_percent': 10.0,
    'max_open_time_minutes': 240, # 4 hours
    'min_transaction_value': 5.0, # Flag closing under this amount
    'alert_retention_days': 45
}

def load_security_settings():
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            # Ensure all keys exist
            for key, value in DEFAULT_SETTINGS.items():
                if key not in settings:
                    settings[key] = value
            return settings
    except:
        return DEFAULT_SETTINGS

def save_security_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving security settings: {e}")
        return False

def load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_alerts(alerts):
    try:
        with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving alerts: {e}")
        return False

def log_security_alert(alert_type, severity, details, user, transaction_id=None):
    """
    Logs a security alert.
    Severity: 'Critical', 'High', 'Medium', 'Low'
    """
    alerts = load_alerts()
    
    alert = {
        'id': str(uuid.uuid4()),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'type': alert_type,
        'severity': severity,
        'details': details,
        'user': user,
        'transaction_id': transaction_id,
        'status': 'Open' # Open, Reviewed, Resolved
    }
    
    # Insert at beginning
    alerts.insert(0, alert)
    
    # Prune old alerts based on retention policy
    try:
        settings = load_security_settings()
        retention_days = settings.get('alert_retention_days', 45)
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        # Filter alerts newer than cutoff_date
        alerts = [
            a for a in alerts 
            if datetime.strptime(a['timestamp'], '%Y-%m-%d %H:%M:%S') > cutoff_date
        ]
    except Exception as e:
        print(f"Error pruning security alerts: {e}")
        # Fallback to count limit if date parsing fails
        if len(alerts) > 1000:
            alerts = alerts[:1000]
        
    save_alerts(alerts)
    return alert

def update_alert_status(alert_id, new_status, user):
    """
    Updates the status of an alert.
    Status: 'New', 'Viewed', 'Resolved'
    """
    alerts = load_alerts()
    for alert in alerts:
        if alert['id'] == alert_id:
            alert['status'] = new_status
            if new_status == 'Resolved':
                alert['resolved_by'] = user
                alert['resolved_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            elif new_status == 'Viewed':
                alert['viewed_by'] = user
                alert['viewed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            save_alerts(alerts)
            return True
    return False

# --- Check Functions ---

def check_discount_alert(discount_value, subtotal, user, transaction_id=None):
    if subtotal <= 0:
        return
    
    settings = load_security_settings()
    percent = (discount_value / subtotal) * 100
    
    if percent > settings['max_discount_percent']:
        details = f"Desconto de {percent:.2f}% (R$ {discount_value:.2f}) aplicado em subtotal de R$ {subtotal:.2f}. Limite: {settings['max_discount_percent']}%"
        log_security_alert(
            alert_type="Desconto Excessivo",
            severity="High" if percent > (settings['max_discount_percent'] * 1.5) else "Medium",
            details=details,
            user=user,
            transaction_id=transaction_id
        )

def check_commission_manipulation(item_name, qty, price, user, table_id, order_locked=False):
    """
    Checks for suspicious item removals, especially after bill printing (locked).
    """
    settings = load_security_settings()
    total_value = qty * price
    
    # Critical: Removing item after bill is printed
    if order_locked:
        log_security_alert(
            alert_type="Manipulação de Comissão (Pós-Fechamento)",
            severity="Critical",
            details=f"Item '{item_name}' (x{qty}, R$ {total_value:.2f}) removido da Mesa {table_id} APÓS impressão da conta (Locked).",
            user=user
        )
        return

    # High/Medium: High value removal
    # Threshold for high value removal, e.g., 50.00
    high_val_threshold = 50.0
    if total_value > high_val_threshold:
        log_security_alert(
            alert_type="Remoção de Item de Alto Valor",
            severity="Medium",
            details=f"Item '{item_name}' (x{qty}, R$ {total_value:.2f}) removido da Mesa {table_id}.",
            user=user
        )

def check_table_transfer_anomaly(source_table, target_table, user):
    """
    Checks for frequent transfers.
    """
    # Simple frequency check: Count recent transfer alerts for this user
    alerts = load_alerts()
    now = datetime.now()
    
    recent_count = 0
    time_window_mins = 30
    
    for alert in alerts[:50]: # Check last 50 alerts
        if alert['type'] == 'Transferência de Mesa' and alert['user'] == user:
            try:
                alert_time = datetime.strptime(alert['timestamp'], '%Y-%m-%d %H:%M:%S')
                if (now - alert_time).total_seconds() < (time_window_mins * 60):
                    recent_count += 1
            except:
                pass
    
    # If more than 3 transfers in 30 mins, flag it
    if recent_count >= 3:
        log_security_alert(
            alert_type="Transferências Frequentes",
            severity="High",
            details=f"Usuário {user} realizou {recent_count + 1} transferências em {time_window_mins} minutos.",
            user=user
        )
    else:
        # Log the transfer itself as a low priority event to build history
        log_security_alert(
            alert_type="Transferência de Mesa",
            severity="Low",
            details=f"Transferência da Mesa {source_table} para {target_table}.",
            user=user
        )

def check_sensitive_access(action, user, details=""):
    """
    Checks for access to sensitive functions outside business hours (e.g., 03:00 - 06:00).
    """
    now = datetime.now()
    hour = now.hour
    
    # Suspicious hours: 3 AM to 6 AM (example)
    if 3 <= hour < 6:
        log_security_alert(
            alert_type="Acesso Fora de Horário",
            severity="High",
            details=f"Ação '{action}' executada fora do horário comercial ({now.strftime('%H:%M')}). {details}",
            user=user
        )
    else:
        # Just log as Low for audit
        log_security_alert(
            alert_type="Acesso Sensível",
            severity="Low",
            details=f"Ação '{action}' executada. {details}",
            user=user
        )

def check_table_closing_anomalies(table_id, duration_minutes, total_value, user):
    settings = load_security_settings()
    
    alerts = []
    
    # Check Duration vs Value
    # If table open for > max_time
    if duration_minutes > settings['max_open_time_minutes']:
        log_security_alert(
            "Mesa Aberta Longo Período", 
            "Medium", 
            f"Mesa {table_id} permaneceu aberta por {int(duration_minutes)} minutos.", 
            user
        )
        
    # Check Quick Close / Low Value
    # Example: Closed in < 5 mins with value < X
    if duration_minutes < 10 and total_value < settings['min_transaction_value']:
        log_security_alert(
            "Fechamento Suspeito", 
            "Medium", 
            f"Mesa {table_id} fechada em {int(duration_minutes)} min com valor total R$ {total_value:.2f} (Abaixo do mínimo).", 
            user
        )

