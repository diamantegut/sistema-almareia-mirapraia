import unittest
import json
import os
from unittest.mock import patch, MagicMock
from app.services.reservation_service import ReservationService

class TestFinancialLogic(unittest.TestCase):
    def setUp(self):
        self.service = ReservationService()
        self.test_file = 'tests/temp_manual_allocations.json'
        self.service.MANUAL_ALLOCATIONS_FILE = self.test_file
        
        # Ensure clean state
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_save_manual_allocation_financial_update_auto(self):
        """Test that extending a stay updates the total amount automatically."""
        # Mock get_reservation_by_id to return a base reservation
        # Original: 2 days (01-03), Amount 200.00 (100/day), Paid 100.00
        mock_res = {
            'id': '123',
            'checkin': '01/02/2024',
            'checkout': '03/02/2024',
            'amount': '200,00',
            'amount_val': 200.00,
            'paid_amount': '100,00',
            'paid_amount_val': 100.00,
            'room': '01'
        }
        
        with patch.object(self.service, 'get_reservation_by_id', return_value=mock_res):
            # Extend to 4 days (01-05) -> Should be 400.00
            self.service.save_manual_allocation(
                reservation_id='123',
                checkin='01/02/2024',
                checkout='05/02/2024',
                room_number='01',
                price_adjustment={'type': 'auto'} # explicitly asking for auto
            )
            
            # Read back
            with open(self.test_file, 'r') as f:
                data = json.load(f)
            
            entry = data.get('123')
            self.assertIsNotNone(entry)
            self.assertEqual(entry['checkin'], '01/02/2024')
            self.assertEqual(entry['checkout'], '05/02/2024')
            
            fin = entry.get('financial', {})
            # 200 / 2 days = 100 per day. New: 4 days * 100 = 400.00
            self.assertEqual(fin.get('amount'), '400.00')
            self.assertEqual(fin.get('paid_amount'), '100.00') # Should remain same
            # To receive: 400 - 100 = 300
            self.assertEqual(fin.get('to_receive'), '300.00')

    def test_save_manual_allocation_financial_update_manual(self):
        """Test that manual price override works."""
        mock_res = {
            'id': '123',
            'checkin': '01/02/2024',
            'checkout': '03/02/2024',
            'amount': 200.00,
            'paid_amount': 100.00
        }
        
        with patch.object(self.service, 'get_reservation_by_id', return_value=mock_res):
            self.service.save_manual_allocation(
                reservation_id='123',
                checkin='01/02/2024',
                checkout='05/02/2024',
                room_number='01',
                price_adjustment={'type': 'manual_total', 'amount': '550.00'}
            )
            
            with open(self.test_file, 'r') as f:
                data = json.load(f)
            
            fin = data['123']['financial']
            self.assertEqual(fin['amount'], '550.00')
            self.assertEqual(fin['to_receive'], '450.00') # 550 - 100

    def test_avg_daily_paid_calculation(self):
        """Test the logic added to merge_overrides_into_reservation for Bug 2."""
        # 1. Create a reservation with overrides
        allocs = {
            '123': {
                'financial': {
                    'amount': '400.00',
                    'paid_amount': '200.00' # Paid 200 for 4 days -> 50/day
                },
                'checkin': '01/02/2024',
                'checkout': '05/02/2024' # 4 days
            }
        }
        
        # Save allocs
        with open(self.test_file, 'w') as f:
            json.dump(allocs, f)
            
        # Base reservation (values don't matter much as they are overridden)
        base_res = {'id': '123', 'checkin': '01/02/2024', 'checkout': '02/02/2024', 'amount': 100, 'paid_amount': 0}
        
        # Test merge
        result = self.service.merge_overrides_into_reservation('123', base_res)
        
        self.assertEqual(result['amount'], '400.00')
        self.assertEqual(result['paid_amount'], '200.00')
        self.assertEqual(result['checkin'], '01/02/2024')
        self.assertEqual(result['checkout'], '05/02/2024')
        
        # Verify Bug 2 fix: avg_daily_paid
        # 200 paid / 4 days = 50.0
        self.assertEqual(result.get('avg_daily_paid'), 50.0)

if __name__ == '__main__':
    unittest.main()
