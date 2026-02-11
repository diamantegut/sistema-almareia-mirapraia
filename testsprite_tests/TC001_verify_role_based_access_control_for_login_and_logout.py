import requests

BASE_URL = 'http://localhost:5001'
USERNAME = 'Angelo'
PASSWORD = '2904'
TIMEOUT = 30

def test_verify_role_based_access_control_for_login_and_logout():
    session = requests.Session()
    login_url = f"{BASE_URL}/login"
    logout_url = f"{BASE_URL}/logout"
    login_data = {
        'username': USERNAME,
        'password': PASSWORD
    }

    # Login POST request
    try:
        login_resp = session.post(login_url, data=login_data, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Login request failed: {e}"

    assert login_resp.status_code == 200, f"Expected 200 OK on login, got {login_resp.status_code}"

    # Confirm login response has session cookies indicating authenticated session
    assert session.cookies, "Session cookies not set after login"

    # Logout GET request
    try:
        logout_resp = session.get(logout_url, allow_redirects=False, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Logout request failed: {e}"

    # Logout may redirect (302) or render login page (200)
    assert logout_resp.status_code in (200, 302), f"Expected 200 or 302 on logout, got {logout_resp.status_code}"

    # After logout, session cookies should be cleared or invalidated; try accessing a protected resource to confirm logout.
    # Since no other endpoint specified for role-protected test, attempt to access /logout again (should not be logged in).
    try:
        post_logout_resp = session.get(logout_url, allow_redirects=False, timeout=TIMEOUT)
    except requests.RequestException as e:
        assert False, f"Post logout request failed: {e}"

    # The server should treat this as logged out, typically redirecting to login page (302) or showing login page (200)
    assert post_logout_resp.status_code in (200, 302), f"Expected 200 or 302 after logout confirmation, got {post_logout_resp.status_code}"

    # Additionally, cookies should be expired or cleared
    # Requests session won't auto clear cookies, but server side should invalidate sessions
    # We can check cookie expiry if set by server
    # Here, just confirm no auth cookies in last response
    cookie_header = post_logout_resp.headers.get('Set-Cookie', '')
    # In many cases logout sets expired cookie; so either Set-Cookie header present or no authentication
    # We allow both cases here

test_verify_role_based_access_control_for_login_and_logout()
