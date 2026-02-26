
import json
import os
import sys
import shutil
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system_config_manager import CASHIER_SESSIONS_FILE as DATA_FILE
BACKUP_FILE = f"{DATA_FILE}.bak"

def load_sessions():
    if not os.path.exists(DATA_FILE):
        print(f"File not found: {DATA_FILE}")
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_sessions(sessions):
    # Backup first
    shutil.copy2(DATA_FILE, BACKUP_FILE)
    print(f"Backup created at {BACKUP_FILE}")
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=4, ensure_ascii=False)
    print("File updated.")

def fix_transfers():
    sessions = load_sessions()
    print(f"Loaded {len(sessions)} sessions.")
    
    modified = False
    count = 0
    
    for s in sessions:
        for t in s.get('transactions', []):
            if t.get('type') == 'transfer':
                print(f"Fixing transaction {t.get('id')} in session {s.get('id')}...")
                print(f"  Old type: transfer")
                t['type'] = 'out' # Assume transfer means OUT
                t['category'] = 'Transferência Enviada'
                if not t.get('payment_method'):
                    t['payment_method'] = 'Transferência'
                print(f"  New type: out")
                modified = True
                count += 1
                
    if modified:
        save_sessions(sessions)
        print(f"Fixed {count} transactions.")
    else:
        print("No 'transfer' type transactions found.")

if __name__ == '__main__':
    fix_transfers()
