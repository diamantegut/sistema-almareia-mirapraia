
import pytest
import json
import os
import sys
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, normalize_room_simple

class TestRoomReportDebug:
    @pytest.fixture
    def client(self):
        app.config['TESTING'] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = 'test_admin'
                sess['role'] = 'admin'
                sess['permissions'] = ['admin']
            yield client

    @pytest.fixture
    def mock_data_paths(self, tmp_path):
        with patch('app.get_data_path') as mock_path:
            def side_effect(filename):
                return str(tmp_path / filename)
            mock_path.side_effect = side_effect
            
            # Patch constants that are resolved at import time
            # We need to patch them on the module where they are defined/used
            with patch('app.ROOM_CHARGES_FILE', str(tmp_path / 'room_charges.json')), \
                 patch('app.ROOM_OCCUPANCY_FILE', str(tmp_path / 'room_occupancy.json')):
                yield tmp_path

    def setup_method(self, method):
        # Reset any global state if necessary
        pass

    def test_normalize_room_simple(self):
        assert normalize_room_simple("33") == "33"
        assert normalize_room_simple("033") == "33"
        assert normalize_room_simple(" 33 ") == "33"
        assert normalize_room_simple("A33") == "A33"
        assert normalize_room_simple("22") == "22"
        assert normalize_room_simple("022") == "22"

    def test_room_report_items_presence(self, client, mock_data_paths):
        # Setup Room Occupancy
        occupancy = {
            "33": {"guest_name": "Guest 33", "status": "occupied"},
            "022": {"guest_name": "Guest 22", "status": "occupied"}
        }
        with open(mock_data_paths / 'room_occupancy.json', 'w') as f:
            json.dump(occupancy, f)

        # Setup Room Charges
        charges = [
            # Charge 1: Room 33, Restaurant, contains Banoffe
            {
                "id": "c1",
                "room_number": "33",
                "status": "pending",
                "source": "restaurant",
                "items": [
                    {"name": "Banoffe", "qty": 1, "price": 15.0},
                    {"name": "Coca Cola", "qty": 2, "price": 5.0}
                ],
                "total": 25.0,
                "date": "01/01/2026",
                "time": "12:00"
            },
            # Charge 2: Room 022 (stored with leading zero), Restaurant
            {
                "id": "c2",
                "room_number": "022",
                "status": "pending",
                "source": "restaurant",
                "items": [
                    {"name": "Banoffe", "qty": 2, "price": 15.0}
                ],
                "total": 30.0,
                "date": "01/01/2026",
                "time": "12:05"
            },
             # Charge 3: Room 23 (stored as int in JSON - simulating edge case), Restaurant
            {
                "id": "c3",
                "room_number": 23,
                "status": "pending",
                "source": "restaurant",
                "items": [
                    {"name": "Banoffe Special", "qty": 1, "price": 20.0}
                ],
                "total": 20.0,
                "date": "01/01/2026",
                "time": "12:10"
            }
        ]
        
        # Add Room 23 to occupancy for consistency (though report doesn't strictly require it for charges to list, 
        # but it does for guest name lookup)
        occupancy["23"] = {"guest_name": "Guest 23", "status": "occupied"}
        with open(mock_data_paths / 'room_occupancy.json', 'w') as f:
            json.dump(occupancy, f)
            
        with open(mock_data_paths / 'room_charges.json', 'w') as f:
            json.dump(charges, f)

        # Test Room 33
        resp = client.get('/reception/room_consumption_report/33')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "Banoffe" in html
        assert "Coca Cola" in html
        assert "Guest 33" in html

        # Test Room 22 (requesting as "22", stored as "022")
        resp = client.get('/reception/room_consumption_report/22')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "Banoffe" in html
        assert "Guest 22" in html

        # Test Room 23 (requesting as "23", stored as int 23)
        resp = client.get('/reception/room_consumption_report/23')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "Banoffe Special" in html
        assert "Guest 23" in html
        
    def test_malformed_items(self, client, mock_data_paths):
        # Charge with malformed items
        charges = [
            {
                "id": "c_bad",
                "room_number": "33",
                "status": "pending",
                "items": [
                    {"name": "Good Item", "qty": 1, "price": 10},
                    "Bad Item String", # Malformed
                    {"no_name": "Just Price", "price": 5} # Missing name
                ],
                "total": 15.0,
                "date": "01/01/2026"
            }
        ]
        
        with open(mock_data_paths / 'room_occupancy.json', 'w') as f:
            json.dump({"33": {"guest_name": "G", "status": "occupied"}}, f)
            
        with open(mock_data_paths / 'room_charges.json', 'w') as f:
            json.dump(charges, f)
            
        resp = client.get('/reception/room_consumption_report/33')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "Good Item" in html
        assert "Item sem nome" in html # Default name
        # "Bad Item String" should be skipped silently
