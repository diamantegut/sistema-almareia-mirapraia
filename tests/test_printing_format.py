
import unittest
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printing_service import format_bill

class TestBillHeader(unittest.TestCase):
    def test_bill_header_guest_format(self):
        # Mock data
        table_id = "101"
        items = [{'name': 'Coke', 'qty': 1, 'price': 5.0}]
        subtotal = 5.0
        service_fee = 0.5
        total = 5.5
        waiter_name = "John"
        guest_name = "Angelo Diamante"
        room_number = "101"

        # Call format_bill
        output_bytes = format_bill(table_id, items, subtotal, service_fee, total, waiter_name, guest_name, room_number)
        
        # Decode for checking (cp850 is used in the function)
        output_str = output_bytes.decode('cp850')
        
        # Check for the specific format with accent
        expected_line = "Hóspede: Angelo Diamante | Quarto: 101"
        
        found = False
        for line in output_str.split('\n'):
            if "Quarto:" in line:
                if expected_line in line:
                    found = True
        
        self.assertTrue(found, f"Expected '{expected_line}' not found in output.")

if __name__ == '__main__':
    unittest.main()
