import requests

BASE_URL = 'http://localhost:5001'
LOGIN_URL = f'{BASE_URL}/login'
BACKUP_TRIGGER_URL = f'{BASE_URL}/api/backups/trigger'

USERNAME = 'Angelo'
PASSWORD = '2904'
TIMEOUT = 30

def test_backup_creation_api_functionality():
    session = requests.Session()
    try:
        # Authenticate as admin
        login_payload = {'username': USERNAME, 'password': PASSWORD}
        login_headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        login_response = session.post(LOGIN_URL, data=login_payload, headers=login_headers, timeout=TIMEOUT)
        assert login_response.status_code == 200, f'Login failed with status code {login_response.status_code}'

        # Backup types to test
        backup_types = ['products', 'restaurant_tables', 'reception_data', 'full_system']

        for backup_type in backup_types:
            trigger_url = f'{BACKUP_TRIGGER_URL}/{backup_type}'

            # Trigger manual backup
            trigger_response = session.post(trigger_url, timeout=TIMEOUT)
            assert trigger_response.status_code == 200, (
                f'Backup trigger failed for type "{backup_type}" with status code {trigger_response.status_code}'
            )

            # Validate response content (assuming JSON with success and retention info)
            try:
                response_json = trigger_response.json()
            except ValueError:
                response_json = {}

            # We expect some indication of success in the response
            # As PRD doesn't specify exact schema, check keys commonly used
            assert 'success' in response_json or trigger_response.text.strip() != '', (
                f'Unexpected response content for backup type "{backup_type}"'
            )

            # Optionally validate retention policy adherence if info present
            if 'retention_policy' in response_json:
                retention = response_json['retention_policy']
                assert isinstance(retention, dict), 'Retention policy should be a dictionary'
                # Example checks on retention policy keys
                assert 'max_backups' in retention or 'retention_days' in retention, (
                    'Retention policy missing expected fields'
                )

        # After all backup triggers, attempt one more to simulate manual trigger without data loss
        manual_trigger_response = session.post(f'{BACKUP_TRIGGER_URL}/full_system', timeout=TIMEOUT)
        assert manual_trigger_response.status_code == 200, (
            'Manual backup trigger for full_system failed.'
        )

    finally:
        # Logout or close session if any logout needed - no logout endpoint explicitly needed here
        session.close()

test_backup_creation_api_functionality()
