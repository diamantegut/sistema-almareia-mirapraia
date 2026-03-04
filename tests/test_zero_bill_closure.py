
import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app

class TestZeroBillClosure(unittest.TestCase):
    def setUp(self):
        app.app.config['TESTING'] = True
        app.app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.app.test_client()
        
        # Mock Session
        with self.client.session_transaction() as sess:
            sess['user'] = 'Manager'
            sess['role'] = 'gerente'
            
    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.load_payment_methods')
    @patch('app.log_action')
    def test_zero_bill_success(self, mock_log, mock_load_methods,
                             mock_save_sessions, mock_load_sessions,
                             mock_save_charges, mock_load_charges):
        
        # Setup Data
        charge_id = 'CHARGE_ZERO'
        
        charge = {
            'id': charge_id,
            'room_number': '101',
            'status': 'pending',
            'total': 0.0,
            'items': [],
            'date': '26/01/2026 10:00'
        }
        
        mock_load_charges.return_value = [charge]
        
        # Open Session
        current_session = {
            'id': 'session_rec_current',
            'status': 'open',
            'type': 'reception_room_billing',
            'transactions': []
        }
        mock_load_sessions.return_value = [current_session]
        
        mock_load_methods.return_value = [{'id': 'pix', 'name': 'Pix', 'available_in': ['reception']}]
        
        # Simulate POST request with payment_data='[]'
        response = self.client.post('/reception/cashier', data={
            'action': 'pay_charge',
            'charge_id': charge_id,
            'payment_data': '[]' # Empty list
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify charge updated
        self.assertEqual(charge['status'], 'paid')
        self.assertEqual(charge['payment_method'], 'Isento/Zerado')

    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.load_payment_methods')
    @patch('app.log_action')
    def test_zero_bill_float_precision(self, mock_log, mock_load_methods,
                             mock_save_sessions, mock_load_sessions,
                             mock_save_charges, mock_load_charges):
        
        # Setup Data with tiny float value
        charge_id = 'CHARGE_ZERO_FLOAT'
        
        charge = {
            'id': charge_id,
            'room_number': '102',
            'status': 'pending',
            'total': 0.00000001, # Almost zero
            'items': [],
            'date': '26/01/2026 10:00'
        }
        
        mock_load_charges.return_value = [charge]
        
        # Open Session
        current_session = {
            'id': 'session_rec_current',
            'status': 'open',
            'type': 'reception_room_billing',
            'transactions': []
        }
        mock_load_sessions.return_value = [current_session]
        
        mock_load_methods.return_value = [{'id': 'pix', 'name': 'Pix', 'available_in': ['reception']}]
        
        # Simulate POST request with payment_data='[]'
        response = self.client.post('/reception/cashier', data={
            'action': 'pay_charge',
            'charge_id': charge_id,
            'payment_data': '[]'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify charge updated
        self.assertEqual(charge['status'], 'paid')
        self.assertEqual(charge['payment_method'], 'Isento/Zerado')

    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.load_payment_methods')
    @patch('app.log_action')
    def test_missing_payment_data_handling(self, mock_log, mock_load_methods,
                             mock_save_sessions, mock_load_sessions,
                             mock_save_charges, mock_load_charges):
        
        # Setup Data with non-zero value
        charge_id = 'CHARGE_NON_ZERO'
        
        charge = {
            'id': charge_id,
            'room_number': '103',
            'status': 'pending',
            'total': 100.00,
            'items': [],
            'date': '26/01/2026 10:00'
        }
        
        mock_load_charges.return_value = [charge]
        
        # Open Session
        current_session = {
            'id': 'session_rec_current',
            'status': 'open',
            'type': 'reception_room_billing',
            'transactions': []
        }
        mock_load_sessions.return_value = [current_session]
        
        mock_load_methods.return_value = [{'id': 'pix', 'name': 'Pix', 'available_in': ['reception']}]
        
        # Simulate POST request with payment_data='[]' AND no legacy payment_method
        response = self.client.post('/reception/cashier', data={
            'action': 'pay_charge',
            'charge_id': charge_id,
            'payment_data': '[]'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify charge NOT updated
        self.assertEqual(charge['status'], 'pending')

if __name__ == '__main__':
    unittest.main()
