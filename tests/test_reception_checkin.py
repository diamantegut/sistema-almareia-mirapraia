import unittest
import json
import os
import re
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services import data_service

# Mock data paths
TEST_DATA_DIR = r'tests\test_data_checkin_fix'

class TestReceptionCheckinFix(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
    def setUp(self):
        # Ensure directory exists
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)

        # Patch data paths
        self.original_occupancy = data_service.ROOM_OCCUPANCY_FILE
        self.original_cleaning = data_service.CLEANING_STATUS_FILE
        
        # Define test file paths
        self.test_occupancy = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        self.test_cleaning = os.path.join(TEST_DATA_DIR, 'cleaning_status.json')

        # Apply patches
        data_service.ROOM_OCCUPANCY_FILE = self.test_occupancy
        data_service.CLEANING_STATUS_FILE = self.test_cleaning
        
        # Reset data
        with open(self.test_occupancy, 'w') as f: json.dump({}, f)
        # Set room 101 as inspected (ready for check-in)
        with open(self.test_cleaning, 'w') as f: 
            json.dump({'101': {'status': 'inspected', 'last_cleaned': '2025-01-01'}}, f)
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'admin']
            sess['department'] = 'Recepção'

    def tearDown(self):
        # Restore paths
        data_service.ROOM_OCCUPANCY_FILE = self.original_occupancy
        data_service.CLEANING_STATUS_FILE = self.original_cleaning
        
        # Clean up
        if os.path.exists(TEST_DATA_DIR):
            import shutil
            shutil.rmtree(TEST_DATA_DIR)

    def test_reception_rooms_page_loads_and_contains_checkin_js(self):
        """Test that /reception/rooms loads and contains check-in JS structure."""
        response = self.client.get('/reception/rooms')
        self.assertEqual(response.status_code, 200)
        
        html = response.data.decode('utf-8')
        
        self.assertIn('function openCheckinModal(room)', html)
        self.assertIn("document.getElementById('checkin_room_select').value = room;", html)
        self.assertIn("var modal = new bootstrap.Modal(document.getElementById('checkinModal'));", html)
        self.assertIn('modal.show();', html)

    def test_checkin_submission(self):
        """Test the backend processing of a check-in."""
        data = {
            'room_number': '101',
            'guest_name': 'Test Guest',
            'doc_id': '123456789',
            'checkin_date': datetime.now().strftime('%Y-%m-%d'),
            'checkout_date': (datetime.now()).strftime('%Y-%m-%d'),
            'num_adults': '1'
        }

        with patch('app.blueprints.reception.routes.load_room_occupancy', return_value={}), \
             patch('app.blueprints.reception.routes.save_room_occupancy') as mock_save_occupancy, \
             patch('app.blueprints.reception.routes.load_table_orders', return_value={}), \
             patch('app.blueprints.reception.routes.save_table_orders'):
            response = self.client.post('/reception/checkin', data=data, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_save_occupancy.called)
            saved_occupancy = mock_save_occupancy.call_args[0][0]
            self.assertIn('101', saved_occupancy)
            self.assertEqual(saved_occupancy['101']['guest_name'], 'Test Guest')
        # Occupancy dictionary does not have a 'status' field, presence implies occupancy
        # self.assertEqual(occupancy['101']['status'], 'occupied')

if __name__ == '__main__':
    unittest.main()
