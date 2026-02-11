
import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from services.cashier_service import CashierService

class TestTransferLogic(unittest.TestCase):
    def setUp(self):
        self.test_file = 'tests/test_cashier_sessions.json'
        # Create a dummy session file
        self.initial_data = [
            {
                "id": "sess_rest_1",
                "type": "restaurant",
                "status": "open",
                "opened_at": "07/02/2026 08:00",
                "user": "admin",
                "initial_balance": 100.0,
                "transactions": []
            },
            {
                "id": "sess_rec_1",
                "type": "reception",
                "status": "open",
                "opened_at": "07/02/2026 08:00",
                "user": "admin",
                "initial_balance": 500.0,
                "transactions": []
            }
        ]
        with open(self.test_file, 'w', encoding='utf-8') as f:
            json.dump(self.initial_data, f)

    def tearDown(self):
        if os.path.exists(self.test_file):
            try:
                os.remove(self.test_file)
            except:
                pass

    @patch('services.cashier_service.CASHIER_SESSIONS_FILE')
    @patch('services.cashier_service.BACKUP_DIR')
    def test_transfer_restaurant_to_reception(self, mock_backup_dir, mock_sessions_file):
        # Setup mocks
        mock_sessions_file.__str__.return_value = self.test_file
        # We need to mock the module-level constant used in _load_sessions and _save_sessions
        # But CashierService uses the constant directly. 
        # Patching 'services.cashier_service.CASHIER_SESSIONS_FILE' works if the code uses it as `CASHIER_SESSIONS_FILE` 
        # but we need to ensure the patch is applied where it is used.
        
        # Actually, let's just use the fact that I can mock `_load_sessions` and `_save_sessions` 
        # BUT I want to test the logic INSIDE `transfer_funds` which calls `_load_sessions`.
        
        # A better way for file path: 
        # The service uses `CASHIER_SESSIONS_FILE`. We can just overwrite it on the class or module if possible.
        # But `patch` is safer.
        
        # Let's verify if patching `services.cashier_service.CASHIER_SESSIONS_FILE` works.
        # It should work since `transfer_funds` calls `_load_sessions` which uses the global `CASHIER_SESSIONS_FILE`.
        
        # Wait, the module imports `CASHIER_SESSIONS_FILE`. 
        # If `_load_sessions` uses it, patch should work.
        pass

    @patch('services.cashier_service.CASHIER_SESSIONS_FILE', new='tests/test_cashier_sessions.json')
    @patch('services.cashier_service.BACKUP_DIR', new='tests/backups')
    def test_transfer_logic_execution(self):
        # Ensure backup dir exists
        if not os.path.exists('tests/backups'):
            os.makedirs('tests/backups')
            
        # Perform transfer
        print("Transferring 50.00 from Restaurant to Reception...")
        try:
            result = CashierService.transfer_funds(
                source_type='restaurant',
                target_type='reception',
                amount=50.0,
                description="Teste Transferencia",
                user="tester"
            )
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"Transfer failed with error: {e}")
        
        # Verify file content
        with open('tests/test_cashier_sessions.json', 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            
        rest_sess = next(s for s in sessions if s['type'] == 'restaurant')
        rec_sess = next(s for s in sessions if s['type'] == 'reception')
        
        # Check Restaurant (Source) - Should have OUT transaction
        print("Checking Restaurant Transactions...")
        out_trans = next((t for t in rest_sess['transactions'] if t['type'] == 'out'), None)
        if not out_trans:
             print("FAIL: No OUT transaction found in Restaurant session!")
             print(f"Transactions: {rest_sess['transactions']}")
        self.assertIsNotNone(out_trans)
        self.assertEqual(out_trans['amount'], 50.0)
        self.assertEqual(out_trans['payment_method'], 'Transferência')
        
        # Check Reception (Target) - Should have IN transaction
        print("Checking Reception Transactions...")
        in_trans = next((t for t in rec_sess['transactions'] if t['type'] == 'in'), None)
        if not in_trans:
             print("FAIL: No IN transaction found in Reception session!")
             print(f"Transactions: {rec_sess['transactions']}")
        self.assertIsNotNone(in_trans)
        self.assertEqual(in_trans['amount'], 50.0)
        self.assertEqual(in_trans['payment_method'], 'Transferência')
        
        # Verify Document IDs match
        self.assertEqual(out_trans['document_id'], in_trans['document_id'])
        print(f"Document ID Match: {out_trans['document_id']}")

if __name__ == '__main__':
    unittest.main()
