import unittest
from unittest.mock import patch, MagicMock
import os
import json
import tempfile
import uuid
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services import data_service

class TestStockDeduplication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, 'stock_entries.json')
        with open(self.temp_file, 'w') as f:
            json.dump([], f)
            
        # Patch the file path in data_service
        self.patcher = patch('app.services.data_service.STOCK_ENTRIES_FILE', self.temp_file)
        self.patcher.start()
        
        # Patch load_stock_entries to use the temp file logic (since it might use _load_json which uses the constant)
        # Actually, data_service uses the constant imported at module level?
        # Let's check data_service.py imports.
        # It imports STOCK_ENTRIES_FILE from system_config_manager.
        # So we need to patch data_service.STOCK_ENTRIES_FILE.
        pass

    def tearDown(self):
        self.patcher.stop()
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_deduplication_logic(self):
        """Test that add_stock_entries_batch prevents duplicate IDs."""
        # 1. Create an entry with ID
        entry_id = str(uuid.uuid4())
        entry = {
            'id': entry_id,
            'product': 'Test Product',
            'qty': -1,
            'date': '22/02/2026',
            'user': 'tester'
        }
        
        # 2. Add it first time
        added = data_service.add_stock_entries_batch([entry])
        self.assertEqual(added, 1, "Should add new entry")
        
        entries = data_service.load_stock_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['id'], entry_id)
        
        # 3. Add SAME entry again (simulating double click / race condition retry)
        added = data_service.add_stock_entries_batch([entry])
        self.assertEqual(added, 0, "Should NOT add duplicate entry")
        
        entries = data_service.load_stock_entries()
        self.assertEqual(len(entries), 1, "Count should remain 1")
        
        # 4. Add new entry
        entry2 = entry.copy()
        entry2['id'] = str(uuid.uuid4())
        added = data_service.add_stock_entries_batch([entry2])
        self.assertEqual(added, 1, "Should add second unique entry")
        
        entries = data_service.load_stock_entries()
        self.assertEqual(len(entries), 2)

    def test_batch_mixed_duplicates(self):
        """Test batch containing both new and existing IDs."""
        entry1 = {'id': 'id1', 'val': 1}
        entry2 = {'id': 'id2', 'val': 2}
        
        # Pre-populate entry1
        data_service.add_stock_entries_batch([entry1])
        
        # Try to add entry1 again + entry2
        added = data_service.add_stock_entries_batch([entry1, entry2])
        self.assertEqual(added, 1, "Should only add entry2")
        
        entries = data_service.load_stock_entries()
        ids = [e['id'] for e in entries]
        self.assertIn('id1', ids)
        self.assertIn('id2', ids)
        self.assertEqual(len(entries), 2)

    def test_legacy_entry_support(self):
        """Test that entries without ID are still added (legacy behavior)."""
        entry_no_id = {'product': 'Legacy', 'qty': 1}
        
        added = data_service.add_stock_entries_batch([entry_no_id])
        self.assertEqual(added, 1)
        
        entries = data_service.load_stock_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['product'], 'Legacy')
        
        # Adding another one without ID should also be added (no deduplication possible)
        added = data_service.add_stock_entries_batch([entry_no_id])
        self.assertEqual(added, 1)
        self.assertEqual(len(data_service.load_stock_entries()), 2)

if __name__ == '__main__':
    unittest.main()
