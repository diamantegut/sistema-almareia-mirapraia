
import unittest
from flask import session
from app import create_app
from app.services.data_service import load_table_orders, save_table_orders, load_users, save_users

class TestStaffConsumption(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        
        # Create a test user
        self.test_user = "TestUserStaff"
        users = load_users()
        users[self.test_user] = {
            "username": self.test_user,
            "full_name": "Test User Staff",
            "role": "admin"
        }
        save_users(users)
        
    def tearDown(self):
        # Cleanup
        orders = load_table_orders()
        keys_to_remove = [k for k in orders if k.startswith(f"FUNC_{self.test_user}")]
        for k in keys_to_remove:
            del orders[k]
        save_table_orders(orders)
        
        users = load_users()
        if self.test_user in users:
            del users[self.test_user]
            save_users(users)
            
        self.ctx.pop()

    def test_open_staff_table_success(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['_user_id'] = 'admin' # flask-login needs this sometimes
            
        response = self.client.post('/restaurant/open_staff_table', data={
            'staff_name': self.test_user
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify persistence
        orders = load_table_orders()
        table_id = f"FUNC_{self.test_user}"
        self.assertIn(table_id, orders)
        self.assertEqual(orders[table_id]['status'], 'open')
        self.assertEqual(orders[table_id]['customer_type'], 'funcionario')
        self.assertEqual(orders[table_id]['created_via'], 'open_staff_table_v2')

    def test_open_staff_table_invalid_user(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
        
        response = self.client.post('/restaurant/open_staff_table', data={
            'staff_name': 'InvalidUserXYZ'
        }, follow_redirects=True)
        
        self.assertIn(b'Funcion\xc3\xa1rio inv\xc3\xa1lido', response.data.replace(b'&aacute;', b'\xc3\xa1')) # Check for flash message (encoding might vary)
        
        orders = load_table_orders()
        table_id = "FUNC_InvalidUserXYZ"
        self.assertNotIn(table_id, orders)

if __name__ == '__main__':
    unittest.main()
