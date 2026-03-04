
import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from flask import url_for

class TestConsumptionButtonRoute(unittest.TestCase):
    def setUp(self):
        self.app = create_app(config_name='testing')
        self.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SERVER_NAME': 'localhost.localdomain'
        })
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Mock session
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'restaurante']

    def tearDown(self):
        self.app_context.pop()

    @patch('app.blueprints.reception.routes.load_room_charges')
    @patch('app.blueprints.reception.routes.load_room_occupancy')
    @patch('app.blueprints.reception.routes.load_cleaning_status')
    @patch('app.blueprints.reception.routes.load_checklist_items')
    @patch('app.blueprints.reception.routes.ReservationService')
    @patch('app.blueprints.reception.routes.ExperienceService')
    def test_reception_rooms_button_presence(self, mock_exp_service, mock_res_service, mock_checklist, mock_cleaning, mock_occupancy, mock_charges):
        # Setup mocks
        mock_occupancy.return_value = {
            '11': {'guest_name': 'Test Guest', 'checkin': '01/01/2024', 'checkout': '05/01/2024'}
        }
        mock_cleaning.return_value = {}
        mock_checklist.return_value = []
        
        # Mock charges for room 11 to trigger "Ver Consumo"
        mock_charges.return_value = [
            {'room_number': '11', 'status': 'pending', 'total': 50.0, 'items': [], 'source': 'restaurant'}
        ]
        
        # Mock ReservationService.ROOM_CAPACITIES
        mock_res_service.ROOM_CAPACITIES = {}
        mock_res_service.return_value.get_upcoming_checkins.return_value = []
        
        # Mock ExperienceService
        mock_exp_service.get_all_experiences.return_value = []
        mock_exp_service.get_unique_collaborators.return_value = []

        with self.client:
             response = self.client.get('/reception/rooms')
             self.assertEqual(response.status_code, 200)
        
        # Verify button presence and link construction
        html = response.data.decode('utf-8')
        
        # Use request context to build expected link
        with self.app.test_request_context():
            expected_link = url_for('restaurant.restaurant_table_order', table_id='11', mode='reception')
        
        # Check for the link in the HTML
        self.assertIn(f'href="{expected_link}"', html)
        self.assertIn('Lançar Consumo', html)
        
        # Check for "Ver Consumo" button
        self.assertIn('Ver Consumo', html)
        self.assertIn('onclick="openConsumptionModal(\'11\')"', html)
        self.assertIn('const groupedCharges =', html)
        self.assertIn('"11"', html)

    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.load_room_occupancy')
    @patch('app.blueprints.restaurant.routes.load_complements')
    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_products')
    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.load_flavor_groups')
    def test_restaurant_table_order_mode_reception(self, mock_flavors, mock_menu, mock_products, mock_users, mock_complements, mock_occupancy, mock_orders):
        # Setup mocks
        mock_orders.return_value = {}
        mock_occupancy.return_value = {'11': {'guest_name': 'Test Guest'}}
        mock_complements.return_value = {}
        mock_users.return_value = {}
        mock_products.return_value = []
        mock_menu.return_value = []
        mock_flavors.return_value = {}

        # Access with mode='reception'
        with self.client:
             response = self.client.get('/restaurant/table/11?mode=reception')
             self.assertEqual(response.status_code, 200)
        
        html = response.data.decode('utf-8')
        
        # Verify back link points to reception
        with self.app.test_request_context():
            expected_back_link = url_for('reception.reception_rooms')
            
        self.assertIn(f'href="{expected_back_link}"', html)

if __name__ == '__main__':
    unittest.main()
