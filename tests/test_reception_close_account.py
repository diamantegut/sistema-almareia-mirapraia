
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestReceptionCloseAccount(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        self.app.testing = True
        
        # Mock session data
        self.user = 'test_user'
        
    @patch('app.load_room_occupancy')
    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_payment_methods')
    @patch('app.CashierService.add_transaction')
    @patch('app.CashierService.get_active_session')
    @patch('app.log_action')
    def test_close_account_success(self, mock_log, mock_get_session, mock_add_tx, mock_load_methods, mock_save_charges, mock_load_charges, mock_load_occupancy):
        # Setup Mocks
        with self.app.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'recepcao'
            sess['permissions'] = ['recepcao']

        mock_load_occupancy.return_value = {
            '101': {'guest_name': 'John Doe', 'checkin': '01/01/2026', 'checkout': '05/01/2026'}
        }
        
        mock_load_charges.return_value = [
            {
                'id': 'charge_1',
                'room_number': '101',
                'status': 'pending',
                'items': [{'name': 'Coke', 'qty': 2, 'price': 5.0, 'service_fee_exempt': True}],
                'total': 10.0
            }
        ]
        
        session_data = {
            'id': 'session_1',
            'user': self.user,
            'status': 'open',
            'type': 'guest_consumption',
            'transactions': []
        }
        mock_get_session.return_value = session_data
        mock_load_methods.return_value = []
        
        # Execute Request
        response = self.app.post('/reception/close_account/101', 
                                 data=json.dumps({'payment_method': 'credit_card', 'print_receipt': False}),
                                 content_type='application/json')
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify Charge Update
        args_charges = mock_save_charges.call_args[0][0]
        self.assertEqual(args_charges[0]['status'], 'paid')
        self.assertEqual(args_charges[0]['payment_method'], 'credit_card')
        
        # Verify CashierService transaction
        self.assertTrue(mock_add_tx.called)
        _, kwargs = mock_add_tx.call_args
        self.assertEqual(kwargs['amount'], 10.0)
        self.assertEqual(kwargs['payment_method'], 'credit_card')
        self.assertEqual(kwargs['user'], self.user)
        self.assertEqual(kwargs['details']['category'], 'Baixa de Conta')

    @patch('app.load_room_occupancy')
    @patch('app.load_room_charges')
    @patch('app.load_cashier_sessions')
    def test_missing_payment_method(self, mock_load_sessions, mock_load_charges, mock_load_occupancy):
        with self.app.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'recepcao'
            sess['permissions'] = ['recepcao']

        response = self.app.post('/reception/close_account/101', 
                                 data=json.dumps({'print_receipt': False}),
                                 content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertIn('Forma de pagamento é obrigatória', data['error'])

    @patch('app.load_room_occupancy')
    @patch('app.CashierService.get_active_session')
    def test_no_open_cashier(self, mock_get_session, mock_load_occupancy):
        with self.app.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'recepcao'
            sess['permissions'] = ['recepcao']
            
        mock_load_occupancy.return_value = {
            '101': {'guest_name': 'John Doe'}
        }
            
        # No open cashier session for guest consumption
        mock_get_session.return_value = None
        
        response = self.app.post('/reception/close_account/101', 
                                 data=json.dumps({'payment_method': 'cash'}),
                                 content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('Nenhum caixa de Consumo de Hóspedes aberto', data['error'])

if __name__ == '__main__':
    unittest.main()
