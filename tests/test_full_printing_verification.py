import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from app import app, load_printers

class TestFullPrintingVerification(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        app.config['TESTING'] = True
        app.secret_key = 'test_secret'
        
        # Mock session data setup helper
        self.mock_printer_config = [
            {'name': 'Bar Printer', 'ip': '192.168.1.100', 'port': 9100, 'type': 'network'},
            {'name': 'Kitchen Printer', 'ip': '192.168.1.101', 'type': 'network'}
        ]

    def tearDown(self):
        self.app_context.pop()

    @patch('app.load_printers')
    @patch('app.print_cashier_ticket')
    @patch('app.save_cashier_sessions')
    @patch('app.load_cashier_sessions')
    def test_sangria_permission_and_printing(self, mock_load_sessions, mock_save_sessions, mock_print, mock_load_printers):
        """
        Verifica:
        1. Garçom NÃO pode fazer sangria.
        2. Admin PODE fazer sangria.
        3. Impressão é chamada corretamente para Admin.
        """
        print("\n=== TESTE: PERMISSÃO E IMPRESSÃO DE SANGRIA ===")
        mock_load_printers.return_value = self.mock_printer_config
        
        # Mock session state
        mock_session_data = [{
            'id': 'CASHIER_REST_TEST',
            'user': 'admin',
            'type': 'restaurant_service',
            'status': 'open',
            'opening_balance': 100.0,
            'transactions': []
        }]
        mock_load_sessions.return_value = mock_session_data

        # 1. Teste como Garçom (Não autorizado)
        with self.client.session_transaction() as sess:
            sess['user'] = 'Garcom Joao'
            sess['role'] = 'garcom'
            sess['permissions'] = []
        
        resp = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50.00',
            'description': 'Tentativa Garcom'
        }, follow_redirects=True)
        
        content = resp.data.decode('utf-8')
        if "Permissão negada" in content or "Apenas Gerentes" in content:
            print("  [OK] Garçom bloqueado de fazer sangria.")
        else:
            print("  [FALHA] Garçom conseguiu fazer sangria ou mensagem de erro incorreta.")
            print(f"  Conteúdo recebido: {content[:200]}...")
            
        mock_print.assert_not_called()

        # 2. Teste como Admin (Autorizado)
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin User'
            sess['role'] = 'admin'
        
        resp = self.client.post('/restaurant/cashier', data={
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50.00',
            'description': 'Sangria Autorizada'
        }, follow_redirects=True)
        
        content = resp.data.decode('utf-8')
        if "Transação registrada" in content:
            print("  [OK] Admin realizou sangria com sucesso.")
        else:
            print("  [FALHA] Admin não conseguiu fazer sangria.")
            print(f"  Conteúdo recebido: {content[:200]}...")

        # Verificar chamada de impressão
        if mock_print.called:
            args, _ = mock_print.call_args
            # args: (printer_config, type_str, amount, user, reason)
            # Check printer is Bar Printer
            printer = args[0]
            if printer['name'] == 'Bar Printer':
                print("  [OK] Impressora 'Bar Printer' selecionada corretamente.")
            else:
                print(f"  [FALHA] Impressora incorreta selecionada: {printer['name']}")
                
            if args[1] == 'withdrawal' and args[2] == 50.0 and args[4] == 'Sangria Autorizada':
                print("  [OK] Dados da impressão corretos (Valor, Motivo).")
            else:
                print(f"  [FALHA] Dados incorretos: {args}")
        else:
            print("  [FALHA] print_cashier_ticket não foi chamado.")

    @patch('app.load_printers')
    @patch('app.print_transfer_ticket')
    @patch('app.save_table_orders')
    @patch('app.load_table_orders')
    def test_transfer_permission_and_printing(self, mock_load_orders, mock_save_orders, mock_print_transfer, mock_load_printers):
        """
        Verifica:
        1. Garçom NÃO pode transferir mesa.
        2. Admin PODE transferir mesa.
        3. Impressão de transferência é chamada corretamente.
        """
        print("\n=== TESTE: PERMISSÃO E IMPRESSÃO DE TRANSFERÊNCIA ===")
        mock_load_printers.return_value = self.mock_printer_config
        
        # Setup Tables
        initial_orders = {
            '10': {
                'status': 'open',
                'items': [{'name': 'Coca Cola', 'price': 5.0, 'qty': 1}],
                'total': 5.0,
                'opened_at': '08/02/2026 10:00'
            }
        }
        # Copy to avoid mutation issues between calls if side_effect used
        mock_load_orders.return_value = initial_orders.copy()

        # 1. Teste como Garçom (Bloqueado)
        with self.client.session_transaction() as sess:
            sess['user'] = 'Garcom Joao'
            sess['role'] = 'garcom'
        
        resp = self.client.post('/restaurant/table/10', data={
            'action': 'transfer_table',
            'target_table_id': '20'
        }, follow_redirects=True)
        
        content = resp.data.decode('utf-8')
        if "Apenas Supervisores" in content or "Permissão negada" in content:
            print("  [OK] Garçom bloqueado de transferir mesa.")
        else:
            print("  [FALHA] Garçom conseguiu transferir ou erro incorreto.")
        
        mock_print_transfer.assert_not_called()

        # 2. Teste como Admin (Autorizado)
        mock_load_orders.return_value = initial_orders.copy() # Reset
        
        with self.client.session_transaction() as sess:
            sess['user'] = 'Admin User'
            sess['role'] = 'admin'
            
        resp = self.client.post('/restaurant/table/10', data={
            'action': 'transfer_table',
            'target_table_id': '20'
        }, follow_redirects=True)
        
        content = resp.data.decode('utf-8')
        if "Mesa 10 transferida para Mesa 20" in content:
            print("  [OK] Admin transferiu mesa com sucesso.")
        else:
            print("  [FALHA] Admin falhou ao transferir mesa.")
            print(f"  Conteúdo: {content[:200]}...")

        # Verificar chamada de impressão
        if mock_print_transfer.called:
            args, _ = mock_print_transfer.call_args
            # args: (from_table, to_table, waiter_name, printers_config)
            if str(args[0]) == '10' and str(args[1]) == '20':
                 print("  [OK] print_transfer_ticket chamado com mesas corretas.")
            else:
                 print(f"  [FALHA] Args incorretos: {args}")
        else:
             print("  [FALHA] print_transfer_ticket não foi chamado.")

if __name__ == '__main__':
    unittest.main()
