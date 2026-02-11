import requests

BASE_URL = "http://localhost:5001"
USERNAME = "Angelo"
PASSWORD = "2904"
TIMEOUT = 30

def authenticate():
    session = requests.Session()
    login_url = f"{BASE_URL}/login"
    data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    response = session.post(login_url, data=data, timeout=TIMEOUT)
    assert response.status_code == 200, f"Login failed with status code {response.status_code}"
    return session

def test_validate_cashier_session_open_close_and_transactions():
    session = authenticate()
    cashier_url = f"{BASE_URL}/reception/cashier"

    # 1. Open cashier
    open_data = {
        "action": "open_cashier",
        "opening_balance": 100.00
    }
    open_response = session.post(cashier_url, data=open_data, timeout=TIMEOUT)
    assert open_response.status_code == 200, f"Open cashier failed: {open_response.text}"
    open_json = None
    try:
        open_json = open_response.json()
    except Exception:
        pass
    # Validate response indicates success or session opened
    if open_json:
        assert ("success" in open_json and open_json["success"] is True) or ("status" in open_json and open_json["status"] == "opened"), \
            f"Open cashier response unexpected: {open_json}"
    else:
        # If no json, just check text contains expected success phrase
        assert "opened" in open_response.text.lower() or "success" in open_response.text.lower(), \
            "Open cashier response missing success indication"

    # 2. Pay charge
    pay_data = {
        "action": "pay_charge",
        "charge_id": "test_charge_123"
    }
    pay_response = session.post(cashier_url, data=pay_data, timeout=TIMEOUT)
    assert pay_response.status_code == 200, f"Pay charge failed: {pay_response.text}"
    pay_json = None
    try:
        pay_json = pay_response.json()
    except Exception:
        pass
    if pay_json:
        assert ("success" in pay_json and pay_json["success"] is True) or ("status" in pay_json and pay_json["status"] == "paid"), \
            f"Pay charge response unexpected: {pay_json}"
    else:
        assert "paid" in pay_response.text.lower() or "success" in pay_response.text.lower(), \
            "Pay charge response missing success indication"

    # 3. Close cashier
    close_data = {
        "action": "close_cashier",
        "closing_balance": 100.00
    }
    close_response = session.post(cashier_url, data=close_data, timeout=TIMEOUT)
    assert close_response.status_code == 200, f"Close cashier failed: {close_response.text}"
    close_json = None
    try:
        close_json = close_response.json()
    except Exception:
        pass
    if close_json:
        assert ("success" in close_json and close_json["success"] is True) or ("status" in close_json and close_json["status"] == "closed"), \
            f"Close cashier response unexpected: {close_json}"
    else:
        assert "closed" in close_response.text.lower() or "success" in close_response.text.lower(), \
            "Close cashier response missing success indication"

test_validate_cashier_session_open_close_and_transactions()
