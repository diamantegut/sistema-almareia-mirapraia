
import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Setup path
sys.path.append(os.getcwd())

from app import create_app

class TestStaffConsumption(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_action')
    def test_open_staff_table_success(self, mock_log, mock_save, mock_load_orders, mock_load_users):
        # Mock Data
        mock_load_users.return_value = {'Angelo': {'username': 'Angelo', 'full_name': 'Angelo Diamante'}}
        mock_load_orders.return_value = {}
        mock_save.return_value = True # Simulate success

        # Simulate Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'Angelo'
            sess['role'] = 'admin'

        # Make Request
        response = self.client.post('/restaurant/open_staff_table', data={'staff_name': 'Angelo'}, follow_redirects=True)
        
        # Check assertions
        self.assertEqual(response.status_code, 200)
        # Should redirect to table order page
        # In testing, we check if logic flowed
        mock_save.assert_called_once()
        args, _ = mock_save.call_args
        orders = args[0]
        self.assertIn('FUNC_Angelo', orders)
        self.assertEqual(orders['FUNC_Angelo']['staff_name'], 'Angelo')

    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    def test_open_staff_table_save_fail(self, mock_save, mock_load_orders, mock_load_users):
        # Mock Data
        mock_load_users.return_value = {'Angelo': {'username': 'Angelo'}}
        mock_load_orders.return_value = {}
        mock_save.return_value = False # Simulate FAIL

        with self.client.session_transaction() as sess:
            sess['user'] = 'Angelo'
            sess['role'] = 'admin'

        response = self.client.post('/restaurant/open_staff_table', data={'staff_name': 'Angelo'}, follow_redirects=True)
        
        # Should show error message
        response_data = response.get_data(as_text=True)
        self.assertIn('Erro ao salvar conta', response_data)

if __name__ == '__main__':
    unittest.main()
