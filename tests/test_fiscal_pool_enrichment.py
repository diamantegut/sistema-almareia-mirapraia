import unittest
from unittest.mock import patch, MagicMock
from app.services.fiscal_pool_service import FiscalPoolService

class TestFiscalPoolEnrichment(unittest.TestCase):
    def setUp(self):
        # Setup mocks for all tests
        self.patcher_load = patch('app.services.fiscal_pool_service.FiscalPoolService._load_pool')
        self.mock_load = self.patcher_load.start()
        
        self.patcher_save = patch('app.services.fiscal_pool_service.FiscalPoolService._save_pool')
        self.mock_save = self.patcher_save.start()
        
        self.patcher_menu = patch('app.services.fiscal_pool_service.load_menu_items')
        self.mock_menu = self.patcher_menu.start()

    def tearDown(self):
        self.patcher_load.stop()
        self.patcher_save.stop()
        self.patcher_menu.stop()

    def test_add_to_pool_enrichment(self):
        # Setup Mock Data
        self.mock_load.return_value = []
        
        # Mock Menu Data - The source of truth
        self.mock_menu.return_value = [
            {
                'id': '1',
                'name': 'Coca Cola',
                'price': 5.0,
                'ncm': '22021000',
                'cest': '0300700',
                'cfop': '5102',
                'origin': 0,
                'active': True
            }
        ]
        
        # Input Items (Raw from Charge - minimal info)
        items = [
            {
                'id': '1', 
                'name': 'Coca Cola', 
                'qty': 2, 
                'price': 5.0,
                'total': 10.0
            }
        ]
        
        payment_methods = [
            {'method': 'Dinheiro', 'amount': 10.0, 'is_fiscal': True}
        ]
        
        # Execute
        FiscalPoolService.add_to_pool(
            origin='restaurant',
            original_id='TEST_1',
            total_amount=10.0,
            items=items,
            payment_methods=payment_methods,
            user='test_user'
        )
        
        # Verify
        self.assertTrue(self.mock_save.called)
        # Get the pool passed to save
        args, _ = self.mock_save.call_args
        saved_pool = args[0]
        entry = saved_pool[-1]
        
        # Check Enrichment
        # The item in pool should now have NCM, CFOP etc from menu
        item_in_pool = entry['items'][0]
        
        self.assertEqual(item_in_pool['ncm'], '22021000')
        self.assertEqual(item_in_pool['cfop'], '5102')
        self.assertEqual(item_in_pool['origin'], 0)
        self.assertEqual(item_in_pool['cest'], '0300700')
        
    def test_update_status_with_error(self):
        # Setup Pool with one entry
        entry = {'id': 'test_id', 'status': 'pending', 'history': []}
        self.mock_load.return_value = [entry]
        
        # Execute
        FiscalPoolService.update_status('test_id', 'failed', error_msg='Test Error Message')
        
        # Verify
        # Since we modified the dict in place inside the mock return list, we can check it
        self.assertEqual(entry['status'], 'failed')
        self.assertEqual(entry.get('last_error'), 'Test Error Message')
        self.assertEqual(entry['history'][-1]['details'], 'Test Error Message')

if __name__ == '__main__':
    unittest.main()
