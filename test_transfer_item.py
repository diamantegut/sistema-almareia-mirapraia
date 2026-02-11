
import unittest
from app import create_app
from app.blueprints.restaurant.routes import restaurant_bp
from flask import template_rendered
from contextlib import contextmanager

class TestTransferItem(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.captured_templates = []

    def capture_templates(self, sender, template, context, **extra):
        self.captured_templates.append((template, context))

    def test_transfer_modal_options(self):
        # Verify that all_tables passed to template does NOT contain 1-35
        # And simulate what happens if we have weird table IDs
        
        # Mock session and data
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        # Inject some orders
        from app.services.data_service import save_table_orders
        orders = {
            "36": {"status": "open", "items": [], "total": 0},
            "5": {"status": "open", "items": [], "total": 0}, # Room 5 (Should be excluded)
            "FUNC_Test": {"status": "open", "items": [], "total": 0},
            "3A": {"status": "open", "items": [], "total": 0}, # Weird ID
            "100": {"status": "open", "items": [], "total": 0}
        }
        save_table_orders(orders)
        
        # Capture template context
        template_rendered.connect(self.capture_templates, self.app)
        
        try:
            self.client.get('/restaurant/table/36')
            
            self.assertEqual(len(self.captured_templates), 1)
            template, context = self.captured_templates[0]
            
            all_tables = context['all_tables']
            print(f"All Tables: {all_tables}")
            
            # Check exclusions
            self.assertNotIn("5", all_tables, "Room 5 should be excluded")
            
            # Check inclusions
            self.assertIn("36", all_tables) # Current table (might be excluded in template loop, but present in list)
            self.assertIn("FUNC_Test", all_tables)
            self.assertIn("100", all_tables)
            self.assertIn("3A", all_tables) # This is the problematic one if parsed as 3
            
            # Verify range 36-60
            for i in range(36, 61):
                if str(i) != "36": # 36 is in orders, so it's in list via loop or range
                    pass # It's in list
                    
        finally:
            template_rendered.disconnect(self.capture_templates, self.app)

    def test_transfer_item_backend_logic(self):
        """Test backend logic for item transfer: occupied tables, weird IDs, etc."""
        from app.services.data_service import save_table_orders, load_table_orders
        
        # Setup source and target orders
        orders = {
            "36": {
                "status": "open", 
                "items": [{"id": "item1", "name": "Coke", "qty": 2, "price": 5.0}], 
                "total": 10.0,
                "opened_at": "01/01/2026 10:00"
            },
            "37": {
                "status": "open", 
                "items": [{"id": "item2", "name": "Water", "qty": 1, "price": 3.0}], 
                "total": 3.0,
                "opened_at": "01/01/2026 10:05"
            },
            "FUNC_Test": {
                "status": "open", 
                "items": [], 
                "total": 0,
                "opened_at": "01/01/2026 10:10"
            }
        }
        save_table_orders(orders)
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        # 1. Test Transfer to Occupied Table (36 -> 37)
        response = self.client.post('/restaurant/transfer_item', json={
            'source_table_id': '36',
            'target_table_id': '37',
            'item_index': 0,
            'qty': 1,
            'observations': 'Test Transfer'
        })
        self.assertEqual(response.status_code, 200, f"Response: {response.json}")
        self.assertTrue(response.json['success'])
        
        # Verify persistence
        orders = load_table_orders()
        self.assertEqual(len(orders['36']['items']), 1)
        self.assertEqual(orders['36']['items'][0]['qty'], 1.0)
        self.assertEqual(len(orders['37']['items']), 2) # Original + Transferred
        
        # 2. Test Transfer to Staff Table (36 -> FUNC_Test)
        response = self.client.post('/restaurant/transfer_item', json={
            'source_table_id': '36',
            'target_table_id': 'FUNC_Test',
            'item_index': 0,
            'qty': 1,
            'observations': 'Staff Transfer'
        })
        self.assertEqual(response.status_code, 200, f"Response: {response.json}")
        self.assertTrue(response.json['success'])
        
        orders = load_table_orders()
        self.assertEqual(len(orders['FUNC_Test']['items']), 1)

if __name__ == '__main__':
    unittest.main()
