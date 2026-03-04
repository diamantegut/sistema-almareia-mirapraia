import unittest
import json
import os
import time
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch
import app as app_module
from app import create_app
from app.services import data_service, cashier_service, transfer_service
from app.blueprints.reception import routes as reception_routes
from app.blueprints.governance import routes as governance_routes
from app.services.reservation_service import ReservationService
from app.services import reservation_service as reservation_service_module

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
        self.original_app_occupancy = getattr(app_module, 'ROOM_OCCUPANCY_FILE', None)
        self.original_app_charges = getattr(app_module, 'ROOM_CHARGES_FILE', None)
        self.original_app_sessions = getattr(app_module, 'CASHIER_SESSIONS_FILE', None)
        self.original_reservations_dir = ReservationService.RESERVATIONS_DIR
        self.original_manual_reservations = ReservationService.MANUAL_RESERVATIONS_FILE
        self.original_reservations_file = ReservationService.RESERVATIONS_FILE
        self.original_res_status_overrides = ReservationService.RESERVATION_STATUS_OVERRIDES_FILE
        self.original_res_payments = ReservationService.RESERVATION_PAYMENTS_FILE
        self.original_module_res_dir = reservation_service_module.RESERVATIONS_DIR
        self.original_module_manual_res = reservation_service_module.MANUAL_RESERVATIONS_FILE
        self.original_module_manual_allocs = reservation_service_module.MANUAL_ALLOCATIONS_FILE
        self.original_module_guest_details = reservation_service_module.GUEST_DETAILS_FILE
        
        # Define test file paths
        self.test_occupancy = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        self.test_cleaning = os.path.join(TEST_DATA_DIR, 'cleaning_status.json')
        self.test_charges = os.path.join(TEST_DATA_DIR, 'room_charges.json')
        self.test_orders = os.path.join(TEST_DATA_DIR, 'table_orders.json')
        self.test_sessions = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        self.test_products = os.path.join(TEST_DATA_DIR, 'products.json')
        self.test_menu = os.path.join(TEST_DATA_DIR, 'menu_items.json')
        self.test_reservations_dir = os.path.join(TEST_DATA_DIR, 'reservations')
        self.test_manual_reservations = os.path.join(self.test_reservations_dir, 'manual_reservations.json')
        self.test_reservation_payments = os.path.join(self.test_reservations_dir, 'reservation_payments.json')
        self.test_status_overrides = os.path.join(self.test_reservations_dir, 'reservation_status_overrides.json')
        self.test_manual_allocations = os.path.join(self.test_reservations_dir, 'manual_allocations.json')
        self.test_guest_details = os.path.join(self.test_reservations_dir, 'guest_details.json')
        self.test_reservations_xlsx = os.path.join(self.test_reservations_dir, 'minhas_reservas.xlsx')

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
        app_module.ROOM_OCCUPANCY_FILE = self.test_occupancy
        app_module.ROOM_CHARGES_FILE = self.test_charges
        app_module.CASHIER_SESSIONS_FILE = self.test_sessions
        ReservationService.RESERVATIONS_DIR = self.test_reservations_dir
        ReservationService.MANUAL_RESERVATIONS_FILE = self.test_manual_reservations
        ReservationService.RESERVATIONS_FILE = self.test_reservations_xlsx
        ReservationService.RESERVATION_STATUS_OVERRIDES_FILE = self.test_status_overrides
        ReservationService.RESERVATION_PAYMENTS_FILE = self.test_reservation_payments
        reservation_service_module.RESERVATIONS_DIR = self.test_reservations_dir
        reservation_service_module.MANUAL_RESERVATIONS_FILE = self.test_manual_reservations
        reservation_service_module.MANUAL_ALLOCATIONS_FILE = self.test_manual_allocations
        reservation_service_module.GUEST_DETAILS_FILE = self.test_guest_details
        
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
        app_module.ROOM_OCCUPANCY_FILE = self.original_app_occupancy
        app_module.ROOM_CHARGES_FILE = self.original_app_charges
        app_module.CASHIER_SESSIONS_FILE = self.original_app_sessions
        ReservationService.RESERVATIONS_DIR = self.original_reservations_dir
        ReservationService.MANUAL_RESERVATIONS_FILE = self.original_manual_reservations
        ReservationService.RESERVATIONS_FILE = self.original_reservations_file
        ReservationService.RESERVATION_STATUS_OVERRIDES_FILE = self.original_res_status_overrides
        ReservationService.RESERVATION_PAYMENTS_FILE = self.original_res_payments
        reservation_service_module.RESERVATIONS_DIR = self.original_module_res_dir
        reservation_service_module.MANUAL_RESERVATIONS_FILE = self.original_module_manual_res
        reservation_service_module.MANUAL_ALLOCATIONS_FILE = self.original_module_manual_allocs
        reservation_service_module.GUEST_DETAILS_FILE = self.original_module_guest_details

    def reset_data(self):
        os.makedirs(self.test_reservations_dir, exist_ok=True)
        with open(self.test_occupancy, 'w') as f: json.dump({}, f)
        with open(self.test_cleaning, 'w') as f: json.dump({}, f)
        with open(self.test_charges, 'w') as f: json.dump([], f)
        with open(self.test_orders, 'w') as f: json.dump({}, f)
        with open(self.test_sessions, 'w') as f: json.dump([], f)
        with open(self.test_manual_reservations, 'w') as f: json.dump([], f)
        with open(self.test_reservation_payments, 'w') as f: json.dump({}, f)
        with open(self.test_status_overrides, 'w') as f: json.dump({}, f)
        with open(self.test_manual_allocations, 'w') as f: json.dump({}, f)
        with open(self.test_guest_details, 'w') as f: json.dump({}, f)
        
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
            'room_number': '01',
            'guest_name': 'Teste Hóspede',
            'checkin_date': datetime.now().strftime('%Y-%m-%d'),
            'checkout_date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
            'num_adults': 2,
            'doc_id': '12345678900'
        }
        
        response = self._measure_performance(
            self.client.post, '/reception/checkin', data=data, follow_redirects=True
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
        reservations_session = next(s for s in sessions if isinstance(s, dict) and s.get('type') == 'reservation_cashier')
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
        reservations_session = next(s for s in sessions if isinstance(s, dict) and s.get('type') == 'reservation_cashier')
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
        reservations_session = next(s for s in sessions if s['type'] == 'reservation_cashier')
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
        reservations_session_after = next(s for s in sessions_after if isinstance(s, dict) and s.get('type') == 'reservation_cashier')
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

    def test_20_scenario_01_checkin_passante_campos_obrigatorios(self):
        data = {
            'room_number': '11',
            'guest_name': 'Passante Teste',
            'checkin_date': datetime.now().strftime('%Y-%m-%d'),
            'checkout_date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
            'num_adults': 2,
            'doc_id': '12345678901'
        }
        response = self.client.post('/reception/checkin', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        occupancy = data_service.load_room_occupancy()
        orders = data_service.load_table_orders()
        self.assertIn('11', occupancy)
        self.assertEqual(occupancy['11']['guest_name'], 'Passante Teste')
        self.assertIn('11', orders)
        self.assertEqual(orders['11']['customer_type'], 'hospede')

    def test_21_scenario_02_pagamento_reserva_parcial_total_multiplos(self):
        service = ReservationService()
        now = datetime.now()
        reservation = service.create_manual_reservation({
            'guest_name': 'Reserva Pagamento',
            'checkin': now.strftime('%d/%m/%Y'),
            'checkout': (now + timedelta(days=2)).strftime('%d/%m/%Y'),
            'amount': '300.00',
            'paid_amount': '0.00',
            'to_receive': '300.00',
            'status': 'Confirmada'
        })
        res_id = reservation['id']

        cashier_service.CashierService.open_session('reservation_cashier', 'admin_tester', opening_balance=0.0)

        debt_before = self.client.get(f'/reception/reservation/{res_id}/debt')
        self.assertEqual(debt_before.status_code, 200)
        self.assertAlmostEqual(float(debt_before.json['remaining']), 300.0, places=2)

        first = self.client.post('/reception/reservation/pay', json={
            'reservation_id': res_id,
            'amount': 100.0,
            'payment_method_id': 'pix',
            'payment_method_name': 'PIX',
            'origin': 'reservations'
        })
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json.get('success'))

        second = self.client.post('/reception/reservation/pay', json={
            'reservation_id': res_id,
            'amount': 120.0,
            'payment_method_id': 'card',
            'payment_method_name': 'Cartão',
            'origin': 'checkin'
        })
        third = self.client.post('/reception/reservation/pay', json={
            'reservation_id': res_id,
            'amount': 80.0,
            'payment_method_id': 'cash',
            'payment_method_name': 'Dinheiro',
            'origin': 'checkin'
        })
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)

        debt_after = self.client.get(f'/reception/reservation/{res_id}/debt')
        self.assertEqual(debt_after.status_code, 200)
        self.assertAlmostEqual(float(debt_after.json['remaining']), 0.0, places=2)

        payments = service.get_reservation_payments().get(str(res_id), [])
        self.assertEqual(len(payments), 3)
        self.assertAlmostEqual(sum(float(p['amount']) for p in payments), 300.0, places=2)

    def test_22_scenario_03_pagamentos_consumo_parcial_total_multiplos(self):
        data_service.save_room_occupancy({'01': {'guest_name': 'Hospede Consumo'}})
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)
        charges = [
            {
                'id': 'charge_partial',
                'room_number': '01',
                'total': 40.0,
                'status': 'pending',
                'items': [{'id': 'i1', 'name': 'Item 1', 'qty': 1, 'price': 40.0, 'category': 'Restaurante'}],
                'date': datetime.now().strftime('%d/%m/%Y %H:%M')
            },
            {
                'id': 'charge_total',
                'room_number': '01',
                'total': 60.0,
                'status': 'pending',
                'items': [{'id': 'i2', 'name': 'Item 2', 'qty': 1, 'price': 60.0, 'category': 'Restaurante'}],
                'date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        ]
        data_service.save_room_charges(charges)

        pay_individual = self.client.post('/reception/rooms', data={
            'action': 'pay_charge',
            'charge_id': 'charge_partial',
            'payment_data': json.dumps([{'id': 'cash', 'name': 'Dinheiro', 'amount': 40.0}])
        }, follow_redirects=True)
        self.assertEqual(pay_individual.status_code, 200)

        close_total = self.client.post('/reception/close_account/01', json={
            'payments': [
                {'method_id': 'pix', 'amount': 30.0},
                {'method_id': 'card', 'amount': 30.0}
            ],
            'print_receipt': False
        })
        self.assertEqual(close_total.status_code, 200)
        self.assertTrue(close_total.json.get('success'))

        updated = data_service.load_room_charges()
        self.assertTrue(all(c.get('status') == 'paid' for c in updated))
        target = next(c for c in updated if c['id'] == 'charge_total')
        self.assertEqual(len(target.get('payment_details', [])), 2)

        html = self.client.get('/reception/rooms').data.decode('utf-8')
        self.assertIn('id="consumptionPaymentModal"', html)
        self.assertIn('id="closeRoomAccountModal"', html)

    def test_23_scenario_04_pagamento_individual_devolucao_edicao(self):
        data_service.save_room_occupancy({'12': {'guest_name': 'Hospede Conta'}})
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)
        cashier_service.CashierService.open_session('restaurant', 'admin_tester', opening_balance=0.0)
        data_service.save_room_charges([
            {
                'id': 'charge_pay',
                'room_number': '12',
                'table_id': '200',
                'total': 50.0,
                'status': 'pending',
                'items': [{'id': 'x1', 'name': 'Prato', 'qty': 1, 'price': 50.0, 'category': 'Restaurante'}],
                'date': datetime.now().strftime('%d/%m/%Y %H:%M')
            },
            {
                'id': 'charge_return',
                'room_number': '12',
                'table_id': '201',
                'total': 35.0,
                'status': 'pending',
                'items': [{'id': 'x2', 'name': 'Suco', 'qty': 1, 'price': 35.0, 'category': 'Restaurante'}],
                'date': datetime.now().strftime('%d/%m/%Y %H:%M')
            },
            {
                'id': 'charge_edit',
                'room_number': '12',
                'table_id': '202',
                'total': 20.0,
                'status': 'pending',
                'items': [{'id': 'x3', 'name': 'Sobremesa', 'qty': 1, 'price': 20.0, 'category': 'Restaurante'}],
                'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'notes': ''
            }
        ])

        pay_resp = self.client.post('/reception/rooms', data={
            'action': 'pay_charge',
            'charge_id': 'charge_pay',
            'payment_data': json.dumps([{'id': 'cash', 'name': 'Dinheiro', 'amount': 50.0}])
        }, follow_redirects=True)
        self.assertEqual(pay_resp.status_code, 200)

        return_resp = self.client.post('/api/reception/return_to_restaurant', json={'charge_id': 'charge_return'})
        self.assertEqual(return_resp.status_code, 200)
        self.assertTrue(return_resp.json.get('success'))

        edit_resp = self.client.post('/reception/charge/edit', data={
            'charge_id': 'charge_edit',
            'new_status': 'pending',
            'new_notes': 'Conta revisada',
            'justification': 'Ajuste solicitado',
            'items_to_add': '[]',
            'items_to_remove': '[]',
            'removal_justifications': '{}'
        }, follow_redirects=True)
        self.assertEqual(edit_resp.status_code, 200)

        charges_after = data_service.load_room_charges()
        charge_pay = next(c for c in charges_after if c['id'] == 'charge_pay')
        charge_edit = next(c for c in charges_after if c['id'] == 'charge_edit')
        self.assertEqual(charge_pay['status'], 'paid')
        self.assertEqual(charge_edit['notes'], 'Conta revisada')

    def test_24_scenario_05_comissao_taxa_servico_permanencia_e_remocao(self):
        data_service.save_room_occupancy({'14': {'guest_name': 'Hospede Comissão'}})
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)
        data_service.save_room_charges([{
            'id': 'charge_fee',
            'room_number': '14',
            'table_id': '300',
            'total': 110.0,
            'status': 'pending',
            'service_fee': 10.0,
            'service_fee_removed': False,
            'waiter_breakdown': {'Carlos': 100.0},
            'items': [{'id': 'base', 'name': 'Refeição', 'qty': 1, 'price': 100.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])

        edit_resp = self.client.post('/reception/charge/edit', data={
            'charge_id': 'charge_fee',
            'new_status': 'pending',
            'new_notes': 'Sem taxa',
            'justification': 'Remoção de taxa',
            'remove_service_fee': 'on',
            'items_to_add': '[]',
            'items_to_remove': '[]',
            'removal_justifications': '{}'
        }, follow_redirects=True)
        self.assertEqual(edit_resp.status_code, 200)

        charge_after_edit = data_service.load_room_charges()[0]
        self.assertTrue(charge_after_edit.get('service_fee_removed'))
        self.assertAlmostEqual(float(charge_after_edit.get('total', 0.0)), 100.0, places=2)

        close_resp = self.client.post('/reception/close_account/14', json={'payment_method': 'cash', 'print_receipt': False})
        self.assertEqual(close_resp.status_code, 200)
        self.assertTrue(close_resp.json.get('success'))

        sessions = data_service.load_cashier_sessions()
        active = next(s for s in sessions if s['type'] == 'guest_consumption')
        tx = active['transactions'][0]
        self.assertTrue(tx.get('details', {}).get('service_fee_removed', False))

    def test_25_scenario_06_devolucao_conta_para_restaurante(self):
        data_service.save_room_occupancy({'15': {'guest_name': 'Hospede Devolução'}})
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)
        cashier_service.CashierService.open_session('restaurant', 'admin_tester', opening_balance=0.0)
        data_service.save_room_charges([{
            'id': 'charge_back',
            'room_number': '15',
            'table_id': '410',
            'total': 45.0,
            'status': 'pending',
            'items': [{'id': 'r1', 'name': 'Sanduíche', 'qty': 1, 'price': 45.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])

        resp = self.client.post('/api/reception/return_to_restaurant', json={'charge_id': 'charge_back'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json.get('success'))
        self.assertFalse(any(c.get('id') == 'charge_back' for c in data_service.load_room_charges()))

    def test_26_scenario_07_transferencia_de_quarto_com_dados_associados(self):
        data_service.save_room_occupancy({'21': {'guest_name': 'Transferir'}})
        data_service.save_table_orders({'21': {'items': [], 'total': 0.0, 'status': 'open', 'room_number': '21'}})
        data_service.save_room_charges([{
            'id': 'charge_transfer',
            'room_number': '21',
            'total': 32.0,
            'status': 'pending',
            'items': [{'id': 'tt1', 'name': 'Lanche', 'qty': 1, 'price': 32.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])

        response = self.client.post('/reception/rooms', data={
            'action': 'transfer_guest',
            'old_room': '21',
            'new_room': '22',
            'reason': 'Troca solicitada'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        occupancy = data_service.load_room_occupancy()
        orders = data_service.load_table_orders()
        charges = data_service.load_room_charges()
        self.assertNotIn('21', occupancy)
        self.assertIn('22', occupancy)
        self.assertNotIn('21', orders)
        self.assertIn('22', orders)
        self.assertEqual(charges[0]['room_number'], '22')

    def test_27_scenario_08_edicao_cadastro_hospede(self):
        data_service.save_room_occupancy({'23': {'guest_name': 'Nome Antigo'}})
        response = self.client.post('/reception/rooms', data={
            'action': 'edit_guest_name',
            'room_number': '23',
            'new_name': 'Nome Atualizado'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        occupancy = data_service.load_room_occupancy()
        self.assertEqual(occupancy['23']['guest_name'], 'Nome Atualizado')

    def test_28_scenario_09_botoes_e_endpoints_frontend_backend_operacionais(self):
        html = self.client.get('/reception/rooms').data.decode('utf-8')
        self.assertIn('id="consumptionPaymentModal"', html)
        self.assertIn('id="closeRoomAccountModal"', html)
        self.assertIn('id="editConsumptionModal"', html)
        self.assertIn('id="deleteConsumptionModal"', html)
        self.assertIn('id="consumptionPaymentForm"', html)
        self.assertIn('openConsumptionPaymentModal(', html)
        self.assertIn('addConsumptionPayment()', html)
        self.assertIn('id="consumptionPaymentList"', html)
        self.assertIn('id="closeRoomPaymentList"', html)
        self.assertIn('id="editConsumptionRemoveServiceFee"', html)
        self.assertIn('submitCloseRoomAccount()', html)
        self.assertIn('/reception/print_individual_bills', html)
        self.assertIn('/reception/charge/edit', html)

        resp_close = self.client.post('/reception/close_account/99', json={})
        resp_print = self.client.post('/reception/print_individual_bills', json={})
        self.assertIn(resp_close.status_code, [400, 403])
        self.assertEqual(resp_print.status_code, 400)

    def test_29_scenario_10_registro_de_logs_de_acoes(self):
        data_service.save_room_charges([{
            'id': 'charge_log',
            'room_number': '24',
            'total': 22.0,
            'status': 'pending',
            'items': [{'id': 'log1', 'name': 'Item', 'qty': 1, 'price': 22.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])
        response = self.client.post('/admin/consumption/cancel', json={
            'charge_id': 'charge_log',
            'justification': 'Teste de auditoria'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json.get('success'))

        audit_logs = data_service.load_audit_logs()
        self.assertGreaterEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[-1].get('action'), 'cancel_consumption')
        self.assertEqual(audit_logs[-1].get('target_id'), 'charge_log')

    def test_30_scenario_11_rotas_impressao_conforme_config_printers(self):
        data_service.save_room_charges([{
            'id': 'charge_print',
            'room_number': '25',
            'total': 18.0,
            'status': 'pending',
            'items': [{'id': 'pp1', 'name': 'Café', 'qty': 1, 'price': 18.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])

        with patch('app.blueprints.reception.routes.load_printer_settings', return_value={'reception_printer_id': 'PRN-01'}):
            html = self.client.get('/reception/rooms').data.decode('utf-8')
            self.assertIn('PRN-01', html)

        with patch('app.blueprints.reception.routes.print_individual_bills_thermal', return_value=(True, None)) as mocked_print:
            resp = self.client.post('/reception/print_individual_bills', json={
                'room_number': '25',
                'guest_name': 'Hóspede',
                'printer_id': 'PRN-01',
                'selected_charge_ids': ['charge_print']
            })
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json.get('success'))
            self.assertTrue(mocked_print.called)

    def test_31_scenario_12_integracao_rooms_reservations(self):
        service = ReservationService()
        now = datetime.now()
        reservation = service.create_manual_reservation({
            'guest_name': 'Integração Nome',
            'checkin': now.strftime('%d/%m/%Y'),
            'checkout': (now + timedelta(days=1)).strftime('%d/%m/%Y'),
            'amount': '0.00',
            'paid_amount': '0.00',
            'to_receive': '0.00',
            'status': 'Confirmada'
        })
        res_id = reservation['id']
        service.save_manual_allocation(res_id, '31', now.strftime('%d/%m/%Y'), (now + timedelta(days=1)).strftime('%d/%m/%Y'))

        response = self.client.post('/reception/checkin', data={
            'room_number': '31',
            'guest_name': 'Integração Nome',
            'doc_id': '11122233344',
            'checkin_date': now.strftime('%Y-%m-%d'),
            'checkout_date': (now + timedelta(days=1)).strftime('%Y-%m-%d'),
            'num_adults': 2
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        occupancy = data_service.load_room_occupancy()
        self.assertEqual(str(occupancy['31'].get('reservation_id')), str(res_id))

        updated = service.get_reservation_by_id(res_id)
        self.assertIsNotNone(updated)
        self.assertIn('checked', str(updated.get('status', '')).lower())

    def test_32_scenario_13_rotas_logica_proximas_reservas(self):
        service = ReservationService()
        now = datetime.now()
        near = service.create_manual_reservation({
            'guest_name': 'Reserva Próxima',
            'checkin': (now + timedelta(days=1)).strftime('%d/%m/%Y'),
            'checkout': (now + timedelta(days=2)).strftime('%d/%m/%Y'),
            'amount': '150.00',
            'paid_amount': '0.00',
            'to_receive': '150.00',
            'status': 'Confirmada'
        })
        service.save_manual_allocation(near['id'], '32', (now + timedelta(days=1)).strftime('%d/%m/%Y'), (now + timedelta(days=2)).strftime('%d/%m/%Y'))

        service.create_manual_reservation({
            'guest_name': 'Reserva Distante',
            'checkin': (now + timedelta(days=10)).strftime('%d/%m/%Y'),
            'checkout': (now + timedelta(days=12)).strftime('%d/%m/%Y'),
            'amount': '200.00',
            'paid_amount': '0.00',
            'to_receive': '200.00',
            'status': 'Confirmada'
        })

        upcoming = service.get_upcoming_checkins(days=2)
        ids = [str(r.get('id')) for r in upcoming]
        self.assertIn(str(near['id']), ids)

        page = self.client.get('/reception/rooms')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Reserva Próxima', page.data.decode('utf-8'))

    def test_33_scenario_14_capacidade_cinco_usuarios_simultaneos(self):
        data_service.save_room_occupancy({'33': {'guest_name': 'Concorrência'}})

        def request_rooms_page(_idx):
            client = self.app.test_client()
            with client.session_transaction() as sess:
                sess['user'] = f'usuario_{_idx}'
                sess['role'] = 'admin'
                sess['permissions'] = ['recepcao', 'admin']
                sess['department'] = 'Recepção'
            response = client.get('/reception/rooms')
            return response.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            statuses = list(executor.map(request_rooms_page, range(5)))

        self.assertEqual(len(statuses), 5)
        self.assertTrue(all(status == 200 for status in statuses))

    def test_34_scenario_15_fechamento_mesa_transferencia_checkout_ver_consumo(self):
        data_service.save_room_occupancy({'34': {'guest_name': 'Checkout Mesa'}})
        data_service.save_table_orders({
            '80': {
                'items': [{'id': 'm1', 'name': 'Jantar', 'qty': 2, 'price': 40.0, 'category': 'Restaurante', 'waiter': 'Ana'}],
                'total': 80.0,
                'status': 'open',
                'waiter': 'Ana',
                'customer_type': 'hospede'
            }
        })
        cashier_service.CashierService.open_session('guest_consumption', 'admin_tester', opening_balance=0.0)

        success, _msg = transfer_service.transfer_table_to_room('80', '34', 'admin_tester', mode='restaurant')
        self.assertTrue(success)

        charges = data_service.load_room_charges()
        transferred = next((c for c in charges if c.get('room_number') == '34' and c.get('status') == 'pending'), None)
        self.assertIsNotNone(transferred)

        close_resp = self.client.post('/reception/close_account/34', json={'payment_method': 'cash', 'print_receipt': False})
        self.assertEqual(close_resp.status_code, 200)
        self.assertTrue(close_resp.json.get('success'))
        charges_after = data_service.load_room_charges()
        self.assertTrue(all(c.get('status') == 'paid' for c in charges_after if c.get('room_number') == '34'))

    def test_35_scenario_16_edicao_conta_individual_com_produtos_e_taxa(self):
        data_service.save_room_charges([{
            'id': 'charge_edit_products',
            'room_number': '35',
            'table_id': '900',
            'total': 22.0,
            'status': 'pending',
            'service_fee_removed': False,
            'items': [{'id': 'item_original', 'name': 'Item Original', 'qty': 1, 'price': 20.0, 'category': 'Restaurante'}],
            'date': datetime.now().strftime('%d/%m/%Y %H:%M')
        }])

        response = self.client.post('/reception/charge/edit', data={
            'charge_id': 'charge_edit_products',
            'source_page': 'reception_rooms',
            'new_status': 'pending',
            'new_notes': 'Ajuste completo',
            'justification': 'Edição de itens e taxa',
            'remove_service_fee': 'on',
            'items_to_add': json.dumps([{'id': '1', 'qty': 2}]),
            'items_to_remove': json.dumps(['item_original']),
            'removal_justifications': json.dumps({'item_original': 'Pedido cancelado'})
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        updated = data_service.load_room_charges()[0]
        self.assertTrue(updated.get('service_fee_removed'))
        self.assertTrue(any(i.get('name') == 'Água' for i in updated.get('items', [])))
        self.assertTrue(any(i.get('id') == 'item_original' for i in updated.get('removed_items', [])))
        self.assertEqual(updated.get('notes'), 'Ajuste completo')

    def test_36_scenario_17_ficha_hospede_carrega_dados_e_edicao_com_item_sem_id(self):
        service = ReservationService()
        now = datetime.now()
        reservation = service.create_manual_reservation({
            'guest_name': "Ana D'Avila",
            'checkin': now.strftime('%d/%m/%Y'),
            'checkout': (now + timedelta(days=1)).strftime('%d/%m/%Y'),
            'amount': '180.00',
            'paid_amount': '20.00',
            'to_receive': '160.00',
            'status': 'Checked-in'
        })
        res_id = reservation['id']
        service.update_guest_details(res_id, {'personal_info': {'name': "Ana D'Avila", 'phone': '81999990000'}})
        data_service.save_room_occupancy({'12': {'guest_name': "Ana D'Avila", 'reservation_id': res_id, 'checkin': now.strftime('%d/%m/%Y')}})

        page_html = self.client.get('/reception/rooms').data.decode('utf-8')
        self.assertIn('openViewGuestModal(', page_html)
        self.assertIn(str(res_id), page_html)
        self.assertIn('Ana D\\u0027Avila', page_html)

        data_service.save_room_charges([{
            'id': 'charge_no_item_id',
            'room_number': '12',
            'table_id': '91',
            'total': 110.0,
            'status': 'pending',
            'service_fee_removed': False,
            'items': [{'name': 'Prato sem ID', 'qty': 1, 'price': 100.0, 'category': 'Restaurante'}],
            'date': now.strftime('%d/%m/%Y %H:%M')
        }])

        edit_response = self.client.post('/reception/charge/edit', data={
            'charge_id': 'charge_no_item_id',
            'source_page': 'reception_rooms',
            'new_status': 'pending',
            'new_notes': 'Removido item sem id',
            'justification': 'Teste remoção sem id',
            'remove_service_fee': 'on',
            'items_to_add': json.dumps([]),
            'items_to_remove': json.dumps(['__idx_0']),
            'removal_justifications': json.dumps({'__idx_0': 'Sem consumo'})
        }, follow_redirects=True)
        self.assertEqual(edit_response.status_code, 200)

        edited = data_service.load_room_charges()[0]
        self.assertEqual(edited.get('items'), [])
        self.assertTrue(edited.get('service_fee_removed'))
        self.assertEqual(float(edited.get('total', 0)), 0.0)

if __name__ == '__main__':
    unittest.main()
