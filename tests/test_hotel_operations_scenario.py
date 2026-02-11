import unittest
import json
import os
import time
from datetime import datetime, timedelta
from app import create_app
from app.services import data_service

# Mock data paths
TEST_DATA_DIR = r'f:\Sistema Almareia Mirapraia\tests\test_data_scenario'

class TestHotelOperationsScenario(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Create a test app environment
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        # Setup mock data directory
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
    def setUp(self):
        # Patch data paths in data_service to use test directory
        self.patch_data_service()
        
        # Reset data before each test
        self.reset_data()
        
        # Login as Admin (superuser for all ops)
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'restaurante', 'financeiro']

    def patch_data_service(self):
        # Define mock file paths
        self.mock_files = {
            'ROOM_OCCUPANCY_FILE': os.path.join(TEST_DATA_DIR, 'room_occupancy.json'),
            'TABLE_ORDERS_FILE': os.path.join(TEST_DATA_DIR, 'table_orders.json'),
            'ROOM_CHARGES_FILE': os.path.join(TEST_DATA_DIR, 'room_charges.json'),
            'SALES_HISTORY_FILE': os.path.join(TEST_DATA_DIR, 'sales_history.json'),
            'MENU_ITEMS_FILE': os.path.join(TEST_DATA_DIR, 'menu_items.json'),
            'PRODUCTS_FILE': os.path.join(TEST_DATA_DIR, 'products.json'),
            'STOCK_ENTRIES_FILE': os.path.join(TEST_DATA_DIR, 'stock_entries.json'),
            'USERS_FILE': os.path.join(TEST_DATA_DIR, 'users.json'),
            'PAYMENT_METHODS_FILE': os.path.join(TEST_DATA_DIR, 'payment_methods.json'),
            'CASHIER_SESSIONS_FILE': os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        }

        # Store originals
        self.original_paths = {}
        for attr, path in self.mock_files.items():
            if hasattr(data_service, attr):
                self.original_paths[attr] = getattr(data_service, attr)
                setattr(data_service, attr, path)
                
    def tearDown(self):
        # Restore original paths
        for attr, original in self.original_paths.items():
            setattr(data_service, attr, original)

    def reset_data(self):
        # Clear/Reset JSON files
        for name, path in self.mock_files.items():
            with open(path, 'w', encoding='utf-8') as f:
                if name == 'ROOM_OCCUPANCY_FILE' or name == 'TABLE_ORDERS_FILE' or name == 'USERS_FILE':
                    json.dump({}, f)
                else:
                    json.dump([], f)

        # Pre-populate Menu Items for orders
        menu = [
            {'id': '101', 'name': 'File Mignon', 'price': 80.0, 'category': 'Pratos'},
            {'id': '102', 'name': 'Suco Laranja', 'price': 15.0, 'category': 'Bebidas'},
            {'id': '32', 'name': 'Couvert Artistico', 'price': 15.0, 'category': 'Couvert'} # Required for logic
        ]
        with open(self.mock_files['MENU_ITEMS_FILE'], 'w') as f:
            json.dump(menu, f)
            
        # Pre-populate Products for stock
        products = [
            {'id': '101', 'name': 'File Mignon', 'price': 40.0, 'unit': 'kg'},
            {'id': '102', 'name': 'Suco Laranja', 'price': 5.0, 'unit': 'l'}
        ]
        with open(self.mock_files['PRODUCTS_FILE'], 'w') as f:
            json.dump(products, f)

    def test_comprehensive_scenario(self):
        """
        Execute comprehensive hotel operations test scenario:
        1. Check-in 10 guests
        2. Restaurant Consumption for all 10
        3. Transfer to Room
        4. Verification
        """
        print("\n=== Starting Comprehensive Hotel Operations Scenario ===")
        
        # --- Step 1: Check-in Process ---
        print("\n[Step 1] Processing Check-ins for 10 Guests...")
        rooms = [str(i) for i in range(1, 11)] # Rooms 1 to 10
        guests = []
        
        for room in rooms:
            guest_name = f"Guest Room {room}"
            guests.append({'room': room, 'name': guest_name})
            
            checkin_data = {
                'action': 'checkin',
                'room_number': room,
                'guest_name': guest_name,
                'checkin_date': datetime.now().strftime('%Y-%m-%d'),
                'checkout_date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
                'num_adults': 2
            }
            
            resp = self.client.post('/reception/rooms', data=checkin_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200, f"Check-in failed for room {room}")
            
        # Verify Check-ins
        occupancy = data_service.load_room_occupancy()
        self.assertEqual(len(occupancy), 10, "Should have 10 occupied rooms")
        print("✓ Successfully checked in 10 guests.")

        # --- Step 2: Restaurant Consumption ---
        print("\n[Step 2] Generating Restaurant Charges...")
        
        for guest in guests:
            room = guest['room']
            table_id = f"90{room}" # Use table IDs 901, 902... to avoid conflicts with real room numbers or filters
            
            # Open Table
            open_data = {
                'action': 'open_table',
                'num_adults': 2,
                'customer_type': 'hospede',
                'room_number': room, # Link to room
                'customer_name': guest['name'],
                'waiter': 'Test Waiter'
            }
            resp = self.client.post(f'/restaurant/table/{table_id}', data=open_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            
            items_data = {
                'action': 'add_batch_items',
                'items_json': json.dumps([
                    {'product': '101', 'qty': 1},
                    {'product': '102', 'qty': 2}
                ]),
                'waiter': 'Test Waiter'
            }
            resp = self.client.post(f'/restaurant/table/{table_id}', data=items_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            
        # Verify Orders Created
        orders = data_service.load_table_orders()
        # Filter for our created tables (901-9010)
        created_tables = {k:v for k,v in orders.items() if k.startswith('90')}
        self.assertEqual(len(created_tables), 10, "Should have 10 open tables (901-9010)")
        
        # Verify Total for one order
        # Total = 80 + 30 = 110. 
        # Note: If service fee is auto-added, it might be more. 
        # By default in logic I saw: total is sum of items. Service fee calculated at payment/transfer.
        sample_order = orders['901']
        self.assertEqual(sample_order['total'], 110.0)
        print("✓ Successfully generated restaurant orders for 10 guests.")

        # --- Step 3: Room Transfer Operation ---
        print("\n[Step 3] Transferring Charges to Rooms...")
        
        for guest in guests:
            room = guest['room']
            table_id = f"90{room}"
            
            transfer_data = {
                'action': 'transfer_to_room',
                'room_number': room
            }
            
            resp = self.client.post(f'/restaurant/table/{table_id}', data=transfer_data, follow_redirects=True)
            self.assertEqual(resp.status_code, 200, f"Transfer failed for table {table_id} to room {room}")
            self.assertIn(b'Transferido para Quarto', resp.data)

        print("✓ Successfully transferred all charges.")

        # --- Step 4: Verification ---
        print("\n[Step 4] Verifying Financial Reconciliation...")
        
        # 1. Tables should be closed/removed from open orders
        orders = data_service.load_table_orders()
        open_scenario_tables = {k:v for k,v in orders.items() if k.startswith('90')}
        self.assertEqual(len(open_scenario_tables), 0, f"Tables {list(open_scenario_tables.keys())} should be closed")
        
        # 2. Room Charges should exist
        charges = data_service.load_room_charges()
        self.assertEqual(len(charges), 10, "Should have 10 room charge records")
        
        # 3. Verify content of a charge
        sample_charge = charges[0]
        # Total transferred = 110 * 1.1 (10% service) = 121.0
        # Check logic in route: `total = order['total'] * 1.1`
        expected_total = 110.0 * 1.1
        self.assertAlmostEqual(sample_charge['total'], expected_total, places=2)
        self.assertEqual(sample_charge['source'], 'restaurant')
        self.assertEqual(sample_charge['status'], 'pending')
        
        # 4. Sales History (Archived Orders)
        history = data_service._load_json(self.mock_files['SALES_HISTORY_FILE'])
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0]['payment_method'], 'Room Charge')
        
        print("✓ Verification Passed: Tables closed, Charges posted, History archived.")
        
        # --- Step 5: Documentation ---
        print("\n[Step 5] Transaction Log:")
        print(f"{'Time':<20} | {'Room':<5} | {'Action':<20} | {'Amount (R$)':<10}")
        print("-" * 65)
        for charge in charges:
            print(f"{charge['date']:<20} | {charge['room_number']:<5} | {'Transfer Restaurant':<20} | {charge['total']:<10.2f}")
            
        print("\n=== Scenario Completed Successfully ===")

if __name__ == '__main__':
    unittest.main()
