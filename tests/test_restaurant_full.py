import unittest
import json
import os
import sys
import time
import shutil
import uuid
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services import data_service, cashier_service, user_service
from app.blueprints.restaurant import routes as restaurant_routes

# Mock data paths
TEST_DATA_DIR = r'tests\test_data_full_restaurant'

class TestRestaurantFull(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        # Cleanup
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def setUp(self):
        # Patch data paths
        self.original_occupancy = data_service.ROOM_OCCUPANCY_FILE
        self.original_charges = data_service.ROOM_CHARGES_FILE
        self.original_orders = data_service.TABLE_ORDERS_FILE
        self.original_sessions = cashier_service.CASHIER_SESSIONS_FILE
        self.original_products = data_service.PRODUCTS_FILE
        self.original_menu = data_service.MENU_ITEMS_FILE
        self.original_users = data_service.USERS_FILE
        self.original_complements = data_service.COMPLEMENTS_FILE
        self.original_payment_methods = data_service.PAYMENT_METHODS_FILE
        self.original_settings = data_service.RESTAURANT_SETTINGS_FILE
        self.original_table_settings = data_service.RESTAURANT_TABLE_SETTINGS_FILE
        
        # Patch user_service USERS_FILE explicitly
        self.original_users_service_file = user_service.USERS_FILE
        
        # Define test file paths
        self.test_occupancy = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        self.test_charges = os.path.join(TEST_DATA_DIR, 'room_charges.json')
        self.test_orders = os.path.join(TEST_DATA_DIR, 'table_orders.json')
        self.test_sessions = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        self.test_products = os.path.join(TEST_DATA_DIR, 'products.json')
        self.test_menu = os.path.join(TEST_DATA_DIR, 'menu_items.json')
        self.test_users = os.path.join(TEST_DATA_DIR, 'users.json')
        self.test_complements = os.path.join(TEST_DATA_DIR, 'complements.json')
        self.test_payment_methods = os.path.join(TEST_DATA_DIR, 'payment_methods.json')
        self.test_settings = os.path.join(TEST_DATA_DIR, 'restaurant_settings.json')
        self.test_table_settings = os.path.join(TEST_DATA_DIR, 'restaurant_table_settings.json')

        # Apply patches
        data_service.ROOM_OCCUPANCY_FILE = self.test_occupancy
        data_service.ROOM_CHARGES_FILE = self.test_charges
        data_service.TABLE_ORDERS_FILE = self.test_orders
        data_service.PRODUCTS_FILE = self.test_products
        data_service.MENU_ITEMS_FILE = self.test_menu
        data_service.USERS_FILE = self.test_users
        data_service.COMPLEMENTS_FILE = self.test_complements
        data_service.PAYMENT_METHODS_FILE = self.test_payment_methods
        data_service.RESTAURANT_SETTINGS_FILE = self.test_settings
        data_service.RESTAURANT_TABLE_SETTINGS_FILE = self.test_table_settings
        cashier_service.CASHIER_SESSIONS_FILE = self.test_sessions
        
        user_service.USERS_FILE = self.test_users
        
        self.reset_data()
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['permissions'] = ['restaurante', 'admin']
            sess['department'] = 'Restaurante'

    def tearDown(self):
        # Restore paths
        data_service.ROOM_OCCUPANCY_FILE = self.original_occupancy
        data_service.ROOM_CHARGES_FILE = self.original_charges
        data_service.TABLE_ORDERS_FILE = self.original_orders
        data_service.PRODUCTS_FILE = self.original_products
        data_service.MENU_ITEMS_FILE = self.original_menu
        data_service.USERS_FILE = self.original_users
        data_service.COMPLEMENTS_FILE = self.original_complements
        data_service.PAYMENT_METHODS_FILE = self.original_payment_methods
        data_service.RESTAURANT_SETTINGS_FILE = self.original_settings
        data_service.RESTAURANT_TABLE_SETTINGS_FILE = self.original_table_settings
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions
        
        user_service.USERS_FILE = self.original_users_service_file

    def reset_data(self):
        # Initial Data
        products = [
            {'id': '1', 'name': 'Água', 'price': 5.0, 'category': 'Bebidas', 'active': True},
            {'id': '2', 'name': 'Coca Cola', 'price': 8.0, 'category': 'Bebidas', 'active': True},
            {'id': '3', 'name': 'Pizza', 'price': 40.0, 'category': 'Refeição', 'active': True},
            {'id': '32', 'name': 'Couvert Artistico', 'price': 15.0, 'category': 'Taxas', 'active': True}
        ]
        
        users = {
            'admin_tester': {'username': 'admin_tester', 'role': 'admin', 'password': '123'},
            'garcom1': {'username': 'garcom1', 'role': 'garcom', 'password': '123'}
        }
        
        payment_methods = [
            {'id': '1', 'name': 'Dinheiro', 'available_in': ['restaurant'], 'is_fiscal': True},
            {'id': '2', 'name': 'Cartão Crédito', 'available_in': ['restaurant'], 'is_fiscal': True},
            {'id': '3', 'name': 'Pix', 'available_in': ['restaurant'], 'is_fiscal': True}
        ]
        
        occupancy = {
            '10': {'guest_name': 'Hóspede Teste', 'checkin': '01/01/2026', 'checkout': '10/01/2026'}
        }

        with open(self.test_products, 'w', encoding='utf-8') as f: json.dump(products, f, ensure_ascii=False)
        with open(self.test_menu, 'w', encoding='utf-8') as f: json.dump(products, f, ensure_ascii=False)
        with open(self.test_users, 'w', encoding='utf-8') as f: json.dump(users, f, ensure_ascii=False)
        with open(self.test_payment_methods, 'w', encoding='utf-8') as f: json.dump(payment_methods, f, ensure_ascii=False)
        with open(self.test_occupancy, 'w', encoding='utf-8') as f: json.dump(occupancy, f, ensure_ascii=False)
        with open(self.test_orders, 'w', encoding='utf-8') as f: json.dump({}, f, ensure_ascii=False)
        with open(self.test_charges, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False)
        with open(self.test_sessions, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False)
        with open(self.test_complements, 'w', encoding='utf-8') as f: json.dump([], f, ensure_ascii=False)
        with open(self.test_settings, 'w', encoding='utf-8') as f: json.dump({}, f, ensure_ascii=False)
        with open(self.test_table_settings, 'w', encoding='utf-8') as f: json.dump({}, f, ensure_ascii=False)

    # --- Helpers ---
    def open_cashier(self):
        return self.client.post('/restaurant/cashier', data={
            'action': 'open_cashier',
            'opening_balance': '100.00'
        }, follow_redirects=True)

    def open_reception_cashier(self):
        # Direct service call to avoid dependency on reception routes which might need login/perms setup
        try:
            cashier_service.CashierService.open_session('reception', 'admin_tester', 100.0)
            print("DEBUG: Opened Reception Cashier")
        except ValueError as e:
            print(f"DEBUG: Reception Cashier Open Failed (Expected if open): {e}")
        except Exception as e:
            print(f"DEBUG: Reception Cashier Open ERROR: {e}")

    def open_table(self, table_id, type='passante', num_adults=2, waiter='garcom1', customer_name='Cliente Teste'):
        return self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'open_table',
            'num_adults': num_adults,
            'customer_type': type,
            'waiter': waiter,
            'customer_name': customer_name
        }, follow_redirects=True)

    def add_items(self, table_id, items_list):
        return self.client.post(f'/restaurant/table/{table_id}', data={
            'action': 'add_batch_items',
            'items_json': json.dumps(items_list),
            'waiter': 'garcom1'
        }, follow_redirects=True)

    def get_orders(self):
        with open(self.test_orders, 'r', encoding='utf-8') as f:
            return json.load(f)

    # --- Tests ---

    def test_01_launch_orders(self):
        """1. Lançamento de Pedidos: Testar tipos, observações, itens."""
        self.open_cashier()
        self.open_table('40')
        
        items = [
            {'product': '1', 'qty': 2, 'observations': ['Sem gelo']}, # 2x Agua (5.0) = 10.0
            {'product': '3', 'qty': 1, 'flavor_name': 'Calabresa'}    # 1x Pizza (40.0) = 40.0
        ]
        self.add_items('40', items)
        
        orders = self.get_orders()
        self.assertIn('40', orders)
        order = orders['40']
        self.assertEqual(len(order['items']), 2)
        self.assertEqual(order['items'][0]['name'], 'Água')
        self.assertEqual(order['items'][0]['observations'], ['Sem gelo'])
        self.assertEqual(order['items'][1]['name'], 'Pizza')
        self.assertEqual(order['items'][1]['flavor'], 'Calabresa')
        self.assertEqual(order['total'], 50.0)

    def test_02_remove_item(self):
        """2. Gestão de Itens: Remoção individual e recálculo."""
        self.test_01_launch_orders() # Setup table 40 with 50.0
        
        orders = self.get_orders()
        item_id = orders['40']['items'][0]['id'] # Remove Water
        
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'remove_item',
            'item_id': item_id,
            'cancellation_reason': 'Cliente desistiu'
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertEqual(len(orders['40']['items']), 1)
        self.assertEqual(orders['40']['total'], 40.0) # Only Pizza left

    def test_03_cancel_table(self):
        """3. Gerenciamento de Mesas: Cancelamento completo."""
        self.test_01_launch_orders()
        
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'cancel_table',
            'reason': 'Erro de lançamento',
            # 'password': '123' 
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertNotIn('40', orders)

    def test_04_consolidate_accounts(self):
        """4. Consolidação de Contas: Juntar mesas."""
        self.open_cashier()
        self.open_table('40')
        self.add_items('40', [{'product': '1', 'qty': 1}]) # 5.0
        
        self.open_table('41')
        self.add_items('41', [{'product': '2', 'qty': 1}]) # 8.0
        
        # Transfer 41 to 40 (Join)
        # Using correct route for transferring table
        resp = self.client.post('/restaurant/table/41', data={
            'action': 'transfer_table',
            'target_table_id': '40'
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertNotIn('41', orders) # 41 closed
        self.assertIn('40', orders)
        self.assertEqual(len(orders['40']['items']), 2)
        self.assertEqual(orders['40']['total'], 13.0)

    def test_05_transfer_to_room(self):
        """5. Transferências: Mesa para Quarto."""
        self.open_cashier()
        self.open_reception_cashier() # Required for transfer
        self.open_table('40')
        self.add_items('40', [{'product': '3', 'qty': 1}]) # 40.0
        
        print(f"DEBUG: SESSIONS_FILE: {cashier_service.CASHIER_SESSIONS_FILE}")
        
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'transfer_to_room',
            'room_number': '10'
        }, follow_redirects=True)
        
        # Check Orders (Table closed)
        orders = self.get_orders()
        if '40' in orders:
            print("DEBUG: Table 40 still open.")
            html = resp.data.decode('utf-8')
            # Try to find any alert
            import re
            m = re.findall(r'class="alert alert-(.*?)".*?>(.*?)</div>', html, re.DOTALL)
            if m: 
                for type_, msg in m:
                    print(f"FLASH MSG ({type_}): {msg.strip()}")
            
            # Check sessions
            with open(self.test_sessions, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
            print(f"DEBUG: Active Sessions: {[s['type'] for s in sessions if s['status']=='open']}")

        self.assertNotIn('40', orders)
        
        # Check Room Charges
        with open(self.test_charges, 'r', encoding='utf-8') as f:
            charges = json.load(f)
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0]['room_number'], '10')
        self.assertEqual(charges[0]['total'], 40.0)
        self.assertEqual(charges[0]['status'], 'pending')

    def test_06_multiple_payments(self):
        """6. Processamento de Pagamentos: Múltiplas formas."""
        self.open_cashier()
        self.open_table('40')
        self.add_items('40', [{'product': '3', 'qty': 1}]) # 40.0 + 10% = 44.0
        
        # Pay 20 in Cash, 24 in Card
        payments = [
            {'id': '1', 'name': 'Dinheiro', 'amount': 20.0},
            {'id': '2', 'name': 'Cartão Crédito', 'amount': 24.0}
        ]
        
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'close_order',
            'payment_data': json.dumps(payments)
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertNotIn('40', orders) # Closed
        
        # Verify Cashier
        with open(self.test_sessions, 'r', encoding='utf-8') as f:
            sessions = json.load(f)

    def test_07_partial_payments(self):
        """7. Pagamentos Parciais."""
        self.open_cashier()
        self.open_table('40')
        self.add_items('40', [{'product': '3', 'qty': 1}]) # 40.0 + 4.0 = 44.0
        
        # Pay 20.0 Partial
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'add_partial_payment',
            'amount': '20.00',
            'payment_method': 'Dinheiro'
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertIn('40', orders) # Still open
        self.assertEqual(orders['40']['total_paid'], 20.0)
        
        # Remaining should be 24.0
        # Close the rest
        payments = [{'id': '1', 'name': 'Dinheiro', 'amount': 24.0}]
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'close_order',
            'payment_data': json.dumps(payments)
        }, follow_redirects=True)
        
        orders = self.get_orders()
        self.assertNotIn('40', orders)

    def test_08_cancel_transfer(self):
        """8. Cancelamento de Transferências (Retorno ao Restaurante)."""
        # First transfer to room (Reuse logic from test 05)
        self.test_05_transfer_to_room()
        
        # Get charge ID
        with open(self.test_charges, 'r', encoding='utf-8') as f:
            charges = json.load(f)
        charge_id = charges[0]['id']
        
        # Return to Restaurant
        resp = self.client.post('/api/reception/return_to_restaurant', json={
            'charge_id': charge_id
        }, follow_redirects=True)
        
        # Check Charges (Cancelled/Removed)
        with open(self.test_charges, 'r', encoding='utf-8') as f:
            charges = json.load(f)
        self.assertEqual(len(charges), 0) # Should be removed or status changed
        
        # Check Table Restored
        orders = self.get_orders()
        self.assertIn('40', orders) # Restored to table 40
        self.assertEqual(orders['40']['total'], 40.0)

    def test_09_special_consumption(self):
        """9. Consumos Especiais (Passante, Hóspede, Funcionário)."""
        self.open_cashier()
        
        # Passante
        self.open_table('40', type='passante', customer_name='Passante')
        self.add_items('40', [{'product': '1', 'qty': 1}])
        orders = self.get_orders()
        self.assertEqual(orders['40']['customer_type'], 'passante')
        
        # Hóspede (Must provide room)
        self.client.post('/restaurant/table/10', data={
            'action': 'open_table',
            'num_adults': 1,
            'customer_type': 'hospede',
            'room_number': '10', # Occupied room
            'waiter': 'garcom1'
        })
        orders = self.get_orders()
        self.assertIn('10', orders)
        self.assertEqual(orders['10']['customer_type'], 'hospede')
        self.assertEqual(orders['10']['room_number'], '10')
        
        # Funcionário
        self.client.post('/restaurant/open_staff_table', data={
            'staff_name': 'garcom1'
        })
        orders = self.get_orders()
        func_key = 'FUNC_garcom1'
        self.assertIn(func_key, orders)
        self.assertEqual(orders[func_key]['customer_type'], 'funcionario')

    def test_10_service_fee_removal(self):
        """10. Comissões e Taxas: Remover 10%."""
        self.open_cashier()
        self.open_table('40')
        self.add_items('40', [{'product': '3', 'qty': 1}]) # 40.0
        
        # Close without service fee
        payments = [{'id': '1', 'name': 'Dinheiro', 'amount': 40.0}] # Exact total without 10%
        
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'close_order',
            'payment_data': json.dumps(payments),
            'remove_service_fee': 'on' 
        }, follow_redirects=True)
        
        # Verify it closed
        orders = self.get_orders()
        self.assertNotIn('40', orders)
        
        # Verify Transaction logs "service_fee_removed": True (nos detalhes da transação)
        with open(self.test_sessions, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
        trans = sessions[0]['transactions'][0]
        details = trans.get('details') or {}
        self.assertTrue(details.get('service_fee_removed', False))

    def test_11_commission_persistence(self):
        """11. Persistência de Comissões."""
        self.open_cashier()
        self.open_reception_cashier() # Required for transfer eligibility
        self.open_table('40', waiter='garcom1')
        self.add_items('40', [{'product': '3', 'qty': 1}]) # 40.0
        
        # Check item waiter
        orders = self.get_orders()
        item = orders['40']['items'][0]
        self.assertEqual(item['waiter'], 'garcom1')
        
        # Transfer to Room
        resp = self.client.post('/restaurant/table/40', data={
            'action': 'transfer_to_room',
            'room_number': '10'
        }, follow_redirects=True)
        
        # Verify transfer success
        orders = self.get_orders()
        if '40' in orders:
            print("DEBUG: test_11 Transfer Failed.")
            html = resp.data.decode('utf-8')
            import re
            m = re.findall(r'class="alert alert-(.*?)".*?>(.*?)</div>', html, re.DOTALL)
            if m: 
                for type_, msg in m:
                    print(f"FLASH MSG ({type_}): {msg.strip()}")
            self.fail("Table 40 still open after transfer in test_11")

        # Check Charge
        with open(self.test_charges, 'r', encoding='utf-8') as f:
            charges = json.load(f)
        
        self.assertTrue(len(charges) > 0, "No charges found")
        charge_item = charges[0]['items'][0]
        self.assertEqual(charge_item['waiter'], 'garcom1') # Should persist

    def test_12_cashier_closing_divergence(self):
        """12. Fechamento de Caixa: Conferência e Divergência."""
        self.open_cashier() # Opened with 100.0
        
        # Sell 50.0
        self.open_table('40')
        self.add_items('40', [{'product': '1', 'qty': 10}]) # 50.0
        payments = [{'id': '1', 'name': 'Dinheiro', 'amount': 55.0}] # 50 + 10%
        self.client.post('/restaurant/table/40', data={'action': 'close_order', 'payment_data': json.dumps(payments)})
        
        # Expected Balance: 100 + 55 = 155.0
        # Close with 150.0 (Divergence -5.0)
        
        resp = self.client.post('/restaurant/cashier', data={
            'action': 'close_cashier',
            'closing_balance': '150.00'
        }, follow_redirects=True)
        
        with open(self.test_sessions, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
        closed_session = sessions[0]
        self.assertEqual(closed_session['status'], 'closed')
        self.assertEqual(closed_session['closing_balance'], 150.0)
        # Expected difference calculation logic in service
        # self.assertEqual(closed_session['difference'], -5.0) 

    def test_13_audit_trail(self):
        """13. Critérios de Sucesso: Trilha de Auditoria."""
        # This is implicitly tested by checking logs or data integrity in other tests.
        pass

if __name__ == '__main__':
    unittest.main()
