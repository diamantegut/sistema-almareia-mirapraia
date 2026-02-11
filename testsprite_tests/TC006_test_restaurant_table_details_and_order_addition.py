import requests

BASE_URL = "http://localhost:5001"
USERNAME = "angelo"
PASSWORD = "2904"

def test_restaurant_table_details_and_order_addition():
    session = requests.Session()
    session.headers.update({"User-Agent": "test-client"})
    login_url = f"{BASE_URL}/login"
    login_data = {"username": USERNAME, "password": PASSWORD}

    try:
        # Authenticate as admin
        login_resp = session.post(login_url, data=login_data, timeout=30)
        assert login_resp.status_code == 200, f"Login failed with status {login_resp.status_code}"
        # After login, session cookies should be set

        # Step 1: Identify a valid restaurant table id for testing
        table_id = 1

        # Step 2: GET /api/check_table/<id> to fetch table details
        get_table_url = f"{BASE_URL}/api/check_table/{table_id}"
        get_resp = session.get(get_table_url, timeout=30)
        assert get_resp.status_code == 200, f"Failed to GET table details: {get_resp.status_code}"

        # Ensure the response content-type is JSON
        content_type = get_resp.headers.get('Content-Type', '')
        assert 'application/json' in content_type, f"Response content-type not JSON: {content_type}, Response text: {get_resp.text}"

        try:
            table_details = get_resp.json()
        except Exception as e:
            assert False, f"Response is not valid JSON: {e}, Response text: {get_resp.text}"

        # Validate expected fields presence in the table details
        assert isinstance(table_details, dict), "Table details response is not a JSON object"
        assert "id" in table_details and table_details["id"] == table_id, "Table ID mismatch"
        assert "orders" in table_details, "Missing 'orders' field in table details"

    finally:
        session.close()