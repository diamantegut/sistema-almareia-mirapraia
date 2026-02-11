
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

def test_single_full_payment(client):
    """Test paying the full amount in one go via close_order"""
    table_id = "101"
    total_base = 100.0
    grand_total = 110.0 # +10%
    
    order_data = create_mock_order(table_id, total_base)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders') as mock_save:
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test_user'
                        sess['role'] = 'admin'
                        
                    payments = [{'amount': 110.0, 'method': 'Dinheiro'}]
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_multiple_partial_payments_closing(client):
    """Test closing a table that was fully paid via partial payments"""
    table_id = "102"
    total_base = 100.0
    grand_total = 110.0
    
    # Already paid 110
    order_data = create_mock_order(table_id, total_base, paid=110.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                        
                    # Send empty payments
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps([]),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_partial_plus_remaining_payment(client):
    """Test paying half via partial, then remaining via close_order"""
    table_id = "103"
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
                        
                    # Pay remaining 60
                    payments = [{'amount': 60.0, 'method': 'Cartão'}]
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data

def test_underpayment_fails(client):
    """Test that paying less than total fails"""
    table_id = "104"
    total_base = 100.0
    grand_total = 110.0
    
    order_data = create_mock_order(table_id, total_base)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
             with client.session_transaction() as sess:
                sess['user'] = 'test'
                
             payments = [{'amount': 109.90, 'method': 'Dinheiro'}] # 10 cents short
             response = client.post(f'/restaurant/table/{table_id}', data={
                'action': 'close_order',
                'payment_data': json.dumps(payments),
                'discount': '0'
             }, follow_redirects=True)
             
             assert b'Valor total pago' in response.data
             assert b'menor que o total' in response.data

def test_precision_tolerance(client):
    """Test that tiny differences (floating point) are handled"""
    table_id = "105"
    # Create a scenario where 10% adds up to a float with many decimals
    # 33.33 * 1.1 = 36.663
    total_base = 33.33
    grand_total = 33.33 * 1.1 # 36.663
    
    # User pays 36.66
    order_data = create_mock_order(table_id, total_base)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                     with client.session_transaction() as sess:
                        sess['user'] = 'test'
                     
                     # If we pay 36.66, remaining is 0.003, which is < 0.01. Should pass.
                     payments = [{'amount': 36.66, 'method': 'Dinheiro'}]
                     response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                     }, follow_redirects=True)
                     
                     assert b'Mesa fechada com sucesso' in response.data

def test_overpayment_success(client):
    """Test that paying more (change) is allowed"""
    table_id = "106"
    total_base = 100.0
    grand_total = 110.0
    
    order_data = create_mock_order(table_id, total_base)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                     with client.session_transaction() as sess:
                        sess['user'] = 'test'
                     
                     payments = [{'amount': 150.0, 'method': 'Dinheiro'}]
                     response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payments),
                        'discount': '0'
                     }, follow_redirects=True)
                     
                     assert b'Mesa fechada com sucesso' in response.data

def test_overpaid_via_partials_closing(client):
    """Test closing a table that was OVERpaid via partial payments"""
    table_id = "107"
    total_base = 100.0
    grand_total = 110.0
    
    # Already paid 120 (Overpaid)
    order_data = create_mock_order(table_id, total_base, paid=120.0)
    
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders'):
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    with client.session_transaction() as sess:
                        sess['user'] = 'test'
                        
                    # Send empty payments
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps([]),
                        'discount': '0'
                    }, follow_redirects=True)
                    
                    assert b'Mesa fechada com sucesso' in response.data
