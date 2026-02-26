import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.printer_manager import load_printers, save_printers, load_printer_settings, save_printer_settings
from app.services.printing_service import format_room_number_str, get_printer_by_id, get_default_printer

class TestPrinterManager(unittest.TestCase):
    
    @patch('app.services.printer_manager.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='[{"id": "1", "name": "Test Printer"}]')
    def test_load_printers_valid(self, mock_file, mock_exists):
        mock_exists.return_value = True
        printers = load_printers()
        self.assertEqual(len(printers), 1)
        self.assertEqual(printers[0]['name'], 'Test Printer')

    @patch('app.services.printer_manager.os.path.exists')
    def test_load_printers_not_found(self, mock_exists):
        mock_exists.return_value = False
        printers = load_printers()
        self.assertEqual(printers, [])

    @patch('app.services.printer_manager.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='invalid json')
    def test_load_printers_invalid_json(self, mock_file, mock_exists):
        mock_exists.return_value = True
        printers = load_printers()
        self.assertEqual(printers, [])

    @patch('builtins.open', new_callable=mock_open)
    def test_save_printers(self, mock_file):
        data = [{'id': '1', 'name': 'New Printer'}]
        save_printers(data)
        mock_file.assert_called_once()
        handle = mock_file()
        # Verify write was called
        handle.write.assert_called()

    @patch('app.services.printer_manager.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"bill_printer_id": "123"}')
    def test_load_printer_settings_valid(self, mock_file, mock_exists):
        mock_exists.return_value = True
        settings = load_printer_settings()
        self.assertEqual(settings.get('bill_printer_id'), "123")

    @patch('app.services.printer_manager.os.path.exists')
    def test_load_printer_settings_default(self, mock_exists):
        mock_exists.return_value = False
        settings = load_printer_settings()
        self.assertIsNone(settings.get('bill_printer_id'))
        self.assertTrue(settings.get('frigobar_filter_enabled'))


class TestPrintingService(unittest.TestCase):
    
    def test_format_room_number_str(self):
        self.assertEqual(format_room_number_str(1), "01")
        self.assertEqual(format_room_number_str("1"), "01")
        self.assertEqual(format_room_number_str(10), "10")
        self.assertEqual(format_room_number_str("10"), "10")
        self.assertEqual(format_room_number_str("abc"), "abc")
        self.assertEqual(format_room_number_str(None), "")

    @patch('app.services.printing_service.load_printers')
    def test_get_printer_by_id(self, mock_load):
        mock_load.return_value = [{'id': '1', 'name': 'P1'}, {'id': '2', 'name': 'P2'}]
        p = get_printer_by_id('2')
        self.assertIsNotNone(p)
        self.assertEqual(p['name'], 'P2')
        
        p = get_printer_by_id('999')
        self.assertIsNone(p)

    @patch('app.services.printing_service.load_printer_settings')
    @patch('app.services.printing_service.get_printer_by_id')
    def test_get_default_printer(self, mock_get_by_id, mock_load_settings):
        mock_load_settings.return_value = {'kitchen_printer_id': '555'}
        mock_get_by_id.return_value = {'id': '555', 'name': 'Kitchen Printer'}
        
        p = get_default_printer('kitchen')
        mock_load_settings.assert_called_once()
        mock_get_by_id.assert_called_with('555')
        self.assertEqual(p['name'], 'Kitchen Printer')

    @patch('app.services.printing_service.socket.socket')
    def test_send_to_printer_success(self, mock_socket):
        from app.services.printing_service import send_to_printer
        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn
        
        success, error = send_to_printer('192.168.1.100', 9100, b'test data')
        
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch('app.services.printing_service.send_to_printer')
    @patch('app.services.printing_service.get_default_printer')
    def test_print_order_items_skip_no_print(self, mock_get_default, mock_send):
        from app.services.printing_service import print_order_items
        
        # Setup
        mock_send.return_value = (True, None)
        mock_get_default.return_value = None
        
        table_id = "10"
        waiter_name = "Waiter"
        
        # Two items: one normal, one with "Não Imprimir"
        new_items = [
            {'id': '1', 'name': 'Coke', 'qty': 1, 'observations': []},
            {'id': '2', 'name': 'Coffee', 'qty': 1, 'observations': ['Não Imprimir']}
        ]
        
        printers_config = [{'id': 'p1', 'name': 'Printer 1', 'ip': '1.2.3.4', 'port': 9100, 'type': 'network'}]
        
        products_db = [
            {'name': 'Coke', 'printer_id': 'p1', 'should_print': True},
            {'name': 'Coffee', 'printer_id': 'p1', 'should_print': True}
        ]
        
        # Execute
        result = print_order_items(table_id, waiter_name, new_items, printers_config, products_db)
        
        # Verify
        # Should only print Coke (id 1)
        self.assertIn('1', result['printed_ids'])
        self.assertNotIn('2', result['printed_ids'])
        
        # Verify send_to_printer called with data containing "Coke" but not "Coffee"
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        sent_data = args[2] # data is 3rd arg
        
        # Check bytes content
        self.assertIn(b'Coke', sent_data)
        self.assertNotIn(b'Coffee', sent_data)

if __name__ == '__main__':
    unittest.main()
