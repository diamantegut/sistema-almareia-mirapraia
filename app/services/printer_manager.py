import json
import os
from app.services.system_config_manager import get_data_path

PRINTERS_FILE = get_data_path('printers.json')
PRINTER_SETTINGS_FILE = get_data_path('printer_settings.json')

def load_printers():
    if not os.path.exists(PRINTERS_FILE):
        return []
    try:
        with open(PRINTERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_printers(printers):
    with open(PRINTERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(printers, f, indent=4, ensure_ascii=False)

def load_printer_settings():
    abs_path = os.path.abspath(PRINTER_SETTINGS_FILE)
    print(f"DEBUG: Loading printer settings from {abs_path}")
    if not os.path.exists(abs_path):
        print(f"DEBUG: Printer settings file does not exist at {abs_path}")
        return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"DEBUG: Raw file content: {content}")
            if not content.strip():
                print("DEBUG: File is empty")
                return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}
            data = json.loads(content)
            print(f"DEBUG: Parsed JSON: {data}")
            if 'frigobar_filter_enabled' not in data:
                data['frigobar_filter_enabled'] = True
            return data
    except Exception as e:
        print(f"DEBUG: Error reading printer settings: {e}")
        return {'bill_printer_id': None, 'fiscal_printer_id': None, 'frigobar_filter_enabled': True}

def save_printer_settings(settings):
    with open(PRINTER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
