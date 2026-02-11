import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app

class TestTransferItem(unittest.TestCase):
    def setUp(self):
        app.app.config['TESTING'] = True
        app.app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.app.test_client()
        
        # Setup Default Session (Supervisor)
        with self.client.session_transaction() as sess:
            sess['user'] = 'SupervisorUser'
            sess['role'] = 'supervisor'

    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.log_action')
    def test_transfer_success(self, mock_log, mock_save, mock_load):
        # Setup Data
        source_table = '10'
        target_table = '20'
        
        # Mock the global orders dictionary directly
        app.orders = {
            source_table: {
                'items': [{'name': 'Coke', 'qty': 2.0, 'price': 5.0, 'printed': True}],
                'total': 10.0
            },
            target_table: {
                'items': [],
                'total': 0.0
            }
        }
        
        mock_load.return_value = app.orders

        # Payload
        payload = {
            'source_table_id': source_table,
            'target_table_id': target_table,
            'item_index': 0,
            'qty': 1.0,
            'observations': 'Customer moved'
        }

        # Execute
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        # Verify Response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])

        # Verify Data Changes
        # Source should have 1.0 left
        self.assertEqual(app.orders[source_table]['items'][0]['qty'], 1.0)
        
        # Target should have 1 item with 1.0 qty
        self.assertEqual(len(app.orders[target_table]['items']), 1)
        target_item = app.orders[target_table]['items'][0]
        self.assertEqual(target_item['name'], 'Coke')
        self.assertEqual(target_item['qty'], 1.0)
        # Check observation format
        self.assertTrue(any('Transf de Mesa 10' in obs for obs in target_item.get('observations', [])))
        self.assertTrue(any('Customer moved' in obs for obs in target_item.get('observations', [])))
        # Check printed status preserved
        self.assertTrue(target_item['printed'])

        # Verify Log
        mock_log.assert_called()

    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.log_action')
    def test_transfer_full_quantity(self, mock_log, mock_save, mock_load):
        # Setup Data
        source_table = '10'
        target_table = '20'
        
        app.orders = {
            source_table: {
                'items': [{'name': 'Coke', 'qty': 1.0, 'price': 5.0}],
                'total': 5.0
            },
            target_table: {
                'items': [],
                'total': 0.0
            }
        }
        mock_load.return_value = app.orders

        # Payload
        payload = {
            'source_table_id': source_table,
            'target_table_id': target_table,
            'item_index': 0,
            'qty': 1.0
        }

        # Execute
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify Source Item Removed
        self.assertEqual(len(app.orders[source_table]['items']), 0)
        # Verify Target Item Added
        self.assertEqual(len(app.orders[target_table]['items']), 1)

    def test_access_denied_waiter(self):
        with self.client.session_transaction() as sess:
            sess['role'] = 'waiter'
            
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps({}),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 403)

    @patch('app.load_table_orders')
    def test_invalid_target_table(self, mock_load):
        app.orders = {'10': {'items': [{'name': 'X', 'qty': 1}]}}
        mock_load.return_value = app.orders
        
        payload = {
            'source_table_id': '10',
            'target_table_id': '999', # Doesn't exist
            'item_index': 0,
            'qty': 1
        }
        
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('não está aberta', data['error'])

    @patch('app.load_table_orders')
    def test_transfer_from_locked_table(self, mock_load):
        app.orders = {
            '10': {'items': [{'name': 'X', 'qty': 1}], 'locked': True},
            '20': {'items': []}
        }
        mock_load.return_value = app.orders
        
        payload = {
            'source_table_id': '10',
            'target_table_id': '20',
            'item_index': 0,
            'qty': 1
        }
        
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('fechada/puxada', data['error'])

    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.log_action')
    def test_save_failure(self, mock_log, mock_save, mock_load):
        app.orders = {
            '10': {'items': [{'name': 'X', 'qty': 1, 'price': 10}]},
            '20': {'items': [], 'total': 0}
        }
        mock_load.return_value = app.orders
        mock_save.side_effect = Exception("Disk error")
        
        payload = {
            'source_table_id': '10',
            'target_table_id': '20',
            'item_index': 0,
            'qty': 1
        }
        
        response = self.client.post('/restaurant/transfer_item', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.data)
        self.assertIn('Falha ao salvar', data['error'])
        
        # Verify log was NOT called
        mock_log.assert_not_called()

if __name__ == '__main__':
    unittest.main()
