import unittest
from unittest.mock import patch, MagicMock
from app import app
import json
from datetime import datetime

class TestGuestManagement(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        
        # Setup session
        with self.app.session_transaction() as sess:
            sess['user'] = 'TestUser'
            sess['role'] = 'recepcao'
            sess['permissions'] = ['recepcao']

    @patch('app.load_room_occupancy')
    @patch('app.save_room_occupancy')
    @patch('app.load_table_orders')
    @patch('app.save_table_orders')
    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_cleaning_status')
    @patch('app.save_cleaning_status')
    @patch('app.log_action')
    def test_transfer_guest_success(self, mock_log, mock_save_clean, mock_load_clean, 
                                  mock_save_charges, mock_load_charges,
                                  mock_save_orders, mock_load_orders,
                                  mock_save_occ, mock_load_occ):
        
        # Setup Data
        occupancy = {
            '101': {'guest_name': 'John Doe', 'checkin': '01/01/2026'}
        }
        mock_load_occ.return_value = occupancy
        
        orders = {
            '101': {'items': [], 'total': 50, 'room_number': '101'}
        }
        mock_load_orders.return_value = orders
        
        charges = [
            {'id': 'c1', 'room_number': '101', 'status': 'pending', 'total': 20}
        ]
        mock_load_charges.return_value = charges
        
        cleaning = {}
        mock_load_clean.return_value = cleaning
        
        # Action: Transfer 101 -> 102
        response = self.app.post('/reception/rooms', data={
            'action': 'transfer_guest',
            'old_room': '101',
            'new_room': '102',
            'reason': 'AC Broken'
        }, follow_redirects=True)
        
        # Verify Response
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'transferido com sucesso', response.data)
        
        # Verify Occupancy Transfer
        self.assertNotIn('101', occupancy)
        self.assertIn('102', occupancy)
        self.assertEqual(occupancy['102']['guest_name'], 'John Doe')
        mock_save_occ.assert_called()
        
        # Verify Orders Transfer
        self.assertNotIn('101', orders)
        self.assertIn('102', orders)
        self.assertEqual(orders['102']['room_number'], '102')
        mock_save_orders.assert_called()
        
        # Verify Charges Transfer
        self.assertEqual(charges[0]['room_number'], '102')
        mock_save_charges.assert_called()
        
        # Verify Cleaning Status (Old room dirty)
        self.assertIn('101', cleaning)
        self.assertEqual(cleaning['101']['status'], 'dirty')
        mock_save_clean.assert_called()

    @patch('app.load_room_occupancy')
    @patch('app.save_room_occupancy')
    @patch('app.log_action')
    def test_edit_guest_name_success(self, mock_log, mock_save_occ, mock_load_occ):
        # Setup Data
        occupancy = {
            '101': {'guest_name': 'John Doe', 'checkin': '01/01/2026'}
        }
        mock_load_occ.return_value = occupancy
        
        # Action: Edit Name
        response = self.app.post('/reception/rooms', data={
            'action': 'edit_guest_name',
            'room_number': '101',
            'new_name': 'Jane Doe'
        }, follow_redirects=True)
        
        # Verify Response
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'atualizado com sucesso', response.data)
        
        # Verify Update
        self.assertEqual(occupancy['101']['guest_name'], 'Jane Doe')
        mock_save_occ.assert_called()

if __name__ == '__main__':
    unittest.main()
