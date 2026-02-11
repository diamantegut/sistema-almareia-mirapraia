
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cashier_service import CashierService

class TestCashierSyncFix(unittest.TestCase):
    
    @patch('app.services.cashier_service.CashierService._load_sessions')
    def test_bidirectional_mapping_restaurant(self, mock_load_sessions):
        # Case 1: Session is 'restaurant', searching for 'restaurant_service'
        mock_session_1 = {
            'id': 'sess_1',
            'status': 'open',
            'type': 'restaurant', # Saved as 'restaurant'
            'user': 'admin'
        }
        mock_load_sessions.return_value = [mock_session_1]
        
        # Search using 'restaurant_service' (what routes.py used to do)
        result = CashierService.get_active_session('restaurant_service')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'sess_1')
        print("Success: Found 'restaurant' session when searching for 'restaurant_service'")

        # Case 2: Session is 'restaurant_service', searching for 'restaurant'
        mock_session_2 = {
            'id': 'sess_2',
            'status': 'open',
            'type': 'restaurant_service', # Saved as 'restaurant_service'
            'user': 'admin'
        }
        mock_load_sessions.return_value = [mock_session_2]
        
        # Search using 'restaurant'
        result = CashierService.get_active_session('restaurant')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'sess_2')
        print("Success: Found 'restaurant_service' session when searching for 'restaurant'")

    @patch('app.services.cashier_service.CashierService._load_sessions')
    def test_bidirectional_mapping_reception(self, mock_load_sessions):
        # Case 3: Session is 'guest_consumption', searching for 'reception_room_billing'
        mock_session_3 = {
            'id': 'sess_3',
            'status': 'open',
            'type': 'guest_consumption',
            'user': 'recepcao'
        }
        mock_load_sessions.return_value = [mock_session_3]
        
        result = CashierService.get_active_session('reception_room_billing')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'sess_3')
        print("Success: Found 'guest_consumption' session when searching for 'reception_room_billing'")

if __name__ == '__main__':
    unittest.main()
