
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock key dependencies before importing app to avoid side effects
sys.modules['printer_manager'] = MagicMock()
sys.modules['printing_service'] = MagicMock()

# Now import app
from app import app

class TestPermissionsAndPrint(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test_secret'
        self.client = app.test_client()

    def test_menu_permission_supervisor_substring(self):
        """Test that a role containing 'supervisor' (e.g. 'supervisor_rh') is allowed."""
        with self.client.session_transaction() as sess:
            sess['role'] = 'supervisor_rh'
            sess['user'] = 'test_sup'
            sess['department'] = 'RH'
            
        # Access the route
        # Since we are mocking dependencies, we expect it to try to render the template
        # or fail later, but NOT redirect to index (302) due to permission
        response = self.client.get('/menu/management')
        
        # If permission denied, it redirects (302). If allowed, it might be 200 or 500 (template error)
        # We assert it is NOT 302 redirecting to index. 
        # Note: If it redirects to login (302) it means login_required failed, but we set session.
        
        if response.status_code == 302:
             # Check if it's redirecting to index (denied) or login
             location = response.headers['Location']
             if 'login' in location:
                 self.fail("Redirected to login despite session set")
             # If it redirects to index, it means permission denied
             # But we can't easily check 'index' url without context, but usually '/' or '/index'
             pass

        # Since we modified the code to allow 'supervisor' substring, this should pass check
        # and proceed to logic.
        # Ideally we check flash message "Acesso restrito" is NOT present.
        with self.client.session_transaction() as sess:
            flashes = sess.get('_flashes', [])
            for cat, msg in flashes:
                if 'Acesso restrito' in msg:
                    self.fail("Access restricted for supervisor_rh")

    def test_menu_permission_denied(self):
        """Test that a regular role (e.g. 'garcom') is denied."""
        with self.client.session_transaction() as sess:
            sess['role'] = 'garcom'
            
        response = self.client.get('/menu/management')
        self.assertEqual(response.status_code, 302)
        
        # Verify flash message manually if possible, or assume 302 is the denial behavior
        # In app.py: flash('Acesso restrito.') -> redirect(url_for('index'))

    @patch('app.print_cashier_ticket')
    @patch('app.load_printer_settings')
    @patch('app.load_printers')
    @patch('app.load_cashier_sessions')
    @patch('app.save_cashier_sessions')
    @patch('app.log_action')
    def test_sangria_print_called(self, mock_log, mock_save, mock_load_sessions, mock_load_printers, mock_load_settings, mock_print):
        """Test that adding a withdrawal transaction triggers print_cashier_ticket."""
        
        # Setup mocks
        mock_load_settings.return_value = {'default_printer_id': 'p1'}
        mock_load_printers.return_value = [{'id': 'p1', 'name': 'Printer1', 'type': 'windows'}]
        mock_print.return_value = (True, "Printed")
        
        # Mock active session
        mock_load_sessions.return_value = [{
             'id': 'sess1',
             'status': 'open',
             'user': 'admin',
             'transactions': [],
             'type': 'restaurant' # Assuming this identifies the session for the view
        }]
        
        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user'] = 'admin'
            sess['username'] = 'admin'
            
        # Post withdrawal
        response = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50,00', # Comma format
            'description': 'Test Sangria'
        }, follow_redirects=True)
        
        # Verify print called
        mock_print.assert_called_once()
        args = mock_print.call_args[1] if mock_print.call_args[1] else mock_print.call_args[0]
        
        # Depending on how it's called (keyword args or positional)
        # print_cashier_ticket(printer_config, type_str, amount, user, reason)
        # In code: type_str="SANGRIA", amount=amount, user=..., reason=...
        
        if 'type_str' in args:
            self.assertEqual(args['type_str'], 'SANGRIA')
        
        # Check amount parsed correctly
        if 'amount' in args:
            self.assertEqual(args['amount'], 50.0)

if __name__ == '__main__':
    unittest.main()
