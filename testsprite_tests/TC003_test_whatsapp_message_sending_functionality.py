import requests
from requests.exceptions import RequestException, Timeout

BASE_URL = 'http://localhost:5001'
USERNAME = 'Angelo'
PASSWORD = '2904'
TIMEOUT = 30

def test_whatsapp_message_sending_functionality():
    session = requests.Session()
    try:
        # Step 1: Authenticate as admin
        login_url = f"{BASE_URL}/login"
        login_data = {
            "username": USERNAME,
            "password": PASSWORD
        }
        login_response = session.post(login_url, data=login_data, timeout=TIMEOUT)
        assert login_response.status_code == 200, f"Login failed with status code {login_response.status_code}"

        # Step 2: Prepare WhatsApp message payload
        send_url = f"{BASE_URL}/api/chat/send"
        
        test_phone = "+1234567890"  # Use a test phone number format
        test_message = "Test WhatsApp message template: Hello, this is a test message from TC003."

        headers = {
            "Content-Type": "application/json"
        }

        # Send message once
        send_payload = {
            "phone": test_phone,
            "message": test_message
        }
        send_response = session.post(send_url, json=send_payload, headers=headers, timeout=TIMEOUT)
        assert send_response.status_code == 200, f"Send message failed with status code {send_response.status_code}"
        send_json = send_response.json()
        # Basic validation of success keys (depends on actual API response schema)
        assert "status" in send_json, "Response missing 'status' field"
        assert send_json["status"] in ("sent", "queued", "delivered", "retrying", "failed"), f"Unexpected status: {send_json['status']}"

        # If the status is retrying or failed, attempt a retry to simulate retry handling
        if send_json["status"] in ("retrying", "failed"):
            retry_response = session.post(send_url, json=send_payload, headers=headers, timeout=TIMEOUT)
            assert retry_response.status_code == 200, f"Retry send failed with status code {retry_response.status_code}"
            retry_json = retry_response.json()
            assert "status" in retry_json, "Retry response missing 'status' field"
            # Validate retry status is not failed if retry was accepted
            assert retry_json["status"] != "failed", f"Retry attempt failed with status: {retry_json['status']}"

        # Testing message templates handling: send a second message simulating template usage
        template_message = "Hello {{name}}, your booking is confirmed."
        send_payload_template = {
            "phone": test_phone,
            "message": template_message.replace("{{name}}", "Angelo")
        }
        template_response = session.post(send_url, json=send_payload_template, headers=headers, timeout=TIMEOUT)
        assert template_response.status_code == 200, f"Template message send failed with status code {template_response.status_code}"
        template_json = template_response.json()
        assert template_json.get("status") in ("sent", "queued", "delivered"), "Template message status invalid"

        # Step 3: Check for presence of chat session indicators or status notifications if provided
        # As the PRD does not specify exact response schema beyond status, we check reasonable fields
        for resp_json in (send_json, template_json):
            # Example check for notification or chat session status keys (may vary)
            if "notifications" in resp_json:
                assert isinstance(resp_json["notifications"], list), "Notifications field present but is not a list"
            if "session_status" in resp_json:
                assert resp_json["session_status"] in ("active", "closed", "pending"), f"Unexpected session_status: {resp_json['session_status']}"

    except (RequestException, Timeout) as e:
        assert False, f"HTTP request failed: {e}"
    finally:
        # Logout to clean the session
        try:
            logout_url = f"{BASE_URL}/logout"
            logout_response = session.get(logout_url, timeout=TIMEOUT)
            assert logout_response.status_code in (200, 302), f"Logout failed with status code {logout_response.status_code}"
        except Exception:
            pass