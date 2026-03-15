import json
import os
import logging
from app.services.system_config_manager import get_data_path

# Configure logger
logger = logging.getLogger(__name__)

PRINTERS_FILE = get_data_path('printers.json')
PRINTER_SETTINGS_FILE = get_data_path('printer_settings.json')

def load_printers():
    if not os.path.exists(PRINTERS_FILE):
        return []
    try:
        with open(PRINTERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {PRINTERS_FILE}")
        return []
    except Exception as e:
        logger.error(f"Error loading printers: {e}")
        return []

def save_printers(printers):
    try:
        with open(PRINTERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(printers, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving printers: {e}")

def load_printer_settings():
    abs_path = os.path.abspath(PRINTER_SETTINGS_FILE)
    if not os.path.exists(abs_path):
        logger.debug(f"Printer settings file not found at {abs_path}")
        return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}
            data = json.loads(content)
            
            if 'frigobar_filter_enabled' not in data:
                data['frigobar_filter_enabled'] = True
            return data
    except Exception as e:
        logger.error(f"Error reading printer settings: {e}")
        return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}

def save_printer_settings(settings):
    try:
        with open(PRINTER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving printer settings: {e}")
