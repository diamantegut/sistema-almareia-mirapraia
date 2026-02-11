
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, save_table_orders

class TestGuestBillIntegration(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.secret_key = 'test_secret'
        self.client = app.test_client()
        
    @patch('app.load_room_occupancy')
    @patch('app.load_printer_settings')
    @patch('app.load_printers')
    @patch('app.print_bill')
    @patch('app.load_table_orders')
    def test_guest_bill_success(self, mock_load_orders, mock_print_bill, mock_load_printers, mock_load_settings, mock_load_occupancy):
        # Setup Mocks
        mock_load_occupancy.return_value = {
            '101': {'guest_name': 'João Silva', 'status': 'occupied'}
        }
        mock_load_settings.return_value = {'bill_printer_id': 'p1'}
        mock_load_printers.return_value = [{'id': 'p1', 'name': 'Bar'}]
        mock_print_bill.return_value = (True, None)
        
        table_id = '10'
        orders = {
            table_id: {
                'items': [{'name': 'Coke', 'qty': 1, 'price': 5.0}],
                'total': 5.0,
                'customer_type': 'hospede',
                'room_number': '101',
                'status': 'open'
            }
        }
        mock_load_orders.return_value = orders
        
        # Simulate Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_user'
            
        # Action
        response = self.client.post(f'/restaurant/table/{table_id}', data={'action': 'pull_bill'}, follow_redirects=True)
        
        # Verify
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Conta enviada para impress', response.data)
        
        # Verify print_bill call args
        mock_print_bill.assert_called_once()
        call_kwargs = mock_print_bill.call_args[1]
        self.assertEqual(call_kwargs['guest_name'], 'João Silva')
        self.assertEqual(call_kwargs['room_number'], '101')

    @patch('app.load_room_occupancy')
    @patch('app.load_table_orders')
    def test_guest_bill_fail_no_room(self, mock_load_orders, mock_load_occupancy):
        # Setup: Hospede but no room number
        table_id = '11'
        orders = {
            table_id: {
                'items': [{'name': 'Coke', 'qty': 1, 'price': 5.0}],
                'total': 5.0,
                'customer_type': 'hospede',
                'room_number': None, # Missing
                'status': 'open'
            }
        }
        mock_load_orders.return_value = orders
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_user'
            
        response = self.client.post(f'/restaurant/table/{table_id}', data={'action': 'pull_bill'}, follow_redirects=True)
        
        self.assertIn(b'Mesa de h\xc3\xb3spede sem n\xc3\xbamero de quarto', response.data) # Check for partial error message (utf-8 encoded)

    @patch('app.load_room_occupancy')
    @patch('app.load_table_orders')
    def test_guest_bill_fail_invalid_guest(self, mock_load_orders, mock_load_occupancy):
        # Setup: Room exists but no guest name (e.g. glitch or not checked in properly)
        mock_load_occupancy.return_value = {
            '102': {'status': 'cleaning'} # No guest_name
        }
        
        table_id = '12'
        orders = {
            table_id: {
                'items': [{'name': 'Coke', 'qty': 1, 'price': 5.0}],
                'total': 5.0,
                'customer_type': 'hospede',
                'room_number': '102',
                'status': 'open'
            }
        }
        mock_load_orders.return_value = orders
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_user'
            
        response = self.client.post(f'/restaurant/table/{table_id}', data={'action': 'pull_bill'}, follow_redirects=True)
        
        self.assertIn(b'H\xc3\xb3spede n\xc3\xa3o encontrado', response.data)

    @patch('app.load_room_occupancy')
    @patch('app.load_printer_settings')
    @patch('app.load_printers')
    @patch('app.print_bill')
    @patch('app.load_table_orders')
    def test_passante_bill_success(self, mock_load_orders, mock_print_bill, mock_load_printers, mock_load_settings, mock_load_occupancy):
        # Setup: Passante (no validation needed)
        mock_load_settings.return_value = {'bill_printer_id': 'p1'}
        mock_load_printers.return_value = [{'id': 'p1', 'name': 'Bar'}]
        mock_print_bill.return_value = (True, None)
        
        table_id = '13'
        orders = {
            table_id: {
                'items': [{'name': 'Coke', 'qty': 1, 'price': 5.0}],
                'total': 5.0,
                'customer_type': 'passante',
                'status': 'open'
            }
        }
        mock_load_orders.return_value = orders
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_user'
            
        response = self.client.post(f'/restaurant/table/{table_id}', data={'action': 'pull_bill'}, follow_redirects=True)
        
        self.assertIn(b'Conta enviada para impress', response.data)
        
        # Verify print_bill called with None for guest info
        call_kwargs = mock_print_bill.call_args[1]
        self.assertIsNone(call_kwargs.get('guest_name'))
        self.assertIsNone(call_kwargs.get('room_number'))

if __name__ == '__main__':
    unittest.main()
