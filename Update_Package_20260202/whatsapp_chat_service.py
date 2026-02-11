import json
import os
import logging
from datetime import datetime
from system_config_manager import get_data_path

MESSAGES_FILE = get_data_path('whatsapp_messages.json')
TAGS_FILE = get_data_path('whatsapp_tags.json')
logger = logging.getLogger(__name__)

class WhatsAppChatService:
    def __init__(self):
        self.ensure_file_exists()

    def ensure_file_exists(self):
        os.makedirs(os.path.dirname(MESSAGES_FILE), exist_ok=True)
        if not os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
                json.dump({"conversations": {}}, f, ensure_ascii=False, indent=4)
        
        if not os.path.exists(TAGS_FILE):
            # Defaults if not created
            default_tags = [
                {"name": "Hotel", "color": "#0d6efd"},
                {"name": "Restaurante", "color": "#198754"},
                {"name": "Orçamento de Reserva em Espera", "color": "#ffc107"},
                {"name": "Passante do Restaurante", "color": "#0dcaf0"},
                {"name": "Esperando Resposta", "color": "#6c757d"},
                {"name": "Dívida Resolvida", "color": "#20c997"},
                {"name": "Reserva", "color": "#6610f2"},
                {"name": "Dúvida", "color": "#fd7e14"},
                {"name": "Financeiro", "color": "#d63384"},
                {"name": "Resolvido", "color": "#adb5bd"}
            ]
            with open(TAGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_tags, f, ensure_ascii=False, indent=4)

    def load_data(self):
        try:
            with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"conversations": {}}

    def save_data(self, data):
        with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def add_message(self, phone_number, message_data):
        """
        message_data should contain:
        - type: 'sent' or 'received'
        - content: text content
        - timestamp: isoformat string
        - status: 'sent', 'delivered', 'read', 'failed' (optional)
        - message_id: whatsapp message id (optional)
        """
        data = self.load_data()
        
        # Normalize phone number (remove non-digits)
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        if clean_phone not in data['conversations']:
            data['conversations'][clean_phone] = {
                "messages": [],
                "tags": []
            }
        
        # Handle legacy list format (if conversation exists but is just a list)
        if isinstance(data['conversations'][clean_phone], list):
             data['conversations'][clean_phone] = {
                "messages": data['conversations'][clean_phone],
                "tags": []
             }
            
        # Add ID if missing
        if 'id' not in message_data:
            import uuid
            message_data['id'] = str(uuid.uuid4())
            
        data['conversations'][clean_phone]["messages"].append(message_data)
        self.save_data(data)
        return message_data

    def update_tags(self, phone_number, tags):
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        if clean_phone not in data['conversations']:
            data['conversations'][clean_phone] = {
                "messages": [],
                "tags": [],
                "name": ""
            }

        if clean_phone in data['conversations']:
            # Handle legacy
            if isinstance(data['conversations'][clean_phone], list):
                 data['conversations'][clean_phone] = {
                    "messages": data['conversations'][clean_phone],
                    "tags": [],
                    "name": ""
                 }
            
            data['conversations'][clean_phone]['tags'] = tags
            self.save_data(data)
            return True
        return False

    def update_contact_name(self, phone_number, name):
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        if clean_phone not in data['conversations']:
            data['conversations'][clean_phone] = {
                "messages": [],
                "tags": [],
                "name": name
            }
        else:
            # Handle legacy
            if isinstance(data['conversations'][clean_phone], list):
                 data['conversations'][clean_phone] = {
                    "messages": data['conversations'][clean_phone],
                    "tags": [],
                    "name": name
                 }
            else:
                data['conversations'][clean_phone]['name'] = name
                
        self.save_data(data)
        return True

    def get_messages(self, phone_number):
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        conv_data = data['conversations'].get(clean_phone, {})
        
        if isinstance(conv_data, list):
            return conv_data
        return conv_data.get('messages', [])

    def get_tags(self, phone_number):
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        conv_data = data['conversations'].get(clean_phone, {})
        
        if isinstance(conv_data, list):
            return []
        return conv_data.get('tags', [])

    def get_contact_name(self, phone_number):
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        conv_data = data['conversations'].get(clean_phone, {})
        
        if isinstance(conv_data, list):
            return ""
        return conv_data.get('name', "")

    def get_all_conversations(self):
        data = self.load_data()
        conversations = []
        for phone, conv_data in data['conversations'].items():
            # Handle legacy list format
            if isinstance(conv_data, list):
                msgs = conv_data
                tags = []
                name = ""
            else:
                msgs = conv_data.get('messages', [])
                tags = conv_data.get('tags', [])
                name = conv_data.get('name', "")
                
            last_msg = msgs[-1] if msgs else None
            conversations.append({
                'phone': phone,
                'last_message': last_msg,
                'message_count': len(msgs),
                'tags': tags,
                'name': name
            })
        # Sort by last message timestamp desc
        conversations.sort(key=lambda x: x['last_message']['timestamp'] if x['last_message'] else '', reverse=True)
        return conversations

    def get_tags_config(self):
        try:
            with open(TAGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_tags_config(self, tags):
        with open(TAGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tags, f, ensure_ascii=False, indent=4)
        return True
