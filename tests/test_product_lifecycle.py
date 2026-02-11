import pytest
import json
import os
import sys
import shutil
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app

class TestProductLifecycle:
    @pytest.fixture
    def client(self):
        app.app.config['TESTING'] = True
        with app.app.test_client() as client:
            yield client

    @pytest.fixture(autouse=True)
    def setup_teardown(self, client):
        self.client = client
        self.app = app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        # Setup temporary data directories
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_lifecycle')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Mock paths
        def side_effect_get_data_path(filename):
            return os.path.join(self.test_dir, filename)
            
        self.patcher_path = patch('app.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_path.start()
        
        self.patcher_scm_path = patch('system_config_manager.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_scm_path.start()

        # Create initial empty files
        self.files = [
            'users.json', 'products.json', 'menu_items.json', 'printer_settings.json', 
            'stock.json', 'flavor_groups.json', 'settings.json'
        ]
        for f in self.files:
            with open(os.path.join(self.test_dir, f), 'w', encoding='utf-8') as file:
                if f == 'users.json':
                    json.dump({'admin': {'password': '123', 'role': 'admin', 'permissions': []}}, file)
                elif f == 'products.json':
                    # Create some stock products (insumos)
                    json.dump([
                        {'name': 'Farinha', 'price': 5.0, 'category': 'Insumo', 'id': '101', 'unit': 'kg'},
                        {'name': 'Ovo', 'price': 1.0, 'category': 'Insumo', 'id': '102', 'unit': 'un'}
                    ], file)
                elif f == 'menu_items.json':
                    json.dump([], file)
                else:
                    json.dump({}, file)

        # Patch file path constants in app module to point to test_dir
        self.original_constants = {}
        constants_to_patch = [
            'PRODUCTS_FILE', 'MENU_ITEMS_FILE', 'STOCK_FILE', 
            'USERS_FILE', 'PRINTER_SETTINGS_FILE', 'FLAVOR_GROUPS_FILE', 'SETTINGS_FILE'
        ]
        
        for const in constants_to_patch:
            if hasattr(app, const):
                self.original_constants[const] = getattr(app, const)
                filename = os.path.basename(getattr(app, const))
                setattr(app, const, os.path.join(self.test_dir, filename))

        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin']

    def teardown_method(self):
        self.patcher_path.stop()
        self.patcher_scm_path.stop()
        
        # Restore constants
        for const, value in self.original_constants.items():
            setattr(app, const, value)
            
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_create_and_edit_product_full_lifecycle(self):
        # 1. Create a new product with all new fields
        payload = {
            'name': 'Bolo Especial',
            'category': 'Sobremesas',
            'price': '25,00',
            'cost_price': '10,00',
            'description': 'Um bolo delicioso',
            'active': 'on',
            'should_print': 'on',
            'visible_virtual_menu': 'on',
            'highlight': 'on',
            'paused': 'off', # Not paused initially
            
            # Recipe (Ingredients)
            'ingredient_id[]': ['101', '102'],
            'ingredient_qty[]': ['0.5', '2']
        }
        
        response = self.client.post('/menu/management', data=payload, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify creation in JSON
        with open(os.path.join(self.test_dir, 'menu_items.json'), 'r', encoding='utf-8') as f:
            items = json.load(f)
            
        assert len(items) == 1
        product = items[0]
        assert product['name'] == 'Bolo Especial'
        assert product['price'] == 25.0
        assert product['highlight'] is True
        assert product['visible_virtual_menu'] is True
        assert product['paused'] is False
        assert len(product['recipe']) == 2
        assert product['recipe'][0]['ingredient_id'] == '101'
        assert product['recipe'][0]['qty'] == 0.5
        
        product_id = product['id']
        print(f"Created product ID: {product_id}")
        
        # 2. Edit the product: Pause it and remove highlight
        edit_payload = {
            'id': product_id,
            'name': 'Bolo Especial (Editado)',
            'category': 'Sobremesas',
            'price': '30,00',
            'active': 'on',
            'visible_virtual_menu': 'on',
            'highlight': 'off', # Turn off highlight
            'paused': 'on',     # Pause it
            'pause_reason': 'Falta de farinha',
            
            # Update Recipe (remove eggs)
            'ingredient_id[]': ['101'],
            'ingredient_qty[]': ['0.6']
        }
        
        response = self.client.post('/menu/management', data=edit_payload, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify updates
        with open(os.path.join(self.test_dir, 'menu_items.json'), 'r', encoding='utf-8') as f:
            items = json.load(f)
            
        product = items[0]
        assert product['name'] == 'Bolo Especial (Editado)'
        assert product['price'] == 30.0
        assert product['highlight'] is False
        assert product['paused'] is True
        assert product['pause_reason'] == 'Falta de farinha'
        assert len(product['recipe']) == 1
        assert product['recipe'][0]['qty'] == 0.6
        
        print("Product update verified successfully.")
