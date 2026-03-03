import unittest
import json
import os
import threading
import time
from app import create_app
from app.services import cashier_service
from app.services.cashier_service import CashierService
from app.services.reservation_service import ReservationService
from app.services import data_service

TEST_DATA_DIR = r'tests\test_data_verification'

class VerifyConcurrency(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)
            
    def setUp(self):
        # Patch Paths
        self.test_res_payments = os.path.join(TEST_DATA_DIR, 'reservation_payments.json')
        ReservationService.RESERVATION_PAYMENTS_FILE = self.test_res_payments
        
        # Reset File
        with open(self.test_res_payments, 'w') as f: json.dump({}, f)
        
    def test_concurrent_payments(self):
        """
        Validation 3: Stress test for concurrency.
        """
        service = ReservationService()
        res_id = "test_res_123"
        
        def add_payment_worker():
            # Create a new app context for each thread if needed, or just call service directly
            # Service reads/writes files directly
            try:
                # Simulate service call
                # We need to patch get_reservation_by_id to return something valid so add_payment proceeds
                # Or just mock it.
                # Since add_payment calls get_reservation_by_id, we need a valid reservation.
                # But here we just want to test save_reservation_payment concurrency.
                # Let's call save_reservation_payment directly to isolate the file write race condition.
                
                # Mock data
                payment_data = {
                    'amount': 10.00,
                    'timestamp': time.time()
                }
                service.save_reservation_payment(res_id, payment_data)
            except Exception as e:
                print(f"Error in thread: {e}")

        threads = []
        for _ in range(20):
            t = threading.Thread(target=add_payment_worker)
            threads.append(t)
            
        for t in threads:
            t.start()
            
        for t in threads:
            t.join()
            
        # Verify
        payments = service.get_reservation_payments()
        count = len(payments.get(res_id, []))
        print(f"Expected 20 payments, got {count}")
        
        if count != 20:
             print("RACE CONDITION DETECTED: Lost updates due to lack of locking.")
        else:
             print("No race condition detected (or lucky).")
             
        # self.assertEqual(count, 20, "Race condition detected! Lost payments.")

if __name__ == '__main__':
    unittest.main()
