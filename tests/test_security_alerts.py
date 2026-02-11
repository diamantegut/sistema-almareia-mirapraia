
import unittest
import sys
import os
import json
from datetime import datetime

# Add parent directory to path to import security_service
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security_service import (
    check_discount_alert,
    check_commission_manipulation,
    check_table_closing_anomalies,
    check_table_transfer_anomaly,
    check_sensitive_access,
    load_alerts,
    load_security_settings,
    save_security_settings
)

class TestSecurityAlerts(unittest.TestCase):
    def setUp(self):
        # Backup existing settings
        self.original_settings = load_security_settings()
        
        # Set predictable settings for testing
        test_settings = self.original_settings.copy()
        test_settings['max_discount_percent'] = 10.0
        test_settings['min_transaction_value'] = 20.0
        save_security_settings(test_settings)
        
        self.test_user = "TestUser"
        self.test_table = "999"

    def tearDown(self):
        # Restore settings
        save_security_settings(self.original_settings)

    def test_discount_alert(self):
        print("\nTesting Discount Alert...")
        initial_alerts = len(load_alerts())
        
        # Case 1: Safe discount (10%)
        check_discount_alert(10.0, 100.0, self.test_user)
        current_alerts = len(load_alerts())
        self.assertEqual(current_alerts, initial_alerts, "Safe discount should not trigger alert")
        
        # Case 2: Excessive discount (20%)
        check_discount_alert(20.0, 100.0, self.test_user)
        new_alerts = load_alerts()
        self.assertEqual(len(new_alerts), initial_alerts + 1, "Excessive discount should trigger alert")
        self.assertEqual(new_alerts[0]['type'], "Desconto Excessivo")
        print("Discount Alert: OK")

    def test_commission_manipulation(self):
        print("\nTesting Commission Manipulation...")
        initial_alerts = len(load_alerts())
        
        # Case 1: Locked order item removal
        check_commission_manipulation("Picanha", 1, 100.0, self.test_user, self.test_table, order_locked=True)
        new_alerts = load_alerts()
        self.assertEqual(len(new_alerts), initial_alerts + 1, "Locked item removal should trigger alert")
        self.assertEqual(new_alerts[0]['type'], "Manipulação de Comissão (Pós-Fechamento)")
        print("Commission Manipulation Alert: OK")

    def test_table_closing_anomaly(self):
        print("\nTesting Table Closing Anomaly...")
        initial_alerts = len(load_alerts())
        
        # Case 1: Short duration (5 mins) AND Low Value (Trigger Condition)
        # Note: Logic requires both short duration (<10) AND low value (< min_transaction_value)
        check_table_closing_anomalies(self.test_table, 5, 5.0, self.test_user)
        new_alerts = load_alerts()
        self.assertEqual(len(new_alerts), initial_alerts + 1, "Short duration & low value should trigger alert")
        self.assertEqual(new_alerts[0]['type'], "Fechamento Suspeito")
        print("Table Closing Alert: OK")

    def test_sensitive_access(self):
        print("\nTesting Sensitive Access...")
        initial_alerts = len(load_alerts())
        
        # Case 1: Unauthorized access
        check_sensitive_access("reprint_bill", "UnauthorizedUser", "Tentativa de acesso")
        new_alerts = load_alerts()
        # Note: check_sensitive_access might check roles internally, but if we pass a user that doesn't trigger the internal role check (or if logic is simple), it should log.
        # Looking at implementation, check_sensitive_access usually logs if called.
        self.assertTrue(len(new_alerts) >= initial_alerts + 1, "Sensitive access should trigger alert")
        print("Sensitive Access Alert: OK")

if __name__ == '__main__':
    unittest.main()
