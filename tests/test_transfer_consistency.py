
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
    from app import app, CashierService
except ImportError:
    # If path issues, adjust sys.path
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from app import app, CashierService
from app.services import cashier_service

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
            
        # Patch CashierService internal file path
        self.original_sessions_file = cashier_service.CASHIER_SESSIONS_FILE
        cashier_service.CASHIER_SESSIONS_FILE = self.test_sessions_file
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'restaurante', 'recepcao']

    def tearDown(self):
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions_file
        if os.path.exists(self.test_sessions_file):
            os.remove(self.test_sessions_file)

    def test_restaurant_to_reception_transfer(self):
        """Test transfer from Restaurant to Reception (guest_consumption)"""
        print("\n--- Testing Restaurant -> Reception Transfer ---")
        amount = 100.0
        CashierService.transfer_funds(
            source_type='restaurant',
            target_type='reception',
            amount=amount,
            description='Test Rest to Rec',
            user='admin'
        )
        
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
        self.assertEqual(rest_trans[0]['amount'], amount)
        self.assertIn('Test Rest to Rec', rest_trans[0]['description'])
        
        # Check Reception (Target)
        # Should have an 'in' transaction
        rec_trans = rec_session['transactions']
        self.assertEqual(len(rec_trans), 1, "Reception should have 1 transaction")
        self.assertEqual(rec_trans[0]['type'], 'in', "Target transaction should be 'in'")
        self.assertEqual(rec_trans[0]['amount'], amount)
        
        print("✅ Restaurant -> Reception Transfer Validated")

    def test_reception_to_restaurant_transfer(self):
        """Test transfer from Reception to Restaurant"""
        print("\n--- Testing Reception -> Restaurant Transfer ---")
        amount = 50.0
        CashierService.transfer_funds(
            source_type='reception',
            target_type='restaurant',
            amount=amount,
            description='Test Rec to Rest',
            user='admin'
        )
        
        # Verify JSON
        with open(self.test_sessions_file, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_session = next(s for s in sessions if s['id'] == 'SESSION_REST_001')
        rec_session = next(s for s in sessions if s['id'] == 'SESSION_REC_001')
        
        # Check Reception (Source)
        rec_trans = rec_session['transactions']
        self.assertEqual(len(rec_trans), 1, "Reception should have 1 transaction")
        self.assertEqual(rec_trans[0]['type'], 'out', "Source transaction should be 'out'")
        self.assertEqual(rec_trans[0]['amount'], amount)
        
        # Check Restaurant (Target)
        rest_trans = rest_session['transactions']
        self.assertEqual(len(rest_trans), 1, "Restaurant should have 1 transaction")
        self.assertEqual(rest_trans[0]['type'], 'in', "Target transaction should be 'in'")
        self.assertEqual(rest_trans[0]['amount'], amount)
        
        print("✅ Reception -> Restaurant Transfer Validated")

if __name__ == '__main__':
    unittest.main()
