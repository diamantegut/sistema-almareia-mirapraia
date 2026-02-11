
import pytest
import json
import os
import uuid
from datetime import datetime, timedelta
from app import app, load_payables, save_payables, load_commission_cycles, save_commission_cycles, load_cashier_sessions, save_cashier_sessions, load_room_charges, save_room_charges, load_room_occupancy, save_room_occupancy, normalize_room_simple

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.secret_key = 'test_secret'
    with app.test_client() as client:
        with app.app_context():
            yield client

@pytest.fixture
def mock_data_paths(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Create empty files
    files = {
        "payables.json": [],
        "suppliers.json": ["Fornecedor A", "Fornecedor B"],
        "cashier_sessions.json": [],
        "commission_cycles.json": [],
        "room_charges.json": [],
        "room_occupancy.json": {},
        "users.json": {"admin": {"password": "123", "role": "admin", "full_name": "Admin User"}}
    }
    
    for filename, content in files.items():
        with open(data_dir / filename, "w") as f:
            json.dump(content, f)
            
    def mock_get_data_path(filename):
        return str(data_dir / filename)
        
    monkeypatch.setattr("app.get_data_path", mock_get_data_path)
    
    # Patch module-level file path constants that were initialized at import time
    monkeypatch.setattr("app.PAYABLES_FILE", str(data_dir / "payables.json"))
    monkeypatch.setattr("app.SUPPLIERS_FILE", str(data_dir / "suppliers.json"))
    monkeypatch.setattr("app.CASHIER_SESSIONS_FILE", str(data_dir / "cashier_sessions.json"))
    monkeypatch.setattr("app.ROOM_CHARGES_FILE", str(data_dir / "room_charges.json"))
    monkeypatch.setattr("app.ROOM_OCCUPANCY_FILE", str(data_dir / "room_occupancy.json"))
    monkeypatch.setattr("app.USERS_FILE", str(data_dir / "users.json"))
    
    # Patch commission_service constant
    # Note: commission_service must be imported or available in sys.modules
    import commission_service
    monkeypatch.setattr(commission_service, "COMMISSION_CYCLES_FILE", str(data_dir / "commission_cycles.json"))
    
    # Patch services.cashier_service constant
    import services.cashier_service
    monkeypatch.setattr(services.cashier_service, "CASHIER_SESSIONS_FILE", str(data_dir / "cashier_sessions.json"))
    
    return data_dir

def login(client, username="admin"):
    with client.session_transaction() as sess:
        sess['user'] = username
        sess['role'] = 'admin'
        sess['permissions'] = ['financeiro', 'recepcao']

def test_accounts_payable_payment(client, mock_data_paths):
    login(client)
    
    # 1. Add a payable
    payable_id = str(uuid.uuid4())
    payable = {
        'id': payable_id,
        'type': 'supplier',
        'supplier': 'Fornecedor A',
        'description': 'Compra de Teste',
        'amount': 100.0,
        'due_date': datetime.now().strftime('%Y-%m-%d'),
        'status': 'pending',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open(mock_data_paths / "payables.json", "w") as f:
        json.dump([payable], f)
        
    # 2. Pay it via POST
    response = client.post('/finance/accounts_payable', data={
        'action': 'pay',
        'id': payable_id,
        'payment_date': datetime.now().strftime('%Y-%m-%d')
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Pagamento registrado!' in response.data
    
    # 3. Verify persistence
    with open(mock_data_paths / "payables.json", "r") as f:
        payables = json.load(f)
        assert payables[0]['status'] == 'paid'
        assert payables[0]['paid_by'] == 'admin'

def test_commission_ranking_logic(client, mock_data_paths):
    login(client)
    
    # Setup Cashier Session with Transactions
    # 1. Normal sale with commission
    # 2. Sale with commission removed (10% Off)
    
    session_id = "sess_1"
    now = datetime.now()
    
    tx1 = {
        "id": "tx1",
        "type": "sale",
        "amount": 110.0, # 100 + 10
        "waiter": "Waiter A",
        "timestamp": now.strftime('%d/%m/%Y %H:%M'),
        "waiter_breakdown": {"Waiter A": 110.0},
        "description": "Venda Normal"
    }
    
    tx2 = {
        "id": "tx2",
        "type": "sale",
        "amount": 100.0, # No commission
        "waiter": "Waiter B",
        "timestamp": now.strftime('%d/%m/%Y %H:%M'),
        "waiter_breakdown": {"Waiter B": 100.0},
        "description": "Venda Sem Comissao [10% Off]",
        "service_fee_removed": True
    }
    
    cashier_session = {
        "id": session_id,
        "status": "closed",
        "transactions": [tx1, tx2]
    }
    
    with open(mock_data_paths / "cashier_sessions.json", "w") as f:
        json.dump([cashier_session], f)
        
    # Request Commission Ranking
    response = client.get('/commission_ranking', follow_redirects=True)
    assert response.status_code == 200
    
    # Verify Content
    html = response.data.decode('utf-8')
    assert "Waiter A" in html
    assert "Waiter B" in html
    
    # Removed Commission Report verification
    assert "Comissões Retiradas" in html

def test_room_consumption_report_normalization(client, mock_data_paths):
    login(client)
    
    # Setup Data
    room_num = "33"
    room_num_alt = "033" # Normalization check
    
    # Occupancy
    with open(mock_data_paths / "room_occupancy.json", "w") as f:
        json.dump({
            room_num: {"guest_name": "Guest 33", "status": "occupied"}
        }, f)
        
    # Charges
    charges = [
        {
            "id": "c1",
            "room_number": room_num,
            "status": "pending",
            "items": json.dumps([{"name": "Item A", "price": 10, "qty": 1}]),
            "date": "01/01/2023"
        },
        {
            "id": "c2",
            "room_number": room_num_alt, # Should match "33"
            "status": "pending",
            "items": json.dumps([{"name": "Banoffe", "price": 15, "qty": 1}]),
            "date": "01/01/2023"
        }
    ]
    
    with open(mock_data_paths / "room_charges.json", "w") as f:
        json.dump(charges, f)
        
    # Request Room Consumption Report
    # Note: route is /reception/room_consumption_report/<room_num>
    response = client.get(f'/reception/room_consumption_report/{room_num}', follow_redirects=True)
    assert response.status_code == 200
    
    html = response.data.decode('utf-8')
    
    # Check if both items are present (meaning normalization worked)
    assert "Item A" in html
    assert "Banoffe" in html
    assert "Guest 33" in html

def test_full_commission_flow_table_to_room_to_cashier(client, mock_data_paths):
    login(client)
    
    # 1. Setup Table Order with Waiters
    table_id = "50"
    room_num = "101"
    
    # Occupancy
    with open(mock_data_paths / "room_occupancy.json", "w") as f:
        json.dump({
            room_num: {"guest_name": "Guest Flow", "status": "occupied"}
        }, f)
    
    # Create mock Transfer Service behavior manually since we are testing app integration
    # We simulate that transfer service ALREADY ran and created the charge with waiter_breakdown
    # This validates that IF transfer service works (verified in other test), app.py handles it correctly.
    
    charge = {
        "id": "charge_flow_1",
        "room_number": room_num,
        "status": "pending",
        "items": [
            {"name": "Steak", "price": 100.0, "qty": 1, "waiter": "Waiter A"},
            {"name": "Wine", "price": 50.0, "qty": 1, "waiter": "Waiter B"}
        ],
        "total": 165.0, # 150 + 10%
        "service_fee": 15.0,
        "waiter_breakdown": {
            "Waiter A": 10.0, # 10% of 100
            "Waiter B": 5.0   # 10% of 50
        },
        "source": "restaurant",
        "date": "01/01/2023"
    }
    
    with open(mock_data_paths / "room_charges.json", "w") as f:
        json.dump([charge], f)
        
    # Open Cashier Session for Reception
    session_id = "sess_rec_1"
    cashier_session = {
        "id": session_id,
        "type": "reception", 
        "status": "open",
        "transactions": []
    }
    # Also need guest_consumption type as per new logic?
    # app.py: CashierService.get_active_session('guest_consumption')
    # If not found, it might look for 'reception_room_billing' or 'reception'
    # Let's mock 'guest_consumption' session
    
    cashier_session_gc = {
        "id": "sess_gc_1",
        "type": "guest_consumption",
        "status": "open",
        "transactions": []
    }
    
    with open(mock_data_paths / "cashier_sessions.json", "w") as f:
        json.dump([cashier_session, cashier_session_gc], f)

    # 2. Close Account via Reception Route
    # Route: /reception/close_account/<room_num>
    response = client.post(f'/reception/close_account/{room_num}', json={
        'payment_method': 'Cartão de Crédito',
        'print_receipt': False
    }, follow_redirects=True)
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    
    # 3. Verify Cashier Transaction has waiter breakdown
    with open(mock_data_paths / "cashier_sessions.json", "r") as f:
        sessions = json.load(f)
        
    gc_session = next(s for s in sessions if s['id'] == "sess_gc_1")
    assert len(gc_session['transactions']) == 1
    tx = gc_session['transactions'][0]
    
    assert 'waiter_breakdown' in tx.get('details', {})
    wb = tx['details']['waiter_breakdown']
    
    assert wb['Waiter A'] == 10.0
    assert wb['Waiter B'] == 5.0

