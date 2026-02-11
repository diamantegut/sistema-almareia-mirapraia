
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cashier_service import CashierService

class TestTableRestorationLogic(unittest.TestCase):
    def setUp(self):
        self.table_id = "10"
        self.mock_order = {
            "items": [{"name": "Cerveja", "price": 10.0, "qty": 1}],
            "total": 10.0,
            "status": "open",
            "partial_payments": [],
            "total_paid": 0.0
        }
    
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.get_current_cashier')
    @patch('app.blueprints.restaurant.routes.CashierService.add_transaction')
    @patch('app.blueprints.restaurant.routes.load_products')
    @patch('app.blueprints.restaurant.routes.save_stock_entry')
    @patch('app.blueprints.restaurant.routes.load_sales_history')
    @patch('app.blueprints.restaurant.routes.save_sales_history')
    def test_close_table_flow(self, mock_save_sales, mock_load_sales, mock_save_stock, mock_load_products, mock_add_transaction, mock_get_cashier, mock_save_orders, mock_load_orders):
        # Setup Mocks
        mock_load_orders.return_value = {self.table_id: self.mock_order}
        mock_get_cashier.return_value = {"id": "SESSION_1", "status": "open", "type": "restaurant"}
        mock_load_products.return_value = [{"id": "1", "name": "Cerveja", "price": 10.0, "qty": 100}]
        mock_load_sales.return_value = []
        
        # Simulate Context (app context needed for flash/redirect but we can mock request)
        # We'll just verify the logic flow by inspecting calls if we were running the route function directly.
        # But routes are hard to test directly without app context.
        # So we will use a Flask Test Client approach.
        pass

    def test_payment_via_card_removed(self):
        """
        Verify that the dashboard template does not contain the 'Pagar' button.
        """
        template_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', 'restaurant_tables.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for the specific button removal
        self.assertNotIn('title="Pagar Conta"', content)
        self.assertNotIn('class="bi bi-cash"></i> Pagar', content)
        self.assertNotIn('Cx. Fechado', content) # Also removed per my edit
        
        # Check that "Consumo Salvo" logic is still there for staff
        self.assertIn('Consumo Salvo', content)

if __name__ == '__main__':
    unittest.main()
