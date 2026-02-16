
import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Setup path
sys.path.append(os.getcwd())

from app import create_app

class TestStaffConsumption(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.log_action')
    def test_open_staff_table_success(self, mock_log, mock_save, mock_load_orders, mock_load_users):
        # Mock Data
        mock_load_users.return_value = {'Angelo': {'username': 'Angelo', 'full_name': 'Angelo Diamante'}}
        mock_load_orders.return_value = {}
        mock_save.return_value = True # Simulate success

        # Simulate Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'Angelo'
            sess['role'] = 'admin'

        # Make Request
        response = self.client.post('/restaurant/open_staff_table', data={'staff_name': 'Angelo'}, follow_redirects=True)
        
        # Check assertions
        self.assertEqual(response.status_code, 200)
        # Should redirect to table order page
        # In testing, we check if logic flowed
        mock_save.assert_called_once()
        args, _ = mock_save.call_args
        orders = args[0]
        self.assertIn('FUNC_Angelo', orders)
        self.assertEqual(orders['FUNC_Angelo']['staff_name'], 'Angelo')

    @patch('app.blueprints.restaurant.routes.load_users')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.save_table_orders')
    def test_open_staff_table_save_fail(self, mock_save, mock_load_orders, mock_load_users):
        # Mock Data
        mock_load_users.return_value = {'Angelo': {'username': 'Angelo'}}
        mock_load_orders.return_value = {}
        mock_save.return_value = False # Simulate FAIL

        with self.client.session_transaction() as sess:
            sess['user'] = 'Angelo'
            sess['role'] = 'admin'

        response = self.client.post('/restaurant/open_staff_table', data={'staff_name': 'Angelo'}, follow_redirects=True)
        
        # Should show error message matching current implementation
        response_data = response.get_data(as_text=True)
        self.assertIn('Erro CRÍTICO ao salvar conta do funcionário. Contate o suporte.', response_data)


class TestLiveMusicToggle(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch('app.blueprints.restaurant.routes.load_restaurant_settings')
    def test_restaurant_tables_shows_live_music_button_state(self, mock_load_settings):
        mock_load_settings.return_value = {'live_music_active': False}

        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        response = self.client.get('/restaurant/tables')
        self.assertEqual(response.status_code, 200)
        response_text = response.get_data(as_text=True)
        self.assertIn('Música ao Vivo: Desativada', response_text)

        mock_load_settings.return_value = {'live_music_active': True}

        response = self.client.get('/restaurant/tables')
        self.assertEqual(response.status_code, 200)
        response_text = response.get_data(as_text=True)
        self.assertIn('Música ao Vivo: Ativada', response_text)


class TestLiveMusicToggleAction(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch('app.blueprints.restaurant.routes.save_restaurant_settings')
    @patch('app.blueprints.restaurant.routes.load_restaurant_settings')
    def test_toggle_live_music_requires_privileged_role(self, mock_load_settings, mock_save_settings):
        mock_load_settings.return_value = {'live_music_active': False}

        with self.client.session_transaction() as sess:
            sess['user'] = 'garcom'
            sess['role'] = 'garcom'

        response = self.client.post('/restaurant/toggle_live_music', follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        response = self.client.post('/restaurant/toggle_live_music', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        mock_save_settings.assert_called()

        mock_save_settings.reset_mock()

        with self.client.session_transaction() as sess:
            sess['user'] = 'supervisor_user'
            sess['role'] = 'supervisor'

        response = self.client.post('/restaurant/toggle_live_music', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        mock_save_settings.assert_called()

    @patch('app.blueprints.restaurant.routes.save_table_orders')
    @patch('app.blueprints.restaurant.routes.load_table_orders')
    @patch('app.blueprints.restaurant.routes.load_menu_items')
    @patch('app.blueprints.restaurant.routes.save_restaurant_settings')
    @patch('app.blueprints.restaurant.routes.load_restaurant_settings')
    def test_toggle_live_music_auto_cover_flags(self, mock_load_settings, mock_save_settings, mock_load_menu, mock_load_orders, mock_save_orders):
        mock_load_settings.return_value = {'live_music_active': False}

        mock_load_menu.return_value = [
            {'id': '32', 'name': 'Couvert Artistico', 'price': 30.0, 'category': 'Couvert'}
        ]

        mock_load_orders.return_value = {
            '40': {
                'items': [],
                'status': 'open',
                'num_adults': 2,
                'customer_type': 'externo'
            }
        }

        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'

        response = self.client.post('/restaurant/toggle_live_music', follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        mock_save_orders.assert_called_once()
        orders_arg, = mock_save_orders.call_args[0]
        self.assertIn('40', orders_arg)
        items = orders_arg['40'].get('items', [])
        auto_covers = [i for i in items if i.get('source') == 'auto_cover_activation']
        self.assertGreaterEqual(len(auto_covers), 1)
        for item in auto_covers:
            self.assertTrue(item.get('service_fee_exempt'))

if __name__ == '__main__':
    unittest.main()
