import unittest
import json
import os
import sys
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, load_table_orders, save_table_orders, load_cashier_sessions, save_cashier_sessions, load_room_charges, save_room_charges
from services.fiscal_pool_service import FiscalPoolService
from services.cashier_service import CashierService

class TestFiscalFlowFull(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.testing = True
        self.user_id = 'admin_user'
        
        # Mock Fiscal Pool in-memory
        self.fiscal_pool_data = []
        
        def _save_pool_mock(pool_data):
            self.fiscal_pool_data[:] = list(pool_data)
            return True

        def _load_pool_mock():
            return list(self.fiscal_pool_data)

        self.load_patcher = patch('services.fiscal_pool_service.FiscalPoolService._load_pool', side_effect=_load_pool_mock)
        self.save_patcher = patch('services.fiscal_pool_service.FiscalPoolService._save_pool', side_effect=_save_pool_mock)

        self.mock_load_pool = self.load_patcher.start()
        self.mock_save_pool = self.save_patcher.start()
            
    def tearDown(self):
        self.load_patcher.stop()
        self.save_patcher.stop()

    @patch('app.get_current_cashier')
    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('services.cashier_service.CashierService._load_sessions')
    @patch('services.cashier_service.CashierService._save_sessions')
    @patch('services.fiscal_pool_service.FiscalPoolService.sync_entry_to_remote') # Mock async call
    def test_restaurant_close_flow(self, mock_sync, mock_save_cs_svc, mock_load_cs_svc, mock_save_sessions, mock_load_sessions, mock_save_orders, mock_load_orders, mock_get_cashier):
        # 1. Setup Data
        table_id = '99'
        order_data = {
            'id': 'ORDER_99',
            'status': 'open',
            'total': 100.0,
            'items': [{'name': 'Pizza', 'price': 100.0, 'qty': 1, 'category': 'Alimentacao'}],
            'waiter': 'Garcom Teste',
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        }
        mock_load_orders.return_value = {table_id: order_data}
        
        # Mock Cashier
        mock_get_cashier.return_value = {
            'id': 'SESSION_REST_TEST', 'status': 'open', 'type': 'restaurant_service', 'transactions': []
        }
        
        # Mock Cashier Sessions
        session_data = [{
            'id': 'SESSION_REST_TEST',
            'type': 'restaurant',
            'status': 'open',
            'transactions': [],
            'opening_balance': 0.0,
            'user': 'admin_user'
        }]
        mock_load_cs_svc.return_value = session_data
        mock_load_sessions.return_value = session_data
        
        with self.app.test_client() as client:
            # Set session for the client
            with client.session_transaction() as sess:
                sess['user'] = self.user_id
                sess['role'] = 'admin'
                sess['permissions'] = ['admin', 'restaurante', 'reception']

            # 2. Execute Close Order (POST)
            payment_data = json.dumps([
                {'id': 'dinheiro', 'amount': 110.0}
            ])
            
            response = client.post(f'/restaurant/table/{table_id}', data={
                'action': 'close_order',
                'payment_data': payment_data,
                'customer_cpf_cnpj': '12345678900'
            }, follow_redirects=True)
            
            self.assertEqual(response.status_code, 200)
            
            time.sleep(0.1) # Give time for the async call to execute
            # 3. Verify Pool Content
            pool = FiscalPoolService._load_pool()
            self.assertEqual(len(pool), 1)
            self.assertEqual(pool[0]['origin'], 'restaurant')
            self.assertEqual(pool[0]['original_id'], table_id)
            self.assertEqual(pool[0]['status'], 'pending')
            entry_id = pool[0]['id']

            # 4. Admin: Emit Invoice
            with patch('fiscal_service.emit_invoice') as mock_emit, \
                 patch('fiscal_service.load_fiscal_settings') as mock_load_settings, \
                 patch('fiscal_service.get_fiscal_integration') as mock_get_integration:
                mock_emit.return_value = {'success': True, 'data': {'id': 'FISCAL_UUID_123'}}
                mock_load_settings.return_value = {}
                mock_get_integration.return_value = {'cnpj_emitente': '00000000000000'}
                
                response_emit = client.post('/admin/fiscal/pool/action', json={
                    'id': entry_id,
                    'action': 'emit'
                })

                self.assertEqual(response_emit.status_code, 200)
                data = json.loads(response_emit.data)
                self.assertTrue(data['success'])

                pool_updated = FiscalPoolService._load_pool()
                self.assertEqual(pool_updated[0]['status'], 'emitted')

    @patch('app.load_room_occupancy')
    @patch('app.CashierService.add_transaction')
    @patch('app.CashierService.get_active_session')
    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('services.fiscal_pool_service.FiscalPoolService.sync_entry_to_remote')
    def test_reception_pay_charge_flow(self, mock_sync, mock_save_charges, mock_load_charges, mock_get_active_session, mock_add_transaction, mock_load_occupancy):
        # 1. Setup Data
        charge_id = 'CHARGE_REC_01'
        charge_data = {
            'id': charge_id,
            'room_number': '101',
            'status': 'pending',
            'total': 50.0,
            'items': [{'name': 'Cerveja', 'price': 10.0, 'qty': 5, 'category': 'Frigobar'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        mock_load_charges.return_value = [charge_data]
        
        mock_get_active_session.return_value = {
            'id': 'SESSION_REC_TEST',
            'status': 'open',
            'type': 'reception_room_billing',
            'transactions': []
        }
        mock_load_occupancy.return_value = {'101': {'guest_name': 'Hóspede Teste'}}
        
        with self.app.test_client() as client:
            # Set session for the client
            with client.session_transaction() as sess:
                sess['user'] = self.user_id
                sess['role'] = 'admin'
                sess['permissions'] = ['admin', 'reception']

            # 2. Execute Pay Charge (POST)
            response = client.post(f'/reception/rooms', data={
                'action': 'pay_charge',
                'charge_id': charge_id,
                'payment_method': 'dinheiro',
                'customer_cpf_cnpj': '12345678900'
            }, follow_redirects=True)

            self.assertEqual(response.status_code, 200)

            time.sleep(0.1) # Give time for the async call to execute
            # 3. Verify Pool Content
            pool = FiscalPoolService._load_pool()
            self.assertEqual(len(pool), 1)
            self.assertEqual(pool[0]['origin'], 'reception')
            self.assertEqual(pool[0]['original_id'], charge_id)
            self.assertEqual(pool[0]['status'], 'pending')
            entry_id = pool[0]['id']

            # 4. Admin: Emit Invoice
            with patch('fiscal_service.emit_invoice') as mock_emit, \
                 patch('fiscal_service.load_fiscal_settings') as mock_load_settings, \
                 patch('fiscal_service.get_fiscal_integration') as mock_get_integration:
                mock_emit.return_value = {'success': True, 'data': {'id': 'FISCAL_UUID_456'}}
                mock_load_settings.return_value = {}
                mock_get_integration.return_value = {'cnpj_emitente': '00000000000000'}
                
                response_emit = client.post('/admin/fiscal/pool/action', json={
                    'id': entry_id,
                    'action': 'emit'
                })

                self.assertEqual(response_emit.status_code, 200)
                data = json.loads(response_emit.data)
                self.assertTrue(data['success'])

                pool_updated = FiscalPoolService._load_pool()
                self.assertEqual(pool_updated[0]['status'], 'emitted')

if __name__ == '__main__':
    unittest.main()
