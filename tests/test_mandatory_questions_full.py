import unittest
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, load_menu_items, save_menu_items, load_table_orders, save_table_orders
from printing_service import format_ticket

class TestMandatoryQuestionsFull(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.app = app.test_client()
        # Backup original file if exists
        self.menu_file = os.path.join(os.path.dirname(__file__), '../data/menu_items.json')
        if os.path.exists(self.menu_file):
            with open(self.menu_file, 'r', encoding='utf-8') as f:
                self.original_data = f.read()
        else:
            self.original_data = None

    def tearDown(self):
        # Restore original file
        if self.original_data:
            with open(self.menu_file, 'w', encoding='utf-8') as f:
                f.write(self.original_data)

    def test_create_product_with_questions_and_paused_field(self):
        """Test creating a product with mandatory questions and verifying the 'paused' fix."""
        
            # Simulate Login
        with self.app.session_transaction() as sess:
            sess['role'] = 'admin'
            sess['user'] = 'TestAdmin'
            sess['username'] = 'TestAdmin'

        # Data for new product
        data = {
            'name': 'Test Burger',
            'category': 'Lanches',
            'price': '30.00',
            'active': 'on',
            'paused': 'on', # Testing the fix
            'pause_reason': 'Lack of ingredients',
            'question_text[]': ['Ponto da Carne', 'Molho Extra'],
            'question_type[]': ['single_choice', 'multiple_choice'],
            'question_options[]': ['Bem Passada, Ao Ponto, Mal Passada', 'Maionese, Ketchup'],
            'question_required[]': ['true', 'false']
        }

        # POST to menu_management
        response = self.app.post('/menu/management', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Verify Persistence
        menu_items = load_menu_items()
        product = next((p for p in menu_items if p['name'] == 'Test Burger'), None)
        
        self.assertIsNotNone(product)
        self.assertTrue(product['active'])
        self.assertTrue(product.get('paused')) # Should be True if fix works
        self.assertEqual(product.get('pause_reason'), 'Lack of ingredients')
        
        # Verify Questions
        self.assertEqual(len(product['mandatory_questions']), 2)
        q1 = product['mandatory_questions'][0]
        self.assertEqual(q1['question'], 'Ponto da Carne')
        self.assertEqual(q1['type'], 'single_choice')
        self.assertTrue(q1['required'])
        
        q2 = product['mandatory_questions'][1]
        self.assertEqual(q2['question'], 'Molho Extra')
        self.assertFalse(q2['required'])

    def test_printing_format(self):
        """Test that questions and answers are formatted correctly in the ticket."""
        item = {
            'name': 'Test Burger',
            'qty': 1,
            'questions_answers': [
                {'question': 'Ponto da Carne', 'answer': 'Ao Ponto'},
                {'question': 'Molho Extra', 'answer': 'Maionese, Ketchup'}
            ]
        }
        
        # Generate ticket bytes
        ticket = format_ticket('10', 'Waiter', [item], 'Kitchen Printer')
        
        # Decode to check string content (ignoring control codes)
        ticket_str = ticket.decode('cp850', errors='replace')
        
        self.assertIn('> Ponto da Carne: Ao Ponto', ticket_str)
        self.assertIn('> Molho Extra: Maionese, Ketchup', ticket_str)

if __name__ == '__main__':
    unittest.main()
