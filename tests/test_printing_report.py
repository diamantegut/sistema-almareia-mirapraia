import unittest
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printing_service import process_and_print_pending_bills

class TestPendingBillsReport(unittest.TestCase):
    def test_valid_input(self):
        pending_bills = [
            {
                "origin": {"client": "Test Client", "table": "1", "order_id": "100"},
                "products": [
                    {"name": "Burger", "qty": 2, "unit_price": 20.0, "subtotal": 40.0},
                    {"name": "Coke", "qty": 1, "unit_price": 5.0, "subtotal": 5.0}
                ]
            },
            {
                "origin": {"client": "Client 2", "table": "2", "order_id": "101"},
                "products": [
                    {"name": "Burger", "qty": 1, "unit_price": 20.0, "subtotal": 20.0}
                ]
            }
        ]
        
        result = process_and_print_pending_bills(pending_bills)
        
        self.assertEqual(result["summary"]["total_bills_count"], 2)
        self.assertEqual(result["summary"]["grand_total"], 65.0)
        
        # Check Product Totals
        self.assertEqual(result["summary"]["product_totals"]["Burger"], 3.0)
        self.assertEqual(result["summary"]["product_totals"]["Coke"], 1.0)
        
        # Check Processed Bills
        self.assertEqual(len(result["bills_processed"]), 2)
        self.assertEqual(result["bills_processed"][0]["total"], 45.0)

    def test_malformed_input(self):
        pending_bills = [
            {
                "origin": {}, # Missing details
                "products": [
                    {"name": "Item A", "qty": "invalid", "unit_price": 10, "subtotal": 0} # Invalid qty
                ]
            }
        ]
        
        result = process_and_print_pending_bills(pending_bills)
        # Should handle gracefully, qty treated as 0
        self.assertEqual(result["summary"]["total_bills_count"], 1)
        self.assertEqual(result["bills_processed"][0]["total"], 0.0) 

    def test_empty_input(self):
        result = process_and_print_pending_bills([])
        self.assertEqual(result["summary"]["total_bills_count"], 0)
        self.assertEqual(result["summary"]["grand_total"], 0)

if __name__ == '__main__':
    unittest.main()
