import sys
import os
import unittest
from datetime import datetime

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cashier_service import CashierService

class TestTransferBug(unittest.TestCase):
    def setUp(self):
        # Backup existing sessions
        self.original_sessions = CashierService._load_sessions()
        # Clear sessions for test
        CashierService._save_sessions([])
        
    def tearDown(self):
        # Restore sessions
        CashierService._save_sessions(self.original_sessions)

    def test_transfer_with_zero_balance(self):
        print("\n--- Testing Zero Balance Transfer ---")
        # 1. Open Source Cashier (Reception) with 0 balance
        source = CashierService.open_session(
            cashier_type='guest_consumption',
            user='TestUser',
            opening_balance=0.0
        )
        
        # 2. Open Target Cashier (Restaurant)
        target = CashierService.open_session(
            cashier_type='restaurant',
            user='TestUser',
            opening_balance=0.0
        )
        
        print(f"[TEST] Opened Source: {source['id']} (Bal: {source['opening_balance']})")
        print(f"[TEST] Opened Target: {target['id']}")

        # 3. Attempt Transfer of 100.00
        # This SHOULD fail.
        try:
            CashierService.transfer_funds(
                source_type='guest_consumption',
                target_type='restaurant',
                amount=100.00,
                description="Test Transfer",
                user="TestUser"
            )
            print("[FAIL] Transfer succeeded unexpectedly!")
            
            # Debugging why it succeeded
            s_fresh = CashierService.get_session_details(source['id'])
            print(f"[DEBUG] Source Transactions: {s_fresh['transactions']}")
            
            self.fail("Transfer should have been blocked due to insufficient funds.")
        except ValueError as e:
            print(f"[SUCCESS] Transfer blocked as expected: {e}")
            
        # 4. Verify Balances
        s_fresh = CashierService.get_session_details(source['id'])
        t_fresh = CashierService.get_session_details(target['id'])
        
        s_bal = CashierService._calculate_cash_balance(s_fresh)
        print(f"[TEST] Source Cash Balance: {s_bal}")
        
        self.assertEqual(len(s_fresh['transactions']), 0, "Source should have no transactions")
        self.assertEqual(len(t_fresh['transactions']), 0, "Target should have no transactions")

    def test_transfer_ambiguity(self):
        print("\n--- Testing Transfer Ambiguity (Reservations vs Reception) ---")
        # Scenario: Reservations has money, Main Reception has 0.
        # User tries to transfer from "Reception" (Main).
        # Should NOT use Reservations money.
        
        # 1. Open Reservations with 500
        res = CashierService.open_session(
            cashier_type='reception_reservations',
            user='ResUser',
            opening_balance=500.0
        )
        
        # 2. Open Main Reception with 0
        main = CashierService.open_session(
            cashier_type='guest_consumption',
            user='MainUser',
            opening_balance=0.0
        )
        
        target = CashierService.open_session(
            cashier_type='restaurant',
            user='RestUser',
            opening_balance=0.0
        )
        
        # 3. Transfer from 'guest_consumption' (Main)
        # Should FAIL because Main has 0.
        # If it succeeds, it might be stealing from Reservations or ignoring balance.
        try:
            CashierService.transfer_funds(
                source_type='guest_consumption',
                target_type='restaurant',
                amount=100.00,
                description="Test Ambiguity",
                user="MainUser"
            )
            print("[FAIL] Transfer succeeded! Likely used wrong cashier or ignored balance.")
            
            # Check who got charged
            res_fresh = CashierService.get_session_details(res['id'])
            main_fresh = CashierService.get_session_details(main['id'])
            
            if len(res_fresh['transactions']) > 0:
                print("[DEBUG] Charged Reservations cashier instead of Main!")
            if len(main_fresh['transactions']) > 0:
                print("[DEBUG] Charged Main cashier (despite 0 balance)!")
                
            self.fail("Transfer should be blocked.")
            
        except ValueError as e:
            print(f"[SUCCESS] Blocked correctly: {e}")

if __name__ == '__main__':
    unittest.main()
