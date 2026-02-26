import json
import os

SESSION_ID = "SESSION_GUEST_CONSUMPTION_20260208075001_jose"
FILE_PATH = os.path.join("data", "cashier_sessions.json")

def is_cash_method(method, t_type):
    method = str(method).strip().lower()
    t_type = str(t_type).strip().lower()
    
    if 'dinheiro' in method or 'espécie' in method or 'especie' in method:
        return True
    if t_type in ['supply', 'suprimento', 'bleeding', 'sangria']:
        return True
    if 'transfer' in method or 'transferência' in method or 'transferencia' in method:
        return True
    return False

def fix_session():
    if not os.path.exists(FILE_PATH):
        print(f"File not found: {FILE_PATH}")
        return

    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        sessions = json.load(f)
    
    target = next((s for s in sessions if s['id'] == SESSION_ID), None)
    if not target:
        print(f"Session {SESSION_ID} not found.")
        return

    print(f"Found session. Current difference: {target.get('difference')}")
    
    opening = float(target.get('opening_balance', 0))
    closing = float(target.get('closing_balance', 0))
    
    total_in = 0.0
    total_out = 0.0
    
    for t in target.get('transactions', []):
        amount = float(t.get('amount', 0))
        t_type = t.get('type', '')
        method = t.get('payment_method', '')
        
        if is_cash_method(method, t_type):
            print(f"Counting cash: {amount} ({method}) [{t_type}]")
            if t_type in ['sale', 'deposit', 'in', 'supply', 'suprimento']:
                total_in += amount
            elif t_type in ['withdrawal', 'out', 'bleeding', 'sangria']:
                total_out += amount
        else:
            # print(f"Skipping non-cash: {amount} ({method})")
            pass

    calculated = opening + total_in - total_out
    difference = closing - calculated
    
    print(f"Recalculated: Opening={opening}, In={total_in}, Out={total_out}, Calc={calculated}")
    print(f"Closing={closing}, New Difference={difference}")
    
    target['difference'] = difference
    
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=4, ensure_ascii=False)
    print("File updated.")

if __name__ == "__main__":
    fix_session()
