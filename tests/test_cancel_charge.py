import unittest
import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_data_path

class TestCancelCharge(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app = app.test_client()
        self.charge_id = f"TEST_CHARGE_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create a dummy pending charge
        self.create_dummy_charge()
        
    def create_dummy_charge(self):
        charges_path = get_data_path('room_charges.json')
        with open(charges_path, 'r', encoding='utf-8') as f:
            charges = json.load(f)
            
        new_charge = {
            "id": self.charge_id,
            "room_number": "999", # Test room
            "status": "pending",
            "items": [{"name": "Test Item", "qty": 1, "price": 10.0}],
            "total": 10.0,
            "date": datetime.now().strftime('%d/%m/%Y %H:%M'),
            "source": "restaurant"
        }
        
        charges.append(new_charge)
        with open(charges_path, 'w', encoding='utf-8') as f:
            json.dump(charges, f, indent=4)
            
    def tearDown(self):
        # Clean up
        charges_path = get_data_path('room_charges.json')
        if os.path.exists(charges_path):
            with open(charges_path, 'r', encoding='utf-8') as f:
                charges = json.load(f)
            
            charges = [c for c in charges if c['id'] != self.charge_id]
            
            with open(charges_path, 'w', encoding='utf-8') as f:
                json.dump(charges, f, indent=4)

    def test_cancel_charge_admin(self):
        with self.app.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin']
        
        # Attempt to cancel
        response = self.app.post('/reception/rooms', data={
            'action': 'cancel_charge',
            'charge_id': self.charge_id,
            'cancellation_reason': 'Test Cancellation'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify status in file
        charges_path = get_data_path('room_charges.json')
        with open(charges_path, 'r', encoding='utf-8') as f:
            charges = json.load(f)
            
        target_charge = next((c for c in charges if c['id'] == self.charge_id), None)
        self.assertIsNotNone(target_charge)
        self.assertEqual(target_charge['status'], 'cancelled', "Charge status should be 'cancelled'")
        self.assertEqual(target_charge.get('cancellation_reason'), 'Test Cancellation')

if __name__ == '__main__':
    unittest.main()
