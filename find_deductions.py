import json
import os
from datetime import datetime

DATA_PATH = r"f:\Sistema Almareia Mirapraia\data\cashier_sessions.json"

def search_deductions():
    if not os.path.exists(DATA_PATH):
        print(f"File not found: {DATA_PATH}")
        return

    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return

    targets = [
        {"date": "18/02/2026", "time": "16:42", "amount": 518.07, "user": "guilherme"},
        {"date": "17/02/2026", "time": "17:10", "amount": 500.00, "user": "eduardo"},
        {"date": "17/02/2026", "time": "17:10", "amount": 420.60, "user": "eduardo"},
    ]

    with open("deductions_report.txt", "w", encoding="utf-8") as out:
        out.write(f"Searching {len(sessions)} sessions for {len(targets)} targets...\n")

        found_count = 0
        for session in sessions:
            transactions = session.get('transactions', [])
            for t in transactions:
                t_amt = float(t.get('amount', 0))
                t_user = t.get('user', '').lower()
                t_ts = t.get('timestamp', '') # dd/mm/yyyy HH:MM
                
                # Check match
                matched = False
                for target in targets:
                    # Approximate match for amount (float)
                    if abs(t_amt - target['amount']) < 0.05:
                        # Check date (fuzzy time?)
                        if target['date'] in t_ts: # Date part
                            # Check user
                            if target['user'] in t_user.lower():
                                matched = True
                                out.write(f"\n[MATCH FOUND]\n")
                                out.write(f"Target: {target}\n")
                                out.write(f"Transaction: ID={t.get('id')}, Amount={t_amt}, User={t_user}, Time={t_ts}\n")
                                out.write(f"Details: {json.dumps(t.get('details', {}), indent=2, ensure_ascii=False)}\n")
                                out.write(f"Description: {t.get('description')}\n")
                                out.write(f"Service Fee Removed: {t.get('service_fee_removed')}\n")
                                
                                details = t.get('details', {})
                                table_id = details.get('table_id')
                                room_number = details.get('room_number')
                                related_charge = details.get('related_charge_id') or t.get('related_charge_id')
                                
                                out.write(f"ORIGIN: Table={table_id}, Room={room_number}, RelatedCharge={related_charge}\n")
                                found_count += 1

        out.write(f"\nTotal matches found: {found_count}\n")
        print(f"Report written to deductions_report.txt")

if __name__ == "__main__":
    search_deductions()
