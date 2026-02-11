
import unittest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestReceiptPrinting(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.secret_key = 'test_secret'
        self.client = app.test_client()
        self.user = 'test_user'

    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.trigger_auto_receipt_print')
    def test_reception_cashier_withdrawal_print_redirect(self, mock_trigger_print, mock_save, mock_load):
        # 1. Setup open session
        session_id = 'REC_TEST_SESSION'
        mock_session = {
            'id': session_id,
            'user': self.user,
            'type': 'guest_consumption', # Correct type for reception cashier
            'status': 'open',
            'opening_balance': 100.0,
            'transactions': []
        }
        # Important: return a copy list so modifications don't affect subsequent calls if using side_effect,
        # but here we just return the list. 
        # Note: App logic modifies objects in place.
        mock_load.return_value = [mock_session]

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'admin'
            sess['permissions'] = ['principal', 'recepcao']

        # 2. Perform Withdrawal
        response = self.client.post('/reception/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50,00',
            'description': 'Test Sangria'
        }, follow_redirects=False)

        # 3. Verify Redirect contains print_receipt
        self.assertEqual(response.status_code, 302)
        redirect_url = response.location
        if 'print_receipt=' not in redirect_url:
             print(f"DEBUG: Redirect URL: {redirect_url}")
        self.assertIn('print_receipt=', redirect_url)
        
        # Verify Trigger was called
        mock_trigger_print.assert_called_once()
        
        # Extract transaction ID from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)
        trans_id = params['print_receipt'][0]
        
        # 4. Verify transaction saved
        saved_sessions = mock_save.call_args[0][0]
        # Find our session
        saved_session = next(s for s in saved_sessions if s['id'] == session_id)
        self.assertEqual(saved_session['transactions'][0]['id'], trans_id)
        
        # 5. Verify GET with print_receipt renders template with receipt block
        # Update mock load to include the new transaction
        mock_session['transactions'].append(saved_session['transactions'][0])
        mock_load.return_value = [mock_session]
        
        response_get = self.client.get(f'/reception/cashier?print_receipt={trans_id}')
        self.assertEqual(response_get.status_code, 200)
        content = response_get.data.decode('utf-8')
        
        # Check for receipt specific HTML
        self.assertIn('id="receipt-print"', content)
        self.assertIn('Comprovante de Retirada (Sangria)', content)
        self.assertIn('Test Sangria', content)
        self.assertIn('50.00', content)

    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.trigger_auto_receipt_print')
    def test_restaurant_cashier_withdrawal_print_redirect(self, mock_trigger_print, mock_save, mock_load):
        # 1. Setup open session
        session_id = 'REST_TEST_SESSION'
        mock_session = {
            'id': session_id,
            'user': self.user,
            'type': 'restaurant_service', # Correct type
            'status': 'open',
            'opening_balance': 200.0,
            'transactions': []
        }
        mock_load.return_value = [mock_session]

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'admin'
            sess['permissions'] = ['principal', 'restaurante']

        # 2. Perform Withdrawal
        response = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '30.00',
            'description': 'Rest Sangria'
        }, follow_redirects=False)

        # 3. Verify Redirect
        self.assertEqual(response.status_code, 302)
        redirect_url = response.location
        if 'print_receipt=' not in redirect_url:
            print(f"DEBUG: Redirect URL: {redirect_url}")
        self.assertIn('print_receipt=', redirect_url)
        
        # Verify Trigger was called
        mock_trigger_print.assert_called_once()
        
        # Extract transaction ID
        import urllib.parse
        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)
        trans_id = params['print_receipt'][0]

        # 4. Verify GET renders template
        # Check what was passed to save
        args = mock_save.call_args[0]
        saved_sessions = args[0]
        
        # Debugging
        if not isinstance(saved_sessions, list):
            print(f"DEBUG: saved_sessions is not list: {type(saved_sessions)}")
            print(f"DEBUG: Content: {saved_sessions}")
        
        saved_session = next(s for s in saved_sessions if s['id'] == session_id)
        mock_session['transactions'].append(saved_session['transactions'][0])
        mock_load.return_value = [mock_session]
        
        response_get = self.client.get(f'/restaurant/cashier?print_receipt={trans_id}')
        self.assertEqual(response_get.status_code, 200)
        content = response_get.data.decode('utf-8')
        
        self.assertIn('id="receipt-print"', content)
        self.assertIn('Comprovante de Retirada (Sangria)', content)
        self.assertIn('Rest Sangria', content)

    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.trigger_auto_receipt_print')
    def test_reception_reservations_cashier_withdrawal_print_redirect(self, mock_trigger_print, mock_save, mock_load):
        # 1. Setup open session
        session_id = 'REC_RES_TEST_SESSION'
        mock_session = {
            'id': session_id,
            'user': self.user,
            'type': 'reception_reservations',
            'status': 'open',
            'opening_balance': 300.0,
            'transactions': []
        }
        mock_load.return_value = [mock_session]

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'admin'
            sess['permissions'] = ['principal', 'recepcao', 'reservas']

        # 2. Perform Withdrawal
        response = self.client.post('/reception/reservations-cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '100.00',
            'description': 'Res Sangria'
        }, follow_redirects=False)

        # 3. Verify Redirect
        self.assertEqual(response.status_code, 302)
        redirect_url = response.location
        self.assertIn('print_receipt=', redirect_url)
        
        # Verify Trigger was called
        mock_trigger_print.assert_called_once()
        
        # Extract transaction ID
        import urllib.parse
        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)
        trans_id = params['print_receipt'][0]

        # 4. Verify GET renders template
        args = mock_save.call_args[0]
        saved_sessions = args[0]
        saved_session = next(s for s in saved_sessions if s['id'] == session_id)
        mock_session['transactions'].append(saved_session['transactions'][0])
        mock_load.return_value = [mock_session]
        
        response_get = self.client.get(f'/reception/reservations-cashier?print_receipt={trans_id}')
        self.assertEqual(response_get.status_code, 200)
        content = response_get.data.decode('utf-8')
        
        self.assertIn('id="receipt-print"', content)
        self.assertIn('Comprovante de Retirada (Sangria)', content)
        self.assertIn('Res Sangria', content)


if __name__ == '__main__':
    unittest.main()
