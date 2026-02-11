import json
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NOTIFICATIONS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'guest_notifications.json')
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'security_settings.json')

def load_notifications():
    if not os.path.exists(NOTIFICATIONS_FILE):
        return []
    try:
        with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_notifications(data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE), exist_ok=True)
    with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def _send_email_mock(recipient, subject, body):
    """
    Simula o envio de um e-mail.
    TODO: Integrar com serviço de e-mail real (SMTP/SendGrid/AWS SES) quando credenciais estiverem disponíveis.
    Atualmente utiliza mock para desenvolvimento e testes.
    """
    logger.info(f"--- MOCK EMAIL SENDING ---")
    logger.info(f"To: {recipient}")
    logger.info(f"Subject: {subject}")
    logger.info(f"Body: {body}")
    logger.info(f"--- END MOCK EMAIL ---")
    return True

def notify_guest(guest_name, room_number, message, notification_type="cancellation"):
    """
    Registra uma notificação para o hóspede.
    Em um sistema real, isso poderia enviar um e-mail ou SMS.
    Aqui, verificamos a configuração e salvamos em um arquivo JSON.
    """
    settings = load_settings()
    
    # Check if notifications are enabled (default to True for system notifications if key is missing)
    if not settings.get('enable_guest_notifications', True):
        return False, "Notificações desativadas na configuração."

    notification = {
        "id": f"NOTIF_{datetime.now().strftime('%Y%m%d%H%M%S')}_{room_number}",
        "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "guest_name": guest_name,
        "room_number": room_number,
        "type": notification_type,
        "message": message,
        "status": "pending", # pending, sent, read
        "method": "system" # system, email, sms
    }
    
    # Check if email alerts are enabled for the guest (mock logic)
    # In a real scenario, we would look up the guest's email address from their profile
    # For this implementation, we use a placeholder or a global setting if available
    email_enabled = settings.get('enable_email_alerts', False)
    # We might assume if 'enable_email_alerts' is True, we try to send to a configured address or the guest
    
    if email_enabled:
        # Try to find a recipient. If we had a guest database, we'd use it.
        # Here we fall back to a global alert recipient or a placeholder guest email
        recipient = settings.get('alert_email_recipient', 'guest@example.com')
        
        subject = f"Aviso de Cancelamento de Consumo - Quarto {room_number}"
        body = f"Olá {guest_name},\n\n{message}\n\nAtenciosamente,\nAdministração"
        
        if _send_email_mock(recipient, subject, body):
            notification['email_sent'] = True
            notification['email_recipient'] = recipient
            notification['status'] = 'sent' # Assuming email sent means notification delivered
            notification['method'] = 'email'

    notifications = load_notifications()
    notifications.append(notification)
    save_notifications(notifications)
    
    return True, "Notificação registrada com sucesso."
