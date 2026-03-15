import json
import os
import shutil
from datetime import datetime
import uuid

from app.services.system_config_manager import get_data_path

USERS_FILE = get_data_path('users.json')
HR_DATA_FILE = get_data_path('hr_data.json')
EPIS_INVENTORY_FILE = get_data_path('epis_inventory.json')
EPIS_DISTRIBUTION_FILE = get_data_path('epis_distribution.json')
# Upload folder is managed by Flask app usually, but if we want to separate data:
UPLOAD_FOLDER = get_data_path('uploads/hr')

COMPANIES = [
    "Almareia Hotel",
    "Restaurante Mirapraia",
    "Outra"
]

CONTRACT_TYPES = [
    "CLT",
    "PJ",
    "Estágio",
    "Temporário",
    "Terceirizado"
]

def load_json(filename):
    if not os.path.exists(filename):
        return {} if filename != EPIS_DISTRIBUTION_FILE else []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {} if filename != EPIS_DISTRIBUTION_FILE else []

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_all_employees():
    users = load_json(USERS_FILE)
    hr_data = load_json(HR_DATA_FILE)
    
    employees = []
    for username, user_data in users.items():
        emp_data = hr_data.get(username, {})
        # Merge basic user data with HR data
        full_data = {
            'username': username,
            'full_name': user_data.get('full_name', username),
            'role': user_data.get('role', ''),
            'department': user_data.get('department', ''),
            'admission_date': user_data.get('admission_date', ''),
            'status': emp_data.get('status', 'Ativo'), # Default to Active
            'company': emp_data.get('company', ''),
            'contract_type': emp_data.get('contract_type', ''),
            'cpf': emp_data.get('cpf', ''),
            'rg': emp_data.get('rg', ''),
            'phone': emp_data.get('phone', ''),
            'email': emp_data.get('email', ''),
            'address': emp_data.get('address', ''),
            'shirt_size': emp_data.get('shirt_size', ''),
            'shoe_size': emp_data.get('shoe_size', ''),
            'pants_size': emp_data.get('pants_size', ''),
        }
        employees.append(full_data)
    return employees

def get_employee_details(username):
    users = load_json(USERS_FILE)
    if username not in users:
        return None
    
    hr_data = load_json(HR_DATA_FILE)
    user_data = users[username]
    emp_data = hr_data.get(username, {})
    
    return {
        'username': username,
        **user_data,
        **emp_data
    }

def update_employee_hr_data(username, form_data):
    hr_data = load_json(HR_DATA_FILE)
    if username not in hr_data:
        hr_data[username] = {}
    
    # Update fields
    fields = ['cpf', 'rg', 'phone', 'email', 'address', 'shirt_size', 'shoe_size', 'pants_size', 'emergency_contact', 'status', 'termination_date', 'termination_reason', 'company', 'contract_type']
    for field in fields:
        if field in form_data:
            hr_data[username][field] = form_data[field]
            
    save_json(HR_DATA_FILE, hr_data)
    
    # Also update basic info in users.json if present
    users = load_json(USERS_FILE)
    if username in users:
        if 'full_name' in form_data:
            users[username]['full_name'] = form_data['full_name']
        if 'admission_date' in form_data:
            users[username]['admission_date'] = form_data['admission_date']
        if 'birthday' in form_data:
            users[username]['birthday'] = form_data['birthday']
        save_json(USERS_FILE, users)

def hire_employee(username, password, basic_info, hr_info):
    users = load_json(USERS_FILE)
    if username in users:
        return False, "Usuário já existe"
    
    # Create in users.json
    users[username] = {
        "password": password,
        "role": basic_info.get('role', 'user'),
        "permissions": [], # Default empty
        "full_name": basic_info.get('full_name', ''),
        "admission_date": basic_info.get('admission_date', ''),
        "birthday": basic_info.get('birthday', ''),
        "score": "0"
    }
    save_json(USERS_FILE, users)
    
    # Create in hr_data.json
    hr_data = load_json(HR_DATA_FILE)
    hr_data[username] = {
        "status": "Ativo",
        **hr_info
    }
    save_json(HR_DATA_FILE, hr_data)
    
    # Create folder
    emp_folder = os.path.join(UPLOAD_FOLDER, username)
    if not os.path.exists(emp_folder):
        os.makedirs(emp_folder)
        
    return True, "Funcionário contratado com sucesso"

def terminate_employee(username, date, reason):
    hr_data = load_json(HR_DATA_FILE)
    if username not in hr_data:
        hr_data[username] = {}
        
    hr_data[username]['status'] = 'Desligado'
    hr_data[username]['termination_date'] = date
    hr_data[username]['termination_reason'] = reason
    save_json(HR_DATA_FILE, hr_data)

# EPIs
def get_inventory():
    return load_json(EPIS_INVENTORY_FILE)

def add_epi_item(name, epi_type, stock, validity):
    inventory = load_json(EPIS_INVENTORY_FILE)
    epi_id = str(uuid.uuid4())[:8]
    inventory[epi_id] = {
        "name": name,
        "type": epi_type,
        "stock": int(stock),
        "validity_days": int(validity)
    }
    save_json(EPIS_INVENTORY_FILE, inventory)

def update_epi_stock(epi_id, quantity):
    inventory = load_json(EPIS_INVENTORY_FILE)
    if epi_id in inventory:
        inventory[epi_id]['stock'] = int(quantity)
        save_json(EPIS_INVENTORY_FILE, inventory)

def assign_epi(username, epi_id, quantity=1):
    inventory = load_json(EPIS_INVENTORY_FILE)
    if epi_id not in inventory:
        return False, "EPI não encontrado"
    
    if inventory[epi_id]['stock'] < quantity:
        return False, "Estoque insuficiente"
        
    # Deduct stock
    inventory[epi_id]['stock'] -= quantity
    save_json(EPIS_INVENTORY_FILE, inventory)
    
    # Log distribution
    log = load_json(EPIS_DISTRIBUTION_FILE)
    if not isinstance(log, list): log = []
    
    entry = {
        "id": str(uuid.uuid4()),
        "username": username,
        "epi_id": epi_id,
        "epi_name": inventory[epi_id]['name'],
        "quantity": quantity,
        "date_distributed": datetime.now().strftime("%Y-%m-%d"),
        "status": "Entregue"
    }
    log.append(entry)
    save_json(EPIS_DISTRIBUTION_FILE, log)
    return True, "EPI entregue com sucesso"

def get_employee_epis(username):
    log = load_json(EPIS_DISTRIBUTION_FILE)
    if not isinstance(log, list): return []
    return [entry for entry in log if entry['username'] == username]

# Documents
def save_employee_document(username, file, filename, doc_type):
    emp_folder = os.path.join(UPLOAD_FOLDER, username)
    if not os.path.exists(emp_folder):
        os.makedirs(emp_folder)
    
    # Add timestamp to avoid overwrite
    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    path = os.path.join(emp_folder, safe_name)
    file.save(path)
    return safe_name

def list_employee_documents(username):
    emp_folder = os.path.join(UPLOAD_FOLDER, username)
    if not os.path.exists(emp_folder):
        return []
    
    files = []
    for f in os.listdir(emp_folder):
        path = os.path.join(emp_folder, f)
        if os.path.isfile(path):
            files.append({
                "name": f,
                "date": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
                "size": os.path.getsize(path)
            })
    return files
