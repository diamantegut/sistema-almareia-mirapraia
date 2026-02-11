import unittest
from datetime import datetime
from app.services.cashier_service import CashierService

class TestCashierDisplay(unittest.TestCase):
    def setUp(self):
        self.base_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    def test_single_payment_transaction(self):
        """Test that single transactions are passed through unchanged."""
        transactions = [
            {
                'id': '1',
                'amount': 100.0,
                'payment_method': 'Dinheiro',
                'description': 'Single Payment',
                'timestamp': self.base_time,
                'details': {}
            }
        ]
        
        result = CashierService.prepare_transactions_for_display(transactions)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '1')
        self.assertFalse(result[0].get('is_group'))

    def test_grouped_payment_transaction(self):
        """Test that transactions with same payment_group_id are grouped."""
        group_id = 'group_123'
        transactions = [
            {
                'id': '1',
                'amount': 60.0,
                'payment_method': 'Cartão',
                'description': 'Sale - Cartão',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            },
            {
                'id': '2',
                'amount': 40.0,
                'payment_method': 'Dinheiro',
                'description': 'Sale - Dinheiro',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            }
        ]
        
        result = CashierService.prepare_transactions_for_display(transactions)
        
        self.assertEqual(len(result), 1)
        group = result[0]
        self.assertTrue(group.get('is_group'))
        self.assertEqual(group['amount'], 100.0)
        self.assertEqual(group['payment_method'], 'Múltiplo')
        self.assertEqual(len(group['sub_transactions']), 2)
        
        # Verify percentages
        sub1 = next(s for s in group['sub_transactions'] if s['method'] == 'Cartão')
        sub2 = next(s for s in group['sub_transactions'] if s['method'] == 'Dinheiro')
        
        self.assertEqual(sub1['amount'], 60.0)
        self.assertEqual(sub1['percent'], 60.0)
        self.assertEqual(sub2['amount'], 40.0)
        self.assertEqual(sub2['percent'], 40.0)

    def test_mixed_transactions(self):
        """Test mixing grouped and single transactions."""
        group_id = 'group_mixed'
        transactions = [
            {
                'id': '1',
                'amount': 50.0,
                'payment_method': 'Pix',
                'description': 'Sale 1',
                'timestamp': self.base_time,
                'details': {}
            },
            {
                'id': '2',
                'amount': 30.0,
                'payment_method': 'Cartão',
                'description': 'Sale 2 - Part 1',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            },
            {
                'id': '3',
                'amount': 70.0,
                'payment_method': 'Dinheiro',
                'description': 'Sale 2 - Part 2',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            }
        ]
        
        result = CashierService.prepare_transactions_for_display(transactions)
        
        self.assertEqual(len(result), 2)
        
        # Find the group
        group = next((t for t in result if t.get('is_group')), None)
        single = next((t for t in result if not t.get('is_group')), None)
        
        self.assertIsNotNone(group)
        self.assertIsNotNone(single)
        
        self.assertEqual(group['amount'], 100.0)
        self.assertEqual(single['amount'], 50.0)

    def test_group_description_cleanup(self):
        """Test that description removes the specific method part if grouped."""
        group_id = 'group_desc'
        transactions = [
            {
                'id': '1',
                'amount': 50.0,
                'payment_method': 'Cartão',
                'description': 'Venda Mesa 10 - Cartão',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            },
            {
                'id': '2',
                'amount': 50.0,
                'payment_method': 'Dinheiro',
                'description': 'Venda Mesa 10 - Dinheiro',
                'timestamp': self.base_time,
                'details': {'payment_group_id': group_id}
            }
        ]
        
        result = CashierService.prepare_transactions_for_display(transactions)
        
        # Should remove the last part after ' - '
        self.assertEqual(result[0]['description'], 'Venda Mesa 10')

    def test_rounding_precision(self):
        """Test percentage calculation with repeating decimals."""
        group_id = 'group_round'
        transactions = [
            {
                'id': '1',
                'amount': 10.0,
                'payment_method': 'A',
                'details': {'payment_group_id': group_id}
            },
            {
                'id': '2',
                'amount': 20.0,
                'payment_method': 'B',
                'details': {'payment_group_id': group_id}
            }
        ]
        # Total 30. 10/30 = 33.333...
        
        result = CashierService.prepare_transactions_for_display(transactions)
        group = result[0]
        
        sub1 = group['sub_transactions'][0]
        self.assertEqual(sub1['percent'], 33.3)

if __name__ == '__main__':
    unittest.main()
