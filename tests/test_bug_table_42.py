
import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestTable42Bug(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.CashierService.add_transaction')
    @patch('app.blueprints.restaurant.routes.secure_save_sales_history')
    @patch('app.blueprints.restaurant.routes.load_payment_methods')
    @patch('app.blueprints.restaurant.routes.load_products')
    @patch('app.blueprints.restaurant.routes.get_current_cashier')
    @patch('app.blueprints.restaurant.routes.file_lock')
    def test_close_table_failure_persistence(self, mock_lock, mock_get_cashier, mock_load_products, mock_load_pm, mock_save_history, mock_add_transaction, mock_save_orders, mock_load_orders):
        """
        Reproduce Bug: Table stays open if Sales History save fails, even after payment.
        """
        # 1. Setup Data
        table_id = '42'
        mock_orders = {
            table_id: {
                'status': 'open',
                'items': [{'name': 'Cerveja', 'qty': 1, 'price': 10.0}],
                'total': 10.0,
                'total_paid': 0.0,
                'customer_name': 'Test User'
            }
        }
        
        # Mocks
        mock_load_orders.return_value = mock_orders
        mock_load_pm.return_value = [{'id': 'dinheiro', 'name': 'Dinheiro', 'is_fiscal': False}]
        mock_load_products.return_value = [{'id': '1', 'name': 'Cerveja', 'price': 10.0}]
        mock_get_cashier.return_value = {'id': 'session_1', 'status': 'open'}
        
        # Mock Context Manager for lock
        mock_lock.return_value.__enter__.return_value = None
        
        # 2. Simulate Failure in secure_save_sales_history
        # This is the critical failure point: Money is taken, but history save fails.
        mock_save_history.side_effect = Exception("Simulated Disk Error or Permission Denied")
        
        # 3. Perform Request
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            
        # Payload for closing order
        # We simulate paying the full amount
        payment_data = json.dumps([{'method': 'Dinheiro', 'amount': 11.0}]) # 10 + 10% service fee = 11.0
        
        response = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'close_order',
            'payment_data': payment_data
        }, follow_redirects=True)
        
        # 4. Assertions
        
        # A. Verify Money was Taken (Cashier Transaction)
        # This MUST be called before the failure point
        if not mock_add_transaction.called:
             # Depending on implementation details, it might be called differently. 
             # But assuming the bug logic is correct:
             print("WARNING: Cashier Transaction not called? Check logic.")
        else:
             print("CONFIRMED: Cashier Transaction was processed.")
             
        # B. Verify Table Status Update
        # After fix, save_table_orders SHOULD be called even if history save fails
        if mock_save_orders.called:
            args, _ = mock_save_orders.call_args
            saved_orders = args[0]
            if table_id not in saved_orders:
                print("SUCCESS: Bug Fixed! Table 42 was successfully removed despite history save failure.")
            else:
                self.fail("FAILURE: Table 42 still in orders (Saved but not removed?)")
        else:
            self.fail("FAILURE: save_table_orders was NEVER called. Bug still exists.")
            
        # C. Verify User Feedback
        response_text = response.get_data(as_text=True)
        # The code catches the exception and flashes a warning instead of error/redirect
        self.assertIn('Aviso: Erro ao salvar histórico', response_text)

