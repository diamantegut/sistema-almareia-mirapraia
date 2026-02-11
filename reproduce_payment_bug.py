
import pytest
from app import create_app
from app.services.data_service import save_table_orders, load_table_orders
from unittest.mock import patch, MagicMock
import json

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_full_payment_bug_reproduction(client):
    """
    Simulates the scenario where a table is fully paid but the system might treat it as partial
    or fail to close due to precision issues.
    """
    # 1. Setup a table with an order
    table_id = "999"
    order_data = {
        table_id: {
            "id": table_id,
            "status": "open",
            "items": [
                {"name": "Item 1", "price": 100.0, "qty": 1, "total": 100.0}
            ],
            "total": 100.0,
            "total_paid": 0.0,
            "partial_payments": []
        }
    }
    
    # Save initial state
    with patch('app.blueprints.restaurant.routes.load_table_orders', return_value=order_data):
        with patch('app.blueprints.restaurant.routes.save_table_orders') as mock_save:
            with patch('app.blueprints.restaurant.routes.get_current_cashier', return_value={'id': 'test_session'}):
                with patch('app.services.cashier_service.CashierService.add_transaction'):
                    
                    # Login
                    with client.session_transaction() as sess:
                        sess['user'] = 'test_user'
                        sess['role'] = 'admin'
                    
                    # 2. Simulate "Add Partial Payment" covering the full amount (100 + 10% = 110)
                    # Case A: User adds a partial payment of 110.00
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'add_partial_payment',
                        'amount': '110.00',
                        'payment_method': 'Dinheiro'
                    }, follow_redirects=True)
                    
                    assert response.status_code == 200
                    assert b'Pagamento parcial registrado' in response.data
                    
                    # Verify state update in mock
                    # In a real integration test, we'd check the file/db. Here we simulate the update manually if needed,
                    # or rely on the mock side effect if we implemented one.
                    # Since we mocked load_table_orders to return fixed data, subsequent calls won't see the update
                    # unless we update the dict inplace. load_table_orders usually returns a dict reference.
                    
                    order_data[table_id]['total_paid'] = 110.00
                    order_data[table_id]['partial_payments'].append({
                        'amount': 110.00,
                        'method': 'Dinheiro'
                    })
                    
                    # 3. Try to "Close Order" with 0 remaining
                    # The UI sends 'payment_data' as JSON. If fully paid via partials, 
                    # the user might just click "Confirmar Pagamento" with 0 amount or empty list?
                    # Or maybe they send the remaining amount?
                    # If it's already fully paid, the UI typically disables the input or shows 0.
                    # Let's assume the user sends an empty payment list because it's already paid?
                    # OR they send the partial payments again?
                    # Looking at the code: "Account for partial payments... already_paid = order.get('total_paid', 0)"
                    # "Sum of NEW payments submitted now... new_payments_total"
                    # If I already paid 110, I send empty new payments.
                    
                    payment_payload = [] 
                    
                    response = client.post(f'/restaurant/table/{table_id}', data={
                        'action': 'close_order',
                        'payment_data': json.dumps(payment_payload),
                        'discount': '0',
                        # 'remove_service_fee': ... default is off (10% applied)
                    }, follow_redirects=True)
                    
                    # Check for success
                    if b'Mesa fechada com sucesso' in response.data:
                        print("SUCCESS: Table closed successfully with full partial payment.")
                    else:
                        print("FAILURE: Could not close table.")
                        if b'Erro: Valor total pago' in response.data:
                            print("Reason: Total paid mismatch error.")
                            print(response.data.decode('utf-8')) # Print part of response to debug
                        elif b'Nenhum pagamento informado' in response.data:
                             print("Reason: No payment provided (blocked empty list even if fully paid).")
                        else:
                             print("Reason: Unknown.")
                             
    # 4. Case B: Floating point precision issue
    # 3 items of 33.33 = 99.99. + 10% = 109.989.
    # If user pays 109.99?
