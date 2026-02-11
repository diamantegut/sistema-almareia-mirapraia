import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app

class TestMenuManagementButtons(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        
        # Simulate SUPER user
        with self.client.session_transaction() as sess:
            sess['user'] = 'super_user'
            sess['role'] = 'super'
            sess['department'] = 'Principal'

    # --- 1. Load Page & Verify Buttons ---
    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.load_printers')
    @patch('app.blueprints.menu.routes.load_products')
    @patch('app.blueprints.menu.routes.load_flavor_groups')
    @patch('app.blueprints.menu.routes.load_settings')
    def test_load_page_and_buttons(self, mock_settings, mock_flavors, mock_products, mock_printers, mock_menu):
        mock_menu.return_value = [
            {'id': '1', 'name': 'Burger', 'category': 'Lanches', 'active': True, 'price': 20.0},
            {'id': '2', 'name': 'Coke', 'category': 'Bebidas', 'active': False, 'price': 5.0}
        ]
        mock_settings.return_value = {}
        
        response = self.client.get('/menu/management')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        
        # Verify Buttons existence by Text or Icon Class
        self.assertIn('Novo', html) # Button text
        self.assertIn('Sabores', html)
        self.assertIn('Categorias', html)
        self.assertIn('Ordenar Menu Digital', html)
        self.assertIn('bi-pencil', html) # Edit icon
        self.assertIn('bi-trash', html) # Delete icon
        self.assertIn('bi-box-seam', html) # Stock icon
        self.assertIn('bi-clock-history', html) # History icon
        
    # --- 2. Toggle Active ---
    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.save_menu_items')
    @patch('app.blueprints.menu.routes.LoggerService.log_acao')
    def test_toggle_active(self, mock_log, mock_save, mock_load):
        mock_load.return_value = [{'id': '1', 'name': 'Test', 'active': True}]
        
        response = self.client.post('/menu/toggle-active/1')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertFalse(data['active']) # Should toggle to False
        
        mock_save.assert_called_once()
        mock_log.assert_called_once()

    # --- 3. Delete Product ---
    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.save_menu_items')
    @patch('app.blueprints.menu.routes.load_printers')
    @patch('app.blueprints.menu.routes.load_products')
    @patch('app.blueprints.menu.routes.load_flavor_groups')
    @patch('app.blueprints.menu.routes.load_settings')
    @patch('app.blueprints.menu.routes.LoggerService.log_acao')
    def test_delete_product(self, mock_log, mock_settings, mock_flavors, mock_products, mock_printers, mock_save, mock_load):
        # Mock data must contain fields used in template (price, category, active) to avoid rendering errors
        mock_load.return_value = [{'id': '1', 'name': 'Test', 'price': 10.0, 'category': 'General', 'active': True}]
        mock_settings.return_value = {}
        mock_printers.return_value = []
        mock_products.return_value = []
        mock_flavors.return_value = []
        
        response = self.client.post('/menu/delete/1', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Produto removido', response.data)
        
        # Verify save called with empty list (item removed)
        # Note: save_menu_items is called with the NEW list (which should be empty if we removed the only item)
        # But wait, load_menu_items is called TWICE. Once inside delete_menu_item, and once inside menu_management (redirect).
        # Since we return the SAME list [item1], delete_menu_item removes it and saves [].
        # Then menu_management calls load_menu_items again, getting [item1] again (because mock is static).
        # This is fine for rendering, but we want to check if SAVE was called with []
        
        args, _ = mock_save.call_args
        self.assertEqual(len(args[0]), 0)

    # --- 4. Save Product (Create/Edit) ---
    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.save_menu_items')
    @patch('app.blueprints.menu.routes.load_printers')
    @patch('app.blueprints.menu.routes.load_products')
    @patch('app.blueprints.menu.routes.load_flavor_groups')
    @patch('app.blueprints.menu.routes.load_settings')
    @patch('app.blueprints.menu.routes.LoggerService.log_acao')
    def test_save_product(self, mock_log, mock_settings, mock_flavors, mock_products, mock_printers, mock_save, mock_load):
        mock_load.return_value = [] # Start empty
        mock_settings.return_value = {}
        mock_printers.return_value = []
        mock_products.return_value = []
        mock_flavors.return_value = []
        
        data = {
            'name': 'New Burger',
            'category': 'Food',
            'price': '25,00',
            'active': 'on'
        }
        
        response = self.client.post('/menu/management', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Produto salvo', response.data)
        
        mock_save.assert_called_once()
        saved_list = mock_save.call_args[0][0]
        self.assertEqual(len(saved_list), 1)
        self.assertEqual(saved_list[0]['name'], 'New Burger')

    # --- 5. History ---
    @patch('app.blueprints.menu.routes.LoggerService.get_logs')
    def test_get_history(self, mock_get_logs):
        mock_get_logs.return_value = {
            'items': [{'timestamp': '2023-01-01T12:00:00', 'colaborador_id': 'admin', 'acao': 'Edit', 'detalhes': 'Changed price'}]
        }
        
        response = self.client.get('/api/menu/history/Burger')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('history', data)
        self.assertEqual(len(data['history']), 1)

    # --- 6. Digital Order ---
    @patch('app.blueprints.menu.routes.load_settings')
    @patch('app.blueprints.menu.routes.save_settings')
    def test_digital_order(self, mock_save, mock_load):
        mock_load.return_value = {}
        
        response = self.client.post('/api/menu/digital-category-order', json={'order': ['B', 'A']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.data)['success'])
        
        mock_save.assert_called_once()
        self.assertEqual(mock_save.call_args[0][0]['digital_menu_category_order'], ['B', 'A'])

    # --- 7. Stock Adjust (Stock Blueprint) ---
    @patch('app.blueprints.stock.load_products')
    @patch('app.blueprints.stock.get_product_balances')
    @patch('app.blueprints.stock.save_stock_entry')
    @patch('app.blueprints.stock.LoggerService.log_acao')
    @patch('app.blueprints.stock.log_stock_action')
    def test_stock_adjust(self, mock_log_stock, mock_logger, mock_save_entry, mock_balances, mock_products):
        mock_products.return_value = [{'name': 'Burger Bun', 'unit': 'un'}]
        mock_balances.return_value = {'Burger Bun': 10.0}
        
        data = {
            'product_name': 'Burger Bun',
            'new_quantity': 15.0,
            'reason': 'Audit'
        }
        
        response = self.client.post('/api/stock/adjust', json=data)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        mock_save_entry.assert_called_once()
        # Verify qty diff is 5.0 (15 - 10)
        self.assertEqual(mock_save_entry.call_args[0][0]['qty'], 5.0)

    # --- 8. Flavor Config Access ---
    @patch('app.blueprints.menu.routes.load_flavor_groups')
    @patch('app.blueprints.menu.routes.load_products')
    @patch('app.blueprints.menu.routes.load_menu_items')
    def test_flavor_config_access(self, mock_menu, mock_products, mock_flavors):
        response = self.client.get('/config/flavors')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Gerenciar Grupos de Sabores', response.data)

    # --- 9. Category Config Access ---
    @patch('app.blueprints.menu.routes.load_menu_items')
    @patch('app.blueprints.menu.routes.load_settings')
    def test_category_config_access(self, mock_settings, mock_menu):
        mock_menu.return_value = []
        mock_settings.return_value = {}
        response = self.client.get('/config/categories')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Ordem das Categorias', response.data)

    # --- 10. Backups Access ---
    @patch('app.services.backup_service.backup_service.list_backups')
    def test_backups_list(self, mock_list):
        mock_list.return_value = []
        response = self.client.get('/menu/backups')
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
