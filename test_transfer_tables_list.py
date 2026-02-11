
import pytest
from app import create_app
from app.services.data_service import save_table_orders, load_table_orders, save_restaurant_table_settings

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            # Setup: Ensure no disabled tables blocking us
            save_restaurant_table_settings({'disabled_tables': []})
            # Ensure some tables are open to test "occupied" status logic if needed
            save_table_orders({})
        yield client

def test_transfer_modal_includes_all_tables(client):
    """Test that transfer modal includes tables beyond 60 (e.g. 100)"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Open table 36 so we can access its order page
    client.post('/restaurant/table/36', data={
        'action': 'open_table',
        'num_adults': '2',
        'customer_type': 'passante'
    }, follow_redirects=True)

    # Get the page
    response = client.get('/restaurant/table/36')
    html = response.data.decode('utf-8')

    # Check for presence of Table 100 in the options
    # The select options look like: <option value="100" ...>
    assert 'value="60"' in html, "Table 60 should be present"
    assert 'value="100"' in html, "Table 100 should be present (bug reproduction)"
    
    # Check Transfer Item Modal specifically (it uses the same list but let's be sure)
    # Since they are rendered in the same loop in HTML, checking once is technically enough,
    # but logically we confirm the fix applies to the whole page.
    # The HTML structure is repeated for options, so finding value="100" confirms it's in the DOM.
    # To be more specific, we could check if it appears multiple times if needed, 
    # but Jinja renders it server-side.
    
    # Let's count occurrences of value="100"
    # It should appear in Transfer Table modal AND Transfer Item modal
    # AND potentially in other selects if any.
    count_100 = html.count('value="100"')
    assert count_100 >= 2, "Table 100 should appear in at least two select menus (Transfer Table and Transfer Item)"
    
    # Also check if it handles alphanumeric if any logic adds them
    # But mainly we want to ensure range 36-101 is covered.

def test_api_available_tables_range(client):
    """Verify API endpoint also returns full range"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'
        
    response = client.get('/api/available_tables')
    data = response.get_json()
    
    assert '60' in data
    assert '100' in data
