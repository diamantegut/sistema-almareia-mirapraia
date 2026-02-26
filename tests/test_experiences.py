import unittest
import json
import os
import shutil
from datetime import datetime
from app import create_app
from app.services import experience_service

TEST_DATA_DIR = r'tests\test_data_experiences'

class TestExperiences(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def setUp(self):
        # Patch data paths
        self.original_experiences_file = experience_service.EXPERIENCES_FILE
        self.original_launched_file = experience_service.LAUNCHED_EXPERIENCES_FILE
        
        self.test_experiences = os.path.join(TEST_DATA_DIR, 'guest_experiences.json')
        self.test_launched = os.path.join(TEST_DATA_DIR, 'launched_experiences.json')
        
        # Apply patches
        experience_service.EXPERIENCES_FILE = self.test_experiences
        experience_service.LAUNCHED_EXPERIENCES_FILE = self.test_launched
        
        self.reset_data()
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'admin']
            sess['department'] = 'Recepção'

    def tearDown(self):
        # Restore paths
        experience_service.EXPERIENCES_FILE = self.original_experiences_file
        experience_service.LAUNCHED_EXPERIENCES_FILE = self.original_launched_file

    def reset_data(self):
        with open(self.test_experiences, 'w') as f: json.dump([], f)
        with open(self.test_launched, 'w') as f: json.dump([], f)

    def test_create_experience_with_internal_fields(self):
        """Test creating an experience with new internal supplier fields"""
        data = {
            'name': 'Passeio de Barco',
            'description': 'Passeio incrível',
            'duration': '2h',
            'min_people': '2',
            'max_people': '10',
            'price': '150.00',
            'type': 'Adventure',
            'is_active': 'on',
            'supplier_name': 'Capitão Gancho',
            'supplier_phone': '99999-9999',
            'supplier_price': '100.00',
            'guest_price': '150.00',
            'expected_commission': '50.00',
            'sales_commission': '10.00',
            'hotel_commission': '40.00'
        }
        
        response = self.client.post('/reception/experiences/create', data=data, follow_redirects=True)
        self.assertIn(b'Experi\xc3\xaancia criada com sucesso!', response.data.decode('utf-8').encode('utf-8'))
        
        # Verify JSON content
        with open(self.test_experiences, 'r', encoding='utf-8') as f:
            exps = json.load(f)
            self.assertEqual(len(exps), 1)
            exp = exps[0]
            self.assertEqual(exp['name'], 'Passeio de Barco')
            self.assertTrue(exp['active']) # Changed from is_active to active
            self.assertEqual(exp['supplier_name'], 'Capitão Gancho')
            self.assertEqual(exp['guest_price'], '150.00') # It stores as string from form
            self.assertEqual(exp['supplier_price'], '100.00')

    def test_toggle_experience(self):
        """Test toggling experience active status"""
        # Create directly via service
        exp_data = {
            'name': 'Test Toggle',
            'active': True
        }
        experience_service.ExperienceService.create_experience(exp_data)
        
        # Get ID
        with open(self.test_experiences, 'r', encoding='utf-8') as f:
            exp_id = json.load(f)[0]['id']
            
        # Toggle OFF
        response = self.client.post(f'/reception/experiences/{exp_id}/toggle')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['active'], False)
        
        # Verify persistence
        with open(self.test_experiences, 'r', encoding='utf-8') as f:
            exp = json.load(f)[0]
            self.assertFalse(exp['active'])
            
        # Toggle ON
        response = self.client.post(f'/reception/experiences/{exp_id}/toggle')
        self.assertEqual(response.json['active'], True)

    def test_launch_experience(self):
        """Test launching an experience for a guest"""
        # Create experience
        exp_data = {
            'name': 'Mergulho',
            'guest_price': '200.00',
            'supplier_price': '150.00',
            'active': True
        }
        experience_service.ExperienceService.create_experience(exp_data)
        
        with open(self.test_experiences, 'r', encoding='utf-8') as f:
            exp_id = json.load(f)[0]['id']
            
        launch_data = {
            'experience_id': exp_id,
            'room_number': '101',
            'guest_name': 'João Silva',
            'collaborator_name': 'Maria Recepcionista',
            'scheduled_date': '2023-10-27T14:30',
            'notes': 'Cliente VIP'
        }
        
        response = self.client.post('/reception/experiences/launch', data=launch_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        
        # Verify launch record
        with open(self.test_launched, 'r', encoding='utf-8') as f:
            launches = json.load(f)
            self.assertEqual(len(launches), 1)
            self.assertEqual(launches[0]['guest_name'], 'João Silva')
            self.assertEqual(launches[0]['scheduled_date'], '2023-10-27T14:30')
            # Verify financial snapshot
            self.assertEqual(launches[0]['guest_price'], '200.00')

    def test_commission_report_filter(self):
        """Test report generation and filtering"""
        # Create mocked launched data directly
        mock_launches = [
            {
                'id': '1',
                'launched_at': '2023-10-01T10:00:00',
                'collaborator_name': 'Ana',
                'supplier_name': 'Tour A',
                'guest_price': 100, 
                'supplier_price': 80
            },
            {
                'id': '2',
                'launched_at': '2023-10-02T10:00:00',
                'collaborator_name': 'Bia',
                'supplier_name': 'Tour B',
                'guest_price': 200, 
                'supplier_price': 150
            }
        ]
        with open(self.test_launched, 'w', encoding='utf-8') as f:
            json.dump(mock_launches, f)
            
        # Test Filter by Collaborator 'Ana'
        response = self.client.get('/reception/experiences/report?collaborator=Ana')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['data'][0]['collaborator_name'], 'Ana')
        
        # Test Filter by Date Range (excluding 2023-10-01)
        response = self.client.get('/reception/experiences/report?start_date=2023-10-02&end_date=2023-10-03')
        data = response.json
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['data'][0]['id'], '2')

    def test_commission_validation(self):
        """Test commission validation logic"""
        # Invalid distribution
        data = {
            'name': 'Invalid Comm',
            'type': 'Test',
            'description': 'Desc',
            'supplier_price': '100.00',
            'guest_price': '150.00',
            'sales_commission': '30.00',
            'hotel_commission': '30.00' # Sum 60 > 50 (Expected)
        }
        
        # Service Level
        with self.assertRaises(ValueError) as cm:
            experience_service.ExperienceService.create_experience(data)
        self.assertIn("excede a Comissão Esperada", str(cm.exception))
        
        # Route Level
        response = self.client.post('/reception/experiences/create', data=data, follow_redirects=True)
        # Should flash error
        self.assertIn(b'Erro:', response.data)
        
        # Valid distribution
        data['hotel_commission'] = '20.00' # Sum 50 == 50
        exp = experience_service.ExperienceService.create_experience(data)
        self.assertIsNotNone(exp)
        
        # Negative values
        data['sales_commission'] = '-10.00'
        with self.assertRaises(ValueError):
            experience_service.ExperienceService.create_experience(data)

if __name__ == '__main__':
    unittest.main()
