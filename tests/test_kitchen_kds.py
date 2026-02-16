import unittest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app


class TestKitchenKDS(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.app.config['TESTING'] = True
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Cozinha'

    @patch('app.blueprints.kitchen.load_table_orders')
    @patch('app.blueprints.kitchen.load_menu_items')
    def test_kds_data_filters_by_station_and_marks_late(self, mock_menu, mock_orders):
        now = datetime.now()
        old_time = (now - timedelta(minutes=50)).strftime('%d/%m/%Y %H:%M')
        mock_menu.return_value = []
        mock_orders.return_value = {
            '10': {
                'status': 'open',
                'opened_at': old_time,
                'items': [
                    {
                        'id': 'item1',
                        'name': 'Batata Frita',
                        'qty': 1,
                        'category': 'Petiscos',
                        'created_at': old_time
                    },
                    {
                        'id': 'item2',
                        'name': 'Refrigerante',
                        'qty': 1,
                        'category': 'Bebidas',
                        'created_at': old_time
                    }
                ]
            }
        }
        response = self.client.get('/kitchen/kds/data?station=cozinha')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        payload = data['data']
        self.assertEqual(payload['station'], 'kitchen')
        self.assertEqual(len(payload['orders']), 1)
        order = payload['orders'][0]
        self.assertTrue(order['is_late'])
        all_items = []
        for sec in order['sections']:
            all_items.extend(sec['items'])
        self.assertEqual(len(all_items), 1)
        self.assertEqual(all_items[0]['id'], 'item1')

    @patch('app.blueprints.kitchen.save_table_orders')
    @patch('app.blueprints.kitchen.load_table_orders')
    def test_update_status_changes_item_and_sets_timestamps(self, mock_load, mock_save):
        base_time = datetime.now().strftime('%d/%m/%Y %H:%M')
        mock_load.return_value = {
            '10': {
                'status': 'open',
                'opened_at': base_time,
                'items': [
                    {
                        'id': 'item1',
                        'name': 'Prato',
                        'qty': 1,
                        'category': 'Principal',
                        'created_at': base_time
                    }
                ]
            }
        }
        resp = self.client.post(
            '/kitchen/kds/update_status',
            json={'table_id': '10', 'item_id': 'item1', 'status': 'preparing'}
        )
        self.assertEqual(resp.status_code, 200)
        saved_orders = mock_save.call_args[0][0]
        item = saved_orders['10']['items'][0]
        self.assertEqual(item['kds_status'], 'preparing')
        self.assertIn('kds_start_time', item)

    @patch('app.blueprints.kitchen.save_table_orders')
    @patch('app.blueprints.kitchen.load_table_orders')
    def test_mark_received_archives_items(self, mock_load, mock_save):
        base_time = datetime.now().strftime('%d/%m/%Y %H:%M')
        mock_load.return_value = {
            '10': {
                'status': 'open',
                'opened_at': base_time,
                'items': [
                    {
                        'id': 'item1',
                        'name': 'Prato',
                        'qty': 1,
                        'category': 'Principal',
                        'created_at': base_time,
                        'kds_status': 'done'
                    }
                ]
            }
        }
        resp = self.client.post(
            '/kitchen/kds/mark_received',
            json={'table_id': '10', 'item_ids': ['item1']}
        )
        self.assertEqual(resp.status_code, 200)
        saved_orders = mock_save.call_args[0][0]
        item = saved_orders['10']['items'][0]
        self.assertEqual(item['kds_status'], 'archived')

    @patch('app.blueprints.kitchen.save_table_orders')
    @patch('app.blueprints.kitchen.load_table_orders')
    @patch('app.blueprints.kitchen.load_menu_items')
    def test_auto_archive_after_120_minutes_pending_no_interaction(self, mock_menu, mock_load, mock_save):
        mock_menu.return_value = []
        old = (datetime.now() - timedelta(minutes=130)).strftime('%d/%m/%Y %H:%M')
        mock_load.return_value = {
            '10': {
                'status': 'open',
                'opened_at': old,
                'items': [
                    {
                        'id': 'item1',
                        'name': 'Prato',
                        'qty': 1,
                        'category': 'Principal',
                        'created_at': old,
                        'kds_status': 'pending'
                    }
                ]
            }
        }
        r = self.client.get('/kitchen/kds/data?station=cozinha')
        self.assertEqual(r.status_code, 200)
        # Deve ter disparado save_table_orders por autoarquivamento
        self.assertTrue(mock_save.called)
        saved_orders = mock_save.call_args[0][0]
        item = saved_orders['10']['items'][0]
        self.assertEqual(item['kds_status'], 'archived')
        self.assertTrue(item.get('kds_no_interaction', False))


if __name__ == '__main__':
    unittest.main()
