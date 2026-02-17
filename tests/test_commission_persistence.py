
import pytest
import os
import json
import shutil
from unittest.mock import patch, MagicMock
from app import app
from app.services.transfer_service import transfer_table_to_room, TransferError

# Setup paths for test
TEST_DIR = 'tests/temp_data'
ORDERS_FILE = os.path.join(TEST_DIR, 'table_orders.json')
OCCUPANCY_FILE = os.path.join(TEST_DIR, 'room_occupancy.json')
CHARGES_FILE = os.path.join(TEST_DIR, 'room_charges.json')
LOCK_FILE = os.path.join(TEST_DIR, 'transfer_lock')

@pytest.fixture
def setup_data():
    if not os.path.exists(TEST_DIR):
        os.makedirs(TEST_DIR)
    
    # Create dummy data
    orders = {
        "40": {
            "items": [
                {"name": "Item 1", "price": 100.0, "qty": 1, "waiter": "Waiter1"}
            ],
            "total": 100.0,
            "waiter": "Waiter1",
            "service_fee_removed": True,
            "customer_type": "hospede",
            "room_number": "01"
        },
        "41": {
            "items": [
                {"name": "Item 2", "price": 100.0, "qty": 1, "waiter": "Waiter1"}
            ],
            "total": 110.0,
            "waiter": "Waiter1",
            "service_fee_removed": False, # Default
            "customer_type": "hospede",
            "room_number": "01"
        }
    }
    
    occupancy = {
        "01": {"guest_name": "Guest Test", "status": "occupied"}
    }
    
    charges = []
    
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f)
    with open(OCCUPANCY_FILE, 'w', encoding='utf-8') as f:
        json.dump(occupancy, f)
    with open(CHARGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(charges, f)
        
    yield
    
    # Cleanup
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)

@patch('app.services.transfer_service.get_data_path')
def test_transfer_persistence_service_fee_removed(mock_get_data_path, setup_data):
    # Mock get_data_path to return our test files
    def side_effect(filename):
        if filename == 'table_orders.json': return ORDERS_FILE
        if filename == 'room_occupancy.json': return OCCUPANCY_FILE
        if filename == 'room_charges.json': return CHARGES_FILE
        if filename == 'transfer_lock': return LOCK_FILE
        return os.path.join(TEST_DIR, filename)
    
    mock_get_data_path.side_effect = side_effect
    
    # Test 1: Transfer with service_fee_removed = True
    transfer_table_to_room("40", "01", "Admin")
    
    with open(CHARGES_FILE, 'r', encoding='utf-8') as f:
        charges = json.load(f)
    
    assert len(charges) == 1
    charge = charges[0]
    assert charge['service_fee_removed'] is True
    assert charge['service_fee'] == 0
    assert charge['total'] == 100.0 # No service fee
    
    # Verify flags
    assert any(f['type'] == 'service_removed' for f in charge.get('flags', []))

@patch('app.services.transfer_service.get_data_path')
def test_transfer_persistence_service_fee_included(mock_get_data_path, setup_data):
    # Mock get_data_path
    def side_effect(filename):
        if filename == 'table_orders.json': return ORDERS_FILE
        if filename == 'room_occupancy.json': return OCCUPANCY_FILE
        if filename == 'room_charges.json': return CHARGES_FILE
        if filename == 'transfer_lock': return LOCK_FILE
        return os.path.join(TEST_DIR, filename)
    
    mock_get_data_path.side_effect = side_effect
    
    # Test 2: Transfer with service_fee_removed = False (Table 41)
    transfer_table_to_room("41", "01", "Admin")
    
    with open(CHARGES_FILE, 'r', encoding='utf-8') as f:
        charges = json.load(f)
    
    # Should be 1 charge (since we start fresh in setup_data or if run sequentially, might be 2 but we check the latest)
    # Actually setup_data runs per test function so it's fresh.
    
    assert len(charges) == 1
    charge = charges[0]
    assert charge.get('service_fee_removed', False) is False
    assert charge['service_fee'] == 10.0 # 10% of 100
    assert charge['total'] == 110.0
