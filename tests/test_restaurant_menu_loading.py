
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
import json

class TestRestaurantMenuLoading(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Mock session
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_flavor_groups')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.render_template')
    def test_menu_loading_context(self, mock_render, mock_load_orders, mock_load_flavors, mock_load_menu):
        # Setup Mock Data
        mock_menu = [
            {
                "id": "1", "name": "Item 1", "category": "Cat A", "price": 10.0,
                "mandatory_questions": [{"question": "Q1", "type": "text"}],
                "flavor_group_id": "fg1"
            },
            {
                "id": "2", "name": "Item 2", "category": "Cat B", "price": 20.0
            }
        ]
        mock_flavors = [{"id": "fg1", "name": "Sabores", "items": []}]
        
        mock_load_menu.return_value = mock_menu
        mock_load_flavors.return_value = mock_flavors
        mock_load_orders.return_value = {}

        # Execute Request
        response = self.client.get('/restaurant/table/1')
        
        # Verify render_template arguments
        args, kwargs = mock_render.call_args
        
        # Check 1: Template name
        self.assertEqual(args[0], 'restaurant_table_order.html')
        
        # Check 2: 'products' should contain menu items, not stock products
        self.assertIn('products', kwargs)
        self.assertEqual(kwargs['products'], mock_menu)
        
        # Check 3: 'grouped_products' should be present and structured
        self.assertIn('grouped_products', kwargs)
        # Verify grouping structure (list of tuples or dict items)
        # The template iterates: {% for category, items in grouped_products %}
        # So it should be a list of tuples like [('Cat A', [item1]), ('Cat B', [item2])] or similar
        grouped = kwargs['grouped_products']
        self.assertTrue(any(g[0] == 'Cat A' for g in grouped))
        
        # Check 4: 'flavor_groups' should be present
        self.assertIn('flavor_groups', kwargs)
        self.assertEqual(kwargs['flavor_groups'], mock_flavors)

if __name__ == '__main__':
    unittest.main()
