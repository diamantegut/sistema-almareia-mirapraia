
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
    @patch('app.blueprints.reception.routes.CashierService.add_transaction')
    @patch('app.blueprints.reception.routes.load_printers')
    @patch('app.blueprints.reception.routes.print_cashier_ticket_async')
    def test_reception_cashier_withdrawal_print_redirect(self, mock_print_async, mock_load_printers, mock_add_transaction, mock_load):
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
        mock_load_printers.return_value = [{'id': 'PRN_REC', 'name': 'Recepcao'}]

        # 2. Perform Withdrawal
        response = self.client.post('/reception/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50,00',
            'description': 'Test Sangria'
        }, follow_redirects=False)

        # 3. Verify Redirect
        self.assertEqual(response.status_code, 302)
        redirect_url = response.location
        self.assertIn('/reception/cashier', redirect_url)
        mock_add_transaction.assert_called_once()
        mock_print_async.assert_called_once()

    @patch('app.blueprints.restaurant.routes.CashierService.get_active_session')
    @patch('app.blueprints.restaurant.routes.CashierService.add_transaction')
    @patch('app.blueprints.restaurant.routes.load_printers')
    @patch('app.blueprints.restaurant.routes.print_cashier_ticket_async')
    def test_restaurant_cashier_withdrawal_print_redirect(self, mock_print_async, mock_load_printers, mock_add_transaction, mock_get_active_session):
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
        mock_get_active_session.return_value = mock_session

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'admin'
            sess['permissions'] = ['principal', 'restaurante']
        mock_load_printers.return_value = [{'id': 'PRN_REST', 'name': 'Restaurante'}]

        # 2. Perform Withdrawal
        response = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '30.00',
            'description': 'Rest Sangria'
        }, follow_redirects=False)

        # 3. Verify response and side effects
        self.assertIn(response.status_code, [200, 302])
        mock_add_transaction.assert_called_once()
        mock_print_async.assert_called_once()

    @patch('app.blueprints.reception.routes.CashierService.get_active_session')
    @patch('app.blueprints.reception.routes.CashierService.add_transaction')
    @patch('app.blueprints.reception.routes.load_printers')
    @patch('app.blueprints.reception.routes.print_cashier_ticket_async')
    def test_reception_reservations_cashier_withdrawal_print_redirect(self, mock_print_async, mock_load_printers, mock_add_transaction, mock_get_active_session):
        # 1. Setup open session
        session_id = 'REC_RES_TEST_SESSION'
        mock_session = {
            'id': session_id,
            'user': self.user,
            'type': 'reservation_cashier',
            'status': 'open',
            'opening_balance': 300.0,
            'transactions': []
        }
        mock_get_active_session.return_value = mock_session
        mock_load_printers.return_value = [{'id': 'PRN_RES', 'name': 'Recepcao Reservas'}]

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
        self.assertIn('/reception/reservations-cashier', redirect_url)
        mock_add_transaction.assert_called_once()
        mock_print_async.assert_not_called()


if __name__ == '__main__':
    unittest.main()
