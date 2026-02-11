import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from services.transfer_service import TransferError

class TestTransferIntegration(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test_key'
        self.client = app.test_client()
        self.user_session = {'user': 'Admin', 'role': 'admin'}

    @patch('app.load_table_orders')
    @patch('app.transfer_table_to_room')
    def test_transfer_to_room_success(self, mock_transfer, mock_load_orders):
        """Test successful transfer redirects to restaurant_tables (default)"""
        # Setup mock
        mock_orders = {
            "10": {
                "customer_type": "hospede",
                "room_number": "101",
                "status": "open"
            }
        }
        mock_load_orders.return_value = mock_orders
        mock_transfer.return_value = (True, "Transferência realizada com sucesso")
        
        # Simulate session
        with self.client.session_transaction() as sess:
            sess.update(self.user_session)

        # Make request
        # action=transfer_to_room is handled in restaurant_table_order POST
        response = self.client.post(f'/restaurant/table/10', data={
            'action': 'transfer_to_room'
        }, follow_redirects=True)

        # Assertions
        mock_transfer.assert_called_once()
        _args, kwargs = mock_transfer.call_args
        self.assertEqual(kwargs.get('table_id'), '10')
        self.assertEqual(kwargs.get('raw_room_number'), '101')
        self.assertEqual(kwargs.get('user_name'), 'Admin')
        self.assertEqual(kwargs.get('mode'), 'restaurant')
        
        self.assertEqual(response.status_code, 200)
        # Check for flash message in response data
        self.assertIn(b'Transfer\xc3\xaancia realizada com sucesso', response.data) # UTF-8 bytes for ê

    @patch('app.load_table_orders')
    @patch('app.transfer_table_to_room')
    def test_transfer_route_integration(self, mock_transfer, mock_load_orders):
        """Full integration test with mocked data loading"""
        # Setup data
        mock_orders = {
            "10": {
                "customer_type": "hospede",
                "room_number": "101",
                "status": "open"
            }
        }
        mock_load_orders.return_value = mock_orders
        mock_transfer.return_value = (True, "Sucesso total")

        with self.client.session_transaction() as sess:
            sess.update(self.user_session)

        # Execute
        response = self.client.post(f'/restaurant/table/10', data={
            'action': 'transfer_to_room'
        }, follow_redirects=True)

        # Verify
        mock_transfer.assert_called_once()
        _args, kwargs = mock_transfer.call_args
        self.assertEqual(kwargs.get('table_id'), '10')
        self.assertEqual(kwargs.get('raw_room_number'), '101')
        self.assertEqual(kwargs.get('user_name'), 'Admin')
        self.assertEqual(kwargs.get('mode'), 'restaurant')
        self.assertIn(b'Sucesso total', response.data)
        
    @patch('app.load_table_orders')
    @patch('app.transfer_table_to_room')
    def test_transfer_error_handling(self, mock_transfer, mock_load_orders):
        """Test handling of TransferError"""
        mock_orders = {
            "10": {
                "customer_type": "hospede",
                "room_number": "101",
                "items": []
            }
        }
        mock_load_orders.return_value = mock_orders
        mock_transfer.side_effect = TransferError("Quarto ocupado")

        with self.client.session_transaction() as sess:
            sess.update(self.user_session)

        response = self.client.post(f'/restaurant/table/10', data={
            'action': 'transfer_to_room'
        }, follow_redirects=True)

        self.assertIn(b'Quarto ocupado', response.data)

if __name__ == '__main__':
    unittest.main()
