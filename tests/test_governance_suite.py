import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestGovernance(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.secret_key = 'test_secret'
        self.client = self.app.test_client()
        
        # Mock Data
        self.mock_occupancy = {
            '22': {'checkin': '20/01/2026', 'checkout': '25/01/2026', 'guest_name': 'João Silva', 'num_adults': 2}
        }
        
        self.mock_cleaning_status = {
            '22': {'status': 'dirty', 'maid': '', 'start_time': ''}
        }
        
        self.mock_menu_items = [
            {'id': '1', 'name': 'Água', 'price': 5.0, 'category': 'Frigobar'},
            {'id': '2', 'name': 'Coca Cola', 'price': 7.0, 'category': 'Frigobar'},
            {'id': '3', 'name': 'Prato', 'price': 20.0, 'category': 'Cozinha'}
        ]

    @patch('app.load_room_occupancy')
    @patch('app.load_cleaning_status')
    @patch('app.load_menu_items')
    @patch('app.load_cleaning_logs')
    def test_dashboard_access(self, mock_logs, mock_menu, mock_status, mock_occ):
        """Unit Test: Verify Dashboard Access"""
        mock_occ.return_value = self.mock_occupancy
        mock_status.return_value = self.mock_cleaning_status
        mock_menu.return_value = self.mock_menu_items
        mock_logs.return_value = []
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'gov_user'
            sess['role'] = 'admin' # Admin has access
            
        response = self.client.get('/governance/rooms')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Controle de Quartos', response.data)
        self.assertIn(b'22', response.data)
        
        # Check if Frigobar items are loaded (water, coca)
        self.assertIn(b'Coca Cola', response.data)

    @patch('app.load_room_occupancy')
    @patch('app.load_cleaning_status')
    @patch('app.save_cleaning_status')
    @patch('app.log_action')
    def test_start_cleaning(self, mock_log, mock_save, mock_status, mock_occ):
        """Unit Test: Start Cleaning Action"""
        mock_occ.return_value = self.mock_occupancy
        mock_status.return_value = self.mock_cleaning_status
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Maria'
            sess['role'] = 'admin'
            
        response = self.client.post('/governance/rooms', data={
            'action': 'start_cleaning',
            'room_number': '22'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Limpeza iniciada', response.data)
        
        # Verify Save was called with updated status
        args, _ = mock_save.call_args
        saved_status = args[0]
        self.assertEqual(saved_status['22']['status'], 'in_progress')
        self.assertEqual(saved_status['22']['maid'], 'Maria')

    @patch('app.load_room_occupancy')
    @patch('app.load_cleaning_status')
    @patch('app.save_cleaning_status')
    @patch('app.save_cleaning_log')
    @patch('app.load_menu_items')
    @patch('app.load_cleaning_logs')
    def test_finish_cleaning(self, mock_logs, mock_menu, mock_save_log, mock_save_status, mock_load_status, mock_occ):
        """Unit Test: Finish Cleaning Action"""
        # Setup: Room 22 is in progress
        current_status = self.mock_cleaning_status.copy()
        started_at = datetime.now() - timedelta(minutes=2)
        current_status['22'] = {
            'status': 'in_progress',
            'previous_status': 'dirty',
            'maid': 'Maria',
            'start_time': started_at.strftime('%d/%m/%Y %H:%M:%S'),
            'last_update': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        mock_load_status.return_value = current_status
        mock_occ.return_value = self.mock_occupancy
        mock_menu.return_value = self.mock_menu_items
        mock_logs.return_value = []
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Maria'
            sess['role'] = 'admin'
            
        response = self.client.post('/governance/rooms', data={
            'action': 'finish_cleaning',
            'room_number': '22',
            'redirect_minibar': 'false'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Limpeza finalizada', response.data)
        
        # Verify Status Update
        args, _ = mock_save_status.call_args
        saved_status = args[0]
        self.assertEqual(saved_status['22']['status'], 'inspected') # Normal flow -> inspected
        
        # Verify Log Saved
        self.assertTrue(mock_save_log.called)

    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_menu_items')
    @patch('app.load_room_occupancy')
    @patch('app.log_action')
    def test_launch_frigobar_success(self, mock_log, mock_occ, mock_menu, mock_save_charges, mock_load_charges):
        """Unit Test: Launch Frigobar Consumption"""
        mock_load_charges.return_value = []
        mock_menu.return_value = self.mock_menu_items
        mock_occ.return_value = self.mock_occupancy
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Maria'
            
        payload = {
            'room_number': '22',
            'items': [
                {'id': '1', 'qty': 2}, # 2x Água (5.0) = 10.0
                {'id': '2', 'qty': 1}  # 1x Coke (7.0) = 7.0
            ]
        }
        
        response = self.client.post('/governance/launch_frigobar', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify Order Creation
        args, _ = mock_save_charges.call_args
        saved_charges = args[0]
        self.assertEqual(len(saved_charges), 1)
        charge = saved_charges[0]
        self.assertEqual(charge['room_number'], '22')
        self.assertEqual(charge['total'], 17.0)
        self.assertEqual(len(charge['items']), 2)
        
        # Verify Log
        self.assertTrue(mock_log.called)

    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.load_menu_items')
    @patch('app.load_room_occupancy')
    def test_launch_frigobar_checkout_room(self, mock_occ, mock_menu, mock_save_charges, mock_load_charges):
        """Scenario Test: Launch Frigobar for Checkout Room (Not in Occupancy)"""
        mock_load_charges.return_value = []
        mock_menu.return_value = self.mock_menu_items
        mock_occ.return_value = self.mock_occupancy # 23 not here
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'gov_user'
            sess['role'] = 'admin'
        
        payload = {
            'room_number': '23', # Checked out room
            'items': [{'id': '1', 'qty': 1}]
        }
        
        response = self.client.post('/governance/launch_frigobar', 
                                  data=json.dumps(payload),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify charge created for the room (occupancy validation is not required here)
        args, _ = mock_save_charges.call_args
        saved_charges = args[0]
        self.assertEqual(len(saved_charges), 1)
        self.assertEqual(saved_charges[0]['room_number'], '23')
        self.assertEqual(saved_charges[0]['total'], 5.0)

    @patch('app.load_cleaning_status')
    @patch('app.save_cleaning_status')
    @patch('app.save_cleaning_log')
    @patch('app.load_room_occupancy')
    @patch('app.load_menu_items')
    @patch('app.load_cleaning_logs')
    @patch('app.load_room_charges')
    @patch('app.save_room_charges')
    @patch('app.log_action')
    def test_integration_full_flow(self, mock_log_action, mock_save_charges, mock_load_charges, 
                                 mock_logs, mock_menu, mock_occ, mock_save_log, mock_save_status, mock_load_status):
        """Integration Test: Start Cleaning -> Launch Frigobar -> Finish Cleaning"""
        
        # 1. Start Cleaning
        mock_load_status.return_value = self.mock_cleaning_status.copy()
        mock_occ.return_value = self.mock_occupancy
        mock_menu.return_value = self.mock_menu_items
        mock_logs.return_value = []
        mock_load_charges.return_value = []
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'IntegrationMaid'
            sess['role'] = 'admin'
            
        self.client.post('/governance/rooms', data={'action': 'start_cleaning', 'room_number': '22'})
        
        # Simulate state update in DB (mock dict)
        current_status = self.mock_cleaning_status.copy()
        started_at = datetime.now() - timedelta(minutes=2)
        current_status['22'] = {
            'status': 'in_progress',
            'previous_status': 'dirty',
            'maid': 'IntegrationMaid',
            'start_time': started_at.strftime('%d/%m/%Y %H:%M:%S'),
            'last_update': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        mock_load_status.return_value = current_status
        
        # 2. Launch Frigobar
        payload = {'room_number': '22', 'items': [{'id': '1', 'qty': 1}]}
        self.client.post('/governance/launch_frigobar', 
                        data=json.dumps(payload),
                        content_type='application/json')
                        
        # Verify charge saved
        self.assertTrue(mock_save_charges.called)
        
        # 3. Finish Cleaning
        self.client.post('/governance/rooms', data={
            'action': 'finish_cleaning', 
            'room_number': '22',
            'redirect_minibar': 'false'
        })
        
        # Verify Status Saved as Inspected
        args, _ = mock_save_status.call_args
        saved_status = args[0]
        self.assertEqual(saved_status['22']['status'], 'inspected')
        self.assertEqual(saved_status['22']['last_cleaned_by'], 'IntegrationMaid')

if __name__ == '__main__':
    unittest.main()
