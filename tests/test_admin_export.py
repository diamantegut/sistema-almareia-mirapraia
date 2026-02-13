
import unittest
import json
import io
from unittest.mock import patch
from app import create_app
from flask import session

class TestAdminExport(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.client = self.app.test_client()
        
        # Mock users data
        self.users_data = {
            "admin_test": {
                "password": "123",
                "role": "admin",
                "department": "Diretoria",
                "full_name": "Admin Test",
                "email": "admin@test.com",
                "admission_date": "2020-01-01"
            },
            "user_test": {
                "password": "123",
                "role": "colaborador",
                "department": "Recepção",
                "full_name": "User Test",
                "admission_date": "2021-01-01"
            }
        }

    @patch('app.blueprints.admin.routes.load_users')
    def test_export_users_excel(self, mock_load_users):
        mock_load_users.return_value = self.users_data
        
        # Login as admin
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_test'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
        
        response = self.client.get('/admin/users/export')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertTrue(response.headers['Content-Disposition'].startswith('attachment; filename=colaboradores_'))
        
        # Verify content (basic check if it's a zip/xlsx file structure)
        self.assertTrue(len(response.data) > 0)
        
    def test_export_users_unauthorized(self):
        # Login as regular user
        with self.client.session_transaction() as sess:
            sess['user'] = 'user_test'
            sess['role'] = 'colaborador'
            sess['department'] = 'Recepção'
            
        response = self.client.get('/admin/users/export')
        # Should redirect or 403 (Redirect in current impl)
        self.assertEqual(response.status_code, 302)

if __name__ == '__main__':
    unittest.main()
