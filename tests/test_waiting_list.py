import unittest
import os
import json
import shutil
from datetime import datetime
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import waiting_list_service

class TestWaitingList(unittest.TestCase):
    def setUp(self):
        # Use a temporary file for testing
        self.original_file = waiting_list_service.WAITING_LIST_FILE
        self.test_file = 'data/waiting_list_test.json'
        waiting_list_service.WAITING_LIST_FILE = self.test_file
        
        # Ensure clean state
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
            
    def tearDown(self):
        # Restore original file path
        waiting_list_service.WAITING_LIST_FILE = self.original_file
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_add_customer(self):
        # Test adding a customer
        result, error = waiting_list_service.add_customer("John Doe", "11999999999", 4)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(result['entry']['name'], "John Doe")
        self.assertEqual(result['position'], 1)
        
        # Add another
        result2, error2 = waiting_list_service.add_customer("Jane Doe", "11888888888", 2)
        self.assertIsNone(error2)
        self.assertEqual(result2['position'], 2)
        
    def test_queue_closed(self):
        # Close queue
        waiting_list_service.update_settings({'is_open': False})
        
        result, error = waiting_list_service.add_customer("Test", "111", 2)
        self.assertIsNotNone(error)
        self.assertIn("fechada", error)
        
    def test_status_update(self):
        # Add customer
        result, _ = waiting_list_service.add_customer("Status Test", "11999999999", 2)
        cust_id = result['entry']['id']
        
        # Update status
        success = waiting_list_service.update_customer_status(cust_id, 'seated')
        self.assertTrue(success)
        
        # Verify
        data = waiting_list_service.load_waiting_data()
        item = next(x for x in data['queue'] if x['id'] == cust_id)
        self.assertEqual(item['status'], 'seated')
        
    def test_metrics(self):
        # Add customer
        result, _ = waiting_list_service.add_customer("Metrics Test", "11999999999", 2)
        
        metrics = waiting_list_service.get_queue_metrics()
        self.assertEqual(metrics['active_count'], 1)

if __name__ == '__main__':
    unittest.main()
