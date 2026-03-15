import requests
import json
import logging
import os

logger = logging.getLogger(__name__)

class FacebookService:
    def __init__(self, page_access_token=None, page_id=None):
        self.page_access_token = page_access_token or os.environ.get('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.page_id = page_id or os.environ.get('FACEBOOK_PAGE_ID')
        self.base_url = "https://graph.facebook.com/v17.0"
        self.last_error = None

    def send_message(self, recipient_id, message_text):
        """
        Sends a text message via Facebook Messenger API.
        
        Args:
            recipient_id (str): The recipient's PSID (Page Scoped ID).
            message_text (str): The message content.
            
        Returns:
            dict: The API response or None if failed.
        """
        self.last_error = None
        if not self.page_access_token:
            logger.warning("Facebook Page Access Token not configured.")
            self.last_error = "api_not_configured"
            return None

        url = f"{self.base_url}/me/messages"
        params = {
            "access_token": self.page_access_token
        }
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "recipient": {
                "id": recipient_id
            },
            "message": {
                "text": message_text
            },
            "messaging_type": "RESPONSE"
        }

        try:
            response = requests.post(url, params=params, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending Facebook message: {e}")
            if hasattr(e, 'response') and e.response:
                 logger.error(f"Response content: {e.response.text}")
                 self.last_error = e.response.text
            else:
                self.last_error = str(e)
            return None
