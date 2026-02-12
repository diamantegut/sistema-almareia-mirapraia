import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestCancelItem(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Simulate Admin User
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Restaurante'

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_action')
    def test_remove_item_success(self, mock_log, mock_save, mock_load):
        # Setup Order
        orders = {
            '10': {
                'items': [
                    {'id': 'item1', 'name': 'Coke', 'qty': 1, 'price': 5.0, 'printed': False, 'print_status': 'pending', 'complements': []},
                    {'id': 'item2', 'name': 'Burger', 'qty': 1, 'price': 20.0, 'printed': True, 'print_status': 'printed', 'complements': []}
                ],
                'total': 25.0
            }
        }
        mock_load.return_value = orders

        # Action: Remove 'item1' (Coke)
        response = self.client.post('/restaurant/table/10', data={
            'action': 'remove_item',
            'item_id': 'item1',
            'cancellation_reason': 'Customer changed mind'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        # Verify Response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['new_total'], 20.0) # 25 - 5

        # Verify Persistence
        saved_orders = mock_save.call_args[0][0]
        self.assertEqual(len(saved_orders['10']['items']), 1)
        self.assertEqual(saved_orders['10']['items'][0]['id'], 'item2')
        self.assertEqual(saved_orders['10']['total'], 20.0)

        # Verify Audit Log
        mock_log.assert_called_with('Item Removido', 
                                   'Item Coke removido da Mesa 10 por admin. Motivo: Customer changed mind', 
                                   department='Restaurante')

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_action')
    def test_remove_item_printed_success_admin(self, mock_log, mock_save, mock_load):
        # Setup Order with printed item
        orders = {
            '10': {
                'items': [
                    {'id': 'item2', 'name': 'Burger', 'qty': 1, 'price': 20.0, 'printed': True, 'print_status': 'printed', 'complements': []}
                ],
                'total': 20.0
            }
        }
        mock_load.return_value = orders

        # Action: Remove 'item2' as Admin
        response = self.client.post('/restaurant/table/10', data={
            'action': 'remove_item',
            'item_id': 'item2',
            'cancellation_reason': 'Mistake'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        # Verify Response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify Saved (Item removed)
        saved_orders = mock_save.call_args[0][0]
        self.assertEqual(len(saved_orders['10']['items']), 0)

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    def test_remove_item_not_found(self, mock_save, mock_load):
        orders = {'10': {'items': [], 'total': 0.0}}
        mock_load.return_value = orders

        response = self.client.post('/restaurant/table/10', data={
            'action': 'remove_item',
            'item_id': 'non_existent',
            'cancellation_reason': 'Test'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertIn('Item não encontrado', data['error'])

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    def test_remove_item_invalid_table(self, mock_load):
        mock_load.return_value = {}

        response = self.client.post('/restaurant/table/99', data={
            'action': 'remove_item',
            'item_id': 'item1'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertIn('Mesa não encontrada', data['error'])

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.load_users')
    def test_remove_item_insufficient_permissions(self, mock_users, mock_load):
        # Setup as Waiter
        with self.client.session_transaction() as sess:
            sess['user'] = 'waiter'
            sess['role'] = 'garcom'

        orders = {'10': {'items': [{'id': 'item1', 'name': 'Soda', 'qty': 1, 'printed': False}], 'total': 5.0}}
        mock_load.return_value = orders
        
        # Action: Try to remove without password
        response = self.client.post('/restaurant/table/10', data={
            'action': 'remove_item',
            'item_id': 'item1',
            'cancellation_reason': 'Test'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertIn('Autorização necessária', data['error'])

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.log_action')
    def test_remove_item_with_authorization(self, mock_log, mock_users, mock_save, mock_load):
        # Setup as Waiter
        with self.client.session_transaction() as sess:
            sess['user'] = 'waiter'
            sess['role'] = 'garcom'

        orders = {'10': {'items': [{'id': 'item1', 'name': 'Soda', 'qty': 1, 'price': 5.0, 'printed': False}], 'total': 5.0}}
        mock_load.return_value = orders
        
        # Mock Users with Admin Password
        mock_users.return_value = {
            'admin': {'role': 'admin', 'password': 'securepass'},
            'waiter': {'role': 'garcom', 'password': '123'}
        }

        # Action: Remove with correct password
        response = self.client.post('/restaurant/table/10', data={
            'action': 'remove_item',
            'item_id': 'item1',
            'cancellation_reason': 'Test',
            'auth_password': 'securepass'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify Persistence (Item removed)
        saved_orders = mock_save.call_args[0][0]
        self.assertEqual(len(saved_orders['10']['items']), 0)

if __name__ == '__main__':
    unittest.main()
