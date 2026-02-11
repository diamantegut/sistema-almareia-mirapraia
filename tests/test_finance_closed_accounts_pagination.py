import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from services.closed_account_service import ClosedAccountService

class TestFinanceClosedAccountsPagination(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        self.app.testing = True
        
        # Sample Data: 50 accounts
        self.sample_accounts = []
        for i in range(50):
            self.sample_accounts.append({
                'id': f'CLOSED_{i:03d}',
                'timestamp': '01/01/2026 12:00:00',
                'closed_at': '01/01/2026 12:00:00',
                'total': 100.0 + i,
                'user': f'cashier_{i%2}', # cashier_0, cashier_1
                'closed_by': f'cashier_{i%2}',
                'status': 'closed' if i % 5 != 0 else 'reopened', # 0, 5, 10... are reopened
                'origin': 'restaurant_table'
            })
            
        # Sort by ID descending as the service does (newest first)
        self.sample_accounts.sort(key=lambda x: x['id'], reverse=True)

    @patch('services.closed_account_service.ClosedAccountService._load_closed_accounts')
    def test_pagination_logic(self, mock_load):
        mock_load.return_value = self.sample_accounts
        
        # Test Page 1, limit 20
        result = ClosedAccountService.search_closed_accounts(page=1, per_page=20)
        self.assertEqual(len(result['items']), 20)
        self.assertEqual(result['total'], 50)
        self.assertEqual(result['pages'], 3)
        self.assertEqual(result['page'], 1)
        
        # Test Page 3 (last page, should have 10 items)
        result = ClosedAccountService.search_closed_accounts(page=3, per_page=20)
        self.assertEqual(len(result['items']), 10)
        
        # Test Out of bounds (Page 4 -> should clamp to last page)
        result = ClosedAccountService.search_closed_accounts(page=4, per_page=20)
        self.assertEqual(result['page'], 3)
        self.assertEqual(len(result['items']), 10)

    @patch('services.closed_account_service.ClosedAccountService._load_closed_accounts')
    def test_cashier_filter_logic(self, mock_load):
        mock_load.return_value = self.sample_accounts
        
        # Filter for cashier_0
        filters = {'user': 'cashier_0', 'status': 'closed'}
        result = ClosedAccountService.search_closed_accounts(filters, page=1, per_page=50)
        
        # Logic:
        # Total items: 50
        # cashier_0 items (even indices): 0, 2, 4... 48 -> 25 items
        # Reopened items (indices divisible by 5): 0, 5, 10, 15, 20, 25, 30, 35, 40, 45
        # cashier_0 AND Reopened: 0, 10, 20, 30, 40 -> 5 items
        # Expected closed items for cashier_0: 25 - 5 = 20 items
        
        self.assertEqual(result['total'], 20)
        for item in result['items']:
            self.assertIn('cashier_0', item['user'])
            self.assertEqual(item['status'], 'closed')

    @patch('services.closed_account_service.ClosedAccountService._load_closed_accounts')
    def test_api_admin_access(self, mock_load):
        mock_load.return_value = self.sample_accounts
        
        with self.app.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        # Admin requests all
        response = self.app.get('/api/closed_accounts?page=1&per_page=10')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data['items']), 10)
        self.assertEqual(data['total'], 50)

    @patch('services.closed_account_service.ClosedAccountService._load_closed_accounts')
    def test_api_cashier_access(self, mock_load):
        mock_load.return_value = self.sample_accounts
        
        with self.app.session_transaction() as sess:
            sess['user'] = 'cashier_0'
            sess['role'] = 'caixa'
            
        # Cashier requests (should be filtered automatically to cashier_0 and closed status)
        response = self.app.get('/api/closed_accounts?page=1&per_page=50')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        # Should only see cashier_0 items that are closed (20 items)
        self.assertEqual(data['total'], 20)
        for item in data['items']:
            self.assertEqual(item['user'], 'cashier_0')
            self.assertEqual(item['status'], 'closed')
            
    @patch('services.closed_account_service.ClosedAccountService._load_closed_accounts')
    def test_api_unauthorized_access(self, mock_load):
        mock_load.return_value = self.sample_accounts
        
        with self.app.session_transaction() as sess:
            sess['user'] = 'guest'
            sess['role'] = 'unknown'
            
        response = self.app.get('/api/closed_accounts')
        self.assertEqual(response.status_code, 403)

if __name__ == '__main__':
    unittest.main()
