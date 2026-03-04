
import unittest
import io
import os
import tempfile
from datetime import datetime
from unittest.mock import patch
from flask import session
from app import create_app
from app.services.card_reconciliation_service import reconcile_transactions

class TestAdminRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.client = self.app.test_client()

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
            sess['permissions'] = ['admin']

    def test_admin_route(self):
        self.login_as_admin()
        response = self.client.get('/admin', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data) # Assuming title or content

    def test_admin_dashboard_route(self):
        self.login_as_admin()
        response = self.client.get('/admin/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data)

    def test_admin_system_dashboard_route(self):
        self.login_as_admin()
        response = self.client.get('/admin/system/dashboard', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Painel Administrativo', response.data)

    def test_admin_unauthorized(self):
        # No login
        response = self.client.get('/admin', follow_redirects=True)
        # Should redirect to login or main index
        # Based on @login_required decorator logic
        self.assertIn(b'Login', response.data) # Assuming login page has "Login" text

    def test_reconciliation_page_has_period_filter(self):
        self.login_as_admin()
        response = self.client.get('/admin/reconciliation', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="start_date"', response.data)
        self.assertIn(b'name="end_date"', response.data)

    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    def test_reconciliation_shows_account_summary_button(
        self,
        mock_load_sessions,
        mock_fetch_pagseguro,
        _mock_audit,
        _mock_log
    ):
        self.login_as_admin()
        mock_load_sessions.return_value = [{
            'type': 'guest_consumption',
            'transactions': [{
                'id': 'tx-room-link',
                'type': 'sale',
                'timestamp': '05/03/2026 10:00',
                'amount': 90.0,
                'description': 'Fechamento Conta Quarto 101',
                'payment_method': 'Cartão Crédito',
                'details': {'room_number': '101'},
                'user': 'caixa1'
            }]
        }]
        mock_fetch_pagseguro.return_value = []
        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-05',
            'end_date': '2026-03-05'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'js-open-account-summary', response.data)
        self.assertIn(b'Resumo da Conta Paga', response.data)

    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.reconcile_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    def test_reconciliation_sync_filters_cashiers_by_department(
        self,
        mock_fetch_pagseguro,
        mock_load_sessions,
        mock_reconcile,
        _mock_log,
        _mock_audit
    ):
        self.login_as_admin()
        mock_fetch_pagseguro.return_value = [{
            'provider': 'PagSeguro (Conta 1)',
            'date': datetime(2026, 3, 1, 12, 0),
            'amount': 100.0,
            'type': '1',
            'status': '3',
            'original_row': {'code': 'abc'}
        }]
        mock_load_sessions.return_value = [
            {
                'type': 'guest_consumption',
                'transactions': [
                    {
                        'id': 'tx-day-before',
                        'type': 'sale',
                        'timestamp': '28/02/2026 23:30',
                        'amount': 99.0,
                        'description': 'Recepção Dia 2',
                        'payment_method': 'Cartão Crédito'
                    },
                    {
                        'id': 'tx-allowed',
                        'type': 'sale',
                        'timestamp': '01/03/2026 12:05',
                        'amount': 100.0,
                        'description': 'Recepção Dia 3',
                        'payment_method': 'Cartão Crédito'
                    }
                ]
            },
            {
                'type': 'reservation_cashier',
                'transactions': [{
                    'id': 'tx-blocked',
                    'type': 'sale',
                    'timestamp': '01/03/2026 12:06',
                    'amount': 100.0,
                    'description': 'Reserva',
                    'payment_method': 'Crédito'
                }]
            }
        ]
        mock_reconcile.return_value = {
            'matched': [],
            'unmatched_system': [],
            'unmatched_card': []
        }

        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-01',
            'end_date': '2026-03-01'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        system_transactions = mock_reconcile.call_args[0][0]
        self.assertEqual(len(system_transactions), 2)
        tx_ids = [t['id'] for t in system_transactions]
        self.assertIn('tx-allowed', tx_ids)
        self.assertIn('tx-blocked', tx_ids)

    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.reconcile_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    @patch('app.blueprints.finance.routes.parse_pagseguro_csv')
    @patch('app.blueprints.finance.routes.os.remove')
    def test_reconciliation_upload_renders_template_with_settings(
        self,
        _mock_remove,
        mock_parse_pagseguro,
        mock_load_sessions,
        mock_reconcile,
        _mock_log,
        _mock_audit
    ):
        self.login_as_admin()
        self.app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
        mock_parse_pagseguro.return_value = [{
            'provider': 'PagSeguro',
            'date': datetime(2026, 3, 1, 10, 0),
            'amount': 50.0,
            'type': '1',
            'status': '3',
            'original_row': {'code': 'csv-1'}
        }]
        mock_load_sessions.return_value = []
        mock_reconcile.return_value = {
            'matched': [],
            'unmatched_system': [],
            'unmatched_card': []
        }

        response = self.client.post('/admin/reconciliation/upload', data={
            'provider': 'pagseguro',
            'file': (io.BytesIO(b'fake-csv-content'), 'pagseguro.csv')
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Configurar Integra', response.data)
        temp_file = os.path.join(self.app.config['UPLOAD_FOLDER'], 'pagseguro.csv')
        if os.path.exists(temp_file):
            os.remove(temp_file)

    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    def test_reconciliation_sync_rejects_invalid_period(self, mock_fetch_pagseguro):
        self.login_as_admin()
        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-10',
            'end_date': '2026-03-01'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Per\xc3\xadodo inv\xc3\xa1lido', response.data)
        mock_fetch_pagseguro.assert_not_called()

    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    def test_reconciliation_sync_rejects_invalid_provider(self, mock_fetch_pagseguro):
        self.login_as_admin()
        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'desconhecido',
            'start_date': '2026-03-01',
            'end_date': '2026-03-01'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Adquirente inv\xc3\xa1lido', response.data)
        mock_fetch_pagseguro.assert_not_called()

    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.reconcile_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    def test_reconciliation_sync_accepts_legacy_single_date(
        self,
        mock_fetch_pagseguro,
        mock_load_sessions,
        mock_reconcile,
        _mock_log,
        _mock_audit
    ):
        self.login_as_admin()
        mock_fetch_pagseguro.return_value = []
        mock_load_sessions.return_value = []
        mock_reconcile.return_value = {
            'matched': [],
            'unmatched_system': [],
            'unmatched_card': []
        }

        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'date': '2026-03-01'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_fetch_pagseguro.called)
        start_date = mock_fetch_pagseguro.call_args[0][0]
        end_date = mock_fetch_pagseguro.call_args[0][1]
        self.assertEqual(start_date.strftime('%Y-%m-%d'), '2026-03-01')
        self.assertEqual(end_date.strftime('%Y-%m-%d'), '2026-03-01')

    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    @patch('app.blueprints.finance.routes.load_card_settings')
    def test_reconciliation_sync_marks_other_pagseguro_token_for_confirmation(
        self,
        mock_load_card_settings,
        mock_load_sessions,
        mock_fetch_pagseguro,
        mock_append_audit
    ):
        self.login_as_admin()
        mock_load_card_settings.return_value = {
            'pagseguro': [
                {'alias': 'Matriz', 'email': 'm@x.com', 'token': 'a'},
                {'alias': 'Filial', 'email': 'f@x.com', 'token': 'b'}
            ]
        }
        mock_load_sessions.return_value = [{
            'type': 'guest_consumption',
            'transactions': [{
                'id': 'tx-1',
                'type': 'sale',
                'timestamp': '05/03/2026 10:05',
                'amount': 100.0,
                'description': 'Fechamento Conta Quarto 101',
                'payment_method': 'Cartão Crédito',
                'details': {}
            }]
        }]
        mock_fetch_pagseguro.return_value = [{
            'provider': 'PagSeguro (Filial)',
            'date': datetime(2026, 3, 5, 10, 10),
            'amount': 100.0,
            'type': '1',
            'status': '3',
            'original_row': {'code': 'abc'}
        }]

        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-05',
            'end_date': '2026-03-05'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'outro token', response.data.lower())
        self.assertTrue(mock_append_audit.called)

    def test_reconcile_transactions_matches_payment_group_id_sum(self):
        system_transactions = [
            {
                'id': 'sys-1',
                'timestamp': datetime(2026, 3, 4, 10, 10),
                'amount': 120.0,
                'description': 'Fechamento Conta Quarto 101',
                'payment_method': 'Cartão Crédito',
                'details': {'payment_group_id': 'grp-1'}
            },
            {
                'id': 'sys-2',
                'timestamp': datetime(2026, 3, 4, 10, 12),
                'amount': 80.0,
                'description': 'Fechamento Conta Quarto 102',
                'payment_method': 'Cartão Crédito',
                'details': {'payment_group_id': 'grp-1'}
            }
        ]
        card_transactions = [
            {
                'provider': 'PagSeguro',
                'date': datetime(2026, 3, 4, 10, 15),
                'amount': 200.0,
                'original_row': {}
            }
        ]

        result = reconcile_transactions(system_transactions, card_transactions)
        self.assertEqual(len(result['matched']), 1)
        self.assertEqual(len(result['unmatched_system']), 0)
        self.assertEqual(len(result['unmatched_card']), 0)
        self.assertEqual(result['matched'][0]['status'], 'matched_group')
        self.assertEqual(result['matched'][0]['system']['amount'], 200.0)

    def test_reconcile_transactions_matches_combined_room_charges_without_group_id(self):
        system_transactions = [
            {
                'id': 'sys-10',
                'timestamp': datetime(2026, 3, 4, 18, 1),
                'amount': 150.0,
                'description': 'Fechamento Conta Quarto 201',
                'payment_method': 'Cartão Crédito',
                'details': {}
            },
            {
                'id': 'sys-11',
                'timestamp': datetime(2026, 3, 4, 18, 3),
                'amount': 250.0,
                'description': 'Fechamento Conta Quarto 202',
                'payment_method': 'Cartão Crédito',
                'details': {}
            }
        ]
        card_transactions = [
            {
                'provider': 'PagSeguro',
                'date': datetime(2026, 3, 4, 18, 5),
                'amount': 400.0,
                'original_row': {}
            }
        ]

        result = reconcile_transactions(system_transactions, card_transactions)
        self.assertEqual(len(result['matched']), 1)
        self.assertEqual(len(result['unmatched_system']), 0)
        self.assertEqual(len(result['unmatched_card']), 0)
        self.assertEqual(result['matched'][0]['status'], 'matched_group')
        self.assertEqual(result['matched'][0]['system']['amount'], 400.0)

    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    def test_reconciliation_approve_route_registers_manual_approval(self, mock_append):
        self.login_as_admin()
        response = self.client.post('/admin/reconciliation/approve', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-05',
            'end_date': '2026-03-05',
            'system_id': 'tx-100',
            'room_number': '101',
            'card_provider': 'PagSeguro (Filial)',
            'card_amount': '200.00',
            'card_date': '2026-03-05 18:30',
            'approved_reason': 'Mesmo valor, recebimento tardio'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'marcada para aprova', response.data.lower())
        self.assertTrue(mock_append.called)

    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.load_card_settings')
    @patch('app.blueprints.finance.routes.load_reconciliation_audits')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    def test_reconciliation_sync_hides_previously_approved_suspect(
        self,
        mock_load_sessions,
        mock_fetch_pagseguro,
        mock_load_audits,
        mock_load_card_settings,
        _mock_append,
        _mock_log
    ):
        self.login_as_admin()
        mock_load_card_settings.return_value = {'pagseguro': []}
        mock_load_sessions.return_value = [{
            'type': 'guest_consumption',
            'transactions': [{
                'id': 'tx-200',
                'type': 'sale',
                'timestamp': '05/03/2026 10:00',
                'amount': 200.0,
                'description': 'Fechamento Conta Quarto 101',
                'payment_method': 'Cartão Crédito',
                'user': 'caixa1',
                'details': {'room_number': '101'}
            }]
        }]
        mock_fetch_pagseguro.return_value = [{
            'provider': 'PagSeguro (Filial)',
            'date': datetime(2026, 3, 5, 16, 0),
            'amount': 200.0,
            'type': '1',
            'status': '3',
            'original_row': {}
        }]
        mock_load_audits.return_value = [{
            'source': 'manual_approval',
            'results': {
                'approval_signature': 'tx-200|PagSeguro (Filial)|200.00'
            }
        }]

        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-05',
            'end_date': '2026-03-05'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sem suspeitas de falso negativo por hor', response.data)
        self.assertIn(b'Aprovado manualmente pelo ADM', response.data)

    @patch('app.blueprints.finance.routes.log_system_action')
    @patch('app.blueprints.finance.routes.append_reconciliation_audit')
    @patch('app.blueprints.finance.routes.load_card_settings')
    @patch('app.blueprints.finance.routes.load_reconciliation_audits')
    @patch('app.blueprints.finance.routes.fetch_pagseguro_transactions')
    @patch('app.blueprints.finance.routes._load_cashier_sessions')
    def test_reconciliation_sync_marks_suspect_when_amount_diff_within_five_percent(
        self,
        mock_load_sessions,
        mock_fetch_pagseguro,
        mock_load_audits,
        mock_load_card_settings,
        _mock_append,
        _mock_log
    ):
        self.login_as_admin()
        mock_load_card_settings.return_value = {'pagseguro': []}
        mock_load_audits.return_value = []
        mock_load_sessions.return_value = [{
            'type': 'guest_consumption',
            'transactions': [{
                'id': 'tx-300',
                'type': 'sale',
                'timestamp': '05/03/2026 10:00',
                'amount': 100.0,
                'description': 'Fechamento Conta Quarto 203',
                'payment_method': 'Cartão Crédito',
                'user': 'caixa2',
                'details': {'room_number': '203', 'guest_name': 'João'}
            }]
        }]
        mock_fetch_pagseguro.return_value = [{
            'provider': 'PagSeguro (Filial)',
            'date': datetime(2026, 3, 5, 10, 10),
            'amount': 104.0,
            'type': '1',
            'status': '3',
            'original_row': {}
        }]

        response = self.client.post('/admin/reconciliation/sync', data={
            'provider': 'pagseguro',
            'start_date': '2026-03-05',
            'end_date': '2026-03-05'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Diferen', response.data)
        self.assertIn(b'5%', response.data)

if __name__ == '__main__':
    unittest.main()
