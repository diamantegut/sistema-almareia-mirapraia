import json
import os
import uuid
from datetime import datetime, timedelta
from whatsapp_service import WhatsAppService

WAITING_LIST_FILE = os.path.join('data', 'waiting_list.json')

def load_waiting_data():
    default_settings = {
        "is_open": True,
        "max_queue_size": 50,
        "average_wait_per_party": 15, # minutes
        "critical_wait_threshold": 45, # minutes
        "whatsapp_api_token": "",
        "whatsapp_phone_id": ""
    }
    
    if not os.path.exists(WAITING_LIST_FILE):
        return {
            "queue": [],
            "history": [],
            "settings": default_settings
        }
    try:
        with open(WAITING_LIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure settings exist and have defaults
            if "settings" not in data:
                data["settings"] = default_settings
            else:
                for key, value in default_settings.items():
                    if key not in data["settings"]:
                        data["settings"][key] = value
            return data
    except json.JSONDecodeError:
        return {
            "queue": [],
            "history": [],
            "settings": default_settings
        }

def save_waiting_data(data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(WAITING_LIST_FILE), exist_ok=True)
    with open(WAITING_LIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_waiting_list():
    data = load_waiting_data()
    # Filter only waiting status for the active queue view
    active_queue = [item for item in data.get('queue', []) if item['status'] == 'waiting']
    # Sort by entry time
    active_queue.sort(key=lambda x: x['entry_time'])
    return active_queue

def get_settings():
    data = load_waiting_data()
    return data.get('settings', {})

def update_settings(new_settings):
    data = load_waiting_data()
    data['settings'].update(new_settings)
    save_waiting_data(data)
    return data['settings']

def add_customer(name, phone, party_size):
    data = load_waiting_data()
    
    if not data['settings']['is_open']:
        return None, "A fila de espera está fechada no momento."
        
    active_count = sum(1 for item in data['queue'] if item['status'] == 'waiting')
    if active_count >= data['settings']['max_queue_size']:
        return None, "A fila de espera atingiu a capacidade máxima."

    # Calculate estimated wait time
    # Simple heuristic: (number of parties * avg wait) / (concurrent tables turning approx 1/3)
    # Or just sum of avg wait per party? Let's keep it simple: avg * count
    estimated_wait = active_count * data['settings']['average_wait_per_party'] // 2 # Rough estimate assuming concurrency
    if estimated_wait < 10: estimated_wait = 10
    
    new_entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": phone,
        "party_size": int(party_size),
        "entry_time": datetime.now().isoformat(),
        "status": "waiting",
        "estimated_wait_minutes": estimated_wait,
        "notifications": []
    }
    
    data['queue'].append(new_entry)
    save_waiting_data(data)
    
    # Return position (1-based index)
    position = active_count + 1
    return {
        "entry": new_entry,
        "position": position,
        "estimated_wait": estimated_wait
    }, None

def update_customer_status(customer_id, new_status, reason=None, user=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    
    for item in queue:
        if item['id'] == customer_id:
            old_status = item['status']
            item['status'] = new_status
            item['last_updated'] = datetime.now().isoformat()
            if reason:
                item['status_reason'] = reason
            if user:
                item['updated_by'] = user
                
            # If moving to final state, maybe move to history? 
            # For now, keep in queue list but filtered out in get_waiting_list
            # Periodically we can archive to history
            
            save_waiting_data(data)
            return item
            
    return None

def log_notification(customer_id, type, method="whatsapp", user="system"):
    data = load_waiting_data()
    queue = data.get('queue', [])
    
    for item in queue:
        if item['id'] == customer_id:
            notification = {
                "type": type,
                "method": method,
                "timestamp": datetime.now().isoformat(),
                "sent_by": user
            }
            if "notifications" not in item:
                item["notifications"] = []
            item["notifications"].append(notification)
            save_waiting_data(data)
            return True
    return False

from whatsapp_chat_service import WhatsAppChatService

def send_notification(customer_id, message_type, user=None):
    """
    Sends a WhatsApp notification to a waiting list customer.
    
    Args:
        customer_id (str): The ID of the customer in the waiting list.
        message_type (str): 'table_ready', 'welcome', or 'cancellation'
        user (str): Username triggering the action (for logging)
        
    Returns: (success, message_or_error)
    """
    settings = get_settings()
    token = settings.get('whatsapp_api_token')
    phone_id = settings.get('whatsapp_phone_id')
    
    if not token or not phone_id:
        return False, "api_not_configured"
        
    data = load_waiting_data()
    queue = data.get('queue', [])
    customer = next((item for item in queue if item['id'] == customer_id), None)
    
    if not customer:
        return False, "Customer not found"
        
    wa_service = WhatsAppService(token, phone_id)
    chat_service = WhatsAppChatService()
    
    message = ""
    if message_type == "table_ready":
        message = f"Olá {customer['name']}, sua mesa no Restaurante Mirapraia está pronta! Por favor, compareça à recepção."
    elif message_type == "welcome":
        message = f"Olá {customer['name']}, confirmamos sua entrada na fila de espera do Mirapraia. Avisaremos por aqui quando sua mesa estiver pronta."
    else:
        message = f"Olá {customer['name']}, notificação do Restaurante Mirapraia."
        
    result = wa_service.send_message(customer['phone'], message)
    
    if result:
        # Log to chat history
        msg_data = {
            'type': 'sent',
            'content': message,
            'timestamp': datetime.now().isoformat(),
            'status': 'sent'
        }
        chat_service.add_message(customer['phone'], msg_data)
        
        # Also ensure name is saved in chat contact
        chat_service.update_contact_name(customer['phone'], customer['name'])
        
        # If welcome message, add 'Restaurante' tag automatically? 
        # Or maybe a specific tag. Let's add "Restaurante" if not present.
        # current_tags = chat_service.get_tags(customer['phone'])
        # if "Restaurante" not in current_tags:
        #    current_tags.append("Restaurante")
        #    chat_service.update_tags(customer['phone'], current_tags)
        
        log_notification(customer_id, message_type, method="whatsapp_api", user=user)
        return True, message
    else:
        return False, "Failed to send message via API"

def get_queue_metrics():
    data = load_waiting_data()
    queue = data.get('queue', [])
    active_count = sum(1 for x in queue if x['status'] == 'waiting')
    
    # Calculate average wait time today
    today_str = datetime.now().strftime('%Y-%m-%d')
    completed_today = [
        x for x in queue 
        if x['status'] == 'seated' and x['entry_time'].startswith(today_str)
    ]
    
    avg_wait = 0
    if completed_today:
        total_wait = 0
        for item in completed_today:
            entry = datetime.fromisoformat(item['entry_time'])
            seated = datetime.fromisoformat(item['last_updated'])
            total_wait += (seated - entry).total_seconds() / 60
        avg_wait = int(total_wait / len(completed_today))
        
    return {
        "active_count": active_count,
        "avg_wait_today": avg_wait
    }
