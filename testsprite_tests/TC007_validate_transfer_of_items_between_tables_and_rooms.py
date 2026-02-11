import requests
from requests.exceptions import RequestException

BASE_URL = 'http://localhost:5001'
USERNAME = 'restaurant_user'
PASSWORD = 'restaurant_pass'
TIMEOUT = 30

def test_validate_transfer_of_items_between_tables_and_rooms():
    session = requests.Session()
    try:
        # Authenticate as restaurant user
        login_url = f"{BASE_URL}/login"
        login_data = {
            'username': USERNAME,
            'password': PASSWORD
        }
        login_resp = session.post(login_url, data=login_data, timeout=TIMEOUT)
        assert login_resp.status_code == 200, f"Login failed with status {login_resp.status_code}"
        # Session cookies are stored automatically in 'session'

        # Dummy data for transfer (normally should come from setup or created resources)
        source_table_id = "T1"
        dest_table_id = "T2"
        source_room_id = "R1"
        dest_room_id = "R2"
        item_id = "item123"
        quantity = 2

        transfer_url = f"{BASE_URL}/restaurant/transfer_item"

        def do_transfer(payload):
            resp = session.post(transfer_url, json=payload, timeout=TIMEOUT)
            return resp

        # Test 1: Successful atomic transfer between tables
        payload_success = {
            "source": {"type": "table", "id": source_table_id},
            "destination": {"type": "table", "id": dest_table_id},
            "items": [{"item_id": item_id, "quantity": quantity}],
            "print_receipt": True
        }
        resp = do_transfer(payload_success)
        assert resp.status_code == 200, f"Expected 200 on successful transfer, got {resp.status_code}"
        resp_json = resp.json()
        assert resp_json.get("status") == "success", f"Transfer response status is not success: {resp_json}"
        assert "receipt" in resp_json, "Receipt info missing in successful transfer response"

        # Test 2: Permission check - try with a user with no permission
        # Log out current session
        logout_url = f"{BASE_URL}/logout"
        session.get(logout_url, timeout=TIMEOUT)

        session_no_perm = requests.Session()
        # Attempt transfer without login
        resp_no_auth = session_no_perm.post(transfer_url, json=payload_success, timeout=TIMEOUT)
        assert resp_no_auth.status_code in (401, 403), f"Expected 401 or 403 for unauthorized transfer, got {resp_no_auth.status_code}"

        # Test 3: Rollback on failure - provide an invalid destination to cause failure
        
        # Log in again for this test
        login_resp2 = session.post(login_url, data=login_data, timeout=TIMEOUT)
        assert login_resp2.status_code == 200, f"Re-login failed with status {login_resp2.status_code}"

        payload_failure = {
            "source": {"type": "table", "id": source_table_id},
            "destination": {"type": "table", "id": "INVALID_TABLE_ID"},
            "items": [{"item_id": item_id, "quantity": quantity}],
            "print_receipt": True
        }
        resp_fail = do_transfer(payload_failure)
        assert resp_fail.status_code >= 400, "Expected failure status code on invalid destination"
        resp_fail_json = resp_fail.json()
        assert resp_fail_json.get("status") == "error" or resp_fail_json.get("error"), "Expected error in response on failure"

        # Verify atomic rollback behavior by checking source table items remain unchanged
        check_table_url = f"{BASE_URL}/api/check_table/{source_table_id}"
        check_resp = session.get(check_table_url, timeout=TIMEOUT)
        assert check_resp.status_code == 200, f"Failed to get source table details for rollback verification"
        table_data = check_resp.json()
        items_list = table_data.get("items", [])
        item_quantities = {item.get("item_id"): item.get("quantity") for item in items_list if "item_id" in item}
        assert item_quantities.get(item_id, 0) >= quantity, "Item quantity after failed transfer indicates no rollback"

    except RequestException as e:
        raise AssertionError(f"HTTP request failed: {e}")
    finally:
        # Logout to clean session
        try:
            logout_url = f"{BASE_URL}/logout"
            session.get(logout_url, timeout=TIMEOUT)
        except Exception:
            pass

test_validate_transfer_of_items_between_tables_and_rooms()
