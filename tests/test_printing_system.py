import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.printing_service import (
    format_individual_bill_thermal, 
    print_individual_bills_thermal,
    get_default_printer
)

class TestPrintingSystem(unittest.TestCase):
    
    def setUp(self):
        self.sample_charges = [
            {
                'id': '123',
                'date': '10/02/2026',
                'total': 55.00,
                'items': [
                    {'name': 'Coca Cola', 'qty': 2, 'price': 5.00, 'total': 10.00},
                    {'name': 'Hamburguer', 'qty': 1, 'price': 40.00, 'total': 40.00}
                ],
                'service_fee': 5.00
            }
        ]
        
    def test_format_individual_bill_thermal(self):
        output = format_individual_bill_thermal(
            room_num='101',
            guest_name='João Silva',
            charges=self.sample_charges,
            total_amount=55.00
        )
        
        # Check for key elements in the output (byte string)
        # Note: encoding might replace non-ascii chars depending on implementation
        self.assertIn(b'HOTEL ALMAREIA', output)
        self.assertIn(b'EXTRATO DE CONSUMO', output)
        self.assertIn(b'Quarto: 101', output)
        
        # Check content presence
        self.assertIn(b'Coca Cola', output)
        self.assertIn(b'Hamburguer', output)
        self.assertIn(b'TOTAL: R$ 55.00', output)

    @patch('app.services.printing_service.get_printer_by_id')
    @patch('app.services.printing_service.send_to_printer')
    def test_print_individual_bills_network(self, mock_send, mock_get_printer):
        # Setup mock printer
        mock_get_printer.return_value = {
            'id': 'print1',
            'type': 'network',
            'ip': '192.168.1.100',
            'port': 9100
        }
        mock_send.return_value = (True, None)
        
        success, error = print_individual_bills_thermal(
            printer_id='print1',
            room_num='101',
            guest_name='Test Guest',
            charges=self.sample_charges,
            total_amount=55.00
        )
        
        self.assertTrue(success)
        mock_send.assert_called_once()
        
    @patch('app.services.printing_service.get_printer_by_id')
    @patch('app.services.printing_service.send_to_windows_printer')
    def test_print_individual_bills_windows(self, mock_send, mock_get_printer):
        # Setup mock printer
        mock_get_printer.return_value = {
            'id': 'print2',
            'type': 'windows',
            'windows_name': 'Reception_Printer'
        }
        mock_send.return_value = (True, None)
        
        success, error = print_individual_bills_thermal(
            printer_id='print2',
            room_num='102',
            guest_name='Test Guest',
            charges=self.sample_charges,
            total_amount=55.00
        )
        
        self.assertTrue(success)
        mock_send.assert_called_once()

    @patch('app.services.printing_service.load_printer_settings')
    @patch('app.services.printing_service.get_printer_by_id')
    def test_get_default_printer(self, mock_get_by_id, mock_load_settings):
        mock_load_settings.return_value = {
            'bill_printer_id': 'p1',
            'kitchen_printer_id': 'p2'
        }
        mock_get_by_id.side_effect = lambda pid: {'id': pid, 'name': f'Printer {pid}'} if pid else None
        
        p = get_default_printer('bill')
        self.assertEqual(p['id'], 'p1')
        
        p = get_default_printer('kitchen')
        self.assertEqual(p['id'], 'p2')

if __name__ == '__main__':
    unittest.main()