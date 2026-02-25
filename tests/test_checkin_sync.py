
import unittest
import json
import os
import sys
import shutil
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from app.services import reservation_service

class TestCheckinSync(unittest.TestCase):
    """
    Tests for the Check-in Synchronization features.
    This test file should be kept to ensure future regressions don't break the sync logic.
    """
    
    def setUp(self):
        # Create temp directory for test data
        self.tmp_dir = os.path.join(os.getcwd(), 'tests', 'temp_sync_perm')
        if not os.path.exists(self.tmp_dir):
            os.makedirs(self.tmp_dir)
            
        self.tmp_overrides = os.path.join(self.tmp_dir, 'status_overrides.json')
        with open(self.tmp_overrides, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def test_reservation_status_override_persistence(self):
        """
        Verify that update_reservation_status correctly persists data 
        to the overrides file.
        """
        svc = reservation_service.ReservationService()
        svc.RESERVATION_STATUS_OVERRIDES_FILE = self.tmp_overrides
        
        test_id = 'RES-PERM-001'
        new_status = 'Checked-in'
        
        # Action
        svc.update_reservation_status(test_id, new_status)
        
        # Verification
        with open(self.tmp_overrides, 'r') as f:
            data = json.load(f)
            
        self.assertIn(test_id, data)
        self.assertEqual(data[test_id], new_status)

    def test_overrides_application_on_fetch(self):
        """
        Verify that get_february_reservations applies the overrides 
        to the returned data.
        """
        svc = reservation_service.ReservationService()
        svc.RESERVATION_STATUS_OVERRIDES_FILE = self.tmp_overrides
        
        # Setup Override
        with open(self.tmp_overrides, 'w') as f:
            json.dump({'RES-MOCK-001': 'Checked-in'}, f)
            
        # Mock Data Source
        mock_reservations = [
            {'id': 'RES-MOCK-001', 'status': 'Pendente', 'guest_name': 'Test Guest'},
            {'id': 'RES-MOCK-002', 'status': 'Pendente', 'guest_name': 'Other Guest'}
        ]
        
        # We mock the internal methods that load raw data
        with patch.object(svc, 'get_manual_reservations_data', return_value=mock_reservations), \
             patch.object(svc, '_parse_excel_file', return_value=[]):
             
             # Action
             results = svc.get_february_reservations()
             
             # Verification
             res1 = next(r for r in results if r['id'] == 'RES-MOCK-001')
             res2 = next(r for r in results if r['id'] == 'RES-MOCK-002')
             
             self.assertEqual(res1['status'], 'Checked-in') # Should be overridden
             self.assertEqual(res2['status'], 'Pendente')   # Should be original

if __name__ == '__main__':
    unittest.main()
