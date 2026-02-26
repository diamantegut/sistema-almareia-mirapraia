import json
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system_config_manager import CASHIER_SESSIONS_FILE as DATA_FILE

def load_sessions():
    if not os.path.exists(DATA_FILE):
        print(f"File not found: {DATA_FILE}")
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def audit_transfers():
    sessions = load_sessions()
    print(f"Loaded {len(sessions)} sessions.")
    
    transfers = []
    
    # 1. Collect all transfers
    for s in sessions:
        s_type = s.get('type')
        s_id = s.get('id')
        user = s.get('user')
        
        for t in s.get('transactions', []):
            t_type = t.get('type')
            t_cat = t.get('category', '')
            t_desc = t.get('description', '')
            t_doc_id = t.get('document_id')
            t_amount = float(t.get('amount', 0))
            
            # Identify Transfer Candidates
            is_transfer = False
            if t_doc_id: # Linked transfer
                is_transfer = True
            elif 'Transferência' in t_cat or 'Transferência' in t_desc:
                is_transfer = True
            elif t_type == 'transfer': # Legacy?
                is_transfer = True
                
            if is_transfer:
                transfers.append({
                    'session_id': s_id,
                    'session_type': s_type,
                    'trans_id': t.get('id'),
                    'document_id': t_doc_id,
                    'type': t_type,
                    'amount': t_amount,
                    'desc': t_desc,
                    'timestamp': t.get('timestamp')
                })

    print(f"Found {len(transfers)} transfer transactions.")
    
    # 2. Analyze Links
    doc_map = {}
    orphans = []
    
    # Group by document_id
    for t in transfers:
        doc_id = t.get('document_id')
        if doc_id:
            if doc_id not in doc_map:
                doc_map[doc_id] = []
            doc_map[doc_id].append(t)
        else:
            orphans.append(t)
            
    print(f"Transfers with document_id: {len(transfers) - len(orphans)}")
    print(f"Orphan transfers (no document_id): {len(orphans)}")
    
    # 3. Validate Linked Pairs
    broken_links = []
    valid_links = 0
    
    for doc_id, items in doc_map.items():
        if len(items) == 2:
            # Check if one is IN and one is OUT
            types = [x['type'] for x in items]
            if 'in' in types and 'out' in types:
                valid_links += 1
            else:
                broken_links.append((doc_id, items, "Types mismatch (expected in+out)"))
        else:
            broken_links.append((doc_id, items, f"Count mismatch (expected 2, got {len(items)})"))
            
    print(f"Valid linked pairs: {valid_links}")
    print(f"Broken linked pairs: {len(broken_links)}")
    
    if broken_links:
        print("\n--- BROKEN LINKS ---")
        for doc_id, items, reason in broken_links:
            print(f"DocID: {doc_id} - {reason}")
            for i in items:
                print(f"  {i['session_type']} ({i['type']}): {i['amount']} - {i['desc']}")
                
    if orphans:
        print("\n--- ORPHAN TRANSFERS (Potential Issues) ---")
        for o in orphans:
            print(json.dumps(o, indent=2, default=str))
            print(f"[{o['timestamp']}] {o['session_type']} ({o['type']}): R$ {o['amount']} - {o['desc']}")

if __name__ == "__main__":
    audit_transfers()
