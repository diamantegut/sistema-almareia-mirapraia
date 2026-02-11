import unittest
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, load_room_charges, save_room_charges
from flask import session

class TestReceptionEditRedirect(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.secret_key = 'test_secret_key'
        self.client = app.test_client()
        self.charge_id = 'test_redirect_charge'
        
        # Create a dummy charge
        charges = load_room_charges()
        self.test_charge = {
            'id': self.charge_id,
            'room_number': '101',
            'total': 100.00,
            'date': '01/01/2026 10:00',
            'status': 'pending',
            'notes': 'Original Note',
            'items': []
        }
        charges.append(self.test_charge)
        save_room_charges(charges)

    def tearDown(self):
        charges = load_room_charges()
        charges = [c for c in charges if c['id'] != self.charge_id]
        save_room_charges(charges)

    def test_redirect_to_rooms(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'Manager'
            sess['role'] = 'gerente'

        response = self.client.post('/reception/charge/edit', data={
            'charge_id': self.charge_id,
            'new_total': '100.00', # No change
            'source_page': 'reception_rooms'
        })
        
        self.assertEqual(response.status_code, 302)
        self.assertIn('/reception/rooms', response.location)

    def test_redirect_default(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'Manager'
            sess['role'] = 'gerente'

        response = self.client.post('/reception/charge/edit', data={
            'charge_id': self.charge_id,
            'new_total': '100.00'
        })
        
        self.assertEqual(response.status_code, 302)
        self.assertIn('/reception/cashier', response.location)

if __name__ == '__main__':
    unittest.main()
