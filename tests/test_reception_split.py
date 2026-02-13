import unittest
from unittest.mock import patch, MagicMock
from app import create_app
import json

class TestReceptionSplit(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch('app.blueprints.reception.routes.load_room_occupancy')
    @patch('app.blueprints.reception.routes.load_room_charges')
    @patch('app.blueprints.reception.routes.CashierService')
    @patch('app.blueprints.reception.routes.FiscalPoolService')
    @patch('app.blueprints.reception.routes.load_payment_methods')
    @patch('app.blueprints.reception.routes.save_room_charges')
    def test_close_account_creates_multiple_fiscal_entries(self, mock_save_charges, mock_payment_methods, mock_fiscal_pool, mock_cashier, mock_load_charges, mock_occupancy):
        # Mock Session with valid user 'Angelo' (admin)
        with self.client.session_transaction() as sess:
            sess['user'] = 'Angelo'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'admin']

        # Mock Data
        mock_occupancy.return_value = {
            '10': {'guest_name': 'Test Guest'}
        }
        
        # Two pending charges
        mock_load_charges.return_value = [
            {
                'id': 'charge1',
                'room_number': '10',
                'status': 'pending',
                'total': 50.0,
                'items': [{'name': 'Item 1', 'price': 50.0, 'qty': 1}]
            },
            {
                'id': 'charge2',
                'room_number': '10',
                'status': 'pending',
                'total': 30.0,
                'items': [{'name': 'Item 2', 'price': 30.0, 'qty': 1}]
            }
        ]
        
        mock_cashier.get_active_session.return_value = {'id': 'session1', 'status': 'open'}
        
        mock_payment_methods.return_value = [
            {'id': 'card', 'name': 'Cartão', 'is_fiscal': True}
        ]

        # Execute POST
        response = self.client.post('/reception/close_account/10', json={
            'payment_method': 'card',
            'print_receipt': False
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Verify Fiscal Pool Calls
        # Should be called twice, once for each charge
        self.assertEqual(mock_fiscal_pool.add_to_pool.call_count, 2)
        
        # Verify call arguments
        calls = mock_fiscal_pool.add_to_pool.call_args_list
        
        # Call 1
        args1, kwargs1 = calls[0]
        self.assertEqual(kwargs1['original_id'], 'CHARGE_charge1')
        self.assertEqual(kwargs1['total_amount'], 50.0)
        
        # Call 2
        args2, kwargs2 = calls[1]
        self.assertEqual(kwargs2['original_id'], 'CHARGE_charge2')
        self.assertEqual(kwargs2['total_amount'], 30.0)

if __name__ == '__main__':
    unittest.main()
