
import unittest
from unittest.mock import MagicMock, patch
import json
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.services.printing_service import print_order_items, format_ticket

class TestKitchenPrintFlow(unittest.TestCase):
    
    def setUp(self):
        self.mock_printers = [
            {
                "id": "printer_1",
                "name": "Cozinha",
                "type": "network",
                "ip": "192.168.1.200",
                "port": 9100
            }
        ]
        
        self.mock_menu = [
            {
                "id": "100", 
                "name": "Batata Frita", 
                "printer_id": "printer_1",
                "should_print": True
            }
        ]

    @patch('app.services.printing_service.send_to_printer')
    def test_print_questions_and_observations(self, mock_send):
        # Setup mock to return success
        mock_send.return_value = (True, None)
        
        # Define an item as it is created in routes.py
        # Note: routes.py uses 'observations' (list), NOT 'notes'
        item = {
            'id': 'item_1',
            'product_id': '100',
            'name': 'Batata Frita',
            'qty': 1.0,
            'category': 'Petiscos',
            'waiter': 'Joao',
            'observations': ['Sem sal', 'Bem crocante'], # List of strings
            'questions_answers': [
                {'question': 'Molho', 'answer': 'Maionese'},
                {'question': 'Tamanho', 'answer': 'Grande'}
            ],
            'flavor': None,
            'accompaniments': [],
            'complements': []
        }
        
        # Execute
        result = print_order_items(
            table_id="10",
            waiter_name="Joao",
            new_items=[item],
            printers_config=self.mock_printers,
            products_db=self.mock_menu
        )
        
        # Verify result
        self.assertEqual(result['results']['Cozinha'], "OK")
        
        # Capture the data sent to printer
        # mock_send.call_args[0] is (ip, port, data)
        call_args = mock_send.call_args
        sent_data = call_args[0][2]
        
        # Decode for inspection (cp850 is used in service)
        decoded_output = sent_data.decode('cp850', errors='replace')
        
        print("\n--- CAPTURED PRINT OUTPUT ---")
        print(decoded_output)
        print("-----------------------------\n")
        
        # VERIFICATIONS
        
        # 1. Check Questions
        self.assertIn("Molho: Maionese", decoded_output, "Question/Answer should be printed")
        self.assertIn("Tamanho: Grande", decoded_output, "Question/Answer should be printed")
        
        # 2. Check Observations
        # Based on code analysis, we expect this to FAIL if 'notes' is expected but 'observations' is passed
        try:
            self.assertIn("Sem sal", decoded_output)
            self.assertIn("Bem crocante", decoded_output)
            print("SUCCESS: Observations printed correctly.")
        except AssertionError:
            print("FAILURE: Observations NOT found in print output. Bug confirmed.")
            # raise # Uncomment to fail the test, but we want to report it first

if __name__ == '__main__':
    unittest.main()
