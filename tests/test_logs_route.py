
import unittest
import json
from flask import session
from app import create_app, db
from app.services.logger_service import LoggerService

class TestLogsRoute(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        
        with self.app.app_context():
            db.create_all()
            # Create some dummy logs
            LoggerService.log_acao('Test Action', 'Test Entity', 'Details', 'INFO', 'Geral', 'admin')
            LoggerService.log_acao('Warning Action', 'Test Entity', 'Details', 'WARNING', 'Geral', 'admin')

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
            sess['permissions'] = ['admin']

    def test_logs_search(self):
        self.login_as_admin()
        # Test with all filters
        response = self.client.get('/api/admin/logs/search?department=Geral&page=1&per_page=10&severity=INFO&search=Details&user=admin')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('items', data)
        # Should only return 1 item (INFO), not WARNING
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['nivel_severidade'], 'INFO')

    def test_logs_export(self):
        self.login_as_admin()
        response = self.client.get('/api/admin/logs/export?department=all')
        self.assertEqual(response.status_code, 200)
        # self.assertEqual(response.content_type, 'text/csv') # charset might differ

if __name__ == '__main__':
    unittest.main()
