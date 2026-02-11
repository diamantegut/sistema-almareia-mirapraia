import unittest
import json
import os
import shutil
import unittest.mock
import app as app_module
from app import app
from services.fiscal_pool_service import FiscalPoolService

class TestFiscalLogic(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config['TESTING'] = True
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_fiscal')
        if not os.path.exists(self.test_dir):
            os.makedirs(self.test_dir)
            
        # Patch constants in app module
        self.orig_table_orders = app_module.TABLE_ORDERS_FILE
        app_module.TABLE_ORDERS_FILE = os.path.join(self.test_dir, 'table_orders.json')
        
        self.orig_cashier = app_module.CASHIER_SESSIONS_FILE
        app_module.CASHIER_SESSIONS_FILE = os.path.join(self.test_dir, 'cashier_sessions.json')
        
        self.orig_menu = app_module.MENU_ITEMS_FILE
        app_module.MENU_ITEMS_FILE = os.path.join(self.test_dir, 'menu_items.json')
        
        self.orig_payment = app_module.PAYMENT_METHODS_FILE
        app_module.PAYMENT_METHODS_FILE = os.path.join(self.test_dir, 'payment_methods.json')

        self.orig_users = app_module.USERS_FILE
        app_module.USERS_FILE = os.path.join(self.test_dir, 'users.json')

        # Patch FiscalPoolService file
        import services.fiscal_pool_service
        self.orig_fiscal_pool = services.fiscal_pool_service.FISCAL_POOL_FILE
        services.fiscal_pool_service.FISCAL_POOL_FILE = os.path.join(self.test_dir, 'fiscal_pool.json')
        
        # Patch LoggerService to print everything
        self.patcher_logger = unittest.mock.patch('logger_service.LoggerService.log_acao')
        self.mock_logger = self.patcher_logger.start()
        def side_effect_log(acao, **kwargs):
            print(f"DEBUG LOG: {acao} - {kwargs}")
        self.mock_logger.side_effect = side_effect_log
        
        # Patch load_settings
        self.patcher_settings = unittest.mock.patch('app.load_settings', return_value={'category_order': [], 'category_colors': {}})
        self.mock_settings = self.patcher_settings.start()
        
        # Setup initial files
        self._setup_initial_data()
        
    def tearDown(self):
        # Restore constants
        app_module.TABLE_ORDERS_FILE = self.orig_table_orders
        app_module.CASHIER_SESSIONS_FILE = self.orig_cashier
        app_module.MENU_ITEMS_FILE = self.orig_menu
        app_module.PAYMENT_METHODS_FILE = self.orig_payment
        app_module.USERS_FILE = self.orig_users
        
        import services.fiscal_pool_service
        services.fiscal_pool_service.FISCAL_POOL_FILE = self.orig_fiscal_pool
        
        self.patcher_logger.stop()
        self.patcher_settings.stop()
        
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except:
                pass

    def _setup_initial_data(self):
        # Users
        users = {'admin': {'password': '123', 'role': 'admin', 'name': 'Admin'}}
        with open(os.path.join(self.test_dir, 'users.json'), 'w') as f:
            json.dump(users, f)
            
        # Payment Methods
        methods = [{'id': '1', 'name': 'Dinheiro', 'available_in': ['restaurant'], 'fiscal_cnpj': '12345678000199'}]
        with open(os.path.join(self.test_dir, 'payment_methods.json'), 'w') as f:
            json.dump(methods, f)
            
        # Menu Items
        items = [{'id': '1', 'name': 'Item1', 'price': 100.0, 'category': 'Food'}]
        with open(os.path.join(self.test_dir, 'menu_items.json'), 'w') as f:
            json.dump(items, f)
            
        # Empty Pool
        with open(os.path.join(self.test_dir, 'fiscal_pool.json'), 'w') as f:
            json.dump([], f)
            
        # Empty Orders
        with open(os.path.join(self.test_dir, 'table_orders.json'), 'w') as f:
            json.dump({}, f)
            
        # Empty Cashier Sessions (needed for close_order)
        sessions = [{'id': 'session_1', 'status': 'open', 'transactions': []}]
        with open(os.path.join(self.test_dir, 'cashier_sessions.json'), 'w') as f:
            json.dump(sessions, f)

    def test_fiscal_pool_amount_with_service_fee_removal(self):
        # 1. Login
        self.client.post('/login', data={'username': 'admin', 'password': '123'})
        
        # 2. Open Table
        self.client.post('/restaurant/table/40', data={'action': 'open_table', 'waiter': 'Test'})
        
        # 3. Add Item (100.00)
        items = [{'id': '1', 'product': 'Item1', 'qty': 1, 'price': 100.0, 'waiter': 'Test'}]
        self.client.post('/restaurant/table/40', data={
            'action': 'add_batch_items',
            'items_json': json.dumps(items),
            'waiter': 'Test'
        })
        
        # 4. Close Table with Service Fee Removal
        print("Closing table now...")
        response = self.client.post('/restaurant/table/40', data={ 
            'action': 'close_order',
            'payment_method': '1', # Dinheiro
            'remove_service_fee': 'on',
            'emit_invoice': 'on'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # 5. Check Fiscal Pool
        with open(os.path.join(self.test_dir, 'fiscal_pool.json'), 'r') as f:
            pool = json.load(f)
            
        print(f"Fiscal Pool Content: {pool}")
        
        self.assertEqual(len(pool), 1, "Fiscal pool should have 1 entry")
        entry = pool[0]
        self.assertEqual(entry['total_amount'], 100.0) # Should be 100, not 110
        
        # Check payment method amount in pool entry
        self.assertEqual(entry['payment_methods'][0]['amount'], 100.0)

    def test_fiscal_pool_serie_number_storage(self):
        # 1. Manually add entry to pool
        entry_id = FiscalPoolService.add_to_pool(
            origin='test',
            original_id='123',
            total_amount=50.0,
            items=[],
            payment_methods=[],
            user='admin'
        )
        
        # 2. Update status with Serie and Number
        FiscalPoolService.update_status(
            entry_id, 
            'emitted', 
            fiscal_doc_uuid='NFE-123',
            serie='1', 
            number='1001'
        )
        
        # 3. Verify storage
        with open(os.path.join(self.test_dir, 'fiscal_pool.json'), 'r') as f:
            pool = json.load(f)
            
        entry = next(e for e in pool if e['id'] == entry_id)
        self.assertEqual(entry['fiscal_serie'], '1')
        self.assertEqual(entry['fiscal_number'], '1001')
        self.assertEqual(entry['fiscal_doc_uuid'], 'NFE-123')

if __name__ == '__main__':
    unittest.main()
