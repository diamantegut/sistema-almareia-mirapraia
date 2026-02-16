import unittest
import json
import os
import time
import shutil
from datetime import datetime, timedelta
from app import create_app
from app.services import data_service, cashier_service, transfer_service
from app.blueprints.reception import routes as reception_routes
from app.blueprints.governance import routes as governance_routes

# Mock data paths
TEST_DATA_DIR = r'tests\test_data_comprehensive'

class TestReceptionComprehensive(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
    def setUp(self):
        # Patch data paths
        self.original_occupancy = data_service.ROOM_OCCUPANCY_FILE
        self.original_cleaning = data_service.CLEANING_STATUS_FILE
        self.original_charges = data_service.ROOM_CHARGES_FILE
        self.original_orders = data_service.TABLE_ORDERS_FILE
        self.original_sessions = cashier_service.CASHIER_SESSIONS_FILE
        self.original_data_sessions = data_service.CASHIER_SESSIONS_FILE
        self.original_products = data_service.PRODUCTS_FILE
        self.original_menu = data_service.MENU_ITEMS_FILE
        self.original_get_data_path = transfer_service.get_data_path
        
        # Define test file paths
        self.test_occupancy = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        self.test_cleaning = os.path.join(TEST_DATA_DIR, 'cleaning_status.json')
        self.test_charges = os.path.join(TEST_DATA_DIR, 'room_charges.json')
        self.test_orders = os.path.join(TEST_DATA_DIR, 'table_orders.json')
        self.test_sessions = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        self.test_products = os.path.join(TEST_DATA_DIR, 'products.json')
        self.test_menu = os.path.join(TEST_DATA_DIR, 'menu_items.json')

        # Apply patches
        data_service.ROOM_OCCUPANCY_FILE = self.test_occupancy
        data_service.CLEANING_STATUS_FILE = self.test_cleaning
        data_service.ROOM_CHARGES_FILE = self.test_charges
        data_service.TABLE_ORDERS_FILE = self.test_orders
        data_service.PRODUCTS_FILE = self.test_products
        data_service.MENU_ITEMS_FILE = self.test_menu
        cashier_service.CASHIER_SESSIONS_FILE = self.test_sessions
        data_service.CASHIER_SESSIONS_FILE = self.test_sessions
        transfer_service.get_data_path = lambda filename: os.path.join(TEST_DATA_DIR, filename)
        
        # Also patch routes if they import directly (common issue in Flask)
        reception_routes.ROOM_OCCUPANCY_FILE = self.test_occupancy # Just in case
        
        self.reset_data()
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'admin']
            sess['department'] = 'Recepção'

    def tearDown(self):
        # Restore paths
        data_service.ROOM_OCCUPANCY_FILE = self.original_occupancy
        data_service.CLEANING_STATUS_FILE = self.original_cleaning
        data_service.ROOM_CHARGES_FILE = self.original_charges
        data_service.TABLE_ORDERS_FILE = self.original_orders
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions
        data_service.PRODUCTS_FILE = self.original_products
        data_service.MENU_ITEMS_FILE = self.original_menu
        data_service.CASHIER_SESSIONS_FILE = self.original_data_sessions
        transfer_service.get_data_path = self.original_get_data_path

    def reset_data(self):
        with open(self.test_occupancy, 'w') as f: json.dump({}, f)
        with open(self.test_cleaning, 'w') as f: json.dump({}, f)
        with open(self.test_charges, 'w') as f: json.dump([], f)
        with open(self.test_orders, 'w') as f: json.dump({}, f)
        with open(self.test_sessions, 'w') as f: json.dump([], f)
        
        # Mock Products/Menu
        products = [{'id': '1', 'name': 'Água', 'price': 5.0, 'category': 'Bebidas'}]
        with open(self.test_products, 'w') as f: json.dump(products, f)
        with open(self.test_menu, 'w') as f: json.dump(products, f)

    def _measure_performance(self, func, *args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        self.assertLess(duration, 3.0, f"Performance failed: {duration:.4f}s > 3.0s")
        return result

    # 1. Check-in de hóspede
    def test_01_checkin_process(self):
        print("\n--- Test 1: Check-in Process ---")
        data = {
            'action': 'checkin',
            'room_number': '01',
            'guest_name': 'Teste Hóspede',
            'checkin_date': datetime.now().strftime('%Y-%m-%d'),
            'checkout_date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
            'num_adults': 2,
            'doc_id': '12345678900'
        }
        
        response = self._measure_performance(
            self.client.post, '/reception/rooms', data=data, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        
        occupancy = data_service.load_room_occupancy()
        self.assertIn('01', occupancy)
        self.assertEqual(occupancy['01']['guest_name'], 'Teste Hóspede')

    # 2. Check-out
    def test_02_checkout_process(self):
        print("\n--- Test 2: Check-out Process ---")
        # Setup: Occupy room
        data_service.save_room_occupancy({'01': {'guest_name': 'Leaving Guest'}})
        
        data = {'action': 'checkout', 'room_number': '01'}
        response = self._measure_performance(
            self.client.post, '/reception/rooms', data=data, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        
        occupancy = data_service.load_room_occupancy()
        self.assertNotIn('01', occupancy)
        
        cleaning = data_service.load_cleaning_status()
        self.assertEqual(cleaning['01']['status'], 'dirty_checkout')

    # 3. Limpeza e manutenção
    def test_03_cleaning_maintenance(self):
        print("\n--- Test 3: Cleaning & Maintenance ---")
        # Setup: Room is dirty
        data_service.save_cleaning_status({'01': {'status': 'dirty'}})
        
        data_service.save_cleaning_status({'01': {'status': 'clean'}})
        
        response = self.client.get('/reception/rooms')
        self.assertIn(b'Aguardando Inspe', response.data)

    # 4. Inspeção de quartos
    def test_04_inspection(self):
        print("\n--- Test 4: Inspection ---")
        data_service.save_cleaning_status({'01': {'status': 'clean'}})
        
        data = {
            'action': 'inspect_room',
            'room_number': '01',
            'inspection_result': 'passed',
            'observation': 'Tudo limpo'
        }
        
        response = self.client.post('/reception/rooms', data=data, follow_redirects=True)
        status = data_service.load_cleaning_status()
        self.assertEqual(status['01']['status'], 'inspected')

    # 5. Mudança de quarto
    def test_05_room_transfer(self):
        print("\n--- Test 5: Room Transfer ---")
        data_service.save_room_occupancy({'01': {'guest_name': 'Mover'}})
        
        data = {
            'action': 'transfer_guest',
            'old_room': '01',
            'new_room': '02',
            'reason': 'Barulho'
        }
        
        self.client.post('/reception/rooms', data=data, follow_redirects=True)
        occupancy = data_service.load_room_occupancy()
        self.assertNotIn('01', occupancy)
        self.assertIn('02', occupancy)
        self.assertEqual(occupancy['02']['guest_name'], 'Mover')

    # 6. Pagamento de consumos (Setup for next tests)
    def _create_charge(self, room='01', amount=100.0, status='pending', table_id=None):
        charges = data_service.load_room_charges()
        charges.append({
            'id': 'charge_1',
            'room_number': room,
            'total': amount,
            'status': status,
            'items': [{'name': 'Jantar', 'price': amount, 'qty': 1, 'category': 'Frigobar'}],
            'table_id': table_id,
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        })
        data_service.save_room_charges(charges)
        return 'charge_1'

    # 13. Abertura de Caixa (Needed for payments)
    def test_13_cashier_opening(self):
        print("\n--- Test 13: Cashier Opening ---")
        data = {'action': 'open_cashier', 'opening_balance': '100,00'}
        response = self.client.post('/reception/cashier', data=data, follow_redirects=True)
        # Check specific flash message part or behavior
        # Note: If already open, it might say "Já existe um Caixa..."
        # We reset data in setUp so it should be clean.
        self.assertIn(b'aberto com sucesso', response.data)
        
        sessions = data_service.load_cashier_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['status'], 'open')
        self.assertEqual(sessions[0]['opening_balance'], 100.0)

    # 6 & 8. Pagamento de consumos e Múltiplos Pagamentos
    def test_06_08_payment_processing(self):
        print("\n--- Test 6 & 8: Payments ---")
        # Ensure cashier is open
        self.test_13_cashier_opening()
        
        charge_id = self._create_charge()
        
        # Multi-payment payload
        payment_data = json.dumps([
            {'id': 'money', 'name': 'Dinheiro', 'amount': 50.0},
            {'id': 'card', 'name': 'Cartão', 'amount': 50.0}
        ])
        
        data = {
            'action': 'pay_charge',
            'charge_id': charge_id,
            'payment_data': payment_data
        }
        
        response = self._measure_performance(
            self.client.post, '/reception/rooms', data=data, follow_redirects=True
        )
        
        charges = data_service.load_room_charges()
        self.assertEqual(charges[0]['status'], 'paid')
        self.assertEqual(charges[0]['payment_method'], 'Múltiplos')

    # 7. Frigobar
    def test_07_minibar_consumption(self):
        print("\n--- Test 7: Minibar ---")
        # Usually governance launches this, but reception sees the charge.
        # We simulate the charge appearing.
        self._create_charge(room='01', amount=15.0)
        response = self.client.get('/reception/rooms')
        self.assertIn(b'Frigobar', response.data)

    # 9. Cancelamentos de itens (Charge Cancellation)
    def test_09_cancellation(self):
        print("\n--- Test 9: Cancellation ---")
        charge_id = self._create_charge()
        
        data = {
            'action': 'cancel_charge',
            'charge_id': charge_id,
            'cancellation_reason': 'Erro de lançamento'
        }
        
        self.client.post('/reception/rooms', data=data, follow_redirects=True)
        charges = data_service.load_room_charges()
        self.assertEqual(charges[0]['status'], 'cancelled')

    # 10. Edição de contas
    def test_10_edit_charge(self):
        print("\n--- Test 10: Edit Charge ---")
        charge_id = self._create_charge()
        
        data = {
            'charge_id': charge_id,
            'new_status': 'paid',
            'new_notes': 'Edited via test',
            'justification': 'Testing Edit'
        }
        
        # Ensure cashier is open for paid status edit logic
        self.test_13_cashier_opening()
        
        response = self.client.post('/reception/charge/edit', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        charges = data_service.load_room_charges()
        self.assertEqual(charges[0]['status'], 'paid')
        self.assertEqual(charges[0]['notes'], 'Edited via test')
        self.assertEqual(charges[0]['audit_log'][0]['justification'], 'Testing Edit')

    # 11. Devolução para restaurante
    def test_11_return_to_restaurant(self):
        print("\n--- Test 11: Return to Restaurant ---")
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)
        cashier_service.CashierService.open_session('restaurant', 'admin_tester', opening_balance=0.0)
        charge_id = self._create_charge(table_id='10')
        
        data = {
            'charge_id': charge_id
        }
        
        response = self.client.post('/api/reception/return_to_restaurant', json=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json.get('success'))

    # 12. Atualização de nome
    def test_12_update_guest_name(self):
        print("\n--- Test 12: Update Name ---")
        data_service.save_room_occupancy({'01': {'guest_name': 'Old Name'}})
        
        data = {
            'action': 'edit_guest_name',
            'room_number': '01',
            'new_name': 'New Name'
        }
        
        self.client.post('/reception/rooms', data=data, follow_redirects=True)
        occupancy = data_service.load_room_occupancy()
        self.assertEqual(occupancy['01']['guest_name'], 'New Name')

    # 14. Fechamento de Caixa
    def test_14_cashier_closing(self):
        print("\n--- Test 14: Cashier Closing ---")
        self.test_13_cashier_opening() # Open first
        
        data = {'action': 'close_cashier', 'closing_balance': '100,00'}
        response = self.client.post('/reception/cashier', data=data, follow_redirects=True)
        self.assertIn(b'fechado com sucesso', response.data)
        
        sessions = data_service.load_cashier_sessions()
        self.assertEqual(sessions[0]['status'], 'closed')

    # 15. Persistência (Implicit)
    def test_15_persistence(self):
        print("\n--- Test 15: Persistence ---")
        # Verify that data survives "restart" (reloading from file)
        data_service.save_room_occupancy({'01': {'guest_name': 'Persistent'}})
        
        # Simulate app restart by reloading module or just reading file
        occupancy = data_service.load_room_occupancy()
        self.assertEqual(occupancy['01']['guest_name'], 'Persistent')

    # 16. Suprimento e Sangria no Caixa da Recepção
    def test_16_reception_cashier_deposit_and_withdrawal(self):
        print("\n--- Test 16: Reception Cashier Deposit & Withdrawal ---")
        # Abre o caixa da recepção com saldo inicial 0
        data = {'action': 'open_cashier', 'opening_balance': '0,00'}
        self.client.post('/reception/cashier', data=data, follow_redirects=True)
        sessions = data_service.load_cashier_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['type'], 'guest_consumption')
        self.assertEqual(sessions[0]['status'], 'open')

        # Suprimento de R$ 200,00
        data_deposit = {
            'action': 'add_transaction',
            'type': 'deposit',
            'amount': '200,00',
            'description': 'Teste Suprimento'
        }
        response_deposit = self.client.post('/reception/cashier', data=data_deposit, follow_redirects=True)
        self.assertEqual(response_deposit.status_code, 200)
        self.assertIn(b'Suprimento registrado com sucesso.', response_deposit.data)

        sessions = data_service.load_cashier_sessions()
        reception_session = next(s for s in sessions if s['type'] == 'guest_consumption')
        self.assertEqual(len(reception_session['transactions']), 1)
        self.assertEqual(reception_session['transactions'][0]['type'], 'in')
        self.assertEqual(reception_session['transactions'][0]['amount'], 200.0)

        # Sangria de R$ 50,00 (deve ser permitida)
        data_withdrawal = {
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '50,00',
            'description': 'Teste Sangria'
        }
        response_withdrawal = self.client.post('/reception/cashier', data=data_withdrawal, follow_redirects=True)
        self.assertEqual(response_withdrawal.status_code, 200)
        self.assertIn(b'Sangria registrada com sucesso.', response_withdrawal.data)

        sessions = data_service.load_cashier_sessions()
        reception_session = next(s for s in sessions if s['type'] == 'guest_consumption')
        self.assertEqual(len(reception_session['transactions']), 2)

        types = [t['type'] for t in reception_session['transactions']]
        amounts = [t['amount'] for t in reception_session['transactions']]
        self.assertIn('in', types)
        self.assertIn('out', types)
        self.assertIn(200.0, amounts)
        self.assertIn(50.0, amounts)

        # Sangria de valor maior que o saldo em espécie deve falhar
        data_withdrawal_blocked = {
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '1000,00',
            'description': 'Sangria Excedente'
        }
        response_blocked = self.client.post('/reception/cashier', data=data_withdrawal_blocked, follow_redirects=True)
        self.assertEqual(response_blocked.status_code, 200)
        self.assertIn(b'Erro:', response_blocked.data)

        sessions_after = data_service.load_cashier_sessions()
        reception_session_after = next(s for s in sessions_after if s['type'] == 'guest_consumption')
        self.assertEqual(len(reception_session_after['transactions']), 2)

    # 17. Transferência de dinheiro entre caixas abertos (Recepção -> Restaurante)
    def test_17_reception_cashier_transfer_between_open_cashiers(self):
        print("\n--- Test 17: Reception Cashier Transfer Between Open Cashiers ---")
        # Abre caixa da recepção e do restaurante
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=500.0)
        cashier_service.CashierService.open_session('restaurant', 'admin_tester', opening_balance=0.0)

        # Executa transferência via endpoint da recepção
        data_transfer = {
            'action': 'add_transaction',
            'type': 'transfer',
            'amount': '150,00',
            'description': 'Transferência para Restaurante',
            'target_cashier': 'restaurant'
        }
        response = self.client.post('/reception/cashier', data=data_transfer, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        sessions = data_service.load_cashier_sessions()
        reception_session = next(s for s in sessions if s['type'] in ['guest_consumption', 'reception_room_billing'])
        restaurant_session = next(s for s in sessions if s['type'] in ['restaurant', 'restaurant_service'])

        # Verifica transação de saída na recepção
        self.assertEqual(len(reception_session['transactions']), 1)
        out_tx = reception_session['transactions'][0]
        self.assertEqual(out_tx['type'], 'out')
        self.assertEqual(out_tx['amount'], 150.0)
        self.assertEqual(out_tx.get('category'), 'Transferência Enviada')

        # Verifica transação de entrada no restaurante
        self.assertEqual(len(restaurant_session['transactions']), 1)
        in_tx = restaurant_session['transactions'][0]
        self.assertEqual(in_tx['type'], 'in')
        self.assertEqual(in_tx['amount'], 150.0)
        self.assertEqual(in_tx.get('category'), 'Transferência Recebida')

    # 18. Suprimento e Sangria no Caixa de Reservas
    def test_18_reservations_cashier_deposit_and_withdrawal(self):
        print("\n--- Test 18: Reservations Cashier Deposit & Withdrawal ---")
        data_open = {'action': 'open_cashier', 'opening_balance': '0'}
        self.client.post('/reception/reservations-cashier', data=data_open, follow_redirects=True)

        sessions = data_service.load_cashier_sessions()
        reservations_session = next(s for s in sessions if isinstance(s, dict) and s.get('type') == 'reception_reservations')
        self.assertEqual(reservations_session['status'], 'open')

        data_deposit = {
            'action': 'add_transaction',
            'type': 'deposit',
            'amount': '300',
            'description': 'Suprimento Reservas'
        }
        response_deposit = self.client.post('/reception/reservations-cashier', data=data_deposit, follow_redirects=True)
        self.assertEqual(response_deposit.status_code, 200)
        self.assertIn(b'Suprimento registrado com sucesso.', response_deposit.data)

        sessions = data_service.load_cashier_sessions()
        reservations_session = next(s for s in sessions if isinstance(s, dict) and s.get('type') == 'reception_reservations')
        self.assertEqual(len(reservations_session['transactions']), 1)
        self.assertEqual(reservations_session['transactions'][0]['type'], 'deposit')
        self.assertEqual(reservations_session['transactions'][0]['amount'], 300.0)

        data_withdrawal = {
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '100',
            'description': 'Sangria Reservas'
        }
        response_withdrawal = self.client.post('/reception/reservations-cashier', data=data_withdrawal, follow_redirects=True)
        self.assertEqual(response_withdrawal.status_code, 200)
        self.assertIn(b'Sangria registrada com sucesso.', response_withdrawal.data)

        sessions = data_service.load_cashier_sessions()
        reservations_session = next(s for s in sessions if s['type'] == 'reception_reservations')
        self.assertEqual(len(reservations_session['transactions']), 2)

        types = [t['type'] for t in reservations_session['transactions']]
        amounts = [t['amount'] for t in reservations_session['transactions']]
        self.assertIn('deposit', types)
        self.assertIn('withdrawal', types)
        self.assertIn(300.0, amounts)
        self.assertIn(100.0, amounts)

        data_withdrawal_blocked = {
            'action': 'add_transaction',
            'type': 'withdrawal',
            'amount': '1000',
            'description': 'Sangria Excedente Reservas'
        }
        response_blocked = self.client.post('/reception/reservations-cashier', data=data_withdrawal_blocked, follow_redirects=True)
        self.assertEqual(response_blocked.status_code, 200)
        self.assertIn(b'Erro:', response_blocked.data)

        sessions_after = data_service.load_cashier_sessions()
        reservations_session_after = next(s for s in sessions_after if isinstance(s, dict) and s.get('type') == 'reception_reservations')
        self.assertEqual(len(reservations_session_after['transactions']), 2)

    # 19. Transferência com caixa de destino fechado via endpoint da Recepção
    def test_19_reception_cashier_transfer_with_closed_target(self):
        print("\n--- Test 19: Reception Cashier Transfer With Closed Target ---")
        data_open = {'action': 'open_cashier', 'opening_balance': '500,00'}
        self.client.post('/reception/cashier', data=data_open, follow_redirects=True)

        sessions = data_service.load_cashier_sessions()
        reception_session = next(s for s in sessions if isinstance(s, dict) and s.get('type') in ['guest_consumption', 'reception_room_billing'])
        self.assertEqual(reception_session['status'], 'open')

        data_transfer = {
            'action': 'add_transaction',
            'type': 'transfer',
            'amount': '100,00',
            'description': 'Transferência para Caixa Fechado',
            'target_cashier': 'restaurant'
        }
        response = self.client.post('/reception/cashier', data=data_transfer, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Erro: Transfer\xc3\xaancia Bloqueada: Caixa de destino (restaurant) est\xc3\xa1 FECHADO.', response.data)

        sessions_after = data_service.load_cashier_sessions()
        reception_session_after = next(s for s in sessions_after if isinstance(s, dict) and s.get('type') in ['guest_consumption', 'reception_room_billing'])
        self.assertEqual(len(reception_session_after['transactions']), 0)

if __name__ == '__main__':
    unittest.main()
