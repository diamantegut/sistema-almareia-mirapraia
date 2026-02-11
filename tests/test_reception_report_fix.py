
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

class TestReceptionReportFix(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        
    @patch('app.load_room_charges')
    @patch('app.load_printer_settings')
    @patch('app.load_printers')
    @patch('app.load_room_occupancy')
    @patch('app.process_and_print_pending_bills')
    @patch('app.load_users')
    def test_service_fee_inclusion(self, mock_load_users, mock_process, mock_occupancy, mock_printers, mock_settings, mock_charges):
        # Setup Mocks
        mock_load_users.return_value = {'test_user': {'password': '123', 'role': 'admin'}}
        mock_charges.return_value = [
            {
                "id": "CHARGE_1",
                "room_number": "02",
                "status": "pending",
                "items": [
                    {"name": "Item A", "qty": 1, "price": 100.0}
                ],
                "service_fee": 10.0,
                "total": 110.0
            }
        ]
        
        mock_printers.return_value = [{'id': 'p1', 'name': 'Printer 1', 'ip': '1.1.1.1'}]
        mock_settings.return_value = {}
        mock_occupancy.return_value = {'02': {'guest_name': 'Test Guest'}}
        
        mock_process.return_value = {
            "summary": {"total_bills_count": 1, "grand_total": 110.0},
            "errors": []
        }
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_user'
            sess['role'] = 'admin'
            
        # Call Endpoint
        response = self.client.post('/reception/print_pending_bills', 
                                  data=json.dumps({'printer_id': 'p1', 'room_number': '02'}),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify process_and_print_pending_bills was called with Service Fee
        args = mock_process.call_args[0][0] # First arg is formatted_bills
        products = args[0]['products']
        
        # Check if Service Fee is in products
        service_fee_item = next((p for p in products if p['name'] == "Taxa de Serviço (10%)"), None)
        self.assertIsNotNone(service_fee_item)
        self.assertEqual(service_fee_item['subtotal'], 10.0)
        
        # Check Item A
        item_a = next((p for p in products if p['name'] == "Item A"), None)
        self.assertIsNotNone(item_a)
        self.assertEqual(item_a['unit_price'], 100.0)

if __name__ == '__main__':
    unittest.main()
