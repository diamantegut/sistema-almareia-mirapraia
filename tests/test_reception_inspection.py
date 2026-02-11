
import unittest
import sys
import os

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from flask import session

class TestReceptionInspection(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app = app.test_client()
        
    def test_inspection_access_regular_user(self):
        """Test that a regular reception user can perform inspection"""
        with self.app.session_transaction() as sess:
            sess['user'] = 'Recepcionista'
            sess['role'] = 'recepcao'
            sess['permissions'] = ['recepcao']
            
        # 1. Set room to clean (needs inspection)
        # We can't easily modify the JSON directly without mocking, 
        # but we can assume room 101 exists or use a mock.
        # Since we are using the real app, we should be careful.
        # But for this test, we just want to see if the POST request is accepted (not 403)
        
        response = self.app.post('/reception/rooms', data={
            'action': 'inspect_room',
            'room_number': '101',
            'inspection_result': 'passed',
            'observation': 'Test inspection'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        # Check if flash message confirms inspection
        self.assertIn(b'inspecionado e liberado', response.data)
        
    def test_inspection_access_admin(self):
        """Test that admin can perform inspection"""
        with self.app.session_transaction() as sess:
            sess['user'] = 'Admin'
            sess['role'] = 'admin'
            
        response = self.app.post('/reception/rooms', data={
            'action': 'inspect_room',
            'room_number': '101',
            'inspection_result': 'passed',
            'observation': 'Admin inspection'
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'inspecionado e liberado', response.data)

if __name__ == '__main__':
    unittest.main()
