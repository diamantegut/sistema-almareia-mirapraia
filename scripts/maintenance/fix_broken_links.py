import os
import json
import shutil
import uuid
from datetime import datetime

import sys
# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from system_config_manager import get_data_path

# Constants
CASHIER_SESSIONS_FILE = get_data_path('cashier_sessions.json')

def load_sessions():
    if not os.path.exists(CASHIER_SESSIONS_FILE):
        return []
    with open(CASHIER_SESSIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_sessions(sessions):
    temp_path = CASHIER_SESSIONS_FILE + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=4, ensure_ascii=False)
    os.replace(temp_path, CASHIER_SESSIONS_FILE)
    print("Sessions saved.")

def parse_dt(dt_str):
    try:
        return datetime.strptime(dt_str, '%d/%m/%Y %H:%M')
    except:
        return None

def find_target_session(sessions, target_type, tx_timestamp_str):
    tx_dt = parse_dt(tx_timestamp_str)
    if not tx_dt:
        return None
        
    candidates = []
    
    # Normalize target type
    target_types = [target_type]
    if target_type == 'reception':
        target_types = ['reception', 'reception_room_billing', 'guest_consumption']
    elif target_type == 'restaurant':
        target_types = ['restaurant', 'restaurant_service']
        
    for s in sessions:
        if s.get('type') in target_types:
            opened_at = parse_dt(s.get('opened_at'))
            closed_at = parse_dt(s.get('closed_at'))
            
            if opened_at and opened_at <= tx_dt:
                if closed_at:
                    if closed_at >= tx_dt:
                        return s
                else:
                    # Open session, check if it was opened before tx
                    # Assuming it's still open or was open at that time
                    return s
    return None

def recalculate_session_balance(session):
    opening = float(session.get('opening_balance', 0))
    total_in = 0.0
    total_out = 0.0
    
    for t in session.get('transactions', []):
        try:
            amt = float(t.get('amount', 0))
        except:
            amt = 0.0
            
        t_type = str(t.get('type', '')).lower()
        if t_type in ['out', 'withdrawal', 'refund']:
            total_out += abs(amt)
        elif t_type in ['in', 'deposit', 'sale']:
            total_in += abs(amt)
        else:
            # Fallback based on amount sign
            if amt < 0:
                total_out += abs(amt)
            else:
                total_in += abs(amt)
                
    calc = opening + total_in - total_out
    
    if session.get('status') == 'closed':
        # Update closing balance to match calculated? 
        # Or just update difference?
        # If we added a transaction, the actual money in drawer (closing_balance) didn't change physically,
        # but the expected balance (calculated) changed.
        # So 'difference' should change.
        # But wait, if this was a transfer that physically happened but wasn't recorded, 
        # then the money WAS in the drawer.
        # If the user counted the money and closed the register, they would have found EXTRA money 
        # (if it was an incoming transfer that wasn't recorded).
        # So the 'difference' would have been positive (Surplus).
        # Now we record the transfer, the calculated balance increases.
        # So 'difference' (Closing - Calculated) should decrease (become closer to 0).
        
        session['closing_balance'] = float(session.get('closing_balance', 0)) # Keep what user counted
        session['difference'] = session['closing_balance'] - calc
    
    return session

def fix_broken_links():
    sessions = load_sessions()
    
    # Index transactions by document_id
    doc_map = {}
    for s in sessions:
        for t in s.get('transactions', []):
            doc_id = t.get('document_id')
            if doc_id:
                if doc_id not in doc_map:
                    doc_map[doc_id] = []
                doc_map[doc_id].append({'session': s, 'trans': t})
    
    broken_count = 0
    fixed_count = 0
    
    for doc_id, items in doc_map.items():
        if len(items) == 1:
            item = items[0]
            s = item['session']
            t = item['trans']
            
            print(f"Broken Link: {doc_id}")
            print(f"  Existing: {s['type']} ({t['type']}) {t['amount']}")
            
            # Determine missing partner
            if t['type'] == 'out':
                # Missing IN
                target_type = 'reception' if 'restaurant' in s['type'] else 'restaurant'
                missing_type = 'in'
                desc_prefix = f"Transferência de {s['type']}"
            else:
                # Missing OUT
                target_type = 'reception' if 'restaurant' in s['type'] else 'restaurant'
                missing_type = 'out'
                desc_prefix = f"Transferência para {target_type}"
            
            # Find target session
            target_s = find_target_session(sessions, target_type, t['timestamp'])
            
            if target_s:
                print(f"  Found target session: {target_s['id']} ({target_s['status']})")
                
                new_trans = {
                    "id": f"TRANS_{doc_id}_FIX_{missing_type.upper()}",
                    "document_id": doc_id,
                    "type": missing_type,
                    "category": "Transferência Recebida" if missing_type == 'in' else "Transferência Enviada",
                    "amount": t['amount'],
                    "description": f"{desc_prefix} (Recuperado)",
                    "payment_method": "Transferência",
                    "timestamp": t['timestamp'],
                    "time": t.get('time', '00:00'),
                    "user": t.get('user', 'System Fix')
                }
                
                target_s['transactions'].append(new_trans)
                recalculate_session_balance(target_s)
                fixed_count += 1
                print(f"  Created missing {missing_type} transaction in {target_s['id']}")
            else:
                print(f"  Could not find target session for type {target_type} at {t['timestamp']}")
                
            broken_count += 1

    if fixed_count > 0:
        save_sessions(sessions)
        print(f"Fixed {fixed_count} broken links.")
    else:
        print("No fixes applied.")

if __name__ == "__main__":
    fix_broken_links()
