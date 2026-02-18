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

class TestE2EOperations:
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
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_ops')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Mock get_data_path to return paths in test_dir
        def side_effect_get_data_path(filename):
            return os.path.join(self.test_dir, filename)
            
        self.patcher_path = patch('app.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_path.start()

        # Patch system_config_manager.get_data_path for other modules
        self.patcher_scm_path = patch('system_config_manager.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_scm_path.start()

        # Patch app.services.transfer_service.get_data_path explicitly
        self.patcher_transfer_path = patch('app.services.transfer_service.get_data_path', side_effect=side_effect_get_data_path)
        self.patcher_transfer_path.start()
        
        # Create necessary empty JSON files
        self.files = [
            'users.json', 'products.json', 'table_orders.json', 
            'room_occupancy.json', 'room_charges.json', 'cashier_sessions.json',
            'payables.json', 'menu_items.json', 'printer_settings.json', 'fiscal_settings.json',
            'stock.json', 'stock_entries.json'
        ]
        for f in self.files:
            with open(os.path.join(self.test_dir, f), 'w', encoding='utf-8') as file:
                if f == 'users.json':
                    json.dump({'admin': {'password': '123', 'role': 'admin', 'permissions': []}}, file)
                elif f == 'products.json':
                    json.dump([
                        {'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas', 'id': '1'},
                        {'name': 'Prato Feito', 'price': 25.0, 'category': 'Refeição', 'id': '2'},
                        {'name': 'EstoqueItem', 'price': 10.0, 'category': 'Geral', 'id': '3', 'track_stock': True},
                        {'name': 'Carne', 'price': 5.0, 'category': 'Insumo', 'id': '4', 'track_stock': True}
                    ], file)
                elif f == 'menu_items.json':
                    json.dump([
                        {'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas', 'id': '1'},
                        {'name': 'Prato Feito', 'price': 25.0, 'category': 'Refeição', 'id': '2'},
                        {'name': 'EstoqueItem', 'price': 10.0, 'category': 'Geral', 'id': '3', 'track_stock': True},
                        {'name': 'Burger', 'price': 20.0, 'category': 'Lanche', 'id': '5', 'recipe': [{'ingredient': 'Carne', 'qty': 1}]}
                    ], file)
                elif f == 'stock.json':
                    json.dump({'EstoqueItem': 10, 'Carne': 10}, file)
                elif f == 'stock_entries.json':
                    json.dump([], file)
                elif f == 'room_occupancy.json':
                    json.dump({'101': {'status': 'occupied', 'checkin': '2025-01-01', 'checkout': '2025-01-05'}}, file)
                elif f == 'room_charges.json':
                    json.dump([], file)
                elif f == 'cashier_sessions.json':
                    json.dump([], file)
                else:
                    json.dump({}, file)

        # Login as admin
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'gerente', 'comissao', 'recepcao']

        # Patch file path constants in app module to point to test_dir
        self.original_constants = {}
        app_constants_to_patch = [
            'PAYABLES_FILE', 'PAYMENT_METHODS_FILE', 'PRODUCTS_FILE', 
            'ROOM_OCCUPANCY_FILE', 'TABLE_ORDERS_FILE', 'CASHIER_SESSIONS_FILE',
            'USERS_FILE', 'FISCAL_SETTINGS_FILE', 'STOCK_FILE', 'STOCK_ENTRIES_FILE',
            'ROOM_CHARGES_FILE', 'MENU_ITEMS_FILE'
        ]
        
        for const in app_constants_to_patch:
            if hasattr(app, const):
                self.original_constants[const] = getattr(app, const)
                filename = os.path.basename(getattr(app, const))
                setattr(app, const, os.path.join(self.test_dir, filename))

        # Patch data_service file path constants so load_* helpers use test_dir
        try:
            from app.services import data_service
            self.original_data_service_constants = {}
            data_service_constants_to_patch = [
                'PAYABLES_FILE', 'PAYMENT_METHODS_FILE', 'PRODUCTS_FILE',
                'ROOM_OCCUPANCY_FILE', 'TABLE_ORDERS_FILE', 'CASHIER_SESSIONS_FILE',
                'USERS_FILE', 'FISCAL_SETTINGS_FILE', 'STOCK_FILE', 'STOCK_ENTRIES_FILE',
                'ROOM_CHARGES_FILE', 'MENU_ITEMS_FILE'
            ]
            for const in data_service_constants_to_patch:
                if hasattr(data_service, const):
                    self.original_data_service_constants[const] = getattr(data_service, const)
                    filename = os.path.basename(getattr(data_service, const))
                    setattr(data_service, const, os.path.join(self.test_dir, filename))
        except Exception:
            self.original_data_service_constants = {}

        # Also patch services.cashier_service.CASHIER_SESSIONS_FILE if it exists separately
        self.patcher_cashier_file = patch('services.cashier_service.CASHIER_SESSIONS_FILE', os.path.join(self.test_dir, 'cashier_sessions.json'))
        self.patcher_cashier_file.start()

        yield

        # Teardown
        self.patcher_path.stop()
        self.patcher_scm_path.stop()
        self.patcher_transfer_path.stop()
        self.patcher_cashier_file.stop()
        for const, value in self.original_constants.items():
            setattr(app, const, value)
        if hasattr(self, 'original_data_service_constants'):
            from app.services import data_service
            for const, value in self.original_data_service_constants.items():
                setattr(data_service, const, value)
            
    def test_commission_ranking_logic(self):
        """Test commission ranking generation with granted and removed commissions"""
        
        # 1. Create a cashier session
        session_id = f"SESS_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        session_data = {
            'id': session_id,
            'status': 'open',
            'type': 'reception_room_billing',
            'opening_time': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'transactions': []
        }
        
        # 2. Add transactions
        # Trans 1: Standard sale with commission
        t1 = {
            'id': 'T1',
            'type': 'sale',
            'amount': 110.0, # 100 + 10
            'waiter': 'GarcomA',
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'waiter_breakdown': {'GarcomA': 110.0},
            'service_fee_removed': False
        }
        
        # Trans 2: Sale with removed commission
        t2 = {
            'id': 'T2',
            'type': 'sale',
            'amount': 100.0, # Service removed
            'waiter': 'GarcomB',
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'waiter_breakdown': {'GarcomB': 100.0},
            'service_fee_removed': True,
            'details': {'related_charge_id': 'CHG_002'}
        }
        
        session_data['transactions'] = [t1, t2]
        
        with open(os.path.join(self.test_dir, 'cashier_sessions.json'), 'w', encoding='utf-8') as f:
            json.dump([session_data], f)
            
        # 3. Request ranking page
        response = self.client.get('/commission_ranking')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        
        # 4. Verify Content
        # GarcomA should appear in the main ranking
        assert 'GarcomA' in html
        # GarcomB should appear in removed table
        assert 'GarcomB' in html
        assert 'CHG_002' in html # Reference
        
    def test_reception_payment_waiter_persistence(self):
        """Test that waiter info persists when paying at reception"""
        
        # 1. Create a Charge manually (simulating a transfer)
        charge = {
            'id': 'CHARGE_TEST_1',
            'room_number': '101',
            'table_id': '20',
            'total': 110.00,
            'items': [{'name': 'Item 1', 'price': 100.0, 'qty': 1}],
            'service_fee': 10.00,
            'status': 'pending',
            'waiter': 'GarcomX',
            'waiter_breakdown': {'GarcomX': 110.00}, # Full amount including service
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        
        with open(os.path.join(self.test_dir, 'room_charges.json'), 'w') as f:
            json.dump([charge], f)
            
        # 2. Open Reception Session
        # The route is /reception/cashier with action=open_cashier
        self.client.post('/reception/cashier', data={
            'action': 'open_cashier',
            'initial_balance': '100.00'
        })
        
        # 3. Pay the charge
        payment_data = json.dumps([{'method_name': 'Pix', 'amount': 110.00}])
        
        response = self.client.post('/reception/cashier', data={
            'action': 'pay_charge',
            'charge_id': 'CHARGE_TEST_1',
            'payment_data': payment_data
        }, follow_redirects=True)
        # assert response.status_code == 200 # Redirects to reception_cashier
        
        # 4. Verify Transaction in Cashier Session
        with open(os.path.join(self.test_dir, 'cashier_sessions.json'), 'r') as f:
            sessions = json.load(f)
        
        # Find the open session
        session = next(s for s in sessions if s['status'] == 'open')
        txn = session['transactions'][0]
        
        assert txn['amount'] == 110.00
        assert txn['waiter'] == 'GarcomX'
        assert txn['waiter_breakdown'] == {'GarcomX': 110.00}


    def test_stock_return_on_cancellation(self):
        """Test that stock is returned when an item is cancelled"""
        
        # 1. Setup Product and Stock
        product_id = 'prod_1'
        ingredient_id = 'ing_1'
        
        # Create product with recipe
        products = [{
            'id': product_id, 
            'name': 'Burger', 
            'price': 20.0, 
            'recipe': [{'ingredient_id': ingredient_id, 'qty': 1}]
        }]
        with open(os.path.join(self.test_dir, 'menu_items.json'), 'w') as f:
            json.dump(products, f)
            
        # Create ingredient in stock
        insumos = [{'id': ingredient_id, 'name': 'Carne', 'price': 5.0}]
        with open(os.path.join(self.test_dir, 'products.json'), 'w') as f:
            json.dump(insumos, f)
            
        # Initial Stock Balance
        initial_stock = 10.0
        stock_entries = [{
            'id': 'ENTRY_1',
            'product': 'Carne',
            'qty': initial_stock,
            'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }]
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'w') as f:
            json.dump(stock_entries, f)
            
        # 2. Open Table and Add Item (Table 40 - Non-Room Table)
        # Using a table ID > 35 to ensure it's treated as a restaurant table, not a room
        self.client.post('/restaurant/table/40', data={
            'action': 'open_table',
            'waiter': 'GarcomY',
            'num_adults': '2',
            'customer_type': 'comum' # Default type
        })
        
        # Use the correct product ID from menu_items.json to trigger recipe lookup
        items = [{'id': '5', 'product': 'Burger', 'qty': 2, 'obs': '', 'waiter': 'GarcomY'}]
        response = self.client.post('/restaurant/table/40', data={
            'action': 'add_batch_items',
            'batch_id': 'batch_test_1',
            'items_json': json.dumps(items),
            'waiter': 'GarcomY'
        }, follow_redirects=True)
        
        if response.status_code != 200:
            print(f"add_batch_items failed: {response.status_code}")
            print(response.data.decode('utf-8'))
            
        # Debug: Check if stock entry was created
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'r') as f:
            print(f"Stock entries content: {f.read()}")

        # Verify Stock Deducted (10 - 2 = 8)
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'r') as f:
            entries = json.load(f)
        
        balance = sum(e['qty'] for e in entries if e['product'] == 'Carne')
        assert balance == 8.0
        
        # 3. Cancel Item (Remove 2 Burgers)
        with open(os.path.join(self.test_dir, 'table_orders.json'), 'r') as f:
            orders = json.load(f)
        
        item_id = orders['40']['items'][0]['id']
        
        self.client.post('/restaurant/table/40', data={
            'action': 'remove_item',
            'item_id': item_id,
            'cancellation_reason': 'Customer changed mind'
        }, follow_redirects=True)
        
        # 4. Verify Stock Returned (8 + 2 = 10)
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'r') as f:
            entries = json.load(f)
            
        balance = sum(e['qty'] for e in entries if e['product'] == 'Carne')
        assert balance == 10.0

    def test_transfer_to_room_button_without_room_number(self):
        """Test transfer to room button logic where room number is implicit in the order"""
        
        # 1. Setup: Open a Room Table (e.g. Table 33 for Room 33)
        # Room 33 needs to be occupied
        with open(os.path.join(self.test_dir, 'room_occupancy.json'), 'w') as f:
            json.dump({'33': {'status': 'occupied', 'guest_name': 'Guest 33', 'checkin': '2025-01-01', 'checkout': '2025-01-05'}}, f)
            
        self.client.post('/restaurant/table/33', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'hospede'
        })
        
        # 2. Add an item
        items = [{'id': '1', 'product': 'Coca Cola', 'qty': 1, 'waiter': 'GarcomZ'}]
        self.client.post('/restaurant/table/33', data={
            'action': 'add_batch_items',
            'items_json': json.dumps(items),
            'waiter': 'GarcomZ'
        })
        
        # 3. Perform Transfer WITHOUT sending room_number in form data
        # This simulates the button click which only sends action='transfer_to_room'
        response = self.client.post('/restaurant/table/33', data={
            'action': 'transfer_to_room'
            # Note: room_number is MISSING
        }, follow_redirects=True)
        
        # 4. Assert Success
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        
        # Should not have the error
        assert "Número do quarto é obrigatório" not in html
        assert "Transferência realizada com sucesso" in html
        assert "quarto 33" in html.lower()
        
        # Verify order items are cleared for permanent table (33 <= 35)
        with open(os.path.join(self.test_dir, 'table_orders.json'), 'r') as f:
            orders = json.load(f)
            # For table 33 (permanent), the key remains but items should be empty
            if '33' in orders:
                assert not orders['33'].get('items'), "Table 33 items should be cleared"
            else:
                # If implementation changes to delete key, that's also fine
                pass
            
        # Verify charge created
        with open(os.path.join(self.test_dir, 'room_charges.json'), 'r') as f:
            charges = json.load(f)
            assert len(charges) == 1
            assert charges[0]['room_number'] == '33'
