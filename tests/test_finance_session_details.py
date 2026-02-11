
import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime
from app import app
from services.cashier_service import CashierService

class TestFinanceSessionDetails(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()

    @patch('services.cashier_service.CashierService._load_sessions')
    def test_get_session_details_endpoint(self, mock_load):
        # Mock session data
        mock_session = {
            'id': 'SESSION_TEST_123',
            'user': 'test_user',
            'status': 'closed',
            'opened_at': '01/01/2026 10:00',
            'closed_at': '01/01/2026 18:00',
            'opening_balance': 100.0,
            'closing_balance': 200.0,
            'transactions': [
                {'type': 'in', 'amount': 50.0, 'description': 'Sale 1', 'payment_method': 'Cash', 'timestamp': '01/01/2026 12:00'},
                {'type': 'in', 'amount': 50.0, 'description': 'Sale 2', 'payment_method': 'Card', 'timestamp': '01/01/2026 14:00'}
            ]
        }
        mock_load.return_value = [mock_session]

        # Login
        with self.app.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        # Test Endpoint
        response = self.app.get('/api/finance/session/SESSION_TEST_123')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['id'], 'SESSION_TEST_123')
        self.assertEqual(len(data['data']['transactions']), 2)

    @patch('app.load_cashier_sessions')
    @patch('services.cashier_service.CashierService._load_sessions')
    def test_get_balance_data_transaction_count(self, mock_load_service, mock_load_app):
        # Mock session data for balance report
        mock_session = {
            'id': 'SESSION_TEST_123',
            'user': 'test_user',
            'type': 'restaurant_service', # Matches mapping
            'status': 'closed',
            'opened_at': '01/01/2026 10:00',
            'closed_at': '01/01/2026 18:00',
            'opening_balance': 100.0,
            'closing_balance': 200.0,
            'transactions': [
                {'type': 'in', 'amount': 10},
                {'type': 'in', 'amount': 10},
                {'type': 'in', 'amount': 10}
            ] # Length 3
        }
        mock_load_service.return_value = [mock_session]
        mock_load_app.return_value = [mock_session]

        # Login
        with self.app.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        # Test Balance Data Endpoint
        # We need to ensure date range covers the session
        response = self.app.get('/finance/balances/data?period_type=annual&year=2026')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertTrue(data['success'])
        # Find the session in the response
        found = False
        for item in data['data']:
            for s in item['sessions']:
                if s['id'] == 'SESSION_TEST_123':
                    self.assertEqual(s['transactions_count'], 3)
                    found = True
        self.assertTrue(found, "Session not found in balance data")

if __name__ == '__main__':
    unittest.main()
