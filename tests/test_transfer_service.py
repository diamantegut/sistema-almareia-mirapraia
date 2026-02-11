
import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transfer_service import transfer_table_to_room, TransferError

class TestTransferService(unittest.TestCase):
    
    def setUp(self):
        self.mock_orders = {
            "10": {
                "items": [
                    {"name": "Burger", "price": 20, "qty": 1, "source": "restaurant"},
                    {"name": "Coke", "price": 5, "qty": 1, "source": "minibar"}
                ],
                "total": 25,
                "waiter": "John"
            }
        }
        self.mock_occupancy = {
            "101": {"status": "occupied", "guest": "Guest A"},
            "102": {"status": "cleaning"} # Not occupied
        }
        self.mock_charges = []

    @patch('services.transfer_service.load_json')
    @patch('services.transfer_service.save_json')
    @patch('services.transfer_service.file_lock')
    @patch('services.transfer_service.log_action')
    def test_transfer_success(self, mock_log, mock_lock, mock_save, mock_load):
        # Setup mocks
        mock_load.side_effect = [self.mock_orders, self.mock_occupancy, self.mock_charges]
        mock_save.return_value = True
        mock_lock.return_value.__enter__.return_value = None
        
        # Execute
        success, msg = transfer_table_to_room("10", "101", "Admin")
        
        # Verify
        self.assertTrue(success)
        self.assertIn("sucesso", msg)
        
        # Check if charges were added (2 charges: rest + minibar)
        # save_json called twice: once for charges, once for orders
        self.assertEqual(mock_save.call_count, 2)
        
        # Verify charges payload
        charges_call = mock_save.call_args_list[0]
        self.assertEqual(charges_call[0][0], 'room_charges.json')
        saved_charges = charges_call[0][1]
        self.assertEqual(len(saved_charges), 2)
        self.assertEqual(saved_charges[0]['type'], 'restaurant')
        self.assertEqual(saved_charges[1]['type'], 'minibar')
        
        # Verify table closed (or cleared if <= 35)
        orders_call = mock_save.call_args_list[1]
        self.assertEqual(orders_call[0][0], 'table_orders.json')
        saved_orders = orders_call[0][1]
        # Table 10 is <= 35, so it stays but empty
        self.assertIn("10", saved_orders)
        self.assertEqual(saved_orders["10"]['items'], [])
        self.assertEqual(saved_orders["10"]['total'], 0)

    @patch('services.transfer_service.load_json')
    @patch('services.transfer_service.save_json')
    @patch('services.transfer_service.file_lock')
    def test_room_not_found(self, mock_lock, mock_save, mock_load):
        mock_load.side_effect = [self.mock_orders, self.mock_occupancy, self.mock_charges]
        mock_lock.return_value.__enter__.return_value = None
        
        with self.assertRaises(TransferError) as cm:
            transfer_table_to_room("10", "999", "Admin")
        
        self.assertIn("não encontrado", str(cm.exception))

    @patch('services.transfer_service.load_json')
    @patch('services.transfer_service.save_json')
    @patch('services.transfer_service.file_lock')
    def test_room_wrong_status(self, mock_lock, mock_save, mock_load):
        mock_load.side_effect = [self.mock_orders, self.mock_occupancy, self.mock_charges]
        mock_lock.return_value.__enter__.return_value = None
        
        with self.assertRaises(TransferError) as cm:
            transfer_table_to_room("10", "102", "Admin") # 102 is cleaning
        
        self.assertIn("não está ocupado", str(cm.exception))

    @patch('services.transfer_service.load_json')
    @patch('services.transfer_service.save_json')
    @patch('services.transfer_service.file_lock')
    def test_fuzzy_room_match(self, mock_lock, mock_save, mock_load):
        # Test "0101" -> "101"
        mock_load.side_effect = [self.mock_orders, self.mock_occupancy, self.mock_charges]
        mock_save.return_value = True
        mock_lock.return_value.__enter__.return_value = None
        
        success, msg = transfer_table_to_room("10", "0101", "Admin")
        self.assertTrue(success)
        self.assertIn("101", msg)

    @patch('services.transfer_service.load_json')
    @patch('services.transfer_service.save_json')
    @patch('services.transfer_service.file_lock')
    @patch('services.transfer_service.log_action')
    def test_revert_on_table_save_fail(self, mock_log, mock_lock, mock_save, mock_load):
        mock_load.side_effect = [self.mock_orders, self.mock_occupancy, self.mock_charges]
        mock_lock.return_value.__enter__.return_value = None
        
        # First save (charges) succeeds, second (table) fails
        mock_save.side_effect = [True, False, True] # True(charges), False(table), True(revert charges)
        
        with self.assertRaises(TransferError) as cm:
            transfer_table_to_room("10", "101", "Admin")
            
        self.assertIn("Falha ao atualizar mesa", str(cm.exception))
        
        # Verify revert called (save charges called again with original list essentially)
        # Note: In my impl, I append then remove.
        # Call 1: save charges (2 added) -> Returns True
        # Call 2: save orders -> Returns False
        # Call 3: save charges (removed) -> Returns True
        self.assertEqual(mock_save.call_count, 3)
        
        # Verify the 3rd call restored the list (empty in this case)
        revert_call = mock_save.call_args_list[2]
        saved_charges = revert_call[0][1]
        self.assertEqual(len(saved_charges), 0)

if __name__ == '__main__':
    unittest.main()
