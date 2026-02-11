
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import app creation (assuming similar structure to existing tests)
try:
    from app import create_app
except ImportError:
    # Fallback if create_app is not directly importable (based on existing test structure)
    from app import app as flask_app
    def create_app(): return flask_app

class TestFrigobarRestriction(unittest.TestCase):
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
    @patch('app.blueprints.restaurant.routes.render_template')
    @patch('app.blueprints.restaurant.routes.load_room_occupancy')
    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_complements')
    @patch('app.blueprints.restaurant.routes.load_flavor_groups')
    @patch('app.blueprints.restaurant.routes.load_observations')
    @patch('app.blueprints.restaurant.routes.load_settings')
    def test_frigobar_hiding_in_menu(self, mock_settings, mock_obs, mock_flavors, mock_comps, mock_users, mock_occupancy, mock_render, mock_load_orders, mock_load_menu):
        # Setup Data
        mock_menu = [
            {"id": "1", "name": "Cerveja", "category": "Frigobar", "price": 10.0},
            {"id": "2", "name": "Agua", "category": "Bebidas", "price": 5.0}
        ]
        # Use "01" as key because route formats room numbers
        mock_orders = {"01": {"items": [], "status": "open"}}
        
        mock_load_menu.return_value = mock_menu
        mock_load_orders.return_value = mock_orders
        mock_occupancy.return_value = {}
        mock_users.return_value = {}
        mock_comps.return_value = []
        mock_flavors.return_value = []
        mock_obs.return_value = []
        mock_settings.return_value = {}

        # 1. Normal Restaurant Mode (No 'mode' param)
        self.client.get('/restaurant/table/1')
        
        args, kwargs = mock_render.call_args
        grouped_products = kwargs.get('grouped_products', [])
        
        # Verify 'Frigobar' is NOT present
        categories_present = [g[0] for g in grouped_products]
        self.assertNotIn('Frigobar', categories_present, "Frigobar should be hidden in restaurant mode")
        self.assertIn('Bebidas', categories_present)

        # 2. Minibar Mode (mode='minibar')
        self.client.get('/restaurant/table/1?mode=minibar')
        
        args, kwargs = mock_render.call_args
        grouped_products = kwargs.get('grouped_products', [])
        
        # Verify 'Frigobar' IS present
        categories_present = [g[0] for g in grouped_products]
        self.assertIn('Frigobar', categories_present, "Frigobar should be visible in minibar mode")

    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_system_action')
    @patch('app.blueprints.restaurant.routes.load_complements')
    def test_frigobar_blocking_in_post(self, mock_comps, mock_log_action, mock_save_orders, mock_load_orders, mock_load_menu):
        # Setup Data
        mock_menu = [
            {"id": "1", "name": "Cerveja", "category": "Frigobar", "price": 10.0, "active": True},
            {"id": "2", "name": "Agua", "category": "Bebidas", "price": 5.0, "active": True}
        ]
        mock_orders = {"01": {"items": [], "status": "open", "total": 0}}
        
        mock_load_menu.return_value = mock_menu
        mock_load_orders.return_value = mock_orders
        mock_comps.return_value = []

        # 1. Attempt to add Frigobar item in Restaurant Mode
        # Business Rule Update: Now allowed, but logged as warning.
        payload = {
            "action": "add_batch_items",
            "items_json": json.dumps([{"product": "1", "qty": 1}]) # ID 1 is Frigobar
        }
        
        response = self.client.post('/restaurant/table/1', data=payload, follow_redirects=True)
        
        # Verify item WAS added (Rule Change)
        self.assertIn(b'Pedido enviado com sucesso', response.data)
        
        # Verify Log was called with new message
        mock_log_action.assert_called()
        call_args = mock_log_action.call_args[0]
        self.assertEqual(call_args[0], 'Venda Item Frigobar no Restaurante')

        # 2. Attempt to add Frigobar item in Minibar Mode
        # Reset mocks
        mock_log_action.reset_mock()
        mock_orders["01"]["items"] = [] # Reset items
        
        payload_minibar = {
            "action": "add_batch_items",
            "mode": "minibar",
            "items_json": json.dumps([{"product": "1", "qty": 1}])
        }
        
        response = self.client.post('/restaurant/table/1', data=payload_minibar, follow_redirects=True)
        
        # Should succeed
        self.assertIn(b'Pedido enviado com sucesso', response.data)
        # Verify item added
        self.assertEqual(len(mock_orders["01"]["items"]), 1)
        self.assertEqual(mock_orders["01"]["items"][0]['name'], 'Cerveja')
        
        # Verify NO security log
        mock_log_action.assert_not_called()

if __name__ == '__main__':
    unittest.main()
