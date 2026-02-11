import unittest
import json
import os
import shutil
from datetime import datetime, timedelta
from app import create_app
from app.services import data_service, checklist_service
from app.blueprints.governance import routes as governance_routes

# Mock data paths
TEST_DATA_DIR = r'f:\Sistema Almareia Mirapraia\tests\test_data_governance'

class TestGovernanceE2E(unittest.TestCase):
    
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
        # 1. Patch data_service paths
        self.patch_data_service()
        # 2. Patch governance routes paths (local imports)
        self.patch_governance_routes()
        # 3. Patch checklist_service paths
        self.patch_checklist_service()
        
        # Reset data before each test
        self.reset_data()
        
        # Login as Admin/Governance
        with self.client.session_transaction() as sess:
            sess['user'] = 'gov_user'
            sess['role'] = 'admin' # Admin has full access
            sess['department'] = 'Governança'
            sess['permissions'] = ['recepcao'] # Some cross-role testing

    def patch_data_service(self):
        self.orig_ds_occupancy = data_service.ROOM_OCCUPANCY_FILE
        self.orig_ds_cleaning = data_service.CLEANING_STATUS_FILE
        self.orig_ds_charges = data_service.ROOM_CHARGES_FILE
        self.orig_ds_products = data_service.PRODUCTS_FILE
        self.orig_ds_stock_entries = data_service.STOCK_ENTRIES_FILE
        self.orig_ds_menu = data_service.MENU_ITEMS_FILE
        
        data_service.ROOM_OCCUPANCY_FILE = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        data_service.CLEANING_STATUS_FILE = os.path.join(TEST_DATA_DIR, 'cleaning_status.json')
        data_service.ROOM_CHARGES_FILE = os.path.join(TEST_DATA_DIR, 'room_charges.json')
        data_service.PRODUCTS_FILE = os.path.join(TEST_DATA_DIR, 'products.json')
        data_service.STOCK_ENTRIES_FILE = os.path.join(TEST_DATA_DIR, 'stock_entries.json')
        data_service.MENU_ITEMS_FILE = os.path.join(TEST_DATA_DIR, 'menu_items.json')

    def patch_governance_routes(self):
        self.orig_gov_cleaning = governance_routes.CLEANING_STATUS_FILE
        self.orig_gov_logs = governance_routes.CLEANING_LOGS_FILE
        
        governance_routes.CLEANING_STATUS_FILE = os.path.join(TEST_DATA_DIR, 'cleaning_status.json')
        governance_routes.CLEANING_LOGS_FILE = os.path.join(TEST_DATA_DIR, 'cleaning_logs.json')

    def patch_checklist_service(self):
        self.orig_ck_items = checklist_service.CHECKLIST_ITEMS_FILE
        self.orig_ck_daily = checklist_service.DAILY_CHECKLISTS_FILE
        
        checklist_service.CHECKLIST_ITEMS_FILE = os.path.join(TEST_DATA_DIR, 'checklist_items.json')
        checklist_service.DAILY_CHECKLISTS_FILE = os.path.join(TEST_DATA_DIR, 'daily_checklists.json')

    def tearDown(self):
        # Restore paths
        data_service.ROOM_OCCUPANCY_FILE = self.orig_ds_occupancy
        data_service.CLEANING_STATUS_FILE = self.orig_ds_cleaning
        data_service.ROOM_CHARGES_FILE = self.orig_ds_charges
        data_service.PRODUCTS_FILE = self.orig_ds_products
        data_service.STOCK_ENTRIES_FILE = self.orig_ds_stock_entries
        data_service.MENU_ITEMS_FILE = self.orig_ds_menu
        
        governance_routes.CLEANING_STATUS_FILE = self.orig_gov_cleaning
        governance_routes.CLEANING_LOGS_FILE = self.orig_gov_logs
        
        checklist_service.CHECKLIST_ITEMS_FILE = self.orig_ck_items
        checklist_service.DAILY_CHECKLISTS_FILE = self.orig_ck_daily

    def reset_data(self):
        # Clear/Reset JSON files
        list_files = [
            'room_charges.json', 'stock_entries.json', 'cleaning_logs.json', 
            'checklist_items.json', 'products.json', 'menu_items.json',
            'stock_requests.json', 'stock_transfers.json'
        ]
        dict_files = [
            'room_occupancy.json', 'cleaning_status.json', 'daily_checklists.json'
        ]
        
        for f in list_files:
            path = os.path.join(TEST_DATA_DIR, f)
            with open(path, 'w', encoding='utf-8') as file:
                json.dump([], file)
                
        for f in dict_files:
            path = os.path.join(TEST_DATA_DIR, f)
            with open(path, 'w', encoding='utf-8') as file:
                json.dump({}, file)

        # Pre-populate Products for Coffee Test
        products = [
            {'id': '492', 'name': 'Café Capsula (GOVERNANÇA)', 'price': 5.0, 'category': 'Estoque'}
        ]
        with open(os.path.join(TEST_DATA_DIR, 'products.json'), 'w') as f:
            json.dump(products, f)

        # Pre-populate Menu for Frigobar
        menu = [
            {'id': '101', 'name': 'Coca Cola', 'price': 6.0, 'category': 'Frigobar'}
        ]
        with open(os.path.join(TEST_DATA_DIR, 'menu_items.json'), 'w') as f:
            json.dump(menu, f)

    def test_01_dashboard_access(self):
        """Test Dashboard Access and Data Loading"""
        print("\n--- Testing Governance Dashboard ---")
        
        # Setup Occupancy
        occupancy = {'10': {'guest_name': 'Guest 1'}}
        with open(os.path.join(TEST_DATA_DIR, 'room_occupancy.json'), 'w') as f:
            json.dump(occupancy, f)
            
        response = self.client.get('/governance/rooms', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Guest 1', response.data)
        print("✓ Dashboard loaded with occupancy data")

    def test_02_cleaning_workflow(self):
        """Test Full Cleaning Lifecycle"""
        print("\n--- Testing Cleaning Workflow ---")
        
        # 1. Start Cleaning
        data = {'action': 'start_cleaning', 'room_number': '10'}
        response = self.client.post('/governance/rooms', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        status = data_service.load_cleaning_status() # Helper calls the patched path? 
        # Wait, I patched data_service.CLEANING_STATUS_FILE. load_cleaning_status uses it.
        # But I should verify directly from file to be sure.
        with open(os.path.join(TEST_DATA_DIR, 'cleaning_status.json'), 'r') as f:
            status = json.load(f)
            
        self.assertEqual(status['10']['status'], 'in_progress')
        print("✓ Cleaning started")
        
        # 2. Finish Cleaning (Routine)
        # Mock time passing? Not needed for logic check
        data = {'action': 'finish_cleaning', 'room_number': '10'}
        response = self.client.post('/governance/rooms', data=data, follow_redirects=True)
        
        with open(os.path.join(TEST_DATA_DIR, 'cleaning_status.json'), 'r') as f:
            status = json.load(f)
        self.assertEqual(status['10']['status'], 'inspected') # Routine defaults to inspected?
        # Code check: if prev_status not dirty_checkout/rejected -> inspected.
        # Default prev_status was dirty. Correct.
        print("✓ Cleaning finished (Routine -> Inspected)")
        
    def test_03_cleaning_checkout(self):
        """Test Cleaning After Checkout"""
        print("\n--- Testing Checkout Cleaning ---")
        
        # Setup Dirty Checkout
        status_data = {'10': {'status': 'dirty_checkout', 'previous_status': 'dirty_checkout'}}
        with open(os.path.join(TEST_DATA_DIR, 'cleaning_status.json'), 'w') as f:
            json.dump(status_data, f)
            
        # 1. Start
        data = {'action': 'start_cleaning', 'room_number': '10'}
        self.client.post('/governance/rooms', data=data, follow_redirects=True)
        
        # 2. Finish
        data = {'action': 'finish_cleaning', 'room_number': '10'}
        self.client.post('/governance/rooms', data=data, follow_redirects=True)
        
        with open(os.path.join(TEST_DATA_DIR, 'cleaning_status.json'), 'r') as f:
            status = json.load(f)
        self.assertEqual(status['10']['status'], 'clean') # Should need inspection
        print("✓ Checkout cleaning finished (-> clean/needs inspection)")
        
        # 3. Inspect
        data = {'action': 'inspect', 'room_number': '10'}
        self.client.post('/governance/rooms', data=data, follow_redirects=True)
        
        with open(os.path.join(TEST_DATA_DIR, 'cleaning_status.json'), 'r') as f:
            status = json.load(f)
        self.assertEqual(status['10']['status'], 'inspected')
        print("✓ Room inspected")

    def test_04_coffee_deduction(self):
        """Test Coffee Stock Deduction"""
        print("\n--- Testing Coffee Deduction ---")
        
        # Setup Stock (Add entries to allow calculation)
        # calculate_inventory sums entries. We need positive balance.
        entry = {
            'id': 'INIT', 'product': 'Café Capsula (GOVERNANÇA)', 'qty': 10, 'date': '01/01/2024'
        }
        with open(os.path.join(TEST_DATA_DIR, 'stock_entries.json'), 'w') as f:
            json.dump([entry], f)
            
        # Deduct
        data = {'room_number': '10'}
        response = self.client.post('/governance/deduct_coffee', json=data, follow_redirects=True)
        if response.status_code != 200:
            print(f"DEBUG Error: {response.json}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        
        # Verify Entry
        with open(os.path.join(TEST_DATA_DIR, 'stock_entries.json'), 'r') as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]['qty'], -2)
        print("✓ Coffee deducted successfully")
        
        # Undo
        response = self.client.post('/governance/undo_deduct_coffee', json=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        with open(os.path.join(TEST_DATA_DIR, 'stock_entries.json'), 'r') as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[2]['qty'], 2) # Added back
        print("✓ Coffee deduction reversed")

    def test_05_frigobar_launch(self):
        """Test Frigobar Launch"""
        print("\n--- Testing Frigobar Launch ---")
        
        data = {
            'room_number': '10',
            'items': [{'id': '101', 'qty': 2}] # Coca Cola
        }
        
        response = self.client.post('/governance/launch_frigobar', json=data, follow_redirects=True)
        if response.status_code != 200:
            print(f"DEBUG Frigobar Error: {response.json}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        
        with open(os.path.join(TEST_DATA_DIR, 'room_charges.json'), 'r') as f:
            charges = json.load(f)
        
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0]['total'], 12.0) # 2 * 6.0
        self.assertEqual(charges[0]['room_number'], '10')
        print("✓ Frigobar item launched")

    def test_06_checklist_api(self):
        """Test Checklist API"""
        print("\n--- Testing Checklist API ---")
        
        # 1. Add Item
        data = {'name': 'Toalhas', 'category': 'Banho', 'unit': 'un', 'department': 'Governança'}
        response = self.client.post('/api/checklist/add_item', json=data)
        self.assertEqual(response.status_code, 200)
        
        with open(os.path.join(TEST_DATA_DIR, 'checklist_items.json'), 'r') as f:
            items = json.load(f)
        self.assertEqual(len(items), 1)
        item_id = items[0]['id']
        print("✓ Checklist item added")
        
        # 2. Initialize Daily Checklist (by visiting view or calling service)
        # This triggers creation of today's list with the new item
        self.client.get('/checklist?department=Governança')
        
        # 3. Update Daily
        data = {'item_id': item_id, 'checked': True, 'qty': 10, 'department': 'Governança'}
        response = self.client.post('/api/checklist/update_daily', json=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        
        # Verify persistence
        with open(os.path.join(TEST_DATA_DIR, 'daily_checklists.json'), 'r', encoding='utf-8') as f:
            daily = json.load(f)
            
        today = datetime.now().strftime('%Y-%m-%d')
        key = f"{today}_Governança"
        
        self.assertIn(key, daily)
        self.assertEqual(daily[key]['items'][0]['qty'], 10)
        print("✓ Daily checklist updated")

if __name__ == '__main__':
    unittest.main()
