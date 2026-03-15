import json
import os
import uuid
from datetime import datetime
from app.services.system_config_manager import get_data_path, BASE_DIR, PASSWORD_RESET_REQUESTS_FILE
from cryptography.fernet import Fernet
import json

def _load_json(filepath, default=None):
    if default is None: default = []
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default

def _save_json(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
        return False

def load_reset_requests(): return _load_json(PASSWORD_RESET_REQUESTS_FILE, [])
def save_reset_requests(data): return _save_json(PASSWORD_RESET_REQUESTS_FILE, data)

DOCUMENTS_FILE = get_data_path('rh_documents.json')
KEY_FILE = get_data_path('rh_secret.key')
UPLOADS_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'rh_documents')

if not os.path.exists(UPLOADS_DIR):
    os.makedirs(UPLOADS_DIR, exist_ok=True)

def load_key():
    """Loads the encryption key from file or generates a new one."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        return key

def load_documents():
    """Loads and decrypts documents from the JSON file."""
    if not os.path.exists(DOCUMENTS_FILE):
        return []
    
    try:
        with open(DOCUMENTS_FILE, 'rb') as f:
            data = f.read()
            
        if not data:
            return []
            
        key = load_key()
        f = Fernet(key)
        
        try:
            # Try to decrypt
            decrypted_data = f.decrypt(data)
            return json.loads(decrypted_data.decode('utf-8'))
        except Exception:
            # Fallback for unencrypted data (migration support)
            try:
                return json.loads(data.decode('utf-8'))
            except:
                return []
                
    except Exception as e:
        print(f"Error loading documents: {e}")
        return []

def save_documents(docs):
    """Encrypts and saves documents to the JSON file."""
    try:
        key = load_key()
        f = Fernet(key)
        
        json_data = json.dumps(docs, indent=4)
        encrypted_data = f.encrypt(json_data.encode('utf-8'))
        
        with open(DOCUMENTS_FILE, 'wb') as file:
            file.write(encrypted_data)
            
    except Exception as e:
        print(f"Error saving documents: {e}")

def create_document(title, filename, created_by, assigned_to):
    docs = load_documents()
    doc_id = str(uuid.uuid4())
    
    new_doc = {
        'id': doc_id,
        'title': title,
        'filename': filename,
        'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'created_by': created_by,
        'assigned_to': assigned_to,
        'status': 'pending',
        'audit_log': [
            {
                'action': 'created',
                'by': created_by,
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        ]
    }
    
    docs.append(new_doc)
    save_documents(docs)
    return doc_id

def sign_document(doc_id, signature_data, signer_username):
    docs = load_documents()
    for doc in docs:
        if doc['id'] == doc_id:
            if doc['assigned_to'] != signer_username:
                return False, "Usuário não autorizado a assinar este documento."
            
            doc['status'] = 'signed'
            doc['signature_data'] = signature_data
            doc['signed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
            doc['audit_log'].append({
                'action': 'signed',
                'by': signer_username,
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')
            })
            save_documents(docs)
            return True, "Documento assinado com sucesso."
    return False, "Documento não encontrado."

def get_user_documents(username):
    docs = load_documents()
    # Sort by created_at desc
    docs.sort(key=lambda x: datetime.strptime(x['created_at'], '%d/%m/%Y %H:%M'), reverse=True)
    return [d for d in docs if d.get('assigned_to') == username]

def get_all_documents():
    docs = load_documents()
    docs.sort(key=lambda x: datetime.strptime(x['created_at'], '%d/%m/%Y %H:%M'), reverse=True)
    return docs

def get_document_by_id(doc_id):
    docs = load_documents()
    return next((d for d in docs if d['id'] == doc_id), None)
