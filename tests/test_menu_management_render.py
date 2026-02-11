import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestMenuManagementRender(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Mock session
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.load_printers')
    @patch('app.blueprints.menu.routes.load_products')
    @patch('app.blueprints.menu.routes.load_flavor_groups')
    @patch('app.blueprints.menu.routes.load_settings')
    @patch('app.blueprints.menu.routes.render_template')
    def test_menu_management_context(self, mock_render, mock_load_settings, mock_load_flavors, mock_load_products, mock_load_printers, mock_load_menu):
        # Setup Mock Data
        mock_menu = [
            {"id": "1", "name": "Item A", "category": "Cat 2", "active": True},
            {"id": "2", "name": "Item B", "category": "Cat 1", "active": True}
        ]
        mock_load_menu.return_value = mock_menu
        mock_load_printers.return_value = []
        mock_load_products.return_value = []
        mock_load_flavors.return_value = []
        
        # Mock Settings with custom order (Reverse alphabetical to prove sorting works)
        mock_settings = {
            'digital_menu_category_order': ['Cat 2', 'Cat 1']
        }
        mock_load_settings.return_value = mock_settings
        
        # Mock render_template to return a string (so the route returns 200)
        mock_render.return_value = "Rendered Template"

        # Execute Request
        response = self.client.get('/menu/management')
        
        # Verify status
        self.assertEqual(response.status_code, 200)
        
        # Verify render_template arguments
        args, kwargs = mock_render.call_args
        
        # Check 1: Template name
        self.assertEqual(args[0], 'menu_management.html')
        
        # Check 2: digital_categories is present
        self.assertIn('digital_categories', kwargs)
        
        # Check 3: digital_categories is sorted correctly according to settings
        # Should be ['Cat 2', 'Cat 1']
        self.assertEqual(kwargs['digital_categories'], ['Cat 2', 'Cat 1'])
        
        # Verify categories (standard sort) is also present
        self.assertIn('categories', kwargs)
        # Standard sort is alphabetical: ['Cat 1', 'Cat 2']
        self.assertEqual(kwargs['categories'], ['Cat 1', 'Cat 2'])

if __name__ == '__main__':
    unittest.main()
