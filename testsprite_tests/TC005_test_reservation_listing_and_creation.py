import requests

BASE_URL = "http://localhost:5001"
USERNAME = "Angelo"
PASSWORD = "2904"
TIMEOUT = 30

def test_reservation_listing_and_creation():
    session = requests.Session()
    try:
        # Authenticate via POST /login
        login_url = f"{BASE_URL}/login"
        login_data = {
            "username": USERNAME,
            "password": PASSWORD
        }
        login_resp = session.post(login_url, data=login_data, timeout=TIMEOUT)
        assert login_resp.status_code == 200, f"Login failed: {login_resp.status_code} {login_resp.text}"

        # Use session cookie set by login for subsequent requests

        # Test GET /reception/rooms - list room status and reservations
        get_rooms_url = f"{BASE_URL}/reception/rooms"
        get_resp = session.get(get_rooms_url, timeout=TIMEOUT)
        assert get_resp.status_code == 200, f"Failed to list rooms: {get_resp.status_code} {get_resp.text}"
        # Response is HTML but should contain some indication of room listing
        assert "room" in get_resp.text.lower() or "reservation" in get_resp.text.lower(), "Response does not appear to contain room or reservation info."

        # Prepare data for POST /reception/rooms to create/update reservation
        post_rooms_url = f"{BASE_URL}/reception/rooms"

        # Minimal form data example to create a reservation or make an update.
        # Since specifics of required fields are not detailed, use common plausible fields.
        # We validate server-side validation by providing correct and incorrect data.

        # First test invalid data (missing required fields) to see validation response
        invalid_data = {
            # deliberately empty or incomplete
        }
        invalid_resp = session.post(post_rooms_url, data=invalid_data, timeout=TIMEOUT)
        # Server should reject invalid input, expecting status code 400 or similar
        assert invalid_resp.status_code in (400, 422), f"Invalid data accepted: {invalid_resp.status_code} {invalid_resp.text}"

        # Now test valid reservation creation data
        # Example fields (assuming typical reservation fields)
        valid_data = {
            "room_number": "101",
            "guest_name": "Test Guest",
            "check_in_date": "2026-03-01",
            "check_out_date": "2026-03-05",
            "guests": "2",
            "notes": "Test reservation creation"
        }
        valid_resp = session.post(post_rooms_url, data=valid_data, timeout=TIMEOUT)
        # Expect redirect or success status (200 or 3xx)
        assert valid_resp.status_code in (200, 201, 302), f"Failed to create/update reservation: {valid_resp.status_code} {valid_resp.text}"

        # Optionally, re-list rooms to confirm new reservation presence (if accessible)
        confirm_resp = session.get(get_rooms_url, timeout=TIMEOUT)
        assert confirm_resp.status_code == 200, f"Failed to confirm reservation listing: {confirm_resp.status_code} {confirm_resp.text}"
        # Confirm guest_name should be in response text after creation, if HTML includes it
        assert "Test Guest" in confirm_resp.text, "Created reservation not found in room listing."

    finally:
        # Logout to clean session if needed
        try:
            logout_resp = session.get(f"{BASE_URL}/logout", timeout=TIMEOUT, allow_redirects=False)
            # logout returns a redirect to login or 200, accept either
            assert logout_resp.status_code in (200, 302), "Logout failed or returned unexpected status."
        except Exception:
            pass
        session.close()

test_reservation_listing_and_creation()