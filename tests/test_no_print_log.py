import unittest
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, load_menu_items, save_menu_items, ACTION_LOGS_DIR, load_table_orders, save_table_orders

class TestNoPrintLog(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        self.table_id = '99'
        
        # Ensure clean state for table 99
        orders = load_table_orders()
        if self.table_id in orders:
            del orders[self.table_id]
            save_table_orders(orders)
        
        # Ensure log dir exists
        if not os.path.exists(ACTION_LOGS_DIR):
            os.makedirs(ACTION_LOGS_DIR)
            
    def test_log_generated_when_should_print_false(self):
        # 1. Login
        with self.app.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user'] = 'TestAdmin'
            sess['username'] = 'TestAdmin'
            
        # 2. Open Table
        print("DEBUG: Opening table...")
        resp = self.app.post(f'/restaurant/table/{self.table_id}', data={
            'action': 'open_table',
            'num_adults': '1',
            'customer_type': 'externo',
            'waiter': 'Angelo'
        }, follow_redirects=True)
        print(f"DEBUG: Open table response: {resp.status_code}")
        
        # 3. Create a product with should_print=False
        product_name = "Test No Print Item"
        
        # Load menu items to inject our test item
        menu_items = load_menu_items()
        test_item = {
            'id': 'test_no_print_1',
            'name': product_name,
            'price': 10.0,
            'category': 'Test',
            'should_print': False, # KEY CONFIG
            'active': True
        }
        menu_items.append(test_item)
        save_menu_items(menu_items)
        
        try:
            # 4. Place Order
            items_json = json.dumps([{
                'product': product_name,
                'qty': 1,
                'complements': [],
                'observations': [],
                'flavor_name': None
            }])
            
            print(f"DEBUG: Placing order for {product_name}...")
            response = self.app.post(f'/restaurant/table/{self.table_id}', data={
                'action': 'add_batch_items',
                'items_json': items_json,
                'waiter': 'Angelo'
            }, follow_redirects=True)
            
            self.assertEqual(response.status_code, 200)
            print(f"DEBUG: Order response text: {response.data.decode('utf-8')[:500]}") # Check for flash messages
            
            # 5. Check Log
            today_str = datetime.now().strftime('%Y-%m-%d')
            log_file = os.path.join(ACTION_LOGS_DIR, f"{today_str}.json")
            
            print(f"DEBUG: Checking log file: {log_file}")
            self.assertTrue(os.path.exists(log_file), "Log file should exist")
            
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
                
            found = False
            for entry in logs:
                if entry.get('action') == 'Venda Sem Impressão' and product_name in entry.get('details', ''):
                    found = True
                    break
            
            self.assertTrue(found, "Audit log entry for 'Venda Sem Impressão' not found")
            
        finally:
            # Cleanup
            menu_items = [i for i in menu_items if i['id'] != 'test_no_print_1']
            save_menu_items(menu_items)
            
            # Clean up table
            orders = load_table_orders()
            if self.table_id in orders:
                del orders[self.table_id]
                save_table_orders(orders)

if __name__ == '__main__':
    unittest.main()
