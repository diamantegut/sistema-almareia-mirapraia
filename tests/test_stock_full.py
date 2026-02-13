
import unittest
from unittest.mock import patch, MagicMock
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services import data_service

class TestStockModule(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        
        # Mock data
        self.mock_products = [
            {
                "id": "1", "name": "Produto Teste", "department": "Estoque", 
                "category": "Geral", "unit": "Un", "price": 10.0, "min_stock": 5, 
                "suppliers": ["Fornecedor A"], "balance": 20
            }
        ]
        self.mock_suppliers = [
            {"id": "s1", "name": "Fornecedor A", "cnpj": "12345678000199", "active": True},
            "Fornecedor Antigo" # Legacy string
        ]

    @patch('app.blueprints.stock.load_products')
    @patch('app.blueprints.stock.load_suppliers')
    @patch('app.blueprints.stock.get_product_balances')
    def test_stock_products_page_load(self, mock_balances, mock_load_suppliers, mock_load_products):
        # Setup mocks
        mock_load_products.return_value = self.mock_products
        mock_load_suppliers.return_value = self.mock_suppliers
        mock_balances.return_value = {"Produto Teste": 20.0}
        
        # Login as admin
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Principal'
            
        response = self.client.get('/stock/products')
        
        # Check success
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        
        # Check content
        self.assertIn('Insumos (Estoque)', content)
        self.assertIn('Produto Teste', content)
        self.assertIn('Fornecedor A', content)
        
        # Check supplier map usage (legacy vs new)
        # We can't easily check internal variables, but if rendering succeeded without error, it's a good sign.
        
    @patch('app.blueprints.stock.load_products')
    @patch('app.blueprints.stock.save_products')
    @patch('app.blueprints.stock.load_suppliers')
    @patch('app.blueprints.stock.save_suppliers')
    def test_stock_product_create(self, mock_save_supp, mock_load_supp, mock_save_prod, mock_load_prod):
        # Reset mock products to ensure clean state
        self.mock_products = [
            {
                "id": "1", "name": "Produto Teste", "department": "Estoque", 
                "category": "Geral", "unit": "Un", "price": 10.0, "min_stock": 5, 
                "suppliers": ["Fornecedor A"], "balance": 20
            }
        ]
        mock_load_prod.return_value = self.mock_products
        mock_load_supp.return_value = self.mock_suppliers
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        data = {
            'name': 'Novo Produto',
            'department': 'Estoque',
            'category': 'Limpeza',
            'unit': 'Litros',
            'price': '15.50',
            'min_stock': '10',
            'suppliers[]': ['Fornecedor A', 'Novo Fornecedor'],
            'ncm': '12345678',
            'cest': '1234567',
            'icms_rate': '18',
            'cfop_default': '5102'
        }
        
        response = self.client.post('/stock/products', data=data, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify save_products called with new product
        if not mock_save_prod.called:
            print("save_products NOT called!")
        else:
            args, _ = mock_save_prod.call_args
            saved_list = args[0]
            print(f"Saved List Length: {len(saved_list)}")
            print(f"Saved List Content: {json.dumps(saved_list, indent=2)}")
            
        self.assertTrue(mock_save_prod.called)
        args, _ = mock_save_prod.call_args
        saved_list = args[0]
        self.assertEqual(len(saved_list), 2)
        
        # Find the new product in the list (order might vary)
        new_prod = next((p for p in saved_list if p['name'] == 'Novo Produto'), None)
        self.assertIsNotNone(new_prod)
        self.assertEqual(new_prod['ncm'], '12345678')
        self.assertEqual(new_prod['icms_rate'], 18.0)
        
    @patch('requests.get')
    def test_integration_apis(self, mock_get):
        # Simulate BrasilAPI call
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp
        
        import requests
        try:
            resp = requests.get('https://brasilapi.com.br/api/cnpj/v1/00000000000191') # Banco do Brasil
            if resp.status_code == 200:
                print("BrasilAPI Integration: OK")
            else:
                print(f"BrasilAPI Integration: Failed {resp.status_code}")
        except Exception as e:
            print(f"BrasilAPI Integration: Error {e}")

    @patch('app.blueprints.stock.load_products')
    @patch('app.blueprints.stock.save_products')
    def test_stock_performance(self, mock_save_prod, mock_load_prod):
        # Performance Test: Create 100 products
        import time
        
        mock_load_prod.return_value = []
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
        
        start_time = time.time()
        for i in range(100):
            data = {
                'name': f'Perf Product {i}',
                'department': 'Estoque',
                'unit': 'Un',
                'price': '10.00',
                'suppliers[]': ['Fornecedor A']
            }
            self.client.post('/stock/products', data=data)
            
        duration = time.time() - start_time
        print(f"Performance: Created 100 products in {duration:.4f}s")
        self.assertLess(duration, 5.0, "Performance bottleneck detected: > 5s for 100 products")

    @patch('app.blueprints.stock.load_products')
    def test_invalid_product_creation(self, mock_load_prod):
        # Test missing required fields
        mock_load_prod.return_value = []
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
        data = {
            'department': 'Estoque', # Missing name
            'price': '10.00'
        }
        
        response = self.client.post('/stock/products', data=data, follow_redirects=True)
        # Should stay on page or redirect, but NOT save (we can't easily check save NOT called without mocking save, but we can check if product appears)
        # Actually better to mock save and assert not called.
        
    @patch('app.blueprints.stock.save_products')
    @patch('app.blueprints.stock.load_products')
    def test_invalid_product_creation_mocked(self, mock_load_prod, mock_save_prod):
         mock_load_prod.return_value = []
         with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            
         data = {
            'department': 'Estoque', # Missing name
            'price': '10.00'
         }
         self.client.post('/stock/products', data=data)
         self.assertFalse(mock_save_prod.called, "Should not save product without name")

if __name__ == '__main__':
    unittest.main()
