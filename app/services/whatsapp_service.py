import requests
import json
import logging

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, token=None, phone_id=None):
        self.token = token
        self.phone_id = phone_id
        self.base_url = "https://graph.facebook.com/v17.0"
        self.last_error = None

    def _normalize_to(self, to_number):
        digits = "".join(filter(str.isdigit, str(to_number or "")))
        if not digits:
            return ""
        if not digits.startswith("55") and len(digits) in (10, 11):
            digits = f"55{digits}"
        return digits

    def send_message(self, to_number, message_text):
        """
        Sends a text message via WhatsApp Cloud API.
        
        Args:
            to_number (str): The recipient's phone number (with country code, e.g., '5511999999999').
            message_text (str): The message content.
            
        Returns:
            dict: The API response or None if failed.
        """
        self.last_error = None
        if not self.token or not self.phone_id:
            logger.warning("WhatsApp credentials not configured.")
            self.last_error = "api_not_configured"
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        clean_phone = self._normalize_to(to_number)
        if not clean_phone:
            self.last_error = "invalid_phone"
            return None
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": message_text
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp message: {e}")
            if hasattr(e, 'response') and e.response:
                 logger.error(f"Response content: {e.response.text}")
                 error_data = {}
                 try:
                     error_data = e.response.json()
                 except:
                     pass
                 
                 # Check for 24h window error (Code 131047)
                 # Structure: {"error": {"message": "...", "code": 131047, ...}}
                 error_code = error_data.get('error', {}).get('code')
                 if error_code == 131047:
                     self.last_error = "Janela de 24h fechada (Code 131047). Envie um Modelo (Template) para iniciar a conversa."
                 else:
                     self.last_error = e.response.text
            else:
                self.last_error = str(e)
            return None

    def send_template(self, to_number, template_name, language_code="pt_BR", components=None):
        """
        Sends a template message via WhatsApp Cloud API.
        """
        self.last_error = None
        if not self.token or not self.phone_id:
            self.last_error = "api_not_configured"
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        clean_phone = self._normalize_to(to_number)
        if not clean_phone:
            self.last_error = "invalid_phone"
            return None
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            }
        }
        
        if components:
            payload["template"]["components"] = components

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp template: {e}")
            if hasattr(e, 'response') and e.response:
                self.last_error = e.response.text
            else:
                self.last_error = str(e)
            return None
