import unittest
import sys
import os

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

class TestAdminAccess(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test_key'
        self.client = app.test_client()

    def test_admin_access_allowed(self):
        """Test that admin user can access /admin"""
        with self.client.session_transaction() as sess:
            sess.update({'user': 'Admin', 'role': 'admin'})

        response = self.client.get('/admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data)

    def test_non_admin_access_denied(self):
        """Test that non-admin user is redirected"""
        with self.client.session_transaction() as sess:
            sess.update({'user': 'Waiter', 'role': 'garcom'})

        response = self.client.get('/admin', follow_redirects=True)
        # Should redirect to index or show error
        # In app.py: flash('Acesso negado...'); redirect(url_for('index'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Acesso negado', response.data)
        # Assuming index has some recognizable content, e.g. "Dashboard" or "Bem-vindo"
        self.assertIn(b'Bem-vindo', response.data)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated user is redirected to login"""
        response = self.client.get('/admin', follow_redirects=True)
        # Should redirect to login
        self.assertIn(b'Login', response.data)

if __name__ == '__main__':
    unittest.main()
