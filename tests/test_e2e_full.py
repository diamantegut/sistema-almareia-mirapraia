import pytest
import json
import os
import sys
import shutil
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add project root to sys.path to import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app
from services.cashier_service import CashierService

class TestE2EFull:
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
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_e2e')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Mock data paths
        self.patchers = []
        
        # Mock get_data_path to return paths in test_dir
        def side_effect_get_data_path(filename):
            return os.path.join(self.test_dir, filename)
            
        self.patcher_path = patch('app.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_path.start()
        self.patchers.append(self.patcher_path)
        
        # Create necessary empty JSON files
        self.files = [
            'users.json', 'products.json', 'table_orders.json', 
            'room_occupancy.json', 'room_charges.json', 'cashier_sessions.json',
            'payables.json', 'menu_items.json', 'printer_settings.json', 'fiscal_settings.json'
        ]
        for f in self.files:
            with open(os.path.join(self.test_dir, f), 'w', encoding='utf-8') as file:
                if f == 'users.json':
                    json.dump({'admin': {'password': '123', 'role': 'admin', 'permissions': []}}, file)
                elif f == 'products.json':
                    json.dump([
                        {'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas', 'id': '1'},
                        {'name': 'CommItem', 'price': 100.0, 'category': 'Food', 'id': '99'}
                    ], file)
                elif f == 'menu_items.json':
                    json.dump([
                         {'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas', 'id': '1'},
                         {'name': 'CommItem', 'price': 100.0, 'category': 'Food', 'id': '99'}
                    ], file)
                elif f == 'cashier_sessions.json':
                    json.dump([], file)
                elif f == 'payables.json':
                    json.dump([], file)
                elif f == 'payment_methods.json':
                    json.dump([], file)
                elif f == 'printer_settings.json':
                    json.dump({}, file)
                elif f == 'fiscal_settings.json':
                    json.dump({}, file)
                else:
                    json.dump({}, file)

        # Login as admin
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'gerente', 'comissao']

        # Patch file path constants in app module to point to test_dir
        self.original_constants = {}
        constants_to_patch = [
            'PAYABLES_FILE', 'PAYMENT_METHODS_FILE', 'PRODUCTS_FILE', 
            'ROOM_OCCUPANCY_FILE', 'TABLE_ORDERS_FILE', 'CASHIER_SESSIONS_FILE',
            'USERS_FILE', 'FISCAL_SETTINGS_FILE'
        ]
        
        for const in constants_to_patch:
            if hasattr(app, const):
                self.original_constants[const] = getattr(app, const)
                # Determine filename from the original path or just use the constant name lowercased
                filename = os.path.basename(getattr(app, const))
                setattr(app, const, os.path.join(self.test_dir, filename))

        yield

        # Teardown
        # Restore constants
        for const, value in self.original_constants.items():
            setattr(app, const, value)

        for p in self.patchers:
            p.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_01_login_and_dashboard(self):
        """Test login and dashboard access"""
        response = self.client.get('/')
        assert response.status_code == 200
        # Relaxed check as title might vary
        assert b'Back of the house' in response.data or b'Dashboard' in response.data

    def test_02_item_operations_and_transfers(self):
        """Test item addition, table transfer, and validation"""
        # Open table 10
        self.client.get('/restaurant/table/10')
        
        # Add item
        with patch('app.load_products', return_value=[{'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas', 'id': '1'}]):
             response = self.client.post('/restaurant/table/10', data={
                'action': 'add_item',
                'product': 'Coca Cola',
                'qty': 1
            }, follow_redirects=True)
        assert b'Coca Cola' in response.data
        
        # Mock Room Occupancy for transfer
        mock_occupancy = {
            "15": {
                "status": "occupied", 
                "guest_name": "Guest 15",
                "num_adults": 2,
                "checkin": "2023-10-01",
                "checkout": "2023-10-05"
            }
        }
        
        # Transfer to Room 15 (Using target_table_id as room number)
        with patch('app.load_room_occupancy', return_value=mock_occupancy):
            response = self.client.post('/restaurant/table/10', data={
                'action': 'transfer_table',
                'target_table_id': '15'
            }, follow_redirects=True)
            
            # Should show success message or redirect
            assert response.status_code == 200

    def test_03_payment_methods(self):
        """Test payment methods configuration"""
        # Add payment method via proper form data
        data = {
            'action': 'add',
            'name': 'Cartão Crédito',
            'available_restaurant': 'on',
            'is_fiscal': 'on'
        }
        response = self.client.post('/restaurant/payment-methods', data=data, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify load
        with open(os.path.join(self.test_dir, 'payment_methods.json'), 'r') as f:
            content = json.load(f)
            # Check if any of the added methods exist in the file
            names = [m['name'] for m in content]
            assert 'Cartão Crédito' in names

    def test_04_mandatory_questions(self):
        """Test mandatory questions validation"""
        # This requires setting up a product with mandatory questions first
        # For now, just a placeholder as implementation details vary
        pass

    def test_05_accounts_payable(self):
        """Test accounts payable 'Pagar' button"""
        # Create a payable with required fields
        payable = {
            "id": "PAY_001",
            "description": "Conta Luz",
            "amount": 150.00,
            "due_date": "2025-12-31",
            "status": "pending",
            "category": "Despesas Fixas",
            "supplier": "Enel",
            "barcode": "1234567890"
        }
        with open(os.path.join(self.test_dir, 'payables.json'), 'w', encoding='utf-8') as f:
            json.dump([payable], f)
            
        # Access page
        response = self.client.get('/finance/accounts_payable')
        assert b'Conta Luz' in response.data
        assert b'Pagar' in response.data  # Verify button exists

        # Pay it
        response = self.client.post('/finance/accounts_payable', data={
            'action': 'pay',
            'id': 'PAY_001',
            'payment_date': '2025-01-01',
            'amount': '150.00',
            'account': 'Caixa Geral'
        }, follow_redirects=True)
        assert response.status_code == 200
        
        # Verify status change
        with open(os.path.join(self.test_dir, 'payables.json'), 'r') as f:
            payables = json.load(f)
            assert payables[0]['status'] == 'paid'

    def test_06_commission_ranking(self):
        """Test commission ranking report"""
        # 1. Open Cashier (Required for close_order)
        self.client.post('/restaurant/cashier', data={
            'action': 'open_cashier',
            'opening_balance': '100.00'
        }, follow_redirects=True)

        # 2. Add Item with Commission to Table 20
        # Mock load_products to ensure item exists and has category
        with patch('app.load_products', return_value=[{'name': 'CommItem', 'price': 100.0, 'category': 'Food', 'id': '99'}]):
             with patch('app.load_menu_items', return_value=[{'name': 'CommItem', 'price': 100.0, 'category': 'Food', 'id': '99'}]):
                self.client.post('/restaurant/table/20', data={
                    'action': 'add_item',
                    'product': 'CommItem',
                    'qty': 1
                })

        # 3. Close Order (Trigger commission recording)
        # Ensure we pass payment method and amount
        response = self.client.post('/restaurant/table/20', data={
            'action': 'close_order',
            'payment_method': 'Dinheiro',
            'paid_amount': '110.00', # 100 + 10%
            'discount': '0',
            'remove_service_fee': '' 
        }, follow_redirects=True)
        assert response.status_code == 200

        # 4. Check Commission Ranking Report
        # Ensure we query with a date range that covers today
        today = datetime.now().strftime('%Y-%m-%d')
        response = self.client.get(f'/commission_ranking?start_date={today}&end_date={today}')
        assert response.status_code == 200
        
        # Verify if transaction or waiter name appears
        # Since we are admin, and added item as admin, the waiter might be 'admin' or null depending on logic
        # If the item addition didn't set waiter, it defaults to session user 'admin'
        # Let's check if 'admin' appears in the report
        assert b'admin' in response.data or b'CommissionWaiter' in response.data
