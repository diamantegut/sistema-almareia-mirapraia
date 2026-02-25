
import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys
import pandas as pd

# Add project root to path
sys.path.append(os.getcwd())

from app.services.reservation_service import ReservationService

class TestImportLogic(unittest.TestCase):

    def setUp(self):
        self.service = ReservationService()
        
        # Mock dependencies
        self.service.get_february_reservations = MagicMock()
        self.service._parse_excel_file = MagicMock()
        self.service.get_conflict_details = MagicMock()
        self.service.save_unallocated_reservations = MagicMock()
        self.service.get_unallocated_reservations = MagicMock()
        
        # Mock constants
        self.service.RESERVATIONS_DIR = "test_reservations"

    def test_duplicate_detection_update(self):
        """Test if duplicate reservations are detected and marked as updates with changes."""
        # Existing reservation
        existing = {
            'id': '123',
            'guest_name': 'John Doe',
            'checkin': '01/02/2026',
            'checkout': '05/02/2026',
            'category': 'Standard',
            'amount': '500.00'
        }
        self.service.get_february_reservations.return_value = [existing]
        
        # Imported reservation (Same ID, changed Amount)
        imported = {
            'id': '123',
            'guest_name': 'John Doe',
            'checkin': '01/02/2026',
            'checkout': '05/02/2026',
            'category': 'Standard',
            'amount': '600.00' # Changed
        }
        self.service._parse_excel_file.return_value = [imported]
        self.service.get_conflict_details.return_value = (True, None)
        
        # Run preview
        result = self.service.preview_import("dummy_path.xlsx")
        
        self.assertTrue(result['success'])
        report = result['report']
        
        # Should be in updates
        self.assertEqual(len(report['updates']), 1)
        self.assertEqual(len(report['new_entries']), 0)
        
        # Verify changes
        update_item = report['updates'][0]
        self.assertEqual(update_item['id'], '123')
        self.assertTrue(any("Valor Total" in c for c in update_item['changes']))

    def test_duplicate_detection_by_key(self):
        """Test if duplicates are detected by Name+Date key when ID differs/missing."""
        existing = {
            'id': '123',
            'guest_name': 'Jane Doe',
            'checkin': '10/02/2026',
            'checkout': '12/02/2026',
            'category': 'Deluxe'
        }
        self.service.get_february_reservations.return_value = [existing]
        
        # Imported (No ID, but same details)
        imported = {
            'id': '999', # Different ID or temp ID
            'guest_name': 'Jane Doe',
            'checkin': '10/02/2026',
            'checkout': '12/02/2026',
            'category': 'Deluxe'
        }
        self.service._parse_excel_file.return_value = [imported]
        
        result = self.service.preview_import("dummy.xlsx")
        
        # Should be unchanged (matched by key)
        self.assertEqual(len(result['report']['unchanged']), 1)
        self.assertEqual(result['report']['unchanged'][0]['original_id'], '123') # Should inherit ID?
        # Actually logic is: if match found, check diff. If no diff -> unchanged.
        # But 'original_id' is set in logic if match found.
        # Wait, looking at code:
        # if match: ... item['original_id'] = match.get('id') ...
        # Yes.

    def test_conflict_detection(self):
        """Test if availability conflict is detected for new/updated items."""
        self.service.get_february_reservations.return_value = []
        
        imported = {
            'id': 'new1',
            'guest_name': 'New Guest',
            'checkin': '20/02/2026',
            'checkout': '25/02/2026',
            'category': 'Suite'
        }
        self.service._parse_excel_file.return_value = [imported]
        
        # Mock NO availability
        self.service.get_conflict_details.return_value = (False, {'type': 'no_availability', 'message': 'Sem disponibilidade na categoria'})
        
        result = self.service.preview_import("dummy.xlsx")
        
        report = result['report']
        self.assertEqual(len(report['conflicts']), 1)
        self.assertTrue(report['new_entries'][0]['has_conflict'])
        self.assertEqual(report['conflicts'][0]['reason'], 'Sem disponibilidade na categoria/período')

    @patch('pandas.DataFrame.to_excel')
    def test_process_import_confirm_saves_files(self, mock_to_excel):
        """Test if process_import_confirm saves valid items to Excel and conflicts to JSON."""
        # Setup mock preview result
        mock_preview = {
            'success': True,
            'report': {
                'new_entries': [
                    {'id': '1', 'name': 'Valid', 'has_conflict': False},
                    {'id': '3', 'name': 'Conflict', 'has_conflict': True, 'reason': 'Full'} # Put conflict item here
                ],
                'updates': [{'id': '2', 'name': 'Updated', 'has_conflict': False, 'original_id': 'old2'}],
                'conflicts': [{'item': {'id': '3'}, 'reason': 'Full'}], # Just for completeness
                'unchanged': [{'id': '4', 'name': 'Same'}]
            }
        }
        
        # Mock preview_import to return our controlled result
        self.service.preview_import = MagicMock(return_value=mock_preview)
        
        result = self.service.process_import_confirm("temp.xlsx", "token123")
        
        self.assertTrue(result['success'])
        
        # Verify Excel save (Valid + Updated + Unchanged = 3 items)
        self.assertTrue(mock_to_excel.called)
        
        # Verify Conflict save
        self.service.save_unallocated_reservations.assert_called_once()
        saved_conflicts = self.service.save_unallocated_reservations.call_args[0][0]
        self.assertEqual(len(saved_conflicts), 1)
        self.assertEqual(saved_conflicts[0]['id'], '3')

    @patch('glob.glob')
    @patch('os.path.getmtime')
    def test_deduplication_keeps_latest(self, mock_getmtime, mock_glob):
        """Test if get_february_reservations keeps only the latest version of a reservation ID."""
        # Unmock get_february_reservations for this test (we mocked it in setUp)
        # We need to recreate service or unmock. 
        # Easier to create a new instance or restore original method.
        # But since we mocked dependencies on instance, we can't easily restore method.
        # Let's create a fresh instance locally.
        service = ReservationService()
        service._parse_excel_file = MagicMock()
        service.get_reservation_status_overrides = MagicMock(return_value={})
        service.get_manual_reservations_data = MagicMock(return_value=[]) # Mock manual reservations
        
        mock_glob.return_value = ['file1.xlsx', 'file2.xlsx']
        
        # Mock mtime: file2 is newer
        def mtime_side_effect(path):
            if 'file1' in path: return 1000
            if 'file2' in path: return 2000
            return 0
        mock_getmtime.side_effect = mtime_side_effect
        
        # Mock parse results
        # File 1: Res A (Old)
        # File 2: Res A (New)
        res_a_old = {'id': 'A', 'status': 'Old'}
        res_a_new = {'id': 'A', 'status': 'New'}
        
        service._parse_excel_file.side_effect = [[res_a_old], [res_a_new]]
        
        results = service.get_february_reservations()
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'New')

    def test_get_conflict_details_invalid_dates(self):
        """Test conflict details with invalid date format."""
        # Use fresh service to avoid setUp mocks
        service = ReservationService()
        # Mock get_february_reservations to avoid file reading error
        service.get_february_reservations = MagicMock(return_value=[])
        
        is_avail, details = service.get_conflict_details('Standard', 'invalid', '2026-02-01')
        self.assertFalse(is_avail)
        self.assertEqual(details['type'], 'invalid_dates')

    def test_get_conflict_details_unknown_category(self):
        """Test conflict details with unknown room category."""
        service = ReservationService()
        # Mock get_february_reservations to avoid file reading error
        service.get_february_reservations = MagicMock(return_value=[])
        
        # We need to mock get_room_mapping to control known categories
        with patch.object(service, 'get_room_mapping', return_value={'Standard': ['01', '02']}):
             # And mock other dependencies of get_conflict_details
             with patch('app.services.data_service.load_room_occupancy', return_value={}):
                 with patch.object(service, 'get_occupancy_grid', return_value={}):
                     with patch.object(service, 'allocate_reservations'):
                         is_avail, details = service.get_conflict_details('Space Station', '01/02/2026', '05/02/2026')
                         self.assertFalse(is_avail)
                         self.assertEqual(details['type'], 'invalid_category')

    def test_get_conflict_details_valid_no_conflict(self):
        """Test conflict details with valid input and no conflict."""
        service = ReservationService()
        service.get_february_reservations = MagicMock(return_value=[])
        
        with patch.object(service, 'get_room_mapping', return_value={'Standard': ['01']}):
            with patch('app.services.data_service.load_room_occupancy', return_value={}):
                with patch.object(service, 'get_occupancy_grid', return_value={'01': {}}): # Empty grid
                    # allocate_reservations is called but we mock it or let it run (if mocked in setUp, need to handle)
                    # Here we use fresh service, so real allocate_reservations is used.
                    # But get_occupancy_grid returns a dict.
                    
                    # We need to make sure allocate_reservations doesn't crash if we don't mock it?
                    # allocate_reservations modifies grid in place.
                    
                    is_avail, details = service.get_conflict_details('Standard', '01/02/2026', '05/02/2026')
                    
                    # Should be available
                    self.assertTrue(is_avail)
                    self.assertIsNone(details)

    def test_preview_import_corrupted_file(self):
        """Test preview import with a file that returns no valid items."""
        self.service._parse_excel_file.return_value = [] # Empty result implies corruption/empty
        
        result = self.service.preview_import("bad.xlsx")
        
        self.assertFalse(result['success'])
        self.assertIn('Nenhuma reserva válida', result['error'])

    def test_preview_import_item_processing_error(self):
        """Test handling of an exception during item processing in preview."""
        self.service.get_february_reservations.return_value = []
        self.service._parse_excel_file.return_value = [{'id': '1', 'category': 'Std', 'checkin': '01/01/2026', 'checkout': '02/01/2026'}]
        
        # Mock get_conflict_details to raise exception
        self.service.get_conflict_details.side_effect = Exception("Unexpected Error")
        
        result = self.service.preview_import("dummy.xlsx")
        
        self.assertTrue(result['success']) # Overall success, but item failed
        report = result['report']
        
        # Should be in conflicts list with error status
        self.assertEqual(len(report['conflicts']), 1)
        conflict = report['conflicts'][0]
        self.assertEqual(conflict['status'], 'error')
        self.assertIn("Unexpected Error", conflict['reason'])

if __name__ == '__main__':
    unittest.main()
