import unittest
import json
import os
import sys
from datetime import datetime

# Adjust path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, CASHIER_SESSIONS_FILE
from services.cashier_service import CashierService
from system_config_manager import get_data_path

class TestTransferBug(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        
        # Mock Session Data
        self.test_sessions_file = get_data_path('cashier_sessions_test_bug.json')
        
        # Patch the file paths in app and service
        app.config['CASHIER_SESSIONS_FILE'] = self.test_sessions_file
        # We also need to patch the global variable if it's used directly, 
        # but app.py seems to use the global constant defined at module level.
        # Ideally we should patch the load/save functions or the constant.
        # Since I can't easily patch the constant in the imported module without reloading,
        # I will overwrite the file path in the app module if possible, or just mock the file content at the real location if safe.
        # SAFE OPTION: Use a temporary file and patch the module attribute
        
        import app as app_module
        app_module.CASHIER_SESSIONS_FILE = self.test_sessions_file
        
        import services.cashier_service as cs_module
        cs_module.CASHIER_SESSIONS_FILE = self.test_sessions_file
        
        # Create initial sessions
        self.initial_sessions = [
            {
                "id": "REST_SESSION_TEST",
                "user": "admin",
                "type": "restaurant", # Normalized to restaurant
                "status": "open",
                "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "opening_balance": 1000.0,
                "transactions": []
            },
            {
                "id": "RECEP_SESSION_TEST",
                "user": "admin",
                "type": "guest_consumption",
                "status": "open",
                "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "opening_balance": 1000.0,
                "transactions": []
            }
        ]
        
        with open(self.test_sessions_file, 'w', encoding='utf-8') as f:
            json.dump(self.initial_sessions, f)

    def tearDown(self):
        if os.path.exists(self.test_sessions_file):
            os.remove(self.test_sessions_file)

    def test_transfer_creates_correct_transaction_type(self):
        print("\nTesting Transfer Transaction Type...")
        
        # Login
        with self.app.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        # Perform Transfer
        response = self.app.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'transfer',
            'target_cashier': 'reception',
            'amount': '100,00',
            'description': 'Test Transfer Logic'
        }, follow_redirects=True)
        
        print("Response Data:", response.get_data(as_text=True))
        
        self.assertEqual(response.status_code, 200)
        
        # Check sessions file
        with open(self.test_sessions_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_session = next(s for s in sessions if s['id'] == "REST_SESSION_TEST")
        recep_session = next(s for s in sessions if s['id'] == "RECEP_SESSION_TEST")
        
        print("Restaurant Transactions:", json.dumps(rest_session['transactions'], indent=2))
        
        # Verify Source Transaction
        source_trans = rest_session['transactions'][-1]
        self.assertEqual(source_trans['type'], 'out', f"Source transaction type should be 'out', got '{source_trans['type']}'")
        self.assertEqual(source_trans['amount'], 100.0)
        
        # Verify Target Transaction
        in_trans = recep_session['transactions'][-1]
        self.assertEqual(in_trans['type'], 'in')
        self.assertEqual(in_trans['amount'], 100.0)
        self.assertEqual(in_trans['document_id'], source_trans['document_id'])

    def test_reception_transfer_creates_correct_transaction_type(self):
        print("\nTesting Reception Transfer Transaction Type...")
        
        # Login
        with self.app.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            # Reception requires 'recepcao' permission or admin role
            
        # Perform Transfer from Reception
        response = self.app.post('/reception/cashier', data={
            'action': 'add_transaction',
            'type': 'transfer',
            'target_cashier': 'restaurant',
            'amount': '50,00',
            'description': 'Test Reception Transfer'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Check sessions file
        with open(self.test_sessions_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_session = next(s for s in sessions if s['id'] == "REST_SESSION_TEST")
        recep_session = next(s for s in sessions if s['id'] == "RECEP_SESSION_TEST")
        
        print("Reception Transactions:", json.dumps(recep_session['transactions'], indent=2))
        
        # Verify Source Transaction (Reception - OUT)
        source_trans = recep_session['transactions'][-1]
        self.assertEqual(source_trans['type'], 'out', f"Source transaction type should be 'out', got '{source_trans['type']}'")
        self.assertEqual(source_trans['amount'], 50.0)
        
        # Verify Target Transaction (Restaurant - IN)
        in_trans = rest_session['transactions'][-1]
        self.assertEqual(in_trans['type'], 'in', f"Target transaction type should be 'in', got '{in_trans['type']}'")
        self.assertEqual(in_trans['amount'], 50.0)
        self.assertEqual(in_trans['document_id'], source_trans['document_id'])

if __name__ == '__main__':
    unittest.main()
