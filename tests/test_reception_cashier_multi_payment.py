
import pytest
import json
import os
import sys
import shutil
import uuid
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app
from app import create_app
from app.services.cashier_service import CashierService

class TestReceptionCashierMultiPayment:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        
        # Setup temporary data directory
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_cashier_mp')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Mock get_data_path
        def side_effect_get_data_path(filename):
            return os.path.join(self.test_dir, filename)

        # Patch app.services.system_config_manager.get_data_path directly
        self.patcher = patch('app.services.system_config_manager.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher.start()
        
        # Patch constants in app.services.data_service and app.services.cashier_service
        # because they import these constants from system_config_manager using 'from ... import ...'
        
        self.patchers = []
        
        files_map = {
            'ROOM_CHARGES_FILE': 'room_charges.json',
            'CASHIER_SESSIONS_FILE': 'cashier_sessions.json',
            'PAYMENT_METHODS_FILE': 'payment_methods.json',
            'ROOM_OCCUPANCY_FILE': 'room_occupancy.json',
            'USERS_FILE': 'users.json',
            'PRODUCTS_FILE': 'products.json',
            'MENU_ITEMS_FILE': 'menu_items.json',
            'STOCK_ENTRIES_FILE': 'stock_entries.json',
            'STOCK_FILE': 'stock.json'
        }
        
        modules_to_patch = ['app.services.data_service', 'app.services.cashier_service']
        
        for var_name, filename in files_map.items():
            file_path = os.path.join(self.test_dir, filename)
            
            # Patch in system_config_manager (source) - just in case
            p1 = patch(f'app.services.system_config_manager.{var_name}', file_path)
            p1.start()
            self.patchers.append(p1)
            
            # Patch in consuming modules
            for module_name in modules_to_patch:
                # We use hasattr check inside a try-except block or just try to patch
                # But patch will fail if attribute doesn't exist.
                # However, we know data_service has most of them.
                try:
                    # Check if module is imported
                    if module_name in sys.modules:
                         mod = sys.modules[module_name]
                         if hasattr(mod, var_name):
                             p = patch(f'{module_name}.{var_name}', file_path)
                             p.start()
                             self.patchers.append(p)
                except Exception as e:
                    print(f"Warning: Could not patch {var_name} in {module_name}: {e}")

        # Create basic files

        # Create basic files
        self.payment_methods = [
            {'id': 'pix_id', 'name': 'Pix', 'available_in': ['reception', 'reservations'], 'is_fiscal': False},
            {'id': 'cash_id', 'name': 'Dinheiro', 'available_in': ['reception', 'reservations'], 'is_fiscal': False},
            {'id': 'credit_id', 'name': 'Crédito', 'available_in': ['reception', 'reservations'], 'is_fiscal': True}
        ]
        with open(os.path.join(self.test_dir, 'payment_methods.json'), 'w') as f:
            json.dump(self.payment_methods, f)
            
        with open(os.path.join(self.test_dir, 'users.json'), 'w') as f:
             json.dump({'admin': {'password': '123', 'role': 'admin'}}, f)
             
        # Initialize empty files
        for f in ['room_charges.json', 'cashier_sessions.json', 'products.json', 'menu_items.json', 'stock_entries.json', 'stock.json']:
            with open(os.path.join(self.test_dir, f), 'w') as file:
                json.dump([], file)
                
        # Room occupancy is a dict
        with open(os.path.join(self.test_dir, 'room_occupancy.json'), 'w') as file:
            json.dump({}, file)
                
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'reservas']

    def teardown_method(self):
        self.patcher.stop()
        for p in self.patchers:
            p.stop()
            
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_reception_cashier_pay_charge_multi(self):
        """Test paying a charge with multiple methods in Guest Consumption Cashier"""
        
        # 1. Setup Charge
        charge = {
            'id': 'CHARGE_101',
            'room_number': '101',
            'total': 100.0,
            'status': 'pending',
            'items': [{'name': 'Item 1', 'price': 100.0, 'qty': 1}],
            'date': '01/01/2026 12:00'
        }
        with open(os.path.join(self.test_dir, 'room_charges.json'), 'w') as f:
            json.dump([charge], f)
            
        # 2. Open Cashier
        CashierService.open_session('guest_consumption', 'admin', 100.0)
        
        # 3. Submit Multi-Payment
        # Form simulates: action='pay_charge', charge_id='CHARGE_101', payment_data='[JSON]'
        payment_data = [
            {'id': 'pix_id', 'name': 'Pix', 'amount': 60.0},
            {'id': 'cash_id', 'name': 'Dinheiro', 'amount': 40.0}
        ]
        
        response = self.client.post('/reception/cashier', data={
            'action': 'pay_charge',
            'charge_id': 'CHARGE_101',
            'payment_data': json.dumps(payment_data),
            'redirect_to': 'reception_cashier'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # 4. Verify Charge Status
        with open(os.path.join(self.test_dir, 'room_charges.json'), 'r', encoding='utf-8') as f:
            charges = json.load(f)
            updated_charge = charges[0]
            assert updated_charge['status'] == 'paid'
            assert updated_charge['payment_method'] == 'Múltiplos'
            assert len(updated_charge['payment_details']) == 2
            
        # 5. Verify Cashier Transactions (Splitting)
        with open(os.path.join(self.test_dir, 'cashier_sessions.json'), 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            session = next(s for s in sessions if s['type'] == 'guest_consumption')
            transactions = session['transactions']
            
            # Should have: 2 Transactions (2 Payments)
            # Opening balance is a property, not a transaction
            assert len(transactions) == 2
            
            # Verify grouping
            t1 = transactions[0]
            t2 = transactions[1]
            
            assert t1['details']['payment_group_id'] == t2['details']['payment_group_id']
            
            # Verify amounts
            assert any(t['amount'] == 60.0 and t['payment_method'] == 'Pix' for t in transactions)
            assert any(t['amount'] == 40.0 and t['payment_method'] == 'Dinheiro' for t in transactions)

    def test_reservations_cashier_sale_multi(self):
        """Test adding a sale transaction with multiple methods in Reservations Cashier"""
        
        # 1. Open Reservations Cashier
        CashierService.open_session('reception_reservations', 'admin', 0.0)
        
        # 2. Submit Multi-Payment Sale
        payment_list = [
            {'id': 'credit_id', 'name': 'Crédito', 'amount': 150.0},
            {'id': 'cash_id', 'name': 'Dinheiro', 'amount': 50.0}
        ]
        
        response = self.client.post('/reception/reservations-cashier', data={
            'action': 'add_transaction',
            'type': 'sale',
            'description': 'Check-in Múltiplo',
            'amount': '200.00',
            'payment_list_json': json.dumps(payment_list)
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # 3. Verify Cashier Transactions
        with open(os.path.join(self.test_dir, 'cashier_sessions.json'), 'r', encoding='utf-8') as f:
            sessions = json.load(f)
            # Find the reception_reservations session
            session = next(s for s in sessions if s['type'] == 'reception_reservations')
            transactions = session['transactions']

            # Should have: 2 Transactions
            # Filter for sale
            sales = [t for t in transactions if t['type'] == 'sale']
            
            # Debug if failure
            if len(sales) == 0:
                 print(f"\nDEBUG: Response Data: {response.get_data(as_text=True)}")
            
            assert len(sales) == 2
            
            # Verify grouping
            t1 = sales[0]
            t2 = sales[1]
            
            assert t1['details']['payment_group_id'] == t2['details']['payment_group_id']
            assert float(t1['amount']) + float(t2['amount']) == 200.0

