import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from app import app

class TestIntegrationOrderPrint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        app.config['TESTING'] = True
        app.secret_key = 'test_secret'

    def tearDown(self):
        self.app_context.pop()

    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.load_printers')
    @patch('app.load_menu_items')
    @patch('app.load_complements') # Need to mock this
    @patch('app.print_order_items')
    @patch('app.load_room_occupancy')
    def test_order_to_print_flow(self, mock_occupancy, mock_print_items, mock_complements, mock_menu, mock_printers, mock_save_orders, mock_load_orders):
        """
        Integration test:
        1. User adds items (Batch) via POST.
        2. System processes items (resolving complement IDs to dicts).
        3. System calls print_order_items with correct data structure (list of dicts).
        """
        print("\n=== INTEGRATION TEST: ORDER -> PRINT FLOW ===")
        
        # 1. Setup Data
        mock_occupancy.return_value = {}
        
        # Existing open table
        orders_db = {
            "40": {
                "status": "open",
                "items": [],
                "total": 0.0,
                "opened_at": "01/01/2026 12:00",
                "waiter": "Joao",
                "customer_type": "cliente"
            }
        }
        mock_load_orders.return_value = orders_db
        
        # Printers
        mock_printers.return_value = [{'id': 1, 'name': 'Kitchen', 'type': 'network', 'ip': '192.168.1.100'}]
        
        # Menu Items (Products)
        mock_menu.return_value = [
            {'id': '101', 'name': 'Gin Tonica', 'price': 25.0, 'printer_id': 1, 'category': 'Bebidas', 'should_print': True},
        ]
        
        # Complements
        mock_complements.return_value = [
            {'id': '201', 'name': 'Gelo', 'price': 0.0, 'category': 'Insumo'}
        ]
        
        # 2. Simulate User Action (Add Batch Items)
        # Payload mimicking the frontend JSON payload for batch items
        # NOTE: Frontend sends 'items_json' string
        
        batch_items_payload = [
            {
                "id": "101", # Gin Tonica
                "product": "Gin Tonica", # Required by backend
                "qty": 1,
                "complements": ["201"], # List of IDs
                "observations": ["Sem canudo"]
            }
        ]
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Garcom Teste'
            
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'add_batch_items',
            'items_json': json.dumps(batch_items_payload),
            'waiter': 'Joao',
            'batch_id': 'BATCH_TEST_001'
        }, follow_redirects=True)
        
        # 3. Verify Response
        self.assertEqual(resp.status_code, 200)
        content = resp.data.decode('utf-8')
        
        # Check if success message appears
        if "itens adicionados e enviados para impressão" in content:
            print("  [OK] Success message received.")
        else:
            print("  [FALHA] Success message not found.")
            print("  --- Response Content Start ---")
            print(content[:2000])
            print("  --- Response Content End ---")

        # 4. Verify Print Call
        # Ensure print_order_items was called
        self.assertTrue(mock_print_items.called, "print_order_items should be called")
        
        # Check arguments passed to print_order_items
        args, kwargs = mock_print_items.call_args
        
        # new_items passed to print function
        new_items = kwargs.get('new_items')
        self.assertIsNotNone(new_items)
        self.assertEqual(len(new_items), 1)
        
        item = new_items[0]
        print(f"  [DEBUG] Item sent to print: {item['name']}")
        print(f"  [DEBUG] Complements: {item['complements']}")
        
        self.assertEqual(item['name'], 'Gin Tonica')
        self.assertEqual(len(item['complements']), 1)
        
        # CRITICAL CHECK: Verify complement is a string (app.py converts to list of strings)
        comp = item['complements'][0]
        self.assertIsInstance(comp, str, "Complement should be a string (name) as processed by app.py")
        self.assertEqual(comp, 'Gelo')
        
        print("  [OK] Integration test passed: Complements resolved and passed as strings.")

if __name__ == '__main__':
    unittest.main()
