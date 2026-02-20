
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import app creation
try:
    from app import create_app
except ImportError:
    from app import app as flask_app
    def create_app(): return flask_app

class TestRestaurantOrderIssue(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Mock session
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_system_action')
    @patch('app.blueprints.restaurant.routes.load_complements')
    @patch('app.blueprints.restaurant.routes.load_printers')
    @patch('app.blueprints.restaurant.routes.print_order_items')
    def test_add_valid_item(self, mock_print, mock_load_printers, mock_comps, mock_log_action, mock_save_orders, mock_load_orders, mock_load_menu):
        # Setup Data
        mock_menu = [
            {"id": "100", "name": "Batata Frita", "category": "Petiscos", "price": 25.0, "active": True},
            {"id": "101", "name": "Coca Cola", "category": "Bebidas", "price": 5.0, "active": True}
        ]
        # Table 01 is open
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        mock_load_menu.return_value = mock_menu
        mock_load_orders.return_value = mock_orders
        mock_comps.return_value = []
        mock_load_printers.return_value = []
        mock_print.return_value = {'printed_ids': [], 'results': {}}

        # Attempt to add valid item
        payload = {
            "action": "add_batch_items",
            "items_json": json.dumps([{"product": "100", "qty": 1}]) 
        }
        
        response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)
        
        # Check for error message
        if b'Nenhum item' in response.data:
            print("\n!!! REPRODUCED: Got 'Nenhum item válido adicionado' for valid item !!!")
        else:
            print("\nSUCCESS: Item added successfully.")
            
        self.assertNotIn(b'Nenhum item', response.data)
        self.assertIn(b'Pedido enviado com sucesso', response.data)

    def test_add_invalid_item_not_found(self):
        # Test case: Product ID not in menu
        mock_menu = [{"id": "100", "name": "Batata", "category": "Petiscos", "active": True}]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        with patch('app.blueprints.restaurant.routes.load_menu_items', return_value=mock_menu), \
             patch('app.blueprints.restaurant.routes.load_table_orders', return_value=mock_orders), \
             patch('app.blueprints.restaurant.routes.load_complements', return_value=[]), \
             patch('app.blueprints.restaurant.routes.load_printers', return_value=[]):
             
            payload = {
                "action": "add_batch_items",
                "items_json": json.dumps([{"product": "999", "qty": 1}]) 
            }
            response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)
            self.assertIn(b'Nenhum item', response.data)
            # Check for detailed error message (decoding for safety)
            decoded_response = response.data.decode('utf-8')
            self.assertIn("Produto ID 999 não encontrado", decoded_response)

    def test_add_inactive_item(self):
        # Test case: Product is inactive
        mock_menu = [{"id": "100", "name": "Batata", "category": "Petiscos", "active": False}]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        with patch('app.blueprints.restaurant.routes.load_menu_items', return_value=mock_menu), \
             patch('app.blueprints.restaurant.routes.load_table_orders', return_value=mock_orders), \
             patch('app.blueprints.restaurant.routes.load_complements', return_value=[]), \
             patch('app.blueprints.restaurant.routes.load_printers', return_value=[]):
             
            payload = {
                "action": "add_batch_items",
                "items_json": json.dumps([{"product": "100", "qty": 1}]) 
            }
            response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)
            self.assertIn(b'Nenhum item', response.data)
            
            decoded_response = response.data.decode('utf-8')
            self.assertIn("inativo ignorado", decoded_response)

    def test_add_invalid_qty(self):
        # Test case: Qty is 0
        mock_menu = [{"id": "100", "name": "Batata", "category": "Petiscos", "active": True}]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        with patch('app.blueprints.restaurant.routes.load_menu_items', return_value=mock_menu), \
             patch('app.blueprints.restaurant.routes.load_table_orders', return_value=mock_orders), \
             patch('app.blueprints.restaurant.routes.load_complements', return_value=[]), \
             patch('app.blueprints.restaurant.routes.load_printers', return_value=[]):
             
            payload = {
                "action": "add_batch_items",
                "items_json": json.dumps([{"product": "100", "qty": 0}]) 
            }
            response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)
            self.assertIn(b'Nenhum item', response.data)
            
            decoded_response = response.data.decode('utf-8')
            self.assertIn("Quantidade deve ser positiva", decoded_response)


    def test_add_item_by_name(self):
        # Test case: Passing product name instead of ID (Legacy Support)
        mock_menu = [{"id": "100", "name": "Batata", "category": "Petiscos", "active": True}]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        with patch('app.blueprints.restaurant.routes.load_menu_items', return_value=mock_menu), \
             patch('app.blueprints.restaurant.routes.load_table_orders', return_value=mock_orders), \
             patch('app.blueprints.restaurant.routes.load_complements', return_value=[]), \
             patch('app.blueprints.restaurant.routes.load_printers', return_value=[]), \
             patch('app.blueprints.restaurant.routes.print_order_items', return_value={'printed_ids': [], 'results': {}}), \
             patch('app.blueprints.restaurant.routes.log_system_action') as mock_log, \
             patch('app.blueprints.restaurant.routes.save_table_orders'):
             
            payload = {
                "action": "add_batch_items",
                "items_json": json.dumps([{"product": "Batata", "qty": 1}]) # Name passed instead of ID
            }
            response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)
            
            self.assertIn(b'Pedido enviado com sucesso', response.data)
            self.assertEqual(len(mock_orders['01']['items']), 1)
            self.assertEqual(mock_orders['01']['items'][0]['product_id'], "100") # Should resolve to ID

    @patch('app.blueprints.restaurant.routes.save_stock_entry')
    @patch('app.blueprints.restaurant.routes.load_products')
    @patch('app.blueprints.restaurant.routes.load_flavor_groups')
    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_system_action')
    @patch('app.blueprints.restaurant.routes.load_complements')
    @patch('app.blueprints.restaurant.routes.load_printers')
    @patch('app.blueprints.restaurant.routes.print_order_items')
    def test_flavor_stock_deduction(self, mock_print, mock_load_printers, mock_comps, mock_log_action, mock_save_orders, mock_load_orders, mock_load_menu, mock_flavor_groups, mock_load_products, mock_save_stock):
        mock_menu = [
            {
                "id": "200",
                "name": "Pizza Dois Sabores",
                "category": "Pizzas",
                "price": 50.0,
                "active": True,
                "flavor_group_id": "Sabores",
                "flavor_multiplier": 1.0
            }
        ]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        mock_flavor_groups.return_value = [
            {
                "id": "Sabores",
                "name": "Sabores",
                "items": [
                    {"id": "131", "name": "Queijo Mussarela", "qty": 0.1, "is_simple": True},
                    {"id": "69", "name": "Charque Desfiada", "qty": 0.2, "is_simple": True}
                ]
            }
        ]
        mock_load_products.return_value = [
            {"id": "131", "name": "Queijo Mussarela", "price": 10.0},
            {"id": "69", "name": "Charque Desfiada", "price": 15.0}
        ]
        mock_load_menu.return_value = mock_menu
        mock_load_orders.return_value = mock_orders
        mock_comps.return_value = []
        mock_load_printers.return_value = []
        mock_print.return_value = {'printed_ids': [], 'results': {}}

        payload = {
            "action": "add_batch_items",
            "items_json": json.dumps([{
                "product": "200",
                "qty": 2,
                "flavor_id": "131,69",
                "flavor_name": "Queijo Mussarela + Charque Desfiada"
            }])
        }

        response = self.client.post('/restaurant/table/01', data=payload, follow_redirects=True)

        self.assertIn(b'Pedido enviado com sucesso', response.data)
        self.assertGreaterEqual(mock_save_stock.call_count, 2)

        calls = [c[0][0] for c in mock_save_stock.call_args_list]
        entries = {(e['product'], round(e['qty'], 4)) for e in calls}
        self.assertIn(("Queijo Mussarela", -0.2), entries)
        self.assertIn(("Charque Desfiada", -0.4), entries)

if __name__ == '__main__':
    unittest.main()
