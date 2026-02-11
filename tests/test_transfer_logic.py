import unittest
import os
import json
import shutil
from datetime import datetime
from services.cashier_service import CashierService

# Use a temp file for testing
TEST_SESSIONS_FILE = 'data/test_cashier_sessions.json'

class TestCashierTransferReproduction(unittest.TestCase):
    def setUp(self):
        # Backup original if exists (just in case, though we use a different filename)
        # But CashierService uses a hardcoded constant CASHIER_SESSIONS_FILE.
        # We need to monkeypatch it or swap the file.
        # Since I can't easily monkeypatch in this environment without a library,
        # I will temporarily rename the real file and restore it after.
        self.real_file = 'data/cashier_sessions.json'
        self.backup_file = 'data/cashier_sessions.json.bak.test'
        
        if os.path.exists(self.real_file):
            shutil.move(self.real_file, self.backup_file)
            
        # Create empty sessions file
        with open(self.real_file, 'w') as f:
            json.dump([], f)
            
    def tearDown(self):
        # Restore original file
        if os.path.exists(self.real_file):
            os.remove(self.real_file)
        if os.path.exists(self.backup_file):
            shutil.move(self.backup_file, self.real_file)

    def test_transfer_restaurant_to_reception(self):
        """
        Reproduce Restaurant -> Reception transfer.
        Expectation: 
        - Restaurant (Source): Debit (OUT)
        - Reception (Target): Credit (IN)
        """
        # 1. Open Restaurant Session
        CashierService.open_session('restaurant', 'user_rest', 1000.0)
        
        # 2. Open Reception Session (guest_consumption)
        CashierService.open_session('guest_consumption', 'user_recep', 500.0)
        
        # 3. Perform Transfer
        amount = 100.0
        CashierService.transfer_funds(
            source_type='restaurant',
            target_type='reception', # Should map to guest_consumption
            amount=amount,
            description='Test Transfer Rest->Recep',
            user='user_rest'
        )
        
        # 4. Verify Sessions
        sessions = CashierService._load_sessions()
        
        # Find Restaurant Session
        rest_session = next(s for s in sessions if s['type'] == 'restaurant')
        # Find Reception Session
        recep_session = next(s for s in sessions if s['type'] == 'guest_consumption')
        
        # Verify Restaurant OUT
        out_trans = next((t for t in rest_session['transactions'] if t['type'] == 'out' and t['amount'] == amount), None)
        self.assertIsNotNone(out_trans, "Restaurant should have OUT transaction")
        self.assertEqual(out_trans['category'], 'Transferência Enviada')
        
        # Verify Reception IN
        in_trans = next((t for t in recep_session['transactions'] if t['type'] == 'in' and t['amount'] == amount), None)
        self.assertIsNotNone(in_trans, "Reception should have IN transaction")
        self.assertEqual(in_trans['category'], 'Transferência Recebida')
        
        # Verify Linked Document ID
        self.assertEqual(out_trans['document_id'], in_trans['document_id'])
        
        print("Rest->Recep Transfer: SUCCESS (Service Logic is Correct)")

    def test_transfer_reception_to_restaurant(self):
        """
        Reproduce Reception -> Restaurant transfer.
        Expectation:
        - Reception (Source): Debit (OUT)
        - Restaurant (Target): Credit (IN)
        """
        # 1. Open Sessions
        CashierService.open_session('restaurant', 'user_rest', 1000.0)
        CashierService.open_session('guest_consumption', 'user_recep', 500.0)
        
        # 2. Perform Transfer
        amount = 50.0
        CashierService.transfer_funds(
            source_type='reception', # Should map to guest_consumption
            target_type='restaurant',
            amount=amount,
            description='Test Transfer Recep->Rest',
            user='user_recep'
        )
        
        # 3. Verify Sessions
        sessions = CashierService._load_sessions()
        rest_session = next(s for s in sessions if s['type'] == 'restaurant')
        recep_session = next(s for s in sessions if s['type'] == 'guest_consumption')
        
        # Verify Reception OUT
        out_trans = next((t for t in recep_session['transactions'] if t['type'] == 'out' and t['amount'] == amount), None)
        self.assertIsNotNone(out_trans, "Reception should have OUT transaction")
        
        # Verify Restaurant IN
        in_trans = next((t for t in rest_session['transactions'] if t['type'] == 'in' and t['amount'] == amount), None)
        self.assertIsNotNone(in_trans, "Restaurant should have IN transaction")
        
        print("Recep->Rest Transfer: SUCCESS (Service Logic is Correct)")

if __name__ == '__main__':
    unittest.main()
