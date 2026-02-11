import requests
import json
import logging

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, token=None, phone_id=None):
        self.token = token
        self.phone_id = phone_id
        self.base_url = "https://graph.facebook.com/v17.0"

    def send_message(self, to_number, message_text):
        """
        Sends a text message via WhatsApp Cloud API.
        
        Args:
            to_number (str): The recipient's phone number (with country code, e.g., '5511999999999').
            message_text (str): The message content.
            
        Returns:
            dict: The API response or None if failed.
        """
        if not self.token or not self.phone_id:
            logger.warning("WhatsApp credentials not configured.")
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        # Format phone number: remove non-digits
        clean_phone = "".join(filter(str.isdigit, to_number))
        
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
            return None

    def send_template(self, to_number, template_name, language_code="pt_BR", components=None):
        """
        Sends a template message via WhatsApp Cloud API.
        """
        if not self.token or not self.phone_id:
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        clean_phone = "".join(filter(str.isdigit, to_number))
        
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
            return None
