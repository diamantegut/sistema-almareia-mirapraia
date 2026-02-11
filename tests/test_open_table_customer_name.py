
import pytest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, load_table_orders, save_table_orders, TABLE_ORDERS_FILE as ORDERS_FILE
import json
import os

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_open_table_with_customer_name(client):
    # Setup: Ensure table 40 is closed
    if os.path.exists(ORDERS_FILE):
        orders = load_table_orders()
        if '40' in orders:
            del orders['40']
            save_table_orders(orders)
    
    # Login as admin
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'
        sess['department'] = 'Principal'

    # Open table with customer name
    response = client.post('/restaurant/table/40', data={
        'action': 'open_table',
        'num_adults': '2',
        'customer_type': 'passante',
        'customer_name': 'Cliente Teste VIP'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Verify order created
    orders = load_table_orders()
    assert '40' in orders
    assert orders['40']['customer_name'] == 'Cliente Teste VIP'
    assert orders['40']['customer_type'] == 'passante'
    
    # Cleanup
    if '40' in orders:
        del orders['40']
        save_table_orders(orders)
