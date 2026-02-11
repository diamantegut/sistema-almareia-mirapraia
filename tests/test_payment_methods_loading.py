
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestPaymentMethodsLoading(unittest.TestCase):
    
    @patch('app.blueprints.restaurant.routes.render_template')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.load_payment_methods')
    @patch('app.blueprints.restaurant.routes.load_room_occupancy')
    @patch('app.blueprints.restaurant.routes.load_complements')
    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_flavor_groups')
    @patch('app.blueprints.restaurant.routes.load_observations')
    @patch('app.blueprints.restaurant.routes.load_settings')
    @patch('app.blueprints.restaurant.routes.get_current_cashier')
    @patch('app.utils.decorators.login_required', lambda x: x) # Bypass login_required
    def test_payment_methods_passed_to_template(self, mock_get_cashier, mock_settings, mock_obs, mock_flavors, mock_menu, mock_users, mock_comps, mock_occupancy, mock_payment_methods, mock_load_orders, mock_render):
        # Setup
        from app.blueprints.restaurant.routes import restaurant_table_order
        
        # Mocks
        mock_load_orders.return_value = {"10": {"items": [], "total": 0}}
        mock_payment_methods.return_value = [{"id": "credit", "name": "Crédito"}]
        mock_get_cashier.return_value = {"status": "open"}
        mock_settings.return_value = {}
        
        # Call function (we need to mock request context or pass args if possible, 
        # but restaurant_table_order expects request.args/form. 
        # Easier to use test_client if we had app context, but unit testing logic here is faster with mocks if we can bypass request)
        
        # Since restaurant_table_order uses `request` and `session`, we need a request context.
        from flask import Flask
        app = Flask(__name__)
        app.secret_key = 'test'
        
        with app.test_request_context('/restaurant/table/10'):
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    
                # We can't easily call the route function directly without setting up all the Flask globals.
                # However, since we are patching the internal calls, we can try invoking it if we import it.
                
                # Re-import inside context to ensure decorators don't block us? 
                # Actually decorators like login_required might block if not mocked or session set.
                # We set session above.
                
                restaurant_table_order('10')
                
                # Assert
                args, kwargs = mock_render.call_args
                context_payment_methods = kwargs.get('payment_methods')
                
                if context_payment_methods is None:
                    print("\nFAIL: payment_methods not found in render_template arguments")
                else:
                    print(f"\nSUCCESS: Found {len(context_payment_methods)} payment methods in context")
                
                self.assertIsNotNone(context_payment_methods, "payment_methods should be passed to template")
                self.assertEqual(len(context_payment_methods), 1)
                self.assertEqual(context_payment_methods[0]['name'], 'Crédito')

if __name__ == '__main__':
    unittest.main()
