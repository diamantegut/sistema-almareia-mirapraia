
import pytest
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.transfer_service import transfer_table_to_room

# Mock data paths
@pytest.fixture
def mock_data_paths(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    def mock_get_data_path(filename):
        return str(data_dir / filename)
    
    monkeypatch.setattr("app.services.transfer_service.get_data_path", mock_get_data_path)
    return data_dir

def test_commission_persistence_on_transfer(mock_data_paths):
    # Setup initial data
    table_id = "50"
    room_number = "10"
    
    # 1. Create Room Occupancy
    room_occupancy = {
        room_number: {
            "status": "occupied",
            "guest_name": "Test Guest",
            "check_in": "2023-01-01"
        }
    }
    with open(mock_data_paths / "room_occupancy.json", "w") as f:
        json.dump(room_occupancy, f)
        
    # 2. Create Table Order with items from different waiters
    order = {
        "items": [
            {
                "id": "item1",
                "name": "Burger",
                "qty": 1,
                "price": 50.0,
                "waiter": "Waiter A"
            },
            {
                "id": "item2",
                "name": "Coke",
                "qty": 2,
                "price": 10.0,
                "waiter": "Waiter B"
            }
        ],
        "total": 70.0,
        "waiter": "Waiter A", # Main waiter
        "status": "open"
    }
    
    orders = {table_id: order}
    with open(mock_data_paths / "table_orders.json", "w") as f:
        json.dump(orders, f)
        
    # 3. Create empty room charges
    with open(mock_data_paths / "room_charges.json", "w") as f:
        json.dump([], f)
        
    # 4. Create empty transfer lock
    with open(mock_data_paths / "transfer_lock.lock", "w") as f:
        f.write("") # Just create the file
    # Remove it so the lock context manager can create it
    os.remove(mock_data_paths / "transfer_lock.lock")
        
    # Execute Transfer
    success, msg = transfer_table_to_room(table_id, room_number, "Admin")
    
    assert success
    
    # Verify Room Charges
    with open(mock_data_paths / "room_charges.json", "r") as f:
        charges = json.load(f)
        
    assert len(charges) == 1
    charge = charges[0]
    
    # Verify Commission Persistence
    # Total = 70. Service Fee = 7.0. Grand Total = 77.0.
    # Waiter A: 50.0 (Burger)
    # Waiter B: 20.0 (Coke)
    # Total Base: 70.0
    
    # Shares:
    # A: 50/70 = ~0.714
    # B: 20/70 = ~0.286
    
    # Breakdown (Grand Total * Share):
    # A: 77.0 * 0.714 = 55.0
    # B: 77.0 * 0.286 = 22.0
    
    print(f"Charge Data: {json.dumps(charge, indent=2)}")
    
    assert 'waiter_breakdown' in charge
    breakdown = charge['waiter_breakdown']
    
    assert "Waiter A" in breakdown
    assert "Waiter B" in breakdown
    
    # Check values with some tolerance for float math
    assert abs(breakdown["Waiter A"] - 55.0) < 0.1
    assert abs(breakdown["Waiter B"] - 22.0) < 0.1
    
    # Verify main waiter fallback
    assert charge['waiter'] == "Waiter A"

if __name__ == "__main__":
    pytest.main([__file__])
