import unittest
import json
import os
import sys
import shutil
from datetime import datetime, timedelta

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services.data_service import (
    load_table_orders, save_table_orders,
    load_cashier_sessions, save_cashier_sessions,
    load_sales_history, save_sales_history,
    load_room_charges, save_room_charges,
    load_stock_logs, load_users,
    load_menu_items, save_menu_items,
    load_payment_methods, save_payment_methods,
    load_room_occupancy, save_room_occupancy
)
from app.services.system_config_manager import (
    TABLE_ORDERS_FILE, CASHIER_SESSIONS_FILE, SALES_HISTORY_FILE,
    ROOM_CHARGES_FILE, STOCK_LOGS_FILE, MENU_ITEMS_FILE, PAYMENT_METHODS_FILE,
    ROOM_OCCUPANCY_FILE
)

class TestRestaurantWorkflows(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        
        # Backup original files using absolute paths
        self.backup_paths = [
            TABLE_ORDERS_FILE,
            CASHIER_SESSIONS_FILE,
            SALES_HISTORY_FILE,
            ROOM_CHARGES_FILE,
            STOCK_LOGS_FILE,
            MENU_ITEMS_FILE,
            PAYMENT_METHODS_FILE,
            ROOM_OCCUPANCY_FILE
        ]
        
        self.backups = {}
        for f in self.backup_paths:
            if os.path.exists(f):
                with open(f, 'r', encoding='utf-8') as src:
                    self.backups[f] = src.read()
            else:
                self.backups[f] = None
        
        # Clear Orders for clean test
        with open(TABLE_ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        # Initialize room occupancy for transfer test
        with open(ROOM_OCCUPANCY_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                '10': {
                    'guest': 'Test Guest', 
                    'checkin': '2024-01-01', 
                    'checkout': '2024-01-05',
                    'num_adults': 2
                }
            }, f)
        
        # Setup Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'restaurante', 'financeiro', 'estoque']

        # Ensure Test Product Exists
        menu = load_menu_items()
        if not any(str(p['id']) == '1' for p in menu):
            menu.append({
                "id": "1",
                "name": "Agua Mineral",
                "price": 5.0,
                "category": "Bebidas",
                "unit": "un"
            })
            save_menu_items(menu)

        methods = load_payment_methods()
        if not methods:
            methods.append({
                "id": "PM_TEST",
                "name": "Dinheiro",
                "available_in": ["restaurant"]
            })
            save_payment_methods(methods)

        # Ensure Cashier is Open
        self.open_cashier()

    def tearDown(self):
        # Restore backups
        for f, content in self.backups.items():
            if content is not None:
                with open(f, 'w', encoding='utf-8') as dst:
                    dst.write(content)
            else:
                if os.path.exists(f):
                    os.remove(f)

    def open_cashier(self):
        """Helper to ensure cashier is open"""
        sessions = load_cashier_sessions()
        # Close any open sessions first to be clean
        for s in sessions:
            if s['status'] == 'open' and s.get('type') in ['restaurant', 'restaurant_service']:
                s['status'] = 'closed'
                s['closed_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        # Open new session
        new_session = {
            "id": "test_session",
            "type": "restaurant",
            "opened_at": datetime.now().strftime('%d/%m/%Y %H:%M'),
            "status": "open",
            "opening_balance": 100.0,
            "user": "admin",
            "transactions": []
        }
        sessions.append(new_session)
        save_cashier_sessions(sessions)

    def create_table_with_item(self, table_id):
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante',
            'customer_name': 'Test Client',
            'waiter': 'Garçom Teste'
        }, follow_redirects=True)
        
        items_json = json.dumps([{
            "product": "1",
            "qty": 2,
            "observations": ["Sem gelo"],
            "flavor_name": None,
            "complements": [],
            "accompaniments": []
        }])
        
        self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'add_batch_items',
            'items_json': items_json,
            'waiter': 'Garçom Teste'
        }, follow_redirects=True)

    def test_workflow_1_table_lifecycle(self):
        print("\n--- Testing Workflow 1: Table Opening and Closing ---")
        
        # 1. Open Table
        table_id = "99"
        resp = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante',
            'customer_name': 'Test Client',
            'waiter': 'Garçom Teste'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        orders = load_table_orders()
        self.assertIn(table_id, orders)
        self.assertEqual(orders[table_id]['customer_name'], 'Test Client')
        self.assertEqual(orders[table_id]['status'], 'open')
        print("✓ Table opened successfully")

        # 2. Add Item (Batch)
        items_json = json.dumps([{
            "product": "1", # Assuming ID 1 exists (Agua usually)
            "qty": 2,
            "observations": ["Sem gelo"],
            "flavor_name": None,
            "complements": [],
            "accompaniments": []
        }])
        
        resp = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'add_batch_items',
            'items_json': items_json,
            'waiter': 'Garçom Teste'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        orders = load_table_orders()
        self.assertEqual(len(orders[table_id]['items']), 1)
        self.assertEqual(orders[table_id]['items'][0]['qty'], 2.0)
        print("✓ Items added successfully")

        # 3. Close Table (Full Payment)
        total = orders[table_id]['total'] * 1.1 # +10%
        payment_data = json.dumps([{
            "method": "Dinheiro",
            "amount": total
        }])
        
        resp = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'close_order',
            'payment_data': payment_data,
            'discount': 0
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        orders = load_table_orders()
        self.assertNotIn(table_id, orders)
        
        history = load_sales_history()
        last_sale = history[-1]
        self.assertEqual(last_sale['final_total'], total)
        print("✓ Table closed successfully")

    def test_close_order_with_payment_name_payload(self):
        table_id = "201"
        self.create_table_with_item(table_id)
        
        orders = load_table_orders()
        total = orders[table_id]['total'] * 1.1
        payment_data = json.dumps([{"name": "Dinheiro", "amount": total}])
        
        resp = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'close_order',
            'payment_data': payment_data,
            'discount': 0
        }, follow_redirects=True)
        
        self.assertEqual(resp.status_code, 200)
        orders = load_table_orders()
        self.assertNotIn(table_id, orders)
        
        history = load_sales_history()
        last_sale = history[-1]
        self.assertEqual(last_sale.get('status'), 'closed')
        self.assertEqual(last_sale['final_total'], total)

    def test_close_order_with_payment_id_payload(self):
        table_id = "202"
        self.create_table_with_item(table_id)
        
        methods = load_payment_methods()
        method_id = methods[0]['id']
        
        orders = load_table_orders()
        total = orders[table_id]['total'] * 1.1
        payment_data = json.dumps([{"id": method_id, "amount": total}])
        
        resp = self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'close_order',
            'payment_data': payment_data,
            'discount': 0
        }, follow_redirects=True)
        
        self.assertEqual(resp.status_code, 200)
        orders = load_table_orders()
        self.assertNotIn(table_id, orders)
        
        history = load_sales_history()
        last_sale = history[-1]
        self.assertEqual(last_sale.get('status'), 'closed')
        self.assertEqual(last_sale['final_total'], total)

    def test_workflow_2_transfer_functionality(self):
        print("\n--- Testing Workflow 2: Table Transfer ---")
        
        # Open two tables
        t1, t2 = "90", "91"
        self.client.post(f'/restaurant/table/{t1}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        self.client.post(f'/restaurant/table/{t2}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        
        # Add item to T1
        items_json = json.dumps([{"product": "1", "qty": 1}])
        self.client.post(f'/restaurant/table/{t1}', data={'action': 'add_batch_items', 'items_json': items_json})
        
        # Transfer Item T1 -> T2
        # Need item index/ID logic. But route uses index.
        # Let's use the JSON API for transfer
        
        resp = self.client.post('/restaurant/transfer_item', json={
            'source_table_id': t1,
            'target_table_id': t2,
            'item_index': 0,
            'qty': 1
        })
        self.assertEqual(resp.status_code, 200)
        
        orders = load_table_orders()
        self.assertEqual(len(orders[t1]['items']), 0)
        self.assertEqual(len(orders[t2]['items']), 1)
        self.assertTrue(orders[t2]['items'][0]['transferred_from'], t1)
        print("✓ Item transferred successfully")

    def test_workflow_3_reception_transfer(self):
        print("\n--- Testing Workflow 3: Reception Transfer ---")
        
        t_id = "80"
        room_num = "10"
        
        # Open table
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        # Add item
        items_json = json.dumps([{"product": "1", "qty": 10}]) # Expensive water
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'add_batch_items', 'items_json': items_json})
        
        # Transfer to Room
        resp = self.client.post(f'/restaurant/table/{t_id}', data={
            'action': 'transfer_to_room',
            'room_number': room_num
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        # Verify Table Closed
        orders = load_table_orders()
        self.assertNotIn(t_id, orders)
        
        # Verify Room Charge Created
        charges = load_room_charges()
        charge = next((c for c in charges if c['room_number'] == room_num and "Restaurante Mesa 80" in c['description']), None)
        self.assertIsNotNone(charge)
        print("✓ Transferred to room successfully")

    def test_workflow_4_payment_processing(self):
        print("\n--- Testing Workflow 4: Payment Processing (Partial) ---")
        
        t_id = "81"
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        items_json = json.dumps([{"product": "1", "qty": 5}]) # Total say 50.0
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'add_batch_items', 'items_json': items_json})
        
        # Add Partial Payment
        resp = self.client.post(f'/restaurant/table/{t_id}', data={
            'action': 'add_partial_payment',
            'amount': '20.00',
            'payment_method': 'Pix'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        orders = load_table_orders()
        self.assertEqual(orders[t_id]['total_paid'], 20.0)
        self.assertEqual(len(orders[t_id]['partial_payments']), 1)
        
        # Verify Cashier
        sessions = load_cashier_sessions()
        for s in sessions:
            if s['status'] == 'open':
                print(f"Session {s['id']} ({s.get('type')}): {len(s.get('transactions', []))} txs")
        
        session_data = next(s for s in sessions if s['id'] == "test_session" and s['status'] == 'open')
        tx = session_data['transactions'][-1]
        self.assertEqual(tx['amount'], 20.0)
        self.assertIn("Pagamento Parcial", tx['description'])
        print("✓ Partial payment processed successfully")

    def test_workflow_5_commission_removal(self):
        print("\n--- Testing Workflow 5: Commission Removal ---")
        
        t_id = "82"
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        items_json = json.dumps([{"product": "1", "qty": 1}]) # Price 5.0 (example)
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'add_batch_items', 'items_json': items_json})
        
        orders = load_table_orders()
        base_total = orders[t_id]['total']
        
        # Close with Remove Service Fee
        payment_data = json.dumps([{
            "method": "Dinheiro",
            "amount": base_total # Exact amount without 10%
        }])
        
        resp = self.client.post(f'/restaurant/table/{t_id}', data={
            'action': 'close_order',
            'payment_data': payment_data,
            'remove_service_fee': 'on',
            'discount': 0
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        history = load_sales_history()
        last_sale = history[-1]
        self.assertAlmostEqual(last_sale['final_total'], base_total)
        print("✓ Commission removed successfully")

    def test_workflow_9_observations(self):
        print("\n--- Testing Workflow 9: Observations ---")
        
        t_id = "83"
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante'})
        
        obs_text = "Extra Spicy"
        items_json = json.dumps([{
            "product": "1",
            "qty": 1,
            "observations": [obs_text]
        }])
        
        self.client.post(f'/restaurant/table/{t_id}', data={'action': 'add_batch_items', 'items_json': items_json})
        
        orders = load_table_orders()
        item = orders[t_id]['items'][0]
        self.assertIn(obs_text, item['observations'])
        print("✓ Observations persisted successfully")

    def test_workflow_6_permanent_commission(self):
        print("\n--- Testing Workflow 6: Permanent Commission Route ---")
        # Currently, the system assigns a 'waiter' to each item when added.
        # We verify that this waiter persists even if table waiter changes (though table waiter usually doesn't change much).
        
        t_id = "84"
        waiter_1 = "Garçom A"
        self.client.post(f'/restaurant/table/{t_id}', data={
            'action': 'open_table', 'num_adults': 1, 'customer_type': 'passante', 'waiter': waiter_1
        })
        
        # Add item as Waiter B (simulated by session switch or just form data if supported)
        # The add_batch_items uses form 'waiter' field.
        waiter_2 = "Garçom B"
        items_json = json.dumps([{"product": "1", "qty": 1}])
        self.client.post(f'/restaurant/table/{t_id}', data={
            'action': 'add_batch_items', 
            'items_json': items_json,
            'waiter': waiter_2
        })
        
        orders = load_table_orders()
        item = orders[t_id]['items'][0]
        self.assertEqual(item['waiter'], waiter_2)
        print("✓ Item commission route (waiter) persisted correctly")

if __name__ == '__main__':
    unittest.main()
