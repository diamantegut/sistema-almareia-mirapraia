import unittest
import json
import os
import shutil
from datetime import datetime, timedelta
from app import create_app
from app.services import cashier_service
from app.services.cashier_service import CashierService
from app.services.reservation_service import ReservationService
from app.services import data_service

TEST_DATA_DIR = r'tests\test_data_reservation_cashier'

class TestReservationCashierSystem(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
        
    def setUp(self):
        # 1. Setup Cashier Session File Patching
        self.original_sessions_file = cashier_service.CASHIER_SESSIONS_FILE
        self.test_sessions_file = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        cashier_service.CASHIER_SESSIONS_FILE = self.test_sessions_file
        
        # 2. Setup Reservation Service Patching
        self.original_res_payments = ReservationService.RESERVATION_PAYMENTS_FILE
        self.test_res_payments = os.path.join(TEST_DATA_DIR, 'reservation_payments.json')
        ReservationService.RESERVATION_PAYMENTS_FILE = self.test_res_payments
        
        self.original_manual_res = ReservationService.MANUAL_RESERVATIONS_FILE
        self.test_manual_res = os.path.join(TEST_DATA_DIR, 'manual_reservations.json')
        ReservationService.MANUAL_RESERVATIONS_FILE = self.test_manual_res
        
        # Patch Reservations Dir/File to avoid scanning real Excel files
        self.original_res_dir = ReservationService.RESERVATIONS_DIR
        self.test_res_dir = TEST_DATA_DIR
        ReservationService.RESERVATIONS_DIR = self.test_res_dir
        
        self.original_res_file = ReservationService.RESERVATIONS_FILE
        self.test_res_file = os.path.join(TEST_DATA_DIR, "minhas_reservas.xlsx")
        ReservationService.RESERVATIONS_FILE = self.test_res_file

        # 3. Setup Payment Methods and Room Occupancy
        self.original_payment_methods = data_service.PAYMENT_METHODS_FILE
        self.test_payment_methods = os.path.join(TEST_DATA_DIR, 'payment_methods.json')
        data_service.PAYMENT_METHODS_FILE = self.test_payment_methods
        
        self.original_room_occupancy = data_service.ROOM_OCCUPANCY_FILE
        self.test_room_occupancy = os.path.join(TEST_DATA_DIR, 'room_occupancy.json')
        data_service.ROOM_OCCUPANCY_FILE = self.test_room_occupancy
        
        # Initialize Empty Files
        with open(self.test_sessions_file, 'w') as f: json.dump([], f)
        with open(self.test_res_payments, 'w') as f: json.dump({}, f)
        with open(self.test_manual_res, 'w') as f: json.dump([], f)
        with open(self.test_room_occupancy, 'w') as f: json.dump({}, f)
        
        # Initialize Payment Methods
        methods = [
            {'id': '1', 'name': 'Dinheiro', 'is_fiscal': False, 'available_in': ['caixa_reservas']},
            {'id': '2', 'name': 'Cartão Crédito', 'is_fiscal': True, 'available_in': ['caixa_reservas']},
            {'id': '3', 'name': 'PIX', 'is_fiscal': True, 'available_in': ['caixa_reservas']}
        ]
        with open(self.test_payment_methods, 'w', encoding='utf-8') as f: 
            json.dump(methods, f, ensure_ascii=False)
        
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'test_admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao', 'admin']

    def tearDown(self):
        # Restore original file paths
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions_file
        ReservationService.RESERVATION_PAYMENTS_FILE = self.original_res_payments
        ReservationService.MANUAL_RESERVATIONS_FILE = self.original_manual_res
        ReservationService.RESERVATIONS_DIR = self.original_res_dir
        ReservationService.RESERVATIONS_FILE = self.original_res_file
        data_service.PAYMENT_METHODS_FILE = self.original_payment_methods
        data_service.ROOM_OCCUPANCY_FILE = self.original_room_occupancy

    def test_01_open_close_cashier(self):
        """Test Opening and Closing Reservation Cashier"""
        print(f"DEBUG: Patched Session File: {cashier_service.CASHIER_SESSIONS_FILE}")
        
        # Open
        response = self.client.post('/reception/reservations-cashier', data={
            'action': 'open_cashier',
            'opening_balance': '100.00'
        }, follow_redirects=True)
        self.assertIn(b'Caixa de Reservas aberto com sucesso', response.data)
        
        # Verify Session Created
        session = CashierService.get_active_session('reservation_cashier')
        self.assertIsNotNone(session)
        self.assertEqual(session['opening_balance'], 100.0)
        
        # Close
        response = self.client.post('/reception/reservations-cashier', data={
            'action': 'close_cashier'
        }, follow_redirects=True)
        self.assertIn(b'Caixa de Reservas fechado com sucesso', response.data)
        
        # Verify Session Closed
        session = CashierService.get_active_session('reservation_cashier')
        self.assertIsNone(session)

    def test_02_create_reservation_with_payment(self):
        """Test Creating Reservation with Initial Payment (Mandatory Modal Logic)"""
        # Ensure clean slate for session
        try:
            CashierService.close_session('reservation_cashier', 'test_admin')
        except:
            pass
            
        # Open Cashier First
        CashierService.open_session('reservation_cashier', 'test_admin', 0)
        
        # Dynamic Dates
        today = datetime.now()
        checkin = (today + timedelta(days=1)).strftime('%d/%m/%Y')
        checkout = (today + timedelta(days=5)).strftime('%d/%m/%Y')
        
        payload = {
            'guest_name': 'João Teste',
            'total_value': '500.00',
            'paid_amount': '200.00',
            'payment_method': '3', # PIX
            'checkin': checkin,
            'checkout': checkout,
            'room_number': '101'
        }
        
        response = self.client.post('/api/reception/create_manual_reservation', 
                                   data=json.dumps(payload),
                                   content_type='application/json')
                                   
        try:
            data = response.get_json()
        except:
            data = None

        if not data or not data.get('success'):
            print(f"DEBUG: Status Code: {response.status_code}")
            with open('test_error_output.html', 'wb') as f:
                f.write(response.data)
            if data:
                print(f"DEBUG: Error Message: {data.get('error')}")
            
        self.assertTrue(data and data['success'])
        res_id = data['reservation']['id']
        
        # Verify Reservation Created
        res_service = ReservationService()
        res = res_service.get_reservation_by_id(res_id)
        print(f"DEBUG: Retrieved Reservation: {res}")
        self.assertEqual(res['guest_name'], 'João Teste')
        
        amount_val = float(res.get('total_value', 0) or res.get('amount', 0))
        print(f"DEBUG: Amount Value: {amount_val}")
        
        # Amount stored as string or float depending on impl, check roughly
        self.assertTrue(abs(amount_val - 500.0) < 0.01)
        
        # Verify Payment Recorded in Cashier
        session = CashierService.get_active_session('reservation_cashier')
        transactions = session['transactions']
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['amount'], 200.0)
        self.assertEqual(transactions[0]['payment_method'], 'PIX')
        self.assertIn('Pagamento Inicial', transactions[0]['description'])
        
        # Verify Payment Recorded in Reservation Service (Sidecar)
        payments = res_service.get_reservation_payments()
        self.assertIn(res_id, payments)
        self.assertEqual(payments[res_id][0]['amount'], 200.0)

    def test_03_pay_existing_reservation(self):
        """Test Receiving Payment for Existing Reservation"""
        # Ensure clean slate for session
        try:
            CashierService.close_session('reservation_cashier', 'test_admin')
        except:
            pass

        # Open Cashier
        CashierService.open_session('reservation_cashier', 'test_admin', 0)
        
        # Dynamic Dates
        today = datetime.now()
        checkin = (today + timedelta(days=1)).strftime('%d/%m/%Y')
        checkout = (today + timedelta(days=5)).strftime('%d/%m/%Y')
        
        # Setup: Create reservation without payment
        res_service = ReservationService()
        res_data = {
            'guest_name': 'Maria Teste',
            'total_value': '1000.00',
            'checkin': checkin,
            'checkout': checkout
        }
        res = res_service.create_manual_reservation(res_data)
        res_id = res['id']
        
        # Pay 300 via Credit Card
        payload = {
            'reservation_id': res_id,
            'amount': '300.00',
            'payment_method_id': '2', # ID
            'payment_method_name': 'Cartão Crédito'
        }
        
        response = self.client.post('/reception/reservation/pay',
                                   data=json.dumps(payload),
                                   content_type='application/json')
                                   
        data = response.get_json()
        if not data.get('success'):
            print(f"DEBUG: Pay Reservation Failed: {data.get('message')}")

        self.assertTrue(data['success'])
        
        # Verify Debt
        response = self.client.get(f'/reception/reservation/{res_id}/debt')
        debt_data = response.get_json()
        self.assertEqual(debt_data['total'], 1000.0)
        self.assertEqual(debt_data['paid'], 300.0)
        self.assertEqual(debt_data['remaining'], 700.0)
        
        # Verify Cashier
        session = CashierService.get_active_session('reservation_cashier')
        # Check last transaction
        tx = session['transactions'][-1]
        self.assertEqual(tx['amount'], 300.0)
        self.assertEqual(tx['payment_method'], 'Cartão Crédito')

    def test_04_payment_validation_closed_cashier(self):
        """Test Payment Rejection when Cashier is Closed"""
        # Ensure Closed
        try:
            CashierService.close_session('reservation_cashier', 'test_admin')
        except ValueError:
            pass # Already closed
        
        # Dynamic Dates
        today = datetime.now()
        checkin = (today + timedelta(days=1)).strftime('%d/%m/%Y')
        checkout = (today + timedelta(days=5)).strftime('%d/%m/%Y')
        
        payload = {
            'guest_name': 'Teste Fechado',
            'total_value': '500.00',
            'paid_amount': '100.00',
            'payment_method': '1',
            'checkin': checkin,
            'checkout': checkout
        }
        
        response = self.client.post('/api/reception/create_manual_reservation',
                                   data=json.dumps(payload),
                                   content_type='application/json')
                                   
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('Caixa de Reservas fechado', data['error'])

    def test_05_cashier_view_totals(self):
        """Test Cashier View Totals Calculation"""
        # Ensure clean slate
        try:
            CashierService.close_session('reservation_cashier', 'test_admin')
        except:
            pass

        CashierService.open_session('reservation_cashier', 'test_admin', 50.0) # Opening 50
        
        # Add transactions manually to service for speed
        CashierService.add_transaction(
            cashier_type='reservation_cashier', 
            amount=100.0, 
            description='T1', 
            payment_method='Dinheiro', 
            user='test', 
            transaction_type='sale',
            is_withdrawal=False
        )
        CashierService.add_transaction(
            cashier_type='reservation_cashier', 
            amount=200.0, 
            description='T2', 
            payment_method='PIX', 
            user='test', 
            transaction_type='sale',
            is_withdrawal=False
        )
        
        session = CashierService.get_active_session('reservation_cashier')
        summary = CashierService.get_session_summary(session)
        
        # Total Cash = Opening (50) + T1 (100) = 150
        # Total PIX = 200
        # Total Overall = 350
        
        self.assertEqual(summary['balance_by_method']['Dinheiro'], 100.0)
        self.assertEqual(summary['balance_by_method']['PIX'], 200.0)
        self.assertEqual(summary['opening_balance'], 50.0)
        self.assertEqual(summary['current_balance'], 350.0)

if __name__ == '__main__':
    unittest.main()
