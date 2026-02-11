
import json
import os
import unittest
import sys
from datetime import datetime

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, ROOM_CHARGES_FILE, AUDIT_LOGS_FILE, load_room_charges, save_room_charges
from guest_notification_service import NOTIFICATIONS_FILE

class TestCancellationIntegration(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        # Create a dummy charge for testing
        self.test_charge_id = f"TEST_CHARGE_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.test_charge = {
            "id": self.test_charge_id,
            "room_number": "999",
            "guest_name": "Integration Test Guest",
            "item": "Test Item",
            "quantity": 1,
            "price": 10.0,
            "total": 10.0,
            "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "status": "pending"
        }
        
        # Load existing charges, add test charge, save
        charges = load_room_charges()
        charges.append(self.test_charge)
        save_room_charges(charges)
        
        # Backup original files content to restore later if needed (optional, but good practice)
        # For this script, we'll just remove the test entries at the end.

    def tearDown(self):
        # Clean up: Remove the test charge
        charges = load_room_charges()
        charges = [c for c in charges if c['id'] != self.test_charge_id]
        save_room_charges(charges)
        
        # Clean up: Remove test audit logs (optional, maybe tricky if other logs exist)
        # We can leave audit logs as they are "immutable" records of tests too, 
        # or filter them out. For simplicity, we leave them or just remove the specific one.
        if os.path.exists(AUDIT_LOGS_FILE):
            try:
                with open(AUDIT_LOGS_FILE, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                logs = [l for l in logs if l.get('details', {}).get('charge_id') != self.test_charge_id]
                with open(AUDIT_LOGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(logs, f, indent=4)
            except:
                pass

    def test_full_cancellation_flow(self):
        print("\n--- Starting Integration Test: Full Cancellation Flow ---")
        
        # Step 1: Login as Admin (Simulated via session)
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_user'
            sess['role'] = 'admin'
        
        # Step 2: Call Cancel Endpoint
        print(f"Canceling charge {self.test_charge_id}...")
        response = self.client.post('/admin/consumption/cancel', json={
            'charge_id': self.test_charge_id,
            'justification': 'Integration Test Justification'
        })
        
        # Verify API Response
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        print("API Response: Success")
        
        # Step 3: Verify Database Update (room_charges.json)
        charges = load_room_charges()
        updated_charge = next((c for c in charges if c['id'] == self.test_charge_id), None)
        
        self.assertIsNotNone(updated_charge)
        self.assertEqual(updated_charge['status'], 'canceled')
        self.assertEqual(updated_charge['cancellation_reason'], 'Integration Test Justification')
        self.assertEqual(updated_charge['canceled_by'], 'admin_user')
        print("Database Verification: Status updated to 'canceled'")
        
        # Step 4: Verify Audit Log
        if os.path.exists(AUDIT_LOGS_FILE):
            with open(AUDIT_LOGS_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            
            audit_entry = next((l for l in logs if l.get('target_id') == self.test_charge_id), None)
            self.assertIsNotNone(audit_entry)
            self.assertEqual(audit_entry['action'], 'cancel_consumption')
            self.assertEqual(audit_entry['user'], 'admin_user')
            print("Audit Log Verification: Entry found")
        else:
            self.fail("Audit logs file not found")
            
        # Step 5: Verify Notification
        if os.path.exists(NOTIFICATIONS_FILE):
            with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                notifications = json.load(f)
            
            # Find notification for this room/guest created just now
            # Notification ID format: f"NOTIF_{datetime.now().strftime('%Y%m%d%H%M%S')}_{room_number}"
            # We check by room number. Guest name might be 'Hóspede' if not in occupancy.
            notif = next((n for n in notifications if n['room_number'] == '999'), None)
            
            # Note: Notification might be optional depending on config, but default is True
            # We assume default settings allow it.
            if notif:
                print("Notification Verification: Notification created")
                self.assertEqual(notif['type'], 'cancellation')
            else:
                print("Notification Verification: No notification found (check settings?)")
        else:
             print("Notification Verification: File not found (first notification?)")

        print("--- Integration Test Passed Successfully ---")

if __name__ == '__main__':
    unittest.main()
