
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

    def test_get_reservation_for_checkin_enriches_room_and_guest_fields(self):
        svc = reservation_service.ReservationService()
        base_reservation = {
            'id': 'RES-CHECKIN-001',
            'guest_name': 'Hospede Teste',
            'category': 'Suíte Mar',
            'checkin': datetime.now().strftime('%d/%m/%Y'),
            'checkout': datetime.now().strftime('%d/%m/%Y')
        }

        with patch.object(svc, 'get_reservation_by_id', return_value=base_reservation), \
             patch.object(svc, '_load_manual_allocations', return_value={'RES-CHECKIN-001': {'room': '14'}}), \
             patch.object(svc, 'get_guest_details', return_value={
                 'personal_info': {
                     'email': 'hospede@teste.com',
                     'phone': '81999990000',
                     'doc_id': '12345678900',
                     'zipcode': '55590-000'
                 }
             }):
            enriched = svc.get_reservation_for_checkin('RES-CHECKIN-001')

        self.assertIsNotNone(enriched)
        self.assertEqual(enriched.get('room'), '14')
        self.assertEqual(enriched.get('doc_id'), '12345678900')
        self.assertEqual(enriched.get('zipcode'), '55590-000')
        self.assertEqual(enriched.get('email'), 'hospede@teste.com')
        self.assertEqual(enriched.get('num_adults'), 2)

    def test_get_guest_details_normalizes_doc_and_zip_keys(self):
        svc = reservation_service.ReservationService()
        guest_details_file = os.path.join(self.tmp_dir, 'guest_details.json')
        with open(guest_details_file, 'w', encoding='utf-8') as f:
            json.dump({
                'R-CPF': {'personal_info': {'cpf': '11122233344', 'zip': '55500-000'}},
                'R-DOC': {'personal_info': {'doc_id': '99988877766', 'zipcode': '55600-000'}}
            }, f)

        with patch.object(reservation_service, 'GUEST_DETAILS_FILE', guest_details_file):
            cpf_details = svc.get_guest_details('R-CPF')
            doc_details = svc.get_guest_details('R-DOC')

        self.assertEqual(cpf_details['personal_info'].get('doc_id'), '11122233344')
        self.assertEqual(cpf_details['personal_info'].get('cpf'), '11122233344')
        self.assertEqual(cpf_details['personal_info'].get('zipcode'), '55500-000')
        self.assertEqual(cpf_details['personal_info'].get('zip'), '55500-000')

        self.assertEqual(doc_details['personal_info'].get('doc_id'), '99988877766')
        self.assertEqual(doc_details['personal_info'].get('cpf'), '99988877766')
        self.assertEqual(doc_details['personal_info'].get('zipcode'), '55600-000')
        self.assertEqual(doc_details['personal_info'].get('zip'), '55600-000')

if __name__ == '__main__':
    unittest.main()
