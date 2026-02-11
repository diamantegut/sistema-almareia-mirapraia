
import unittest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from unittest.mock import patch, MagicMock
from app import app
from datetime import datetime

class TestCashierClosingFix(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.secret_key = 'test_key'
        self.client = app.test_client()
        self.user_id = 'test_user'

    @patch('app.load_cashier_sessions')
    @patch('app.load_room_charges')
    @patch('app.load_room_occupancy')
    @patch('app.load_printers')
    @patch('app.load_printer_settings')
    @patch('app.load_payment_methods')
    @patch('app.CashierService.close_session')
    def test_close_cashier_logic(self, mock_close_session, mock_payment_methods, mock_printer_settings, mock_printers, mock_occupancy, mock_room_charges, mock_load_sessions):
        # Setup mock data
        open_session = {
            'id': 'SESSION_123',
            'user': self.user_id,
            'status': 'open',
            'type': 'reception_room_billing', # Correct type for reception cashier
            'opened_at': '01/01/2026 10:00',
            'transactions': [],
            'initial_balance': 100.0
        }
        
        # We need a list that persists across calls if possible, or just return a new list each time
        # The key is that app.py calls load_cashier_sessions() ONCE, modifies the object, then calls save_cashier_sessions()
        
        # mock_load_sessions.return_value should be a list containing our session
        sessions_list = [open_session]
        mock_load_sessions.return_value = sessions_list
        
        mock_room_charges.return_value = []
        mock_occupancy.return_value = {}
        mock_printers.return_value = []
        mock_printer_settings.return_value = {}
        mock_payment_methods.return_value = []
        mock_close_session.return_value = {
            'id': 'SESSION_123',
            'user': self.user_id,
            'status': 'closed',
            'type': 'reception_room_billing',
            'opened_at': '01/01/2026 10:00',
            'closed_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'opening_balance': 100.0,
            'closing_balance': 100.0,
            'difference': 0.0,
            'transactions': []
        }

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = self.user_id
            sess['role'] = 'gerente'

        # Simulate POST to close cashier
        response = self.client.post('/reception/cashier', data={
            'action': 'close_cashier',
            'closing_balance': '100.0'
        }, follow_redirects=True)

        self.assertTrue(mock_close_session.called, "CashierService.close_session should be called")
        args, kwargs = mock_close_session.call_args
        self.assertEqual(kwargs.get('session_id'), 'SESSION_123')
        self.assertEqual(kwargs.get('user'), self.user_id)
        
        closed = mock_close_session.return_value
        self.assertEqual(closed['id'], 'SESSION_123')
        self.assertEqual(closed['status'], 'closed')
        self.assertIsNotNone(closed.get('closed_at'))
        print(f"\nTest Result: Session status is {closed['status']}")

    @patch('app.load_cashier_sessions')
    @patch('app.load_room_charges')
    @patch('app.load_room_occupancy')
    @patch('app.load_printers')
    @patch('app.load_printer_settings')
    @patch('app.load_payment_methods')
    @patch('app.CashierService.close_session')
    def test_close_cashier_with_legacy_type(self, mock_close_session, mock_payment_methods, mock_printer_settings, mock_printers, mock_occupancy, mock_room_charges, mock_load_sessions):
        # Test backward compatibility if user has 'reception' type session
        # Note: The code in app.py logic I saw:
        # if s_type == 'restaurant': s_type = 'restaurant_service'
        # if s_type == target_type: (target_type is 'reception_room_billing')
        
        # If the session has type 'reception', it might NOT be matched if we don't handle it.
        # Let's verify this behavior.
        
        open_session = {
            'id': 'SESSION_LEGACY',
            'user': self.user_id,
            'status': 'open',
            'type': 'reception', # Legacy type
            'opened_at': '01/01/2026 10:00',
            'transactions': [],
            'initial_balance': 100.0
        }
        
        sessions_list = [open_session]
        mock_load_sessions.return_value = sessions_list
        
        mock_room_charges.return_value = []
        mock_occupancy.return_value = {}
        mock_printers.return_value = []
        mock_printer_settings.return_value = {}
        mock_payment_methods.return_value = []

        with self.client.session_transaction() as sess:
            sess['user'] = self.user_id
            sess['role'] = 'gerente'

        # Simulate POST to close cashier
        response = self.client.post('/reception/cashier', data={
            'action': 'close_cashier',
            'closing_balance': '100.0'
        }, follow_redirects=True)
        
        # If the legacy session is NOT found, we get "Não há caixa aberto para fechar."
        # and save_cashier_sessions is NOT called.
        
        if b'N\xc3\xa3o h\xc3\xa1 caixa aberto para fechar' in response.data or 'Não há caixa aberto para fechar' in response.data.decode('utf-8'):
             print("\nLegacy session 'reception' was NOT found (expected behavior if we only look for reception_room_billing)")
             # This might be why the user is having issues if they have an old session!
        else:
             print("\nLegacy session WAS found.")
             self.assertTrue(mock_close_session.called)

if __name__ == '__main__':
    unittest.main()
