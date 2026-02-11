import unittest
import json
import os
import shutil
import tempfile
import sys

# Add project root to sys.path to allow importing scripts
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from scripts.safe_updater import merge_json_files

class TestUpdaterMerge(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.local_file = os.path.join(self.test_dir, 'local.json')
        self.update_file = os.path.join(self.test_dir, 'update.json')
        
        # Local data (User customizations)
        self.local_data = [
            {
                "id": 1,
                "name": "Custom Name",
                "description": "Custom Description",
                "price": 10.0,
                "questions": ["Q1"],
                "paused": True
            },
            {
                "id": 2,
                "name": "Item 2",
                "price": 20.0
            }
        ]
        
        # Update data (New version)
        self.update_data = [
            {
                "id": 1,
                "name": "Factory Name",
                "description": "Factory Description",
                "price": 15.0, # Price change
                "image_url": "/new/img.png"
            },
            {
                "id": 3,
                "name": "New Item",
                "price": 30.0
            }
        ]
        
        with open(self.local_file, 'w', encoding='utf-8') as f:
            json.dump(self.local_data, f)
            
        with open(self.update_file, 'w', encoding='utf-8') as f:
            json.dump(self.update_data, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_merge_json_files(self):
        """
        Test the actual merge_json_files function from safe_updater.py
        """
        protected_fields = ['name', 'description', 'questions', 'paused']
        
        # Run merge
        success = merge_json_files(self.local_file, self.update_file, protected_fields)
        self.assertTrue(success)
        
        # Verify results
        with open(self.local_file, 'r', encoding='utf-8') as f:
            merged_list = json.load(f)
            
        merged_dict = {item['id']: item for item in merged_list}
        
        # Item 1: Should have Custom Name, Custom Desc, Updated Price, Old Paused, Old Questions, New Image
        self.assertEqual(merged_dict[1]['name'], "Custom Name")
        self.assertEqual(merged_dict[1]['description'], "Custom Description")
        self.assertEqual(merged_dict[1]['price'], 15.0) # Updated price
        self.assertEqual(merged_dict[1]['paused'], True)
        self.assertEqual(merged_dict[1]['questions'], ["Q1"])
        self.assertEqual(merged_dict[1]['image_url'], "/new/img.png")
        
        # Item 3: Should be added
        self.assertIn(3, merged_dict)
        self.assertEqual(merged_dict[3]['name'], "New Item")
        
        # Item 2: Should be kept (not in update)
        self.assertIn(2, merged_dict)
        self.assertEqual(merged_dict[2]['name'], "Item 2")
        
    def test_merge_missing_files(self):
        """Test graceful failure when files are missing"""
        success = merge_json_files("nonexistent.json", self.update_file, [])
        self.assertFalse(success)

if __name__ == '__main__':
    unittest.main()
