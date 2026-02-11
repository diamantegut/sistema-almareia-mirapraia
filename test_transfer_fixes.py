
import pytest
import json
from app import create_app
from app.services.data_service import load_table_orders, save_table_orders, save_restaurant_table_settings

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            # Setup initial state
            orders = {}
            # Table 40: Source with items
            orders['40'] = {
                'items': [
                    {'name': 'Coke', 'price': 5.0, 'qty': 2, 'observations': []},
                    {'name': 'Pizza', 'price': 20.0, 'qty': 1, 'observations': []}
                ],
                'total': 30.0,
                'opened_at': '01/01/2025 12:00',
                'status': 'open'
            }
            save_table_orders(orders)
            save_restaurant_table_settings({'disabled_tables': []})
            
        yield client
        # Cleanup
        save_table_orders({})
        save_restaurant_table_settings({})

def test_transfer_table_to_empty_81(client):
    """Test transferring a table to an empty table 81 (previously invalid)"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Transfer 40 -> 81
    response = client.post('/restaurant/table/40', data={
        'action': 'transfer_table',
        'target_table_id': '81'
    }, follow_redirects=True)

    orders = load_table_orders()
    
    # 40 should be closed (not in orders)
    assert '40' not in orders
    
    # 81 should be open and have items
    assert '81' in orders
    assert len(orders['81']['items']) == 2
    assert orders['81']['total'] == 30.0
    assert b'Mesa transferida para 81 com sucesso' in response.data

def test_undo_transfer_copy_fix(client):
    """Test undo transfer to verify copy import fix"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # First, perform a transfer 40 -> 81 to set up the state
    client.post('/restaurant/table/40', data={
        'action': 'transfer_table',
        'target_table_id': '81'
    }, follow_redirects=True)
    
    # Verify 81 is open
    orders = load_table_orders()
    assert '81' in orders
    
    # Now UNDO transfer (81 -> 40)
    # The 'cancel_transfer' action relies on 'return_table_id'
    response = client.post('/restaurant/table/81', data={
        'action': 'cancel_transfer',
        'return_table_id': '40'
    }, follow_redirects=True)
    
    # If 'import copy' is missing, this would raise 500 or UnboundLocalError
    assert response.status_code == 200
    assert b'Transfer\xc3\xaancia desfeita' in response.data or b'Transferencia desfeita' in response.data or b'desfeita' in response.data
    
    orders = load_table_orders()
    # 81 should be closed
    assert '81' not in orders
    # 40 should be restored
    assert '40' in orders
    assert len(orders['40']['items']) == 2

def test_transfer_item_to_empty_81(client):
    """Test transferring an item to an empty table 81"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Transfer 1 Coke (index 0) from 40 to 81
    # Route: /restaurant/transfer_item (POST JSON)
    response = client.post('/restaurant/transfer_item', json={
        'source_table_id': '40',
        'target_table_id': '81',
        'item_index': 0,
        'qty': 1
    }, follow_redirects=True)
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    
    orders = load_table_orders()
    
    # 40 should still be open with less items/qty
    assert '40' in orders
    # Coke qty was 2, transferred 1 -> remaining 1
    assert orders['40']['items'][0]['name'] == 'Coke'
    assert orders['40']['items'][0]['qty'] == 1.0
    
    # 81 should be auto-created and have 1 Coke
    assert '81' in orders
    assert len(orders['81']['items']) == 1
    assert orders['81']['items'][0]['name'] == 'Coke'
    assert orders['81']['items'][0]['qty'] == 1.0
