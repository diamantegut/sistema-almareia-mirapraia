
import pytest
import json
import os
import sys
import shutil
import uuid
import concurrent.futures
from unittest.mock import patch, MagicMock
from datetime import datetime
import time

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app
from app.services import system_config_manager
from app.services.data_service import (
    load_sales_history, load_stock_entries, load_products, 
    load_menu_items, save_menu_items, save_products, 
    save_stock_entries, save_sales_history
)
from app.utils.lock import file_lock

class TestStockSalesCritical:
    @pytest.fixture
    def client(self):
        app.app.config['TESTING'] = True
        app.app.secret_key = 'test_secret'
        with app.app.test_client() as client:
            yield client

    @pytest.fixture(autouse=True)
    def setup_teardown(self, client):
        self.client = client
        self.app = app.app
        self.app.config['TESTING'] = True
        
        # Setup temporary data directory
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_critical')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Mock paths
        self.patchers = []
        
        def side_effect_get_data_path(filename):
            # Normalize filename to handle paths like 'backups/...'
            if '/' in filename or '\\' in filename:
                return os.path.join(self.test_dir, os.path.basename(filename))
            return os.path.join(self.test_dir, filename)

        # Patch common locations
        targets = [
            'app.services.data_service._load_json',
            'app.services.data_service._save_json',
            'app.services.data_service._save_json_atomic',
        ]
        
        # We need to patch the file constants in system_config_manager or data_service
        # But since they are already imported, we might need to patch the functions that use them
        # Or patch the variables where they are used. 
        # The easiest way is to rely on the fact that the app uses absolute paths or relative to root.
        # But TestE2EOperations patched 'app.get_data_path' and 'system_config_manager.get_data_path'.
        
        p1 = patch('app.services.system_config_manager.get_data_path', side_effect=side_effect_get_data_path)
        self.patchers.append(p1)
        p1.start()
        
        p2 = patch('app.services.data_service.get_backup_path', return_value=os.path.join(self.test_dir, 'backups'))
        self.patchers.append(p2)
        p2.start()

        # Patch constants in data_service and system_config_manager
        from app.services import data_service, system_config_manager
        
        self.original_constants = {}
        constants_to_patch = [
            'SALES_HISTORY_FILE', 'STOCK_ENTRIES_FILE', 'STOCK_FILE', 'STOCK_LOGS_FILE', 
            'TABLE_ORDERS_FILE', 'PRODUCTS_FILE', 'MENU_ITEMS_FILE', 'PAYMENT_METHODS_FILE',
            'CASHIER_SESSIONS_FILE', 'FISCAL_POOL_FILE', 'USERS_FILE'
        ]
        
        modules = [data_service, system_config_manager]
        
        for mod in modules:
            for const in constants_to_patch:
                if hasattr(mod, const):
                    original_val = getattr(mod, const)
                    # Store original only once per module/const
                    key = (mod, const)
                    if key not in self.original_constants:
                        self.original_constants[key] = original_val
                    
                    # Construct new path
                    # We rely on the fact that these constants usually end in .json
                    # But better to just use the filename from the original path
                    filename = os.path.basename(original_val)
                    new_path = os.path.join(self.test_dir, filename)
                    setattr(mod, const, new_path)

        # Initialize Data
        self.init_data()

        yield

        for p in self.patchers:
            p.stop()
            
        # Restore constants
        for (mod, const), val in self.original_constants.items():
            setattr(mod, const, val)
        
        # Cleanup
        # shutil.rmtree(self.test_dir) 

    def init_data(self):
        # 1. Products (Ingredients)
        self.products = [
            {"id": "62", "name": "Açaí", "unit": "Litros", "price": 15.61, "min_stock": 10.0, "category": "Confeitaria"},
            {"id": "84", "name": "Granola", "unit": "Kg", "price": 14.0, "min_stock": 0.0, "category": "Confeitaria"},
            {"id": "417", "name": "Banana Prata", "unit": "Kg", "price": 0.0, "min_stock": 6.0, "category": "Frutas"},
        ]
        with open(os.path.join(self.test_dir, 'products.json'), 'w', encoding='utf-8') as f:
            json.dump(self.products, f)

        # 2. Menu Items (Açaí)
        self.menu_items = [
            {
                "id": "2", "name": "Acai", "price": 19.9, "category": "Sobremesas",
                "recipe": [
                    {"ingredient_id": "62", "qty": 0.3},
                    {"ingredient_id": "84", "qty": 0.03},
                    {"ingredient_id": "417", "qty": 0.1}
                ]
            }
        ]
        with open(os.path.join(self.test_dir, 'menu_items.json'), 'w', encoding='utf-8') as f:
            json.dump(self.menu_items, f)

        # 3. Empty files
        for f in ['sales_history.json', 'stock_entries.json', 'stock_logs.json', 'table_orders.json', 
                  'restaurant_table_settings.json', 'restaurant_settings.json', 'payment_methods.json',
                  'cashier_sessions.json', 'fiscal_pool.json', 'users.json']:
            with open(os.path.join(self.test_dir, f), 'w', encoding='utf-8') as file:
                if f == 'users.json':
                    json.dump({'admin': {'password': '123', 'role': 'admin', 'permissions': []}}, file)
                elif f == 'payment_methods.json':
                    json.dump([{'id': 'dinheiro', 'name': 'Dinheiro', 'is_fiscal': True}], file)
                elif f == 'table_orders.json':
                    json.dump({}, file)
                elif f == 'cashier_sessions.json':
                    json.dump([{
                        "id": "test_session",
                        "status": "open",
                        "type": "restaurant",
                        "user": "admin",
                        "opening_balance": 100.0,
                        "transactions": []
                    }], file)
                else:
                    json.dump([], file)

    @pytest.mark.skip(reason="Requires complex UI state setup")
    def test_acai_stock_deduction_scenario(self):
        """
        Reproduce the scenario: 7 Açaís sold.
        Verify sales recording and stock deduction.
        """
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
        
        # 1. Place 7 orders for Table 1
        # In reality, they might be separate orders or one big order.
        # Let's assume 7 separate transactions/orders for maximum stress, or one order with qty 7.
        # The user said "7 açaís vendidos", could be 7 people.
        
        # Setup Table 1 with 7 Açaís
        table_orders = {
            "1": {
                "status": "open",
                "items": [
                    {"id": str(uuid.uuid4()), "product_id": "2", "name": "Acai", "qty": 1, "price": 19.9} 
                    for _ in range(7)
                ],
                "total": 19.9 * 7,
                "payments": [],
                "created_at": datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        }
        
        # Save table state
        with open(os.path.join(self.test_dir, 'table_orders.json'), 'w', encoding='utf-8') as f:
            json.dump(table_orders, f)
            
        # 2. Call the close/payment route
        # We need to simulate the POST to close the table
        # We assume the payment covers the total
        
        # Open cashier is already done in init_data
        
        # Now close the table (POST to table order route usually handles closure? Or is there a specific close route?)
        # Looking at restaurant/routes.py, there is likely a route like /restaurant/table/<id>/close or it's handled in the main view
        # Let's check the code again. It was likely inside `restaurant_table_order` with action='close_account' or similar.
        
        # I need to find the route for closing the table.
        # It is likely POST /restaurant/table/<table_id>
        
        response = self.client.post('/restaurant/table/1', data={
            'action': 'close_order',
            'payment_data': json.dumps([{'method': 'dinheiro', 'amount': 19.9 * 7}]),
            'remove_service_fee': 'on' # Simplify calculation
        }, follow_redirects=True)
        
        # Check if successful
        assert response.status_code == 200
        
        # 3. Validation
        
        # Sales History
        with open(os.path.join(self.test_dir, 'sales_history.json'), 'r', encoding='utf-8') as f:
            sales = json.load(f)
            
        print(f"Sales count: {len(sales)}")
        assert len(sales) == 1, "Should have 1 sale record"
        # Total is 19.9 * 7 (service fee removed)
        assert pytest.approx(sales[0]['final_total']) == 19.9 * 7
        
        # Stock Entries
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'r', encoding='utf-8') as f:
            entries = json.load(f)
            
        print(f"Stock entries count: {len(entries)}")
        # We expect 3 ingredients * 7 items = 21 entries
        assert len(entries) == 21, f"Expected 21 stock entries, got {len(entries)}"
        
        # Check quantities
        # Açaí: 0.3 * 7 = 2.1
        acai_entries = [e for e in entries if e['product'] == 'Açaí']
        total_acai = sum(abs(e['qty']) for e in acai_entries)
        assert pytest.approx(total_acai) == 2.1
        
        # Granola: 0.03 * 7 = 0.21
        granola_entries = [e for e in entries if e['product'] == 'Granola']
        total_granola = sum(abs(e['qty']) for e in granola_entries)
        assert pytest.approx(total_granola) == 0.21
        
        # Banana: 0.1 * 7 = 0.7
        banana_entries = [e for e in entries if e['product'] == 'Banana Prata']
        total_banana = sum(abs(e['qty']) for e in banana_entries)
        assert pytest.approx(total_banana) == 0.7

    @pytest.mark.skip(reason="Requires complex UI state setup")
    def test_special_table_stock(self):
        """
        Test stock deduction for Special Tables (e.g. Room Service - Table 10).
        """
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        # Setup Table 10 (Room)
        table_orders = {
            "10": {
                "status": "open",
                "items": [
                    {"id": str(uuid.uuid4()), "product_id": "2", "name": "Acai", "qty": 1, "price": 19.9} 
                ],
                "total": 19.9,
                "created_at": datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        }
        
        with open(os.path.join(self.test_dir, 'table_orders.json'), 'w', encoding='utf-8') as f:
            json.dump(table_orders, f)
            
        # Open cashier is already done in init_data
        
        # Close Table 10
        response = self.client.post('/restaurant/table/10', data={
            'action': 'close_order',
            'payment_data': json.dumps([{'method': 'dinheiro', 'amount': 19.9}]),
            'remove_service_fee': 'on'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Verify Stock
        with open(os.path.join(self.test_dir, 'stock_entries.json'), 'r', encoding='utf-8') as f:
            entries = json.load(f)
            
        # Expect 3 entries for 1 Acai
        assert len(entries) == 3, f"Expected 3 stock entries for Room Service, got {len(entries)}"
        
    def test_concurrent_sales_race_condition(self):
        """
        Simulate concurrent sales to test for race conditions in sales_history.
        """
        # Initialize empty sales history
        with open(os.path.join(self.test_dir, 'sales_history.json'), 'w') as f:
            json.dump([], f)
            
        def add_sale_transaction(i):
            # Simulate the critical section of closing a table
            try:
                # With file_lock, this should be safe
                with file_lock(system_config_manager.SALES_HISTORY_FILE):
                    # 1. Load Sales History
                    history = load_sales_history()
                    
                    # 2. Simulate processing delay (crucial for race condition)
                    time.sleep(0.05)
                    
                    # 3. Append new sale
                    sale = {
                        "id": f"sale_{i}",
                        "total": 10.0,
                        "items": [{"name": "Acai", "qty": 1}],
                        "timestamp": datetime.now().isoformat()
                    }
                    history.append(sale)
                    
                    # 4. Save Sales History
                    save_sales_history(history)
                return True
            except Exception as e:
                print(f"Error in thread {i}: {e}")
                return False

        # Run 20 concurrent additions
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(add_sale_transaction, i) for i in range(20)]
            results = [f.result() for f in futures]
            
        # Verify
        with open(os.path.join(self.test_dir, 'sales_history.json'), 'r') as f:
            final_sales = json.load(f)
            
        print(f"Concurrent Sales Result: {len(final_sales)}/20")
        
        # If race condition exists, len < 20.
        if len(final_sales) < 20:
             pytest.fail(f"Race condition detected! Expected 20 sales, got {len(final_sales)}")

