import unittest
import json
import os
import shutil
from datetime import datetime
from app import create_app
from app.services import cashier_service
from app.services.cashier_service import CashierService
from app.services.reservation_service import ReservationService
from app.services import data_service

TEST_DATA_DIR = r'tests\test_data_verification'

class VerifyReservationFlow(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
        
    def setUp(self):
        # Patch Paths
        self.original_sessions = cashier_service.CASHIER_SESSIONS_FILE
        self.test_sessions = os.path.join(TEST_DATA_DIR, 'cashier_sessions.json')
        cashier_service.CASHIER_SESSIONS_FILE = self.test_sessions
        
        self.original_res_payments = ReservationService.RESERVATION_PAYMENTS_FILE
        self.test_res_payments = os.path.join(TEST_DATA_DIR, 'reservation_payments.json')
        ReservationService.RESERVATION_PAYMENTS_FILE = self.test_res_payments
        
        self.original_manual_res = ReservationService.MANUAL_RESERVATIONS_FILE
        self.test_manual_res = os.path.join(TEST_DATA_DIR, 'manual_reservations.json')
        ReservationService.MANUAL_RESERVATIONS_FILE = self.test_manual_res
        
        self.original_payment_methods = data_service.PAYMENT_METHODS_FILE
        self.test_payment_methods = os.path.join(TEST_DATA_DIR, 'payment_methods.json')
        data_service.PAYMENT_METHODS_FILE = self.test_payment_methods

        # Initialize Files
        with open(self.test_sessions, 'w') as f: json.dump([], f)
        with open(self.test_res_payments, 'w') as f: json.dump({}, f)
        with open(self.test_manual_res, 'w') as f: json.dump([], f)
        
        # Payment Methods
        methods = [
            {'id': '1', 'name': 'Dinheiro', 'available_in': ['caixa_reservas', 'reception']},
            {'id': '2', 'name': 'PIX', 'available_in': ['caixa_reservas', 'reception']}
        ]
        with open(self.test_payment_methods, 'w', encoding='utf-8') as f:
            json.dump(methods, f, ensure_ascii=False)
            
        # Login
        with self.client.session_transaction() as sess:
            sess['user'] = 'tester'
            sess['role'] = 'admin'
            sess['permissions'] = ['recepcao']

    def tearDown(self):
        cashier_service.CASHIER_SESSIONS_FILE = self.original_sessions
        ReservationService.RESERVATION_PAYMENTS_FILE = self.original_res_payments
        ReservationService.MANUAL_RESERVATIONS_FILE = self.original_manual_res
        data_service.PAYMENT_METHODS_FILE = self.original_payment_methods

    def test_reservation_payment_flow(self):
        """
        Validation 1 & 2: Verify reservation payment flow and check-in integration.
        """
        # 1. Create Manual Reservation
        res_service = ReservationService()
        new_res = res_service.create_manual_reservation({
            'guest_name': 'Teste Flow',
            'checkin': '01/03/2026',
            'checkout': '05/03/2026',
            'amount': '1000.00',
            'paid_amount': '0.00',
            'to_receive': '1000.00'
        })
        res_id = new_res['id']
        
        # 2. Open Cashier
        self.client.post('/reception/reservations-cashier', data={
            'action': 'open_cashier',
            'opening_balance': '100.00'
        })
        
        # 3. Simulate Payment via Modal (POST /reception/reservation/pay)
        resp = self.client.post('/reception/reservation/pay', json={
            'reservation_id': res_id,
            'amount': 200.00,
            'payment_method_id': '2',
            'payment_method_name': 'PIX'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json['success'])
        
        # 4. Verify Payment Recorded in ReservationService
        payments = res_service.get_reservation_payments()
        self.assertIn(res_id, payments)
        self.assertEqual(len(payments[res_id]), 1)
        self.assertEqual(payments[res_id][0]['amount'], 200.00)
        self.assertEqual(payments[res_id][0]['details']['method'], 'PIX')
        
        # 5. Verify Debt Calculation
        resp_debt = self.client.get(f'/reception/reservation/{res_id}/debt')
        data = resp_debt.json
        self.assertEqual(data['total'], 1000.00)
        # Note: manual_reservations.json might not be updated by add_payment if it relies on file structure not fully mocked or if add_payment logic for manual update fails silently.
        # Check if manual reservation file was updated
        updated_res = res_service.get_reservation_by_id(res_id)
        # In the service code read earlier:
        # if res.get('source_type') == 'manual': self.update_manual_reservation_payment(...)
        # get_reservation_by_id checks manual file.
        
        self.assertEqual(float(updated_res['paid_amount']), 200.00)
        self.assertEqual(float(updated_res['to_receive']), 800.00)
        
        # 6. Verify Cashier Transaction
        session = CashierService.get_active_session('reservation_cashier')
        self.assertIsNotNone(session)
        transactions = session['transactions']
        self.assertEqual(len(transactions), 1) # +1 opening? No, transactions list usually starts empty or with opening?
        # Check specific transaction
        sale_trans = [t for t in transactions if t.get('type') != 'opening']
        self.assertEqual(len(sale_trans), 1)
        self.assertEqual(sale_trans[0]['amount'], 200.00)
        self.assertIn('Teste Flow', sale_trans[0]['description'])
        
        print("Reservation Payment Flow Verified Successfully")

if __name__ == '__main__':
    unittest.main()
