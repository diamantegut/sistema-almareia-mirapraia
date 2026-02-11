
import pytest
from app import create_app
from unittest.mock import patch, MagicMock
import json

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def create_mock_order(table_id, total, paid=0.0):
    return {
        table_id: {
            "id": table_id,
            "status": "open",
            "items": [
                {"name": "Item 1", "price": total, "qty": 1, "total": total}
            ],
            "total": total,
            "total_paid": paid,
            "partial_payments": []
        }
    }

def test_partial_plus_overpayment_change(client):
    """Test paying part first, then overpaying the rest (change scenario)"""
    table_id = "201"
    total_base = 100.0
    grand_total = 110.0
    
    # Already paid 50
    order_data = create_mock_order(table_id, total_base, paid=50.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                    
                    # Remaining is 60. User pays 100.
                    payments = [{'amount': 100.0, 'method': 'Dinheiro'}]
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_huge_overpayment_warning(client):
    """
    Test a huge overpayment. 
    Currently the code allows any overpayment. 
    This test just confirms it passes.
    """
    table_id = "202"
    total_base = 10.0
    grand_total = 11.0
    
    order_data = create_mock_order(table_id, total_base, paid=0.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                    
                    # Bill is 11. User pays 1000.
                    payments = [{'amount': 1000.0, 'method': 'Dinheiro'}]
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_exact_float_match(client):
    """Test with float values that might have representation issues"""
    table_id = "203"
    total_base = 14.32
    grand_total = 14.32 * 1.1 # 15.752
    
    # Let's say we round to 2 decimals for payment: 15.75
    # The code uses strict comparison with 0.01 tolerance.
    # 15.752 - 15.75 = 0.002. Should pass.
    
    order_data = create_mock_order(table_id, total_base, paid=0.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                    
                    payments = [{'amount': 15.75, 'method': 'Dinheiro'}]
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_close_without_payments_if_zero_total(client):
    """Test closing a table with 0 total (e.g. 100% discount or free items)"""
    table_id = "204"
    total_base = 0.0
    grand_total = 0.0
    
    order_data = create_mock_order(table_id, total_base, paid=0.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                    
                    # Empty payments, total is 0. Should pass.
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps([]),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data
