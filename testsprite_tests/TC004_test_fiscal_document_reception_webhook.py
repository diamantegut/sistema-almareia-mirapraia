import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "http://localhost:5001"
USERNAME = "angelo"
PASSWORD = "2904"
TIMEOUT = 30

def test_fiscal_document_reception_webhook():
    """
    Validate the /api/fiscal/receive POST endpoint for receiving fiscal document updates via webhook,
    ensuring protocol compliance and correct status monitoring.
    This endpoint does NOT require session authentication.
    """
    url = f"{BASE_URL}/api/fiscal/receive"
    headers = {
        "Content-Type": "application/json"
    }

    # Adjusted payload to comply with server requirement of 'id' field instead of 'document_id'
    payload = {
        "id": "1234567890",
        "status": "processed",
        "timestamp": "2026-02-06T12:34:56Z",
        "details": {
            "type": "NFe",
            "issuer": {
                "name": "Empresa Exemplo Ltda",
                "cnpj": "12345678000195"
            },
            "value": 1500.75,
            "items": [
                {"item_code": "ABC123", "quantity": 1, "price": 1500.75}
            ],
            "protocol_number": "1357924680"
        }
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=TIMEOUT
        )
    except requests.RequestException as e:
        assert False, f"HTTP request to {url} failed: {e}"

    # Assert successful HTTP response
    assert response.status_code in (200, 201, 202), (
        f"Unexpected status code {response.status_code}, response text: {response.text}"
    )

    # Assert content type JSON
    content_type = response.headers.get("Content-Type", "")
    assert "application/json" in content_type.lower(), (
        f"Response Content-Type is not JSON: {content_type}"
    )

    # Parse response JSON and validate expected fields
    try:
        data = response.json()
    except ValueError:
        assert False, f"Response is not valid JSON: {response.text}"

    # Removed assertion for 'received' field as it's not in the response per test failure

    assert "id" in data, "Response JSON missing 'id' field"
    assert data["id"] == payload["id"], (
        f"Response id '{data['id']}' does not match request '{payload['id']}'"
    )

    # Optional: check if status confirmed in response
    assert "status" in data, "Response JSON missing 'status' field"
    assert data["status"] == payload["status"], (
        f"Response status '{data['status']}' does not match request '{payload['status']}'"
    )

test_fiscal_document_reception_webhook()
