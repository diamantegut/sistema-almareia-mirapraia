import unittest
import os
import json
from app.services import cashier_service
from app.services.cashier_service import CashierService

TEST_SESSIONS_FILE = 'tests/test_data_transfer_logic_cashier_sessions.json'

class TestCashierTransferReproduction(unittest.TestCase):
    def setUp(self):
        self.original_sessions_file = cashier_service.CASHIER_SESSIONS_FILE
        cashier_service.CASHIER_SESSIONS_FILE = TEST_SESSIONS_FILE
        with open(TEST_SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
            
    def tearDown(self):
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions_file
        if os.path.exists(TEST_SESSIONS_FILE):
            os.remove(TEST_SESSIONS_FILE)

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
