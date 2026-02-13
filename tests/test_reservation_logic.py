
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.services.reservation_service import ReservationService

class TestReservationLogic(unittest.TestCase):

    def setUp(self):
        self.service = ReservationService()
        
        # Mock dependencies
        self.service.get_reservation_by_id = MagicMock()
        self.service.get_manual_room = MagicMock()
        self.service.get_manual_dates = MagicMock()
        
        # Mock Data Service load_room_occupancy
        self.patcher_occupancy = patch('app.services.data_service.load_room_occupancy')
        self.mock_load_occupancy = self.patcher_occupancy.start()
        self.mock_load_occupancy.return_value = {} # Default empty occupancy
        
        # Mock Check Collision (we want to test logic inside calculate, but check_collision calls other things)
        # Actually, let's let check_collision run but mock its dependencies (occupancy and get_february_reservations)
        
        self.service.get_february_reservations = MagicMock()
        self.service.get_february_reservations.return_value = []

    def tearDown(self):
        self.patcher_occupancy.stop()

    def test_calculate_update_simple_resize(self):
        # Scenario: Resize reservation from 2 days to 3 days
        res_id = "123"
        self.service.get_reservation_by_id.return_value = {
            'id': res_id,
            'checkin': '01/02/2026',
            'checkout': '03/02/2026', # 2 days
            'amount_val': 200.0,
            'allocated_room': '10'
        }
        
        # Current: 2 days, 200.0 total -> 100.0/day
        # New: 01/02 to 04/02 (3 days) -> Should be 300.0 total
        
        result = self.service.calculate_reservation_update(
            res_id, 
            new_room='10', 
            new_checkin='01/02/2026', 
            new_checkout='04/02/2026'
        )
        
        self.assertTrue(result['valid'])
        self.assertEqual(result['old_total'], 200.0)
        self.assertEqual(result['new_total'], 300.0)
        self.assertEqual(result['days'], 3)
        self.assertEqual(result['diff'], 100.0)

    def test_calculate_update_conflict_occupancy(self):
        # Scenario: Move to a room that is occupied by a checked-in guest
        res_id = "123"
        self.service.get_reservation_by_id.return_value = {
            'id': res_id,
            'checkin': '05/02/2026',
            'checkout': '06/02/2026',
            'amount_val': 100.0,
            'allocated_room': '10'
        }
        
        # Occupancy: Room 11 is occupied from 01/02 to 10/02
        self.mock_load_occupancy.return_value = {
            "11": {
                "checkin": "01/02/2026",
                "checkout": "10/02/2026",
                "guest_name": "Occupant",
                "status": "occupied"
            }
        }
        
        # Try to move to Room 11 for 05/02-06/02
        result = self.service.calculate_reservation_update(
            res_id, 
            new_room='11', 
            new_checkin='05/02/2026', 
            new_checkout='06/02/2026'
        )
        
        self.assertFalse(result['valid'])
        self.assertIn("ocupado por Occupant", result['conflict_message'])

    def test_calculate_update_conflict_reservation(self):
        # Scenario: Move to a room reserved by another future reservation
        res_id = "123"
        self.service.get_reservation_by_id.return_value = {
            'id': res_id,
            'checkin': '01/02/2026',
            'checkout': '02/02/2026',
            'amount_val': 100.0,
            'allocated_room': '10'
        }
        
        # Existing reservations: One in Room 12 from 05/02 to 07/02
        # We need to mock get_february_reservations AND get_manual_room to simulate allocation
        other_res = {
            'id': '456',
            'guest_name': 'Other Guest',
            'checkin': '05/02/2026',
            'checkout': '07/02/2026'
        }
        self.service.get_february_reservations.return_value = [
            self.service.get_reservation_by_id.return_value, # Current
            other_res
        ]
        
        # Mock manual room for other res
        self.service.get_manual_room.side_effect = lambda rid: '12' if rid == '456' else None
        self.service.get_manual_dates.return_value = (None, None)
        
        # Try to move to Room 12 overlapping (06/02 - 08/02)
        # Overlap: 06/02 is inside 05/02-07/02
        result = self.service.calculate_reservation_update(
            res_id, 
            new_room='12', 
            new_checkin='06/02/2026', 
            new_checkout='08/02/2026'
        )
        
        self.assertFalse(result['valid'])
        self.assertIn("Conflito com reserva de Other Guest", result['conflict_message'])

if __name__ == '__main__':
    unittest.main()
