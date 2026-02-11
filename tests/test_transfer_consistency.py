
import unittest
import json
import os
import shutil
from unittest.mock import MagicMock, patch
from datetime import datetime

# Setup environment before importing app
os.environ['TESTING'] = 'true'

# Import app but we'll need to patch things before running tests
# Since we can't easily import app without triggering things, we'll try to rely on patching
# But we need 'app' object.
# Assuming we can import app.
try:
    from app import app, CASHIER_SESSIONS_FILE, CashierService
except ImportError:
    # If path issues, adjust sys.path
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from app import app, CASHIER_SESSIONS_FILE, CashierService

class TestTransferConsistency(unittest.TestCase):
    
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        
        # Setup temp file for cashier sessions
        self.test_sessions_file = 'tests/temp_cashier_sessions_consistency.json'
        
        # Initial State: One Restaurant Session, One Reception Session
        self.initial_sessions = [
            {
                "id": "SESSION_REST_001",
                "user": "admin",
                "type": "restaurant", # or restaurant_service
                "status": "open",
                "opened_at": "07/02/2026 08:00",
                "opening_balance": 1000.0,
                "transactions": [],
                "closing_balance": 0.0
            },
            {
                "id": "SESSION_REC_001",
                "user": "admin",
                "type": "guest_consumption", # Reception mapped type
                "status": "open",
                "opened_at": "07/02/2026 08:00",
                "opening_balance": 1000.0,
                "transactions": [],
                "closing_balance": 0.0
            }
        ]
        
        with open(self.test_sessions_file, 'w', encoding='utf-8') as f:
            json.dump(self.initial_sessions, f)
            
        # Patch the file path in app and CashierService
        self.patcher = patch('app.CASHIER_SESSIONS_FILE', self.test_sessions_file)
        self.mock_file = self.patcher.start()
        
        # Also patch CashierService internal file path if it uses a module level constant
        self.patcher_service = patch('services.cashier_service.CASHIER_SESSIONS_FILE', self.test_sessions_file)
        self.mock_file_service = self.patcher_service.start()
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'restaurante', 'recepcao']

    def tearDown(self):
        self.patcher.stop()
        self.patcher_service.stop()
        if os.path.exists(self.test_sessions_file):
            os.remove(self.test_sessions_file)

    def test_restaurant_to_reception_transfer(self):
        """Test transfer from Restaurant to Reception (guest_consumption)"""
        print("\n--- Testing Restaurant -> Reception Transfer ---")
        
        response = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'transfer',
            'target_cashier': 'reception', # Should map to guest_consumption
            'amount': '100.00',
            'description': 'Test Rest to Rec'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify JSON
        with open(self.test_sessions_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_session = next(s for s in sessions if s['id'] == 'SESSION_REST_001')
        rec_session = next(s for s in sessions if s['id'] == 'SESSION_REC_001')
        
        # Check Restaurant (Source)
        # Should have an 'out' transaction
        rest_trans = rest_session['transactions']
        self.assertEqual(len(rest_trans), 1, "Restaurant should have 1 transaction")
        self.assertEqual(rest_trans[0]['type'], 'out', "Source transaction should be 'out'")
        self.assertEqual(rest_trans[0]['amount'], 100.0)
        self.assertIn('Test Rest to Rec', rest_trans[0]['description'])
        
        # Check Reception (Target)
        # Should have an 'in' transaction
        rec_trans = rec_session['transactions']
        self.assertEqual(len(rec_trans), 1, "Reception should have 1 transaction")
        self.assertEqual(rec_trans[0]['type'], 'in', "Target transaction should be 'in'")
        self.assertEqual(rec_trans[0]['amount'], 100.0)
        
        print("✅ Restaurant -> Reception Transfer Validated")

    def test_reception_to_restaurant_transfer(self):
        """Test transfer from Reception to Restaurant"""
        print("\n--- Testing Reception -> Restaurant Transfer ---")
        
        response = self.client.post('/reception/cashier', data={
            'action': 'add_transaction',
            'type': 'transfer',
            'target_cashier': 'restaurant_service',
            'amount': '50.00',
            'description': 'Test Rec to Rest'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify JSON
        with open(self.test_sessions_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_session = next(s for s in sessions if s['id'] == 'SESSION_REST_001')
        rec_session = next(s for s in sessions if s['id'] == 'SESSION_REC_001')
        
        # Check Reception (Source)
        rec_trans = rec_session['transactions']
        self.assertEqual(len(rec_trans), 1, "Reception should have 1 transaction")
        self.assertEqual(rec_trans[0]['type'], 'out', "Source transaction should be 'out'")
        self.assertEqual(rec_trans[0]['amount'], 50.0)
        
        # Check Restaurant (Target)
        rest_trans = rest_session['transactions']
        self.assertEqual(len(rest_trans), 1, "Restaurant should have 1 transaction")
        self.assertEqual(rest_trans[0]['type'], 'in', "Target transaction should be 'in'")
        self.assertEqual(rest_trans[0]['amount'], 50.0)
        
        print("✅ Reception -> Restaurant Transfer Validated")

if __name__ == '__main__':
    unittest.main()
