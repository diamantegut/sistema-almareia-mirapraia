
import unittest
from flask import session
from app import create_app

class TestAdminRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.client = self.app.test_client()

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
            sess['permissions'] = ['admin']

    def test_admin_route(self):
        self.login_as_admin()
        response = self.client.get('/admin', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data) # Assuming title or content

    def test_admin_dashboard_route(self):
        self.login_as_admin()
        response = self.client.get('/admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data)

    def test_admin_system_dashboard_route(self):
        self.login_as_admin()
        response = self.client.get('/admin/system/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data)

    def test_admin_unauthorized(self):
        # No login
        response = self.client.get('/admin', follow_redirects=True)
        # Should redirect to login or main index
        # Based on @login_required decorator logic
        self.assertIn(b'Login', response.data) # Assuming login page has "Login" text

if __name__ == '__main__':
    unittest.main()
