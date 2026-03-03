import sys
import os
import unittest
import json
from flask import session

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services.data_service import load_payment_methods, save_payment_methods, PAYMENT_METHODS_FILE

class TestPaymentMethods(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        
        # Backup original file
        self.original_methods = load_payment_methods()
        
    def tearDown(self):
        # Restore original file
        save_payment_methods(self.original_methods)
        self.ctx.pop()

    def test_add_and_edit_payment_method(self):
        # 1. Add new method with Reservations checked
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        response = self.client.post('/payment-methods', data={
            'action': 'add',
            'name': 'Test Reservation Method',
            'available_restaurant': 'on',
            'available_reception': 'on',
            'available_reservas': 'on', # This is the field for 'Caixa Reservas'
            'is_fiscal': 'on',
            'fiscal_cnpj': '28952732000109'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify saved data
        methods = load_payment_methods()
        method = next((m for m in methods if m['name'] == 'Test Reservation Method'), None)
        self.assertIsNotNone(method)
        self.assertIn('reservations', method['available_in']) # Verify 'reservations' is saved
        self.assertTrue(method['is_fiscal'])
        self.assertEqual(method['fiscal_cnpj'], '28952732000109')
        
        method_id = method['id']
        print(f'Added method ID: {method_id}, Available in: {method['available_in']}')

        # 2. Edit method - Uncheck Reservations
        response = self.client.post('/payment-methods', data={
            'action': 'edit',
            'id': method_id,
            'name': 'Test Reservation Method Edited',
            'available_restaurant': 'on',
            'available_reception': 'on',
            # 'available_reservas': 'on', # Unchecked
            'is_fiscal': 'on',
            'fiscal_cnpj': '28952732000109'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        methods = load_payment_methods()
        method = next((m for m in methods if m['id'] == method_id), None)
        self.assertEqual(method['name'], 'Test Reservation Method Edited')
        self.assertNotIn('reservations', method['available_in']) # Should be removed
        print(f'Edited method (removed reservations): {method['available_in']}')

        # 3. Edit method - Check Reservations again
        response = self.client.post('/payment-methods', data={
            'action': 'edit',
            'id': method_id,
            'name': 'Test Reservation Method Edited 2',
            'available_restaurant': 'on',
            'available_reception': 'on',
            'available_reservas': 'on', # Checked again
            'is_fiscal': 'on',
            'fiscal_cnpj': '28952732000109'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        methods = load_payment_methods()
        method = next((m for m in methods if m['id'] == method_id), None)
        self.assertIn('reservations', method['available_in']) # Should be added back
        print(f'Edited method (added reservations): {method['available_in']}')

        # 4. Edit method - Uncheck ALL (Empty available_in)
        # This tests the data_service fix
        response = self.client.post('/payment-methods', data={
            'action': 'edit',
            'id': method_id,
            'name': 'Test Empty Method',
            # All unchecked
            'is_fiscal': 'off',
            'fiscal_cnpj': ''
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        methods = load_payment_methods()
        method = next((m for m in methods if m['id'] == method_id), None)
        self.assertIsNotNone(method, 'Method should still exist even with empty available_in')
        self.assertEqual(method['available_in'], [])
        print(f'Edited method (empty available_in): {method['available_in']}')

if __name__ == '__main__':
    unittest.main()
