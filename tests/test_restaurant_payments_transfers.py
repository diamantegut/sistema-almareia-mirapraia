import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestRestaurantPaymentsTransfers(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Simulate User
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Restaurante'

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.CashierService.add_transaction')
    @patch('app.blueprints.restaurant.routes.get_current_cashier')
    def test_partial_payment_flow(self, mock_get_cashier, mock_add_transaction, mock_save, mock_load):
        # Setup
        mock_get_cashier.return_value = {'id': 'session1', 'status': 'open'}
        orders = {
            '10': {
                'items': [{'name': 'Item 1', 'qty': 1, 'price': 100.0}],
                'total': 100.0,
                'status': 'open',
                'partial_payments': [],
                'total_paid': 0.0
            }
        }
        mock_load.return_value = orders

        # 1. Add Partial Payment
        response = self.client.post('/restaurant/table/10', data={
            'action': 'add_partial_payment',
            'amount': '40.00',
            'payment_method': 'Pix'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Pagamento parcial registrado', response.data)
        
        # Verify Cashier called
        mock_add_transaction.assert_called_once()
        args, kwargs = mock_add_transaction.call_args
        self.assertEqual(kwargs['amount'], 40.0)
        self.assertEqual(kwargs['transaction_type'], 'sale')
        
        # Verify Order Updated
        saved_order = mock_save.call_args[0][0]['10']
        self.assertEqual(saved_order['total_paid'], 40.0)
        self.assertEqual(len(saved_order['partial_payments']), 1)

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.load_sales_history')
    @patch('app.blueprints.restaurant.routes.save_sales_history')
    @patch('app.blueprints.restaurant.routes.CashierService.add_transaction')
    @patch('app.blueprints.restaurant.routes.get_current_cashier')
    def test_close_order_with_partial_payment(self, mock_get_cashier, mock_add_trans, mock_save_hist, mock_load_hist, mock_save_orders, mock_load_orders):
        # Scenario: Total 110 (100 + 10 service). Paid 40 partial. Remaining 70.
        # User pays 70.
        
        mock_get_cashier.return_value = {'id': 'session1', 'status': 'open'}
        orders = {
            '10': {
                'items': [{'name': 'Item 1', 'qty': 1, 'price': 100.0}],
                'total': 100.0,
                'status': 'open',
                'partial_payments': [{'amount': 40.0, 'method': 'Pix'}],
                'total_paid': 40.0
            }
        }
        mock_load_orders.return_value = orders
        mock_load_hist.return_value = []

        # Simulate Form Data
        # We send ONLY the remaining payment (70)
        payment_data = json.dumps([{'method': 'Dinheiro', 'amount': 70.0}])
        
        response = self.client.post('/restaurant/table/10', data={
            'action': 'close_order',
            'payment_data': payment_data,
            # We assume backend calculates grand total = 110
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify Cashier: Should be called ONLY for 70.0
        # If it's called for 110 or 40+70, it's wrong (double counting 40)
        mock_add_trans.assert_called_once()
        self.assertEqual(mock_add_trans.call_args[1]['amount'], 70.0)
        
        # Verify History: Should include BOTH payments
        saved_history = mock_save_hist.call_args[0][0]
        closed_order = saved_history[0]
        # Total payments in history should be list of dicts
        self.assertEqual(len(closed_order['payments']), 2) # 1 partial + 1 new

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    def test_transfer_item_validation(self, mock_save, mock_load):
        # Scenario: Table 10 has 1 item (100.0). Paid 90.0. Remaining 10.0 + service.
        # Try to transfer the item (100.0).
        # Remaining balance becomes negative (-90). This should be BLOCKED.
        
        orders = {
            '10': {
                'items': [{'name': 'Item 1', 'qty': 1, 'price': 100.0}],
                'total': 100.0,
                'total_paid': 90.0,
                'status': 'open'
            },
            '50': {
                'items': [],
                'total': 0.0,
                'status': 'open'
            }
        }
        mock_load.return_value = orders
        
        data = {
            'source_table_id': '10',
            'target_table_id': '50',
            'item_index': 0,
            'qty': 1
        }
        
        response = self.client.post('/restaurant/transfer_item', json=data)
        
        # Expect Error because transferring 100 would leave table with 0 total but 90 paid
        self.assertEqual(response.status_code, 400)
        self.assertIn('Transferência bloqueada', response.json['error'])
        self.assertIn('excederia o novo total', response.json['error'])

if __name__ == '__main__':
    unittest.main()
