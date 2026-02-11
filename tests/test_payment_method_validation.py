
import unittest
from unittest.mock import patch, MagicMock
import logging

# Configure logging to capture output during tests
logging.basicConfig(level=logging.ERROR)

from app.services.data_service import load_payment_methods

class TestPaymentMethodValidation(unittest.TestCase):

    @patch('app.services.data_service._load_json')
    def test_valid_payment_method(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": ["restaurant", "reception"],
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0]['id'], 'pix')

    @patch('app.services.data_service._load_json')
    def test_missing_id(self, mock_load):
        mock_load.return_value = [{
            "name": "Pix",
            "available_in": ["restaurant"],
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_missing_name(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "available_in": ["restaurant"],
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_invalid_available_in_type(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": "restaurant", # Should be list
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_invalid_category(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": ["space_station"], # Invalid
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_valid_categories(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": ["restaurant", "reception", "reservations"],
            "is_fiscal": False
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 1)

    @patch('app.services.data_service._load_json')
    def test_missing_is_fiscal(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": ["restaurant"]
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_invalid_is_fiscal_type(self, mock_load):
        mock_load.return_value = [{
            "id": "pix",
            "name": "Pix",
            "available_in": ["restaurant"],
            "is_fiscal": "yes" # Should be bool
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 0)

    @patch('app.services.data_service._load_json')
    def test_legacy_dinheiro_autofix(self, mock_load):
        mock_load.return_value = [{
            "id": "dinheiro",
            "name": "Dinheiro"
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0]['id'], 'dinheiro')
        self.assertEqual(methods[0]['is_fiscal'], False)
        self.assertEqual(methods[0]['available_in'], ['restaurant', 'reception'])

    @patch('app.services.data_service._load_json')
    def test_legacy_dinheiro_partial_fix(self, mock_load):
        mock_load.return_value = [{
            "id": "dinheiro",
            "name": "Dinheiro",
            "available_in": ["reservations"]
        }]
        
        methods = load_payment_methods()
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0]['available_in'], ['reservations']) # Should preserve existing
        self.assertEqual(methods[0]['is_fiscal'], False) # Should add missing

if __name__ == '__main__':
    unittest.main()
