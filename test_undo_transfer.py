
import pytest
from app import create_app
from app.services.data_service import load_table_orders, save_table_orders, save_restaurant_table_settings
import json

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            # Setup initial state
            orders = {}
            # Table 20: Target (has items transferred from 10)
            orders['20'] = {
                'items': [{'name': 'Coke', 'price': 5.0, 'qty': 1}],
                'total': 5.0,
                'opened_at': '01/01/2025 12:00',
                'last_transfer': {'source_table': '10', 'timestamp': '...'}
            }
            save_table_orders(orders)
            
            # Reset table settings
            save_restaurant_table_settings({})
            
        yield client
        # Cleanup
        save_table_orders({})
        save_restaurant_table_settings({})

def test_undo_transfer_success(client):
    """Test undoing transfer to an empty original table"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Try to undo transfer from 20 back to 10
    response = client.post('/restaurant/table/20', data={
        'action': 'cancel_transfer',
        'return_table_id': '10'
    }, follow_redirects=True)
    
    # Check if Table 10 is open and has the item
    orders = load_table_orders()
    assert '10' in orders
    assert len(orders['10']['items']) == 1
    assert orders['10']['items'][0]['name'] == 'Coke'
    
    # Check if Table 20 is closed
    assert '20' not in orders

def test_undo_transfer_merge(client):
    """Test undoing transfer to an occupied table (merge)"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'
        
        # Setup: Table 10 is ALSO occupied
        orders = load_table_orders()
        orders['10'] = {
            'items': [{'name': 'Burger', 'price': 10.0, 'qty': 1}],
            'total': 10.0,
            'opened_at': '01/01/2025 12:05'
        }
        # Keep Table 20 as set in fixture
        save_table_orders(orders)

    # Try to undo transfer from 20 back to 10
    response = client.post('/restaurant/table/20', data={
        'action': 'cancel_transfer',
        'return_table_id': '10'
    }, follow_redirects=True)
    
    # Check if Table 10 has BOTH items
    orders = load_table_orders()
    assert '10' in orders
    items = orders['10']['items']
    names = [i['name'] for i in items]
    assert 'Coke' in names
    assert 'Burger' in names
    
    # Table 20 should be closed
    assert '20' not in orders

def test_check_table_status_endpoint(client):
    """Test API endpoint for checking table status"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'
        
    # Table 20 is occupied (from fixture)
    resp = client.get('/api/check_table/20')
    data = json.loads(resp.data)
    assert data['status'] == 'occupied'
    
    # Table 99 is empty
    resp = client.get('/api/check_table/99')
    data = json.loads(resp.data)
    assert data['status'] == 'open'

def test_get_available_tables_endpoint(client):
    """Test API endpoint for available tables list"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'
        
    # Table 20 is occupied
    resp = client.get('/api/available_tables')
    data = json.loads(resp.data)
    
    assert isinstance(data, list)
    assert '20' not in data # Should be occupied
    assert '36' in data # Should be available (start of range)
    assert '100' in data # Should be available (end of range)
    assert '40' in data # Should be available (Area 1)

def test_undo_transfer_invalid_table(client):
    """Test undoing transfer with invalid table ID"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Try to undo transfer from 20 to invalid table ID
    response = client.post('/restaurant/table/20', data={
        'action': 'cancel_transfer',
        'return_table_id': 'INVALID#TABLE'
    }, follow_redirects=True)
    
    # Should flash error and NOT move items
    assert b'ID da mesa de destino inv' in response.data or b'Mesa de destino para devolu' in response.data
    
    # Check if Table 20 is still open
    orders = load_table_orders()
    assert '20' in orders
