import unittest
import json
import os
import sys
from unittest.mock import patch
from datetime import datetime

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

class TestConsumptionCancellation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.testing = True
        cls.client = cls.app.test_client()

    def setUp(self):
        # Sample charge data
        self.sample_charge = {
            "id": "CHARGE_TEST_001",
            "room_number": "101",
            "status": "pending",
            "total": 100.0,
            "date": "27/01/2026",
            "items": '[{"name": "Coca Cola", "price": 10.0, "qty": 10}]'
        }
        
        self.canceled_charge = {
            "id": "CHARGE_TEST_002",
            "room_number": "102",
            "status": "canceled",
            "total": 50.0,
            "date": "27/01/2026"
        }

    def set_session(self, role='admin', user='admin_user'):
        with self.client.session_transaction() as sess:
            sess['role'] = role
            sess['user'] = user

    def test_access_denied_non_admin(self):
        self.set_session(role='recepcao')
        
        response = self.client.post(
            '/admin/consumption/cancel',
            json={'charge_id': 'CHARGE_TEST_001', 'justification': 'Test'}
        )
        
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertIn('Acesso negado', data.get('message', ''))

    def test_missing_data(self):
        self.set_session(role='admin')
        
        response = self.client.post(
            '/admin/consumption/cancel',
            json={'charge_id': 'CHARGE_TEST_001'} # Missing justification
        )
        
        self.assertEqual(response.status_code, 400)
        
    @patch('app.blueprints.reception.routes.load_room_charges')
    def test_charge_not_found(self, mock_load):
        self.set_session(role='admin')
        mock_load.return_value = [] # Empty list
        
        response = self.client.post(
            '/admin/consumption/cancel',
            json={'charge_id': 'NON_EXISTENT', 'justification': 'Test'}
        )
        
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertIn('Consumo não encontrado', data['message'])

    @patch('app.blueprints.reception.routes.load_room_charges')
    def test_already_canceled(self, mock_load):
        self.set_session(role='admin')
        mock_load.return_value = [self.canceled_charge]
        
        response = self.client.post(
            '/admin/consumption/cancel',
            json={'charge_id': 'CHARGE_TEST_002', 'justification': 'Test'}
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('já foi cancelado', data['message'])

    @patch('app.blueprints.reception.routes.LoggerService.log_acao')
    @patch('app.blueprints.reception.routes.load_room_charges')
    @patch('app.blueprints.reception.routes.save_room_charges')
    @patch('app.blueprints.reception.routes.load_audit_logs')
    @patch('app.blueprints.reception.routes.save_audit_logs')
    def test_successful_cancellation(self, mock_save_audit, mock_load_audit, mock_save_charges, mock_load_charges, mock_log_acao):
        self.set_session(role='admin')
        
        # Setup mocks
        mock_load_charges.return_value = [self.sample_charge.copy()]
        mock_load_audit.return_value = []
        
        response = self.client.post(
            '/admin/consumption/cancel',
            json={'charge_id': 'CHARGE_TEST_001', 'justification': 'Erro de lançamento'}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        
        # Verify charge update
        saved_charges = mock_save_charges.call_args[0][0]
        updated_charge = saved_charges[0]
        self.assertEqual(updated_charge['status'], 'canceled')
        self.assertEqual(updated_charge['cancellation_reason'], 'Erro de lançamento')
        self.assertEqual(updated_charge['canceled_by'], 'admin_user')
        
        # Verify audit log
        saved_logs = mock_save_audit.call_args[0][0]
        self.assertEqual(len(saved_logs), 1)
        self.assertEqual(saved_logs[0]['action'], 'cancel_consumption')
        self.assertEqual(saved_logs[0]['target_id'], 'CHARGE_TEST_001')

if __name__ == '__main__':
    unittest.main()
