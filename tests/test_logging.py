import unittest
import sys
import os
import json
from datetime import datetime, timedelta
from io import BytesIO

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from database import db
from models import LogAcaoDepartamento
from logger_service import LoggerService

class TestLoggingSystem(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['SECRET_KEY'] = 'test_key'
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_log_creation(self):
        """Test basic log creation via LoggerService"""
        success = LoggerService.log_acao(
            acao="Teste Unitario",
            entidade="Teste",
            detalhes={"key": "value"},
            nivel_severidade="INFO",
            departamento_id="TI",
            colaborador_id="Tester"
        )
        self.assertTrue(success)
        
        log = LogAcaoDepartamento.query.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.acao, "Teste Unitario")
        self.assertEqual(log.departamento_id, "TI")
        self.assertEqual(json.loads(log.detalhes)['key'], 'value')

    def test_middleware_logging(self):
        """Test that middleware captures requests"""
        # Simulate a POST request
        with self.client.session_transaction() as sess:
            sess['user'] = 'MiddlewareTester'
            sess['department'] = 'DevOps'
            
        response = self.client.post('/api/some/endpoint', data={'field': 'value'})
        # Note: The endpoint might 404, but middleware should still run before request
        
        # Check if log was created
        log = LogAcaoDepartamento.query.filter_by(colaborador_id='MiddlewareTester').first()
        self.assertIsNotNone(log)
        self.assertIn('Requisição POST', log.acao)
        detalhes = json.loads(log.detalhes)
        self.assertIn('form_data', detalhes)
        self.assertIn('field', detalhes['form_data']) 
        # Ensure value IS logged now (but safe)
        self.assertEqual('value', detalhes['form_data']['field'])

    def test_export_logs(self):
        """Test log export to CSV"""
        # Create dummy logs
        LoggerService.log_acao("ExportAction", "EntidadeExp", colaborador_id="ExpUser", departamento_id="ExpDept")
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        response = self.client.get('/api/admin/logs/export')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('attachment; filename=logs_export.csv', response.headers['Content-disposition'])
        
        content = response.data.decode('utf-8')
        self.assertIn('ID;Data/Hora;Usuário;Departamento;Ação;Detalhes;Entidade;Nível', content)
        self.assertIn('ExportAction', content)
        self.assertIn('ExpUser', content)

    def test_admin_logs_access(self):
        """Test access control for admin logs"""
        # 1. Non-admin access
        with self.client.session_transaction() as sess:
            sess['user'] = 'User'
            sess['role'] = 'user'
            
        response = self.client.get('/admin/logs', follow_redirects=True)
        self.assertIn(b'Acesso restrito', response.data) # Flash message
        
        # 2. Admin access
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        response = self.client.get('/admin/logs')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Auditoria e Logs', response.data)

    def test_api_logs_filtering(self):
        """Test API log filtering"""
        # Create dummy logs
        LoggerService.log_acao("Acao 1", "Entidade A", colaborador_id="User1", departamento_id="DeptA")
        LoggerService.log_acao("Acao 2", "Entidade B", colaborador_id="User2", departamento_id="DeptB")
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        # Filter by User1
        response = self.client.get('/api/admin/logs?colaborador_id=User1')
        data = json.loads(response.data)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['colaborador_id'], 'User1')
        
        # Filter by DeptB
        response = self.client.get('/api/admin/logs?department_id=DeptB')
        data = json.loads(response.data)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['departamento_id'], 'DeptB')

    def test_export_csv(self):
        """Test CSV export functionality"""
        LoggerService.log_acao("Export Me", "CSV", detalhes="Details", colaborador_id="Exporter")
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        response = self.client.get('/api/admin/logs/export')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn(b'Exporter', response.data)
        self.assertIn(b'Export Me', response.data)

    def test_old_route_redirect(self):
        """Test redirection of deprecated service log route"""
        with self.client.session_transaction() as sess:
            sess['user'] = 'User'
            sess['role'] = 'user'
            
        response = self.client.get('/service/123/log', follow_redirects=True)
        # Should redirect to index
        self.assertIn(b'O acesso aos logs foi centralizado', response.data)
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        response = self.client.get('/service/123/log', follow_redirects=True)
        # Should redirect to admin logs
        self.assertIn(b'Auditoria e Logs', response.data)

if __name__ == '__main__':
    unittest.main()
