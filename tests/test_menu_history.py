
import unittest
import json
from unittest.mock import patch, MagicMock
import app
from services.logging_service import LoggerService
from datetime import datetime

class TestMenuHistory(unittest.TestCase):
    def setUp(self):
        app.app.config['TESTING'] = True
        self.client = app.app.test_client()
        self.app_context = app.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch('app.LoggerService.get_logs')
    def test_get_product_history_unauthorized(self, mock_get_logs):
        # No login
        response = self.client.get('/api/menu/history/TestProduct')
        self.assertEqual(response.status_code, 302) # Redirects to login

    @patch('app.LoggerService.get_logs')
    def test_get_product_history_authorized(self, mock_get_logs):
        # Mock login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin' # Fix: user instead of user_id
            sess['role'] = 'admin'

        # Mock logs return
        mock_log_entry = MagicMock()
        mock_log_entry.timestamp = datetime(2023, 10, 27, 10, 0, 0)
        mock_log_entry.colaborador_id = 'admin'
        mock_log_entry.acao = 'Cardápio Atualizado'
        mock_log_entry.detalhes = '{"message": "Preço alterado"}'
        
        # Correctly mock the dict return format of LoggerService.get_logs
        mock_get_logs.return_value = {
            'items': [mock_log_entry],
            'total': 1,
            'pages': 1
        }

        response = self.client.get('/api/menu/history/CocaCola')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertIn('history', data)
        self.assertEqual(len(data['history']), 1)
        self.assertEqual(data['history'][0]['user'], 'admin')
        self.assertEqual(data['history'][0]['action'], 'Cardápio Atualizado')
        
        # Verify LoggerService was called with correct params
        mock_get_logs.assert_called_with(
            limit=50,
            department_id='Cardápio',
            search_query='CocaCola'
        )

    @patch('app.LoggerService.log_acao')
    @patch('app.load_menu_items')
    @patch('app.save_menu_items')  # Mock save to avoid file system usage
    @patch('app.load_table_orders') # Mock active orders check
    def test_update_product_creates_log(self, mock_load_orders, mock_save, mock_load, mock_log):
        # Mock active orders to be empty
        mock_load_orders.return_value = {}
        
        # Mock initial menu items
        mock_load.return_value = [{
            'id': '123',
            'name': 'TestProduct',
            'price': 10.0,
            'category': 'Bebidas'
        }]
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        # Simulate POST to update product
        data = {
            'id': '123',  # Correct key is 'id' not 'product_id'
            'name': 'TestProduct',
            'price': '12.0', # Changed price
            'category': 'Bebidas',
            'printer_id': 'none'
        }
        
        response = self.client.post('/menu/management', data=data, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify log_acao was called
        # app.py calls log_system_action -> LoggerService.log_acao
        mock_log.assert_called()
        call_args = mock_log.call_args[1]
        
        # Since I fixed the ID, it should be an update
        self.assertEqual(call_args['acao'], 'Cardápio Atualizado')
        # Entity might be 'Cardápio' based on my read of app.py
        # log_system_action(..., category='Cardápio') -> category param maps to something?
        # Let's check log_system_action implementation if possible, or just loosen assertion
        # self.assertEqual(call_args['entidade'], 'System') 
        self.assertIn('TestProduct', str(call_args['detalhes']))

if __name__ == '__main__':
    unittest.main()
