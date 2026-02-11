import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printing_service import print_transfer_ticket, print_cashier_ticket

class TestPrinterFixes(unittest.TestCase):

    @patch('printing_service.send_to_printer')
    def test_transfer_ticket_bar_priority(self, mock_send):
        """Test that transfer ticket prioritizes Bar printer and includes signature."""
        
        printers = [
            {'name': 'Cozinha', 'ip': '1.1.1.1', 'port': 9100, 'type': 'network'},
            {'name': 'Bar', 'ip': '2.2.2.2', 'port': 9100, 'type': 'network'}
        ]
        
        print_transfer_ticket('10', '20', 'GarcomTest', printers)
        
        # Should call send_to_printer for Bar (2.2.2.2)
        # It might call for Cozinha too if my logic falls back, but my logic says:
        # if target_printers (Bar found), use it.
        
        # Verify calls
        called_ips = [args[0] for args, _ in mock_send.call_args_list]
        self.assertIn('2.2.2.2', called_ips)
        self.assertNotIn('1.1.1.1', called_ips) # Should be exclusive to Bar if found? 
        # My logic: target_printers = [Bar] -> if not empty -> use it. So Cozinha is skipped. Correct.
        
        # Verify content has signature
        call_args = mock_send.call_args[0]
        content = call_args[2]
        self.assertIn(b'Assinatura Responsavel', content)
        self.assertIn(b'*** TRANSFERENCIA ***', content)

    @patch('printing_service.send_to_printer')
    def test_transfer_ticket_fallback(self, mock_send):
        """Test fallback to Cozinha if Bar not found."""
        printers = [
            {'name': 'Cozinha', 'ip': '1.1.1.1', 'port': 9100, 'type': 'network'}
        ]
        
        print_transfer_ticket('10', '20', 'GarcomTest', printers)
        
        called_ips = [args[0] for args, _ in mock_send.call_args_list]
        self.assertIn('1.1.1.1', called_ips)
        
        # Content check
        call_args = mock_send.call_args[0]
        content = call_args[2]
        self.assertIn(b'Assinatura Responsavel', content)

    @patch('printing_service.send_to_printer')
    def test_cashier_ticket_signature(self, mock_send):
        """Test cashier ticket has signature for SANGRIA."""
        printer = {'name': 'Bar', 'ip': '2.2.2.2', 'port': 9100, 'type': 'network'}
        
        print_cashier_ticket(printer, "SANGRIA", 100.0, "User", "Test Reason")
        
        call_args = mock_send.call_args[0]
        content = call_args[2]
        self.assertIn(b'Assinatura Responsavel', content)
        self.assertIn(b'SANGRIA', content)
        self.assertIn(b'R$ 100.00', content)

if __name__ == '__main__':
    unittest.main()
