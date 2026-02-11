import unittest
import os
import shutil
import json
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.cashier_service import CashierService

# Use a test file for sessions to avoid messing with production data
TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'test_data')
TEST_SESSIONS_FILE = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
TEST_BACKUP_DIR = os.path.join(TEST_DATA_DIR, 'backups', 'Caixa')

class TestCashierService(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Create test directories
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
        if not os.path.exists(TEST_BACKUP_DIR):
            os.makedirs(TEST_BACKUP_DIR)
            
        # Patch the file paths in CashierService
        # Note: In a real app we might use dependency injection or config, 
        # but here we'll just mock/patch or rely on the fact we can't easily patch class constants
        # So we will temporarily backup and restore the real file if we can't patch.
        # Alternatively, we can assume CashierService uses a constant we can modify if we import it.
        # But constants in python are module level.
        
        # Let's try to monkeypatch the module variables if possible
        import services.cashier_service as cs
        cls.original_file = cs.CASHIER_SESSIONS_FILE
        cls.original_backup = cs.BACKUP_DIR
        cs.CASHIER_SESSIONS_FILE = TEST_SESSIONS_FILE
        cs.BACKUP_DIR = TEST_BACKUP_DIR

    @classmethod
    def tearDownClass(cls):
        # Restore paths
        import services.cashier_service as cs
        cs.CASHIER_SESSIONS_FILE = cls.original_file
        cs.BACKUP_DIR = cls.original_backup
        
        # Clean up test data
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def setUp(self):
        # Clear sessions file before each test
        if os.path.exists(TEST_SESSIONS_FILE):
            os.remove(TEST_SESSIONS_FILE)

    def test_open_session(self):
        session = CashierService.open_session('restaurant', 'user_test', 100.0)
        self.assertEqual(session['status'], 'open')
        self.assertEqual(session['type'], 'restaurant')
        self.assertEqual(session['opening_balance'], 100.0)
        self.assertEqual(session['user'], 'user_test')
        
        # Verify it's in the file
        sessions = CashierService._load_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['id'], session['id'])

    def test_open_duplicate_session_fails(self):
        CashierService.open_session('restaurant', 'user_test')
        with self.assertRaises(ValueError):
            CashierService.open_session('restaurant', 'user_test_2')

    def test_add_transaction(self):
        CashierService.open_session('guest_consumption', 'receptionist')
        
        CashierService.add_transaction(
            cashier_type='guest_consumption',
            amount=50.0,
            description='Payment',
            payment_method='Credit Card',
            user='receptionist'
        )
        
        session = CashierService.get_active_session('guest_consumption')
        self.assertEqual(len(session['transactions']), 1)
        self.assertEqual(session['transactions'][0]['amount'], 50.0)
        self.assertEqual(session['transactions'][0]['type'], 'sale')

    def test_close_session(self):
        open_session = CashierService.open_session('daily_rates', 'manager', 0.0)
        
        # Add some transactions
        CashierService.add_transaction('daily_rates', 100.0, 'Rate', 'Cash', 'manager') # In
        CashierService.add_transaction('daily_rates', 20.0, 'Refund', 'Cash', 'manager', is_withdrawal=True) # Out
        
        # Close
        closed = CashierService.close_session(open_session['id'], 'manager', closing_balance=80.0)
        
        self.assertEqual(closed['status'], 'closed')
        self.assertIsNotNone(closed['closed_at'])
        self.assertEqual(closed['closing_balance'], 80.0)
        self.assertEqual(closed['difference'], 0.0) # 0 + 100 - 20 = 80. User reported 80. Diff 0.

    def test_close_session_divergence(self):
        open_session = CashierService.open_session('restaurant', 'waiter', 0.0)
        CashierService.add_transaction('restaurant', 100.0, 'Sale', 'Cash', 'waiter')
        
        # System balance = 100. User reports 90.
        closed = CashierService.close_session(open_session['id'], 'waiter', closing_balance=90.0)
        
        self.assertEqual(closed['difference'], -10.0)

    def test_auto_backup_on_transaction(self):
        # This implicitly tests backup creation since add_transaction triggers _save_sessions which triggers backup
        CashierService.open_session('restaurant', 'test')
        CashierService.add_transaction('restaurant', 10.0, 'Test', 'Cash', 'test')
        
        # Check if backup file exists
        files = os.listdir(TEST_BACKUP_DIR)
        self.assertTrue(len(files) > 0)
        self.assertTrue(files[0].startswith('backup_cashier_'))

if __name__ == '__main__':
    unittest.main()
