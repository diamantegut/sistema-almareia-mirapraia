import json
import os
import logging
from datetime import datetime
from app.services.system_config_manager import (
    WHATSAPP_MESSAGES_FILE as MESSAGES_FILE,
    WHATSAPP_TAGS_FILE as TAGS_FILE,
    WHATSAPP_QUICK_REPLIES_FILE as QUICK_REPLIES_FILE,
    WHATSAPP_TEMPLATES_FILE as TEMPLATES_FILE
)
from app.services.logging_service import LoggerService
logger = logging.getLogger(__name__)

class WhatsAppChatService:
    def __init__(self):
        self.ensure_file_exists()

    def _normalize_tags(self, tags):
        if tags is None:
            return []
        if isinstance(tags, str):
            t = tags.strip()
            return [t] if t else []
        if not isinstance(tags, list):
            return []
        cleaned = []
        for t in tags:
            if t is None:
                continue
            t_str = str(t).strip()
            if t_str:
                cleaned.append(t_str)
        if not cleaned:
            return []
        return [cleaned[-1]]

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
                {"name": "Nova Conversa", "color": "#0dcaf0"},
                {"name": "Resolvido", "color": "#adb5bd"}
            ]
            with open(TAGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_tags, f, ensure_ascii=False, indent=4)

        if not os.path.exists(QUICK_REPLIES_FILE):
            with open(QUICK_REPLIES_FILE, 'w', encoding='utf-8') as f:
                json.dump({"items": []}, f, ensure_ascii=False, indent=4)

        if not os.path.exists(TEMPLATES_FILE):
             with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
                json.dump([
                    {
                        "name": "hello_world",
                        "language": "en_US",
                        "label": "Hello World (Teste)"
                    }
                ], f, ensure_ascii=False, indent=4)

    def load_data(self):
        try:
            with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"conversations": {}}

    def save_data(self, data):
        with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def add_message(self, phone_number, message_data, channel='whatsapp'):
        """
        message_data should contain:
        - type: 'sent' or 'received'
        - content: text content
        - timestamp: isoformat string
        - status: 'sent', 'delivered', 'read', 'failed' (optional)
        - message_id: whatsapp message id (optional)
        
        channel: 'whatsapp' or 'facebook'
        """
        data = self.load_data()
        
        # Normalize phone number (remove non-digits)
        # For Facebook, this will be the PSID (numeric string)
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        if clean_phone not in data['conversations']:
            data['conversations'][clean_phone] = {
                "messages": [],
                "tags": ["Nova Conversa"],
                "notes": "",
                "created_at": datetime.now().isoformat(),
                "channel": channel
            }
        
        # Handle legacy list format (if conversation exists but is just a list)
        if isinstance(data['conversations'][clean_phone], list):
             data['conversations'][clean_phone] = {
                "messages": data['conversations'][clean_phone],
                "tags": [],
                "channel": 'whatsapp'
             }
            
        # Ensure tags exist if empty (legacy dict)
        if isinstance(data['conversations'][clean_phone], dict):
             if 'tags' not in data['conversations'][clean_phone]:
                 data['conversations'][clean_phone]['tags'] = []
             
             # Update channel info
             if 'channel' not in data['conversations'][clean_phone]:
                 data['conversations'][clean_phone]['channel'] = 'whatsapp'
             elif channel != data['conversations'][clean_phone]['channel']:
                 data['conversations'][clean_phone]['channel'] = channel

             # If no tags and adding a message, add 'Nova Conversa' if it's the first message or empty
             # Actually user request: "toda nova conversa ao inves da tag outros adicione uma tag automatica de nova conversa"
             # This implies when a NEW conversation starts.
             if not data['conversations'][clean_phone]['tags'] and not data['conversations'][clean_phone].get('messages'):
                  data['conversations'][clean_phone]['tags'] = ["Nova Conversa"]

        # Add ID if missing
        if 'id' not in message_data:
            import uuid
            message_data['id'] = str(uuid.uuid4())
            
        if 'messages' not in data['conversations'][clean_phone]:
            data['conversations'][clean_phone]['messages'] = []

        data['conversations'][clean_phone]["messages"].append(message_data)
        
        # Update last_activity
        data['conversations'][clean_phone]['last_activity'] = datetime.now().isoformat()
        
        self.save_data(data)
        return message_data

    def delete_message(self, phone_number, message_id, user_deleted_by="unknown"):
        """
        Removes a message from conversation and logs it to a separate file.
        Returns True if found and deleted, False otherwise.
        """
        data = self.load_data()
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        if clean_phone not in data['conversations']:
            return False
            
        conv = data['conversations'][clean_phone]
        messages = conv.get('messages', []) if isinstance(conv, dict) else conv
        
        # Find message by ID or Timestamp (if ID is missing)
        msg_to_delete = None
        msg_index = -1
        
        for i, msg in enumerate(messages):
            # Check ID match
            if msg.get('id') and str(msg.get('id')) == str(message_id):
                msg_to_delete = msg
                msg_index = i
                break
            # Fallback: check timestamp if passed ID looks like a timestamp (legacy support)
            # But let's rely on ID first. If frontend passes timestamp as ID for legacy messages?
            if not msg.get('id') and msg.get('timestamp') == message_id:
                msg_to_delete = msg
                msg_index = i
                break

        if msg_to_delete:
            # Log deletion
            self._log_deleted_message(clean_phone, msg_to_delete, user_deleted_by)
            
            # Remove from list
            messages.pop(msg_index)
            
            # Save updates
            if isinstance(conv, dict):
                conv['messages'] = messages
            else:
                data['conversations'][clean_phone] = messages # Legacy list format
                
            self.save_data(data)
            return True
            
        return False

    def _log_deleted_message(self, phone, message_data, deleted_by):
        """
        Logs deleted message to centralized LoggerService.
        """
        try:
            details = {
                "conversation_phone": phone,
                "message": message_data,
                "deleted_at": datetime.now().isoformat()
            }
            
            LoggerService.log_acao(
                acao="Exclusão de Mensagem WhatsApp",
                entidade="WhatsApp",
                detalhes=details,
                departamento_id="Comunicação",
                colaborador_id=deleted_by
            )
        except Exception as e:
            logger.error(f"Failed to log deleted message: {e}")

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
            
            data['conversations'][clean_phone]['tags'] = self._normalize_tags(tags)
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
        return self._normalize_tags(conv_data.get('tags', []))

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
                tags = self._normalize_tags(conv_data.get('tags', []))
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

    def get_templates(self):
        try:
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
             return []

    def save_templates(self, templates):
         with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=4)
            return True


    def save_tags_config(self, tags):
        with open(TAGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tags, f, ensure_ascii=False, indent=4)
        return True

    def _load_quick_replies_data(self):
        try:
            with open(QUICK_REPLIES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"items": []}
                items = data.get("items")
                if not isinstance(items, list):
                    return {"items": []}
                return {"items": items}
        except (json.JSONDecodeError, FileNotFoundError):
            return {"items": []}

    def _save_quick_replies_data(self, data):
        with open(QUICK_REPLIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True

    def get_unread_count(self, last_check_time=None):
        data = self.load_data()
        count = 0
        for phone, conv_data in data['conversations'].items():
            # Handle legacy list format
            if isinstance(conv_data, list):
                msgs = conv_data
            else:
                msgs = conv_data.get('messages', [])
            
            if not msgs:
                continue
                
            if last_check_time:
                # Count received messages newer than last_check_time
                for msg in msgs:
                    if msg.get('type') == 'received':
                        msg_time = msg.get('timestamp')
                        if msg_time and msg_time > last_check_time:
                            count += 1
            else:
                # Fallback: Count conversation if last message is received
                last_msg = msgs[-1]
                if last_msg.get('type') == 'received':
                    count += 1
        return count

    def get_quick_replies(self):
        data = self._load_quick_replies_data()
        items = data.get("items", [])
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            r_id = str(item.get("id") or "").strip()
            text = str(item.get("text") or "").strip()
            title = str(item.get("title") or "").strip()
            if not r_id or not text:
                continue
            normalized.append({
                "id": r_id,
                "title": title,
                "text": text,
                "created_at": item.get("created_at"),
                "created_by": item.get("created_by"),
                "updated_at": item.get("updated_at"),
                "updated_by": item.get("updated_by"),
            })
        normalized.sort(key=lambda x: (x.get("title") or "").lower())
        return normalized

    def add_quick_reply(self, title, text, user=None):
        title = str(title or "").strip()
        text = str(text or "").strip()
        if not text:
            return None
        import uuid
        now = datetime.now().isoformat()
        item = {
            "id": str(uuid.uuid4()),
            "title": title,
            "text": text,
            "created_at": now,
            "created_by": user,
            "updated_at": now,
            "updated_by": user,
        }
        data = self._load_quick_replies_data()
        data.setdefault("items", [])
        data["items"].append(item)
        self._save_quick_replies_data(data)
        return item

    def update_quick_reply(self, reply_id, title, text, user=None):
        reply_id = str(reply_id or "").strip()
        if not reply_id:
            return False
        title = str(title or "").strip()
        text = str(text or "").strip()
        if not text:
            return False
        data = self._load_quick_replies_data()
        items = data.get("items", [])
        now = datetime.now().isoformat()
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != reply_id:
                continue
            item["title"] = title
            item["text"] = text
            item["updated_at"] = now
            item["updated_by"] = user
            self._save_quick_replies_data({"items": items})
            return True
        return False

    def delete_quick_reply(self, reply_id):
        reply_id = str(reply_id or "").strip()
        if not reply_id:
            return False
        data = self._load_quick_replies_data()
        items = data.get("items", [])
        new_items = []
        removed = False
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == reply_id:
                removed = True
                continue
            new_items.append(item)
        if not removed:
            return False
        self._save_quick_replies_data({"items": new_items})
        return True
