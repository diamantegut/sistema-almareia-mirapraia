
import pytest
import json
import os
import sys
import shutil
import uuid
import time
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cashier_service import CashierService

class TestCashierRecovery:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        # Setup temporary data directory
        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_recovery')
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        self.backup_dir = os.path.join(self.test_dir, 'Backups', 'Caixa')
        os.makedirs(self.backup_dir)
        
        self.sessions_file = os.path.join(self.test_dir, 'cashier_sessions.json')
        
        # Patch Constants in CashierService
        self.patchers = []
        
        p1 = patch('app.services.cashier_service.CASHIER_SESSIONS_FILE', self.sessions_file)
        p1.start()
        self.patchers.append(p1)
        
        p2 = patch('app.services.cashier_service.BACKUP_DIR', self.backup_dir)
        p2.start()
        self.patchers.append(p2)
        
        # Initialize empty sessions file
        with open(self.sessions_file, 'w') as f:
            json.dump([], f)
            
        yield
        
        # Teardown
        for p in self.patchers:
            p.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_backup_creation_on_open(self):
        """Test that a backup is created when a session is opened."""
        CashierService.open_session('restaurant', 'admin', 100.0)
        
        # Check if backup file exists
        backups = os.listdir(self.backup_dir)
        assert len(backups) > 0
        assert backups[0].startswith('backup_cashier_')
        
        # Verify backup content
        with open(os.path.join(self.backup_dir, backups[0]), 'r') as f:
            content = f.read()
            # It should be base64 encoded
            import base64
            decoded = base64.b64decode(content).decode('utf-8')
            data = json.loads(decoded)
            assert len(data['sessions']) == 1
            assert data['sessions'][0]['opening_balance'] == 100.0

    def test_recovery_from_missing_file(self):
        """Test recovery when sessions file is missing."""
        # 1. Create a session (creates backup)
        CashierService.open_session('restaurant', 'admin', 100.0)
        
        # 2. Delete the sessions file
        os.remove(self.sessions_file)
        assert not os.path.exists(self.sessions_file)
        
        # 3. Load sessions - should trigger recovery
        sessions = CashierService._load_sessions()
        
        assert len(sessions) == 1
        assert sessions[0]['opening_balance'] == 100.0
        
        # 4. Verify file was restored
        assert os.path.exists(self.sessions_file)

    def test_recovery_from_empty_file(self):
        """Test recovery when sessions file is empty (0 bytes)."""
        # 1. Create a session (creates backup)
        CashierService.open_session('restaurant', 'admin', 100.0)
        
        # 2. Corrupt the file (make it empty)
        with open(self.sessions_file, 'w') as f:
            pass # Empty
            
        assert os.path.getsize(self.sessions_file) == 0
        
        # 3. Load sessions - should trigger recovery
        sessions = CashierService._load_sessions()
        
        assert len(sessions) == 1
        assert sessions[0]['opening_balance'] == 100.0
        
    def test_recovery_from_invalid_json(self):
        """Test recovery when sessions file has invalid JSON."""
        # 1. Create a session (creates backup)
        CashierService.open_session('restaurant', 'admin', 100.0)
        
        # 2. Corrupt the file (invalid JSON)
        with open(self.sessions_file, 'w') as f:
            f.write("{invalid_json")
            
        # 3. Load sessions - should trigger recovery
        sessions = CashierService._load_sessions()
        
        assert len(sessions) == 1
        assert sessions[0]['opening_balance'] == 100.0

    def test_manual_restore(self):
        """Test manual restore function."""
        # 1. Create a session (creates backup)
        CashierService.open_session('restaurant', 'admin', 100.0)
        
        # 2. Modify current session (simulate unwanted change)
        sessions = CashierService._load_sessions()
        sessions[0]['opening_balance'] = 0.0
        CashierService._save_sessions(sessions)
        
        # 3. Trigger manual restore
        result = CashierService.restore_latest_backup()
        assert result is True
        
        # 4. Verify original value restored
        sessions = CashierService._load_sessions()
        assert sessions[0]['opening_balance'] == 100.0

    def test_transfer_funds_locking(self):
        """Test transfer funds updates both sessions."""
        # Open source and target
        CashierService.open_session('restaurant', 'admin', 1000.0)
        CashierService.open_session('reception', 'admin', 500.0)
        
        # Transfer
        CashierService.transfer_funds('restaurant', 'reception', 200.0, 'Test Transfer', 'admin')
        
        sessions = CashierService._load_sessions()
        
        restaurant = next(s for s in sessions if s['type'] == 'restaurant')
        reception = next(s for s in sessions if s['type'] == 'reception')
        
        # Check transactions
        assert len(restaurant['transactions']) == 1
        assert restaurant['transactions'][0]['type'] == 'out'
        assert restaurant['transactions'][0]['amount'] == 200.0
        
        assert len(reception['transactions']) == 1
        assert reception['transactions'][0]['type'] == 'in'
        assert reception['transactions'][0]['amount'] == 200.0
