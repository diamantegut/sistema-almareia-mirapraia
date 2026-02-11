import unittest
import json
import os
import tempfile
import app as app_module
from unittest.mock import patch
from app import app, save_table_orders, load_table_orders, load_users, save_users, load_menu_items, save_menu_items, TABLE_ORDERS_FILE
import security_service
from security_service import ALERTS_FILE as SECURITY_ALERTS_FILE, load_alerts
from datetime import datetime

class TestSecurityWorkflow(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.secret_key = 'test_secret'
        self.client = app.test_client()
        self.user = 'TestAdmin'
        self.password = '123456'

        self._temp_dir = tempfile.TemporaryDirectory()
        self._orig_app_paths = {
            'TABLE_ORDERS_FILE': app_module.TABLE_ORDERS_FILE,
            'USERS_FILE': app_module.USERS_FILE,
            'MENU_ITEMS_FILE': app_module.MENU_ITEMS_FILE,
            'CASHIER_SESSIONS_FILE': app_module.CASHIER_SESSIONS_FILE,
            'PAYMENT_METHODS_FILE': app_module.PAYMENT_METHODS_FILE,
        }

        app_module.TABLE_ORDERS_FILE = os.path.join(self._temp_dir.name, 'table_orders.json')
        app_module.USERS_FILE = os.path.join(self._temp_dir.name, 'users.json')
        app_module.MENU_ITEMS_FILE = os.path.join(self._temp_dir.name, 'menu_items.json')
        app_module.CASHIER_SESSIONS_FILE = os.path.join(self._temp_dir.name, 'cashier_sessions.json')
        app_module.PAYMENT_METHODS_FILE = os.path.join(self._temp_dir.name, 'payment_methods.json')

        with open(app_module.TABLE_ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        with open(app_module.USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        with open(app_module.MENU_ITEMS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=4, ensure_ascii=False)
        with open(app_module.CASHIER_SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump([{
                'id': 'TEST_SESSION',
                'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'opened_by': self.user,
                'status': 'open',
                'transactions': [],
                'type': 'restaurant_service'
            }], f, indent=4, ensure_ascii=False)
        with open(app_module.PAYMENT_METHODS_FILE, 'w', encoding='utf-8') as f:
            json.dump([{
                'id': '1',
                'name': 'Dinheiro',
                'available_in': ['restaurant', 'reception']
            }], f, indent=4, ensure_ascii=False)
        
        # Setup User
        users = load_users()
        users[self.user] = {'password': self.password, 'role': 'admin'}
        save_users(users)
        
        # Setup Menu Item
        items = load_menu_items()
        self.test_item = next((i for i in items if i['name'] == 'ItemTesteWorkflow'), None)
        if not self.test_item:
            self.test_item = {
                'id': '99999',
                'name': 'ItemTesteWorkflow',
                'price': 100.0,
                'category': 'Teste',
                'active': True
            }
            items.append(self.test_item)
            save_menu_items(items)
            
        # Clear Orders
        save_table_orders({})
        
        # Clear Alerts (optional, or count them)
        self._original_alerts_file = security_service.ALERTS_FILE
        fd, temp_alerts_path = tempfile.mkstemp(prefix='security_alerts_test_', suffix='.json')
        os.close(fd)
        with open(temp_alerts_path, 'w', encoding='utf-8') as f:
            f.write('[]')
        security_service.ALERTS_FILE = temp_alerts_path
        globals()['SECURITY_ALERTS_FILE'] = temp_alerts_path
        self.initial_alerts_count = 0

    def tearDown(self):
        try:
            for k, v in self._orig_app_paths.items():
                setattr(app_module, k, v)
            try:
                self._temp_dir.cleanup()
            except:
                pass
            temp_path = security_service.ALERTS_FILE
            security_service.ALERTS_FILE = self._original_alerts_file
            globals()['SECURITY_ALERTS_FILE'] = self._original_alerts_file
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
        except:
            pass

    def login(self):
        with self.client.session_transaction() as sess:
            sess['user'] = self.user
            sess['role'] = 'admin'
            sess['full_name'] = 'Test Administrator'

    def test_suspicious_workflow(self):
        self.login()
        table_id = '99'

        patches = [
            patch('app.FiscalPoolService.add_to_pool', return_value='TEST_FISCAL_POOL_ENTRY'),
            patch('app.print_bill', return_value=None),
            patch('app.print_cancellation_items', return_value=None),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        
        # 1. Open Table
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'open_table',
            'num_adults': '1',
            'customer_type': 'passante'
        })
        
        # 2. Add Item
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'add_item',
            'product': 'ItemTesteWorkflow',
            'qty': '1'
        })
        
        # 3. Pull Bill
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'pull_bill'
        })
        
        # Verify Locked
        orders = load_table_orders()
        self.assertTrue(orders[table_id]['locked'])
        self.assertIn('pulled_at', orders[table_id])
        
        # 4. Unlock Table
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'unlock_table'
        })
        
        # Verify Reopened Flag
        orders = load_table_orders()
        self.assertFalse(orders[table_id]['locked'])
        self.assertTrue(orders[table_id].get('reopened_after_pull'))
        
        # 5. Remove Item
        # Need index or name.
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'remove_item',
            'product_name': 'ItemTesteWorkflow',
            'cancellation_reason': 'Teste de workflow',
            'auth_password': self.password # Admin authorizes self
        })
        
        # Verify Removal Flag
        orders = load_table_orders()
        self.assertTrue(orders[table_id].get('items_removed_after_reopen'))
        
        # 6. Close Order
        # Need to open cashier first? Logic checks 'get_current_cashier'.
        # Mocking get_current_cashier might be needed or ensuring one is open.
        # Let's bypass cashier check if possible or mock it.
        # Actually, let's just create a dummy cashier session file if needed.
        # But app.py checks get_current_cashier.
        # I'll rely on existing cashier or mock the function.
        # For this test, I'll modify the cashier check or ensure a cashier is open.
        # To avoid complexity, I will just check if the flag is set in step 5, which is the core logic for detection.
        # Step 6 triggers the log.
        
        # Let's try to close. If it fails due to cashier, I'll see the flash message.
        # But the alert is logged BEFORE redirect if cashier is open.
        # Wait, the cashier check is at the BEGINNING of close_order.
        # So I MUST have a cashier open.
        
        from app import save_cashier_sessions, CASHIER_SESSIONS_FILE
        sessions = []
        if os.path.exists(CASHIER_SESSIONS_FILE):
             try:
                 with open(CASHIER_SESSIONS_FILE, 'r') as f:
                     sessions = json.load(f)
             except: pass
        
        # Ensure open session
        has_open = any(s['status'] == 'open' for s in sessions)
        if not has_open:
            sessions.append({
                'id': 'TEST_SESSION',
                'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'opened_by': self.user,
                'status': 'open',
                'transactions': [],
                'type': 'restaurant_service' 
            })
            save_cashier_sessions(sessions)

        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'close_order',
            'payment_method': '1', # Assuming 1 exists or is default
            'paid_amount': '100.00'
        })
        
        # 7. Check Alerts
        final_alerts = load_alerts()
        self.assertGreater(len(final_alerts), self.initial_alerts_count)
        new_alerts = final_alerts[self.initial_alerts_count:]
        self.assertTrue(any(a.get('type') == 'Fechamento Suspeito (Fluxo Irregular)' for a in new_alerts))
        print("Security Workflow Test Passed!")

if __name__ == '__main__':
    unittest.main()
