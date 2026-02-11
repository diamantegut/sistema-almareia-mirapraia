
import pytest
import uuid
import logging
from app import create_app
from app.services.data_service import load_table_orders, save_table_orders, save_restaurant_table_settings

@pytest.fixture
def client(caplog):
    app = create_app()
    app.config['TESTING'] = True
    # Configure logging to capture
    app.logger.setLevel(logging.ERROR)
    
    with app.test_client() as client:
        with app.app_context():
            orders = {}
            # Table 60: Source
            item_id = str(uuid.uuid4())
            orders['60'] = {
                'items': [
                    {
                        'id': item_id,
                        'name': 'Soda', 
                        'price': 5.0, 
                        'qty': 5.0, 
                        'observations': []
                    }
                ],
                'total': 25.0,
                'opened_at': '01/01/2025 12:00',
                'status': 'open'
            }
            save_table_orders(orders)
            save_restaurant_table_settings({'disabled_tables': []})
            
        yield client, item_id, caplog
        save_table_orders({})
        save_restaurant_table_settings({})

def test_transfer_item_not_found_id(client):
    """Test transfer with non-existent item ID"""
    client_app, real_item_id, caplog = client
    fake_id = str(uuid.uuid4())
    
    with client_app.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    response = client_app.post('/restaurant/transfer_item', json={
        'source_table_id': '60',
        'target_table_id': '61',
        'item_index': -1,
        'item_id': fake_id,
        'qty': 1.0
    }, follow_redirects=True)
    
    assert response.status_code == 404
    data = response.get_json()
    assert 'Item não encontrado' in data['error']
    
    # Verify Error Log
    assert "Transfer Item Failed: Item Not Found" in caplog.text
    assert f"ItemID={fake_id}" in caplog.text

def test_transfer_item_invalid_format(client):
    """Test transfer with null ID and invalid index"""
    client_app, real_item_id, caplog = client
    
    with client_app.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    response = client_app.post('/restaurant/transfer_item', json={
        'source_table_id': '60',
        'target_table_id': '61',
        'item_index': 'invalid_index',
        'item_id': None,
        'qty': 1.0
    }, follow_redirects=True)
    
    assert response.status_code == 404
    assert 'Item não encontrado' in response.get_json()['error']

def test_transfer_item_fallback_to_index(client):
    """Test fallback to index if ID is missing (backward compatibility)"""
    client_app, real_item_id, caplog = client
    
    with client_app.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Provide valid index (0) but NO item_id
    response = client_app.post('/restaurant/transfer_item', json={
        'source_table_id': '60',
        'target_table_id': '61',
        'item_index': 0,
        # item_id missing
        'qty': 1.0
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert response.get_json()['success'] is True
    
    # Verify item moved
    orders = load_table_orders()
    # Source has 4 left
    assert orders['60']['items'][0]['qty'] == 4.0
    # Target has 1
    assert '61' in orders
    assert orders['61']['items'][0]['qty'] == 1.0

def test_transfer_item_priority_id_over_index(client):
    """Test that valid ID takes precedence over invalid index"""
    client_app, real_item_id, caplog = client
    
    with client_app.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Index 999 is invalid, but ID is valid
    response = client_app.post('/restaurant/transfer_item', json={
        'source_table_id': '60',
        'target_table_id': '62',
        'item_index': 999,
        'item_id': real_item_id,
        'qty': 1.0
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert response.get_json()['success'] is True

