
import unittest
import json
import os
from datetime import datetime
import shutil

# Mocking the data structures and functions found in app.py

class TestStockReversal(unittest.TestCase):
    def setUp(self):
        self.test_dir = 'test_data_stock_reversal'
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        self.products_file = os.path.join(self.test_dir, 'products.json')
        self.stock_entries_file = os.path.join(self.test_dir, 'stock_entries.json')
        
        # Setup initial products (Insumos/Direct Products)
        self.products = [
            {'id': '1', 'name': 'Coca Cola', 'price': 5.0, 'category': 'Bebidas'},
            {'id': '2', 'name': 'Farinha', 'price': 2.0, 'category': 'Insumo'},
            {'id': '3', 'name': 'Ovo', 'price': 0.5, 'category': 'Insumo'}
        ]
        with open(self.products_file, 'w', encoding='utf-8') as f:
            json.dump(self.products, f)
            
        # Setup initial stock entries
        self.stock_entries = []
        with open(self.stock_entries_file, 'w', encoding='utf-8') as f:
            json.dump(self.stock_entries, f)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def load_products(self):
        with open(self.products_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_stock_entry(self, entry_data):
        entries = []
        if os.path.exists(self.stock_entries_file):
            with open(self.stock_entries_file, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        entries.append(entry_data)
        with open(self.stock_entries_file, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=4)

    def test_direct_product_refund(self):
        """
        Simulates the logic found in app.py for removing a non-recipe item (Direct stock refund).
        """
        # Context
        table_id = "10"
        product_name = "Coca Cola" # Matches product in products.json
        qty_removed = 2.0
        
        # Logic from app.py (adapted)
        insumos = self.load_products()
        # Normalize names for comparison
        target_name = product_name.strip().lower()
        insumo_data = next((i for i in insumos if i['name'].strip().lower() == target_name), None)
        
        if insumo_data:
            total_refund = qty_removed
            
            entry_data = {
                'id': f"REFUND_{table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{insumo_data['id']}",
                'user': 'TestUser',
                'product': insumo_data['name'],
                'supplier': f"ESTORNO: Mesa {table_id}",
                'qty': total_refund,
                'price': insumo_data.get('price', 0),
                'invoice': f"Cancelado: {product_name}",
                'date': datetime.now().strftime('%d/%m/%Y'),
                'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
            self.save_stock_entry(entry_data)
            
        # Verify
        with open(self.stock_entries_file, 'r', encoding='utf-8') as f:
            entries = json.load(f)
            
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['product'], 'Coca Cola')
        self.assertEqual(entries[0]['qty'], 2.0)
        self.assertEqual(entries[0]['supplier'], 'ESTORNO: Mesa 10')
        print("Direct product refund test passed!")

    def test_direct_product_refund_case_insensitive(self):
        """
        Simulates the logic found in app.py for removing a non-recipe item with case mismatch.
        """
        # Context
        table_id = "10"
        product_name = "coca cola" # Lowercase, but product is "Coca Cola"
        qty_removed = 1.0
        
        # Logic from app.py (adapted)
        insumos = self.load_products()
        # Normalize names for comparison
        target_name = product_name.strip().lower()
        insumo_data = next((i for i in insumos if i['name'].strip().lower() == target_name), None)
        
        if insumo_data:
            total_refund = qty_removed
            entry_data = {
                'id': f"REFUND_{table_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{insumo_data['id']}",
                'user': 'TestUser',
                'product': insumo_data['name'],
                'product_id': insumo_data['id'],
                'qty': total_refund
            }
            self.save_stock_entry(entry_data)
            
        # Verify
        with open(self.stock_entries_file, 'r', encoding='utf-8') as f:
            entries = json.load(f)
            
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['product'], 'Coca Cola') # Should use the name from products.json
        print("Case insensitive refund test passed!")

if __name__ == '__main__':
    unittest.main()
