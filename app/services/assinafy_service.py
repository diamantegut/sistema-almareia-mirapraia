import requests
import json
import os
from app.services.system_config_manager import get_config_value

API_BASE_URL = "https://api.assinafy.com.br/v1"

def get_headers():
    token = os.environ.get('ASSINAFY_API_TOKEN') or get_config_value('assinafy_api_token', 'YOUR_API_TOKEN')
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def get_account_id():
    return os.environ.get('ASSINAFY_ACCOUNT_ID') or get_config_value('assinafy_account_id', 'YOUR_ACCOUNT_ID')

def create_signer(name, email, phone=None):
    """
    Creates a signer in Assinafy.
    
    Args:
        name (str): Full name of the signer.
        email (str): Email of the signer.
        phone (str, optional): Phone number (E.164 format, e.g., +5511999999999).
        
    Returns:
        dict: API response with signer details or error.
    """
    account_id = get_account_id()
    if not account_id or account_id == 'YOUR_ACCOUNT_ID':
        return {"error": "Assinafy Account ID not configured."}

    url = f"{API_BASE_URL}/accounts/{account_id}/signers"
    
    payload = {
        "full_name": name,
        "email": email
    }
    
    if phone:
        payload["phone"] = phone
        
    try:
        response = requests.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if response.text:
            try:
                error_data = response.json()
                error_msg = error_data.get('message', error_msg)
            except:
                error_msg = response.text
        return {"error": error_msg}

def list_signers():
    account_id = get_account_id()
    if not account_id:
        return {"error": "Account ID missing"}
        
    url = f"{API_BASE_URL}/accounts/{account_id}/signers"
    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
