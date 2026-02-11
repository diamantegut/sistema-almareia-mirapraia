
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestReceptionCheckout(unittest.TestCase):
    
    @patch('app.blueprints.reception.routes.render_template')
    @patch('app.blueprints.reception.routes.load_payment_methods')
    @patch('app.blueprints.reception.routes.load_cashier_sessions')
    @patch('app.blueprints.reception.routes.load_room_charges')
    @patch('app.blueprints.reception.routes.load_room_occupancy')
    @patch('app.blueprints.reception.routes.load_menu_items')
    @patch('app.blueprints.reception.routes.load_printers')
    @patch('app.blueprints.reception.routes.load_printer_settings')
    @patch('app.utils.decorators.login_required', lambda x: x) # Bypass login_required
    def test_payment_methods_available_reception(self, mock_settings, mock_printers, mock_menu, mock_occupancy, mock_charges, mock_sessions, mock_payment_methods, mock_render):
        # Setup
        from app.blueprints.reception.routes import reception_cashier
        from flask import Flask, session
        
        app = Flask(__name__)
        app.secret_key = 'test'
        
        # Mocks
        mock_payment_methods.return_value = [
            {"id": "credit", "name": "Crédito", "available_in": ["reception"]},
            {"id": "debit", "name": "Débito", "available_in": ["reception"]},
            {"id": "cash", "name": "Dinheiro", "available_in": ["restaurant", "reception"]},
            {"id": "meal_voucher", "name": "Vale Refeição", "available_in": ["restaurant"]} # Should be filtered out if strict, but let's check logic
        ]
        
        mock_sessions.return_value = [{"id": "SESS_1", "status": "open", "type": "guest_consumption", "transactions": []}]
        mock_charges.return_value = []
        mock_occupancy.return_value = {}
        mock_menu.return_value = []
        mock_printers.return_value = []
        mock_settings.return_value = {}

        with app.test_request_context('/reception/cashier'):
            # Set session directly in request context
            session['user'] = 'admin'
            session['role'] = 'admin'
            session['permissions'] = ['recepcao', 'principal']
            
            # Mock url_for to avoid build error
            with patch('flask.url_for', return_value='/'):
                # Call Route
                reception_cashier()
                
                # Assert
                args, kwargs = mock_render.call_args
                context_payment_methods = kwargs.get('payment_methods')
                
                self.assertIsNotNone(context_payment_methods, "Payment methods missing from reception context")
                
                # Verify Filtering
                method_ids = [m['id'] for m in context_payment_methods]
                self.assertIn('credit', method_ids)
                self.assertIn('debit', method_ids)
                self.assertIn('cash', method_ids)
                
                # Logic in route: 
                # payment_methods = [m for m in payment_methods if 'reception' in m.get('available_in', ['restaurant', 'reception'])]
                # So 'meal_voucher' (only restaurant) should be EXCLUDED
                self.assertNotIn('meal_voucher', method_ids)
                
                print(f"\nSUCCESS: Verified {len(context_payment_methods)} payment methods available in Reception Checkout.")

if __name__ == '__main__':
    unittest.main()
