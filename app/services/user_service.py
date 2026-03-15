import os
import json
import hashlib
import unicodedata
from werkzeug.utils import secure_filename
from app.services.system_config_manager import get_data_path, DEPARTMENTS

USERS_FILE = get_data_path('users.json')
EX_EMPLOYEES_FILE = get_data_path('ex_employees.json')
PASSWORD_RESET_REQUESTS_FILE = get_data_path('password_reset_requests.json')

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

def load_ex_employees():
    if not os.path.exists(EX_EMPLOYEES_FILE):
        return []
    try:
        with open(EX_EMPLOYEES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_ex_employees(ex_employees):
    with open(EX_EMPLOYEES_FILE, 'w', encoding='utf-8') as f:
        json.dump(ex_employees, f, indent=4, ensure_ascii=False)

def load_reset_requests():
    if not os.path.exists(PASSWORD_RESET_REQUESTS_FILE):
        return []
    try:
        with open(PASSWORD_RESET_REQUESTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_reset_requests(requests):
    with open(PASSWORD_RESET_REQUESTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(requests, f, indent=4, ensure_ascii=False)
