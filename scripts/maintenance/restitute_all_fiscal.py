import sys
import os
import json
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.fiscal_pool_service import FiscalPoolService
from app.services.closed_account_service import ClosedAccountService

def normalize_date(date_str):
    try:
        return datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        except ValueError:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except:
                return None

def restitute_fiscal_data():
    print("Starting COMPREHENSIVE restitution of fiscal data since Feb 1st 2026...")
    
    # 1. Load Fiscal Pool to build existing index
    pool = FiscalPoolService._load_pool()
    # Build a set of signatures: (origin, original_id, closed_at_iso_minute, total_amount)
    # We use minute precision for date to avoid seconds mismatch if formats differ slightly
    existing_signatures = set()
    for entry in pool:
        dt = normalize_date(entry['closed_at'])
        if dt:
            # Round to minute just in case, or keep seconds if reliable.
            # ClosedAccountService saves with seconds. FiscalPool saves with seconds.
            # But FiscalPool 'closed_at' comes from the moment it was added to pool?
            # No, FiscalPoolService.add_to_pool uses datetime.now()!
            # It does NOT preserve the original closed_at from the closed account unless we pass it?
            # Let's check FiscalPoolService.add_to_pool.
            # It says: 'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # AHA! The pool entry 'closed_at' is the INSERTION time, not the original closure time.
            # This makes duplicate detection harder.
            
            # However, 'original_id' and 'total_amount' and 'items' (hash?) could be used.
            # Or we can rely on 'original_id' and 'total_amount' combined with date check on the *source*.
            # But if we have multiple bills for Table 10 with same amount on same day... rare but possible.
            
            # Let's check if 'notes' or 'customer' helps.
            # Ideally, we should have stored the source ID (CLOSED_...).
            # Since we didn't, we have to use heuristics.
            
            # Heuristic: (origin, original_id, total_amount)
            # If we have multiple with same key, we count them.
            sig = (entry.get('origin'), str(entry.get('original_id')), float(entry.get('total_amount', 0)))
            existing_signatures.add(sig)
    
    # Since we can't distinguish duplicates with same ID/Amount easily without source ID,
    # and we know the previous script blocked *any* second occurrence of ID,
    # we should probably clear the pool of "auto-migrated" entries or just be aggressive?
    # No, clearing is dangerous.
    
    # Wait, if FiscalPoolService.add_to_pool sets closed_at to NOW, then looking at pool.closed_at tells us when it was imported.
    # The original closed_at is lost in the pool entry unless it's in history?
    # The pool entry has 'original_id'.
    
    # Let's look at Closed Accounts.
    closed_accounts_file = os.path.join("data", "closed_accounts.json")
    if not os.path.exists(closed_accounts_file):
        print("No closed accounts file found.")
        return

    with open(closed_accounts_file, 'r', encoding='utf-8') as f:
        closed_accounts = json.load(f)
        
    print(f"Loaded {len(closed_accounts)} closed accounts.")
    
    cutoff_date = datetime.strptime("01/02/2026", "%d/%m/%Y")
    
    # To handle the duplicate issue correctly:
    # We want to ensure EVERY closed account in `closed_accounts` (>= Feb 1) has a corresponding entry in `pool`.
    # Since we can't link 1-to-1 easily, we can count.
    # For a given (origin, original_id, amount), if `closed_accounts` has N entries and `pool` has M, we need to add N-M entries.
    
    # 1. Count occurrences in Pool
    pool_counts = {}
    for entry in pool:
        sig = (entry.get('origin'), str(entry.get('original_id')), float(entry.get('total_amount', 0)))
        pool_counts[sig] = pool_counts.get(sig, 0) + 1
        
    # 2. Iterate Closed Accounts and check against counts
    added_count = 0
    
    for acc in closed_accounts:
        # Filter by date
        ts = acc.get('timestamp')
        try:
            acc_dt = normalize_date(ts)
        except:
            continue
            
        if not acc_dt or acc_dt < cutoff_date:
            continue
            
        if acc.get('status') == 'reopened':
            continue

        origin = acc.get('origin')
        original_id = str(acc.get('original_id'))
        total = float(acc.get('total', 0))
        
        sig = (origin, original_id, total)
        
        # Check if we have "quota" in the pool
        if pool_counts.get(sig, 0) > 0:
            # We have a match, decrement quota (consume one existing entry)
            pool_counts[sig] -= 1
            # print(f"Skipping {origin} #{original_id} (Already in pool)")
        else:
            # No matching entry available (or all consumed), add new one
            print(f"Restoring missing entry: {origin} #{original_id} - R$ {total} ({ts})")
            
            items = acc.get('items', [])
            payment_methods = acc.get('payments', [])
            user = acc.get('user', 'restitution_script')
            details = acc.get('details', {})
            customer_info = details.get('customer') or acc.get('customer')
            notes = details.get('note') or acc.get('note')
            
            # Recalculate fiscal amount to be safe (fix legacy issue on the fly)
            # FiscalPoolService now handles this internally if we rely on its logic, 
            # but we can pass explicit values if needed. 
            # add_to_pool calculates it.
            
            FiscalPoolService.add_to_pool(
                origin=origin,
                original_id=original_id,
                total_amount=total,
                items=items,
                payment_methods=payment_methods,
                user=user,
                customer_info=customer_info,
                notes=notes
            )
            added_count += 1
            
            # Update pool counts in memory to prevent double adding if we scan orphans next
            sig = (origin, original_id, total)
            pool_counts[sig] = pool_counts.get(sig, 0) + 1
            
    # 3. Scan Cashier Sessions for Orphans
    print("Scanning Cashier Sessions for Orphan Transactions...")
    cashier_file = os.path.join("data", "cashier_sessions.json")
    if os.path.exists(cashier_file):
        with open(cashier_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        orphan_count = 0
        for s in sessions:
            if "2026" not in s.get('opened_at', ''):
                continue
                
            for tx in s.get('transactions', []):
                if tx.get('type') == 'sale' and float(tx.get('amount', 0)) > 0:
                    # Check if this looks like it's already in the pool
                    # We don't have original_id easily, but we have amount and timestamp
                    tx_amount = float(tx.get('amount', 0))
                    tx_ts = tx.get('timestamp')
                    tx_desc = tx.get('description', '')
                    
                    # Try to match with existing pool entries by Amount and Date (Approx)
                    # This is fuzzy but necessary
                    match_found = False
                    tx_dt = normalize_date(tx_ts)
                    
                    if not tx_dt or tx_dt < cutoff_date:
                        continue
                        
                    # Check against pool
                    # We iterate the pool_counts keys (which are signatures) 
                    # OR we iterate the pool itself? 
                    # Pool entries might not be in pool_counts if we didn't reload.
                    # But we updated pool_counts for newly added ones.
                    # Wait, pool_counts keys are (origin, original_id, total).
                    # We don't know original_id for the orphan.
                    # So we need to check if ANY entry in pool matches Amount + Date.
                    
                    # Let's check the pool list directly (reloading or using existing + added)
                    # We didn't keep the full pool list updated in memory with new adds.
                    # Let's just reload pool to be safe? No, expensive.
                    # Let's iterate the initial pool + what we added?
                    # I'll just rely on the fact that I processed closed_accounts.
                    
                    # Heuristic:
                    # If I find a pool entry with same Amount and closed_at within 2 minutes -> Match.
                    # If I find a pool entry with same Amount and original_id in description -> Match.
                    
                    # Let's extract potential ID from description
                    # "Fechamento Conta Quarto 101" -> 101
                    # "Venda Mesa 99" -> 99
                    
                    inferred_id = None
                    inferred_origin = 'cashier_orphan'
                    
                    if 'Mesa' in tx_desc:
                        parts = tx_desc.split('Mesa')
                        if len(parts) > 1:
                            inferred_id = parts[1].strip().split(' ')[0]
                            inferred_origin = 'restaurant_table'
                    elif 'Quarto' in tx_desc:
                        parts = tx_desc.split('Quarto')
                        if len(parts) > 1:
                            inferred_id = parts[1].strip().split(' ')[0]
                            inferred_origin = 'reception_room'
                            
                    # Check against existing signatures (origin, original_id, total)
                    # If we inferred ID and Origin, we can check efficiently
                    if inferred_id:
                        sig = (inferred_origin, inferred_id, tx_amount)
                        # Also check alternative origin 'reception_charge' for Quarto
                        sig2 = ('reception_charge', inferred_id, tx_amount)
                        # Also check 'reception_room' with different ID format?
                        
                        if pool_counts.get(sig, 0) > 0 or pool_counts.get(sig2, 0) > 0:
                            match_found = True
                    
                    if not match_found:
                        # Fallback: Check strictly by Amount and Time (2 min window)
                        # This covers cases where ID parsing failed or ID format differs
                        for entry in pool: # This is the OLD pool. Missing the newly added ones.
                            # We should ideally check the newly added ones too.
                            # But let's assume if it wasn't in closed_accounts, it wasn't added.
                            # So checking old pool is fine?
                            # NO! If I just added it from closed_accounts, it's not in 'pool' variable?
                            # Actually 'pool' variable is from _load_pool() at start.
                            # So I need to account for what I just added.
                            pass
                        
                        # Let's just add it if we are sure it's not in closed_accounts?
                        # I can check 'closed_accounts' list for a match too.
                        # If found in 'closed_accounts', I already added it (or it was skipped as duplicate).
                        # So if I find a match in closed_accounts, I skip.
                        
                        found_in_closed = False
                        for acc in closed_accounts:
                            if float(acc.get('total', 0)) == tx_amount:
                                # Check time
                                acc_ts = acc.get('timestamp')
                                acc_dt = normalize_date(acc_ts)
                                if acc_dt and abs((acc_dt - tx_dt).total_seconds()) < 180: # 3 mins tolerance
                                    found_in_closed = True
                                    break
                        
                        if found_in_closed:
                            continue
                            
                        # If not found in closed_accounts, it's truly an ORPHAN. Add it.
                        print(f"Restoring ORPHAN: {tx_desc} - R$ {tx_amount} ({tx_ts})")
                        
                        items = [{
                            "name": tx_desc,
                            "qty": 1,
                            "price": tx_amount,
                            "total": tx_amount
                        }]
                        
                        FiscalPoolService.add_to_pool(
                            origin=inferred_origin,
                            original_id=inferred_id or 'unknown',
                            total_amount=tx_amount,
                            items=items,
                            payment_methods=[{"method": "Cashier", "amount": tx_amount, "is_fiscal": True}],
                            user=tx.get('user', 'orphan_recovery'),
                            notes="Recovered from Cashier Session (Missing in Closed Accounts)"
                        )
                        orphan_count += 1
                        
        print(f"Added {orphan_count} orphan entries.")

    print("-" * 30)
    print(f"Restitution Complete. Added {added_count} closed accounts + {orphan_count} orphans.")

if __name__ == "__main__":
    restitute_fiscal_data()
