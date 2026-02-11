
import unittest
from flask import session
from app import create_app
from app.services.data_service import save_users, load_users

class TestAdminAudit(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.client = self.app.test_client()
        
        # Ensure admin user exists
        users = load_users()
        if 'admin' not in users:
            users['admin'] = {
                'password': '123',
                'role': 'admin',
                'department': 'Diretoria'
            }
            save_users(users)

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
            sess['permissions'] = ['admin']

    def test_admin_users(self):
        self.login_as_admin()
        response = self.client.get('/admin/users', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Gerenciar', response.data)

    def test_admin_backups(self):
        self.login_as_admin()
        response = self.client.get('/admin/backups', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Backups', response.data)

    def test_admin_security(self):
        self.login_as_admin()
        response = self.client.get('/admin/security/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Monitoramento', response.data)

    def test_printers_config(self):
        self.login_as_admin()
        response = self.client.get('/config/printers', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Impressoras', response.data)

    def test_fiscal_config(self):
        self.login_as_admin()
        response = self.client.get('/config/fiscal', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Fiscal', response.data)

    def test_fiscal_pool(self):
        self.login_as_admin()
        response = self.client.get('/admin/fiscal/pool', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # Assuming template has some content.
        
if __name__ == '__main__':
    unittest.main()
