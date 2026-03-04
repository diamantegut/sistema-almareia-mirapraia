import unittest
from unittest.mock import patch
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app

class TestReceptionCheckout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def test_payment_methods_available_reception(self):
        payment_methods = [
            {"id": "credit", "name": "Crédito", "available_in": ["reception"]},
            {"id": "debit", "name": "Débito", "available_in": ["reception"]},
            {"id": "cash", "name": "Dinheiro", "available_in": ["restaurant", "reception"]},
            {"id": "meal_voucher", "name": "Vale Refeição", "available_in": ["restaurant"]}
        ]
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'principal', 'admin']
            sess['department'] = 'Recepção'

        with patch('app.blueprints.reception.routes.load_payment_methods', return_value=payment_methods), \
             patch('app.load_payment_methods', return_value=payment_methods), \
             patch('app.blueprints.reception.routes.load_cashier_sessions', return_value=[{"id": "SESS_1", "status": "open", "type": "guest_consumption", "transactions": []}]), \
             patch('app.blueprints.reception.routes.load_room_charges', return_value=[]), \
             patch('app.blueprints.reception.routes.load_room_occupancy', return_value={}), \
             patch('app.blueprints.reception.routes.load_menu_items', return_value=[]), \
             patch('app.blueprints.reception.routes.load_printers', return_value=[]), \
             patch('app.blueprints.reception.routes.load_printer_settings', return_value={}), \
             patch('app.blueprints.reception.routes.render_template', return_value='ok') as mock_render:
            response = self.client.get('/reception/cashier')
        self.assertEqual(response.status_code, 200)
        _, kwargs = mock_render.call_args
        context_payment_methods = kwargs.get('payment_methods')
        self.assertIsNotNone(context_payment_methods)
        method_ids = [m['id'] for m in context_payment_methods]
        self.assertIn('credit', method_ids)
        self.assertIn('debit', method_ids)
        self.assertIn('cash', method_ids)
        self.assertNotIn('meal_voucher', method_ids)

if __name__ == '__main__':
    unittest.main()
