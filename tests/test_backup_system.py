import unittest
import os
import shutil
import json
import time
from datetime import datetime
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.backup_service import BackupService, BACKUP_CONFIGS, DATA_DIR, BACKUPS_DIR
import services.backup_service

class TestBackupSystem(unittest.TestCase):
    def setUp(self):
        # Setup temporary directories for testing
        self.test_data_dir = os.path.join(os.path.dirname(__file__), 'test_data')
        self.test_backups_dir = os.path.join(os.path.dirname(__file__), 'test_backups')
        
        os.makedirs(self.test_data_dir, exist_ok=True)
        os.makedirs(self.test_backups_dir, exist_ok=True)
        
        # Override global configs for testing
        self.original_data_dir = services.backup_service.DATA_DIR
        self.original_configs = services.backup_service.BACKUP_CONFIGS.copy()
        
        # Patch DATA_DIR
        services.backup_service.DATA_DIR = self.test_data_dir
        
        # Create a test config
        services.backup_service.BACKUP_CONFIGS = {
            'test_type': {
                'source_files': ['test_file.json'],
                'dest_dir': os.path.join(self.test_backups_dir, 'TestType'),
                'interval_seconds': 1,
                'retention_minutes': 1,
                'description': 'Test Backup'
            }
        }
        
        # Ensure dest dir exists
        os.makedirs(services.backup_service.BACKUP_CONFIGS['test_type']['dest_dir'], exist_ok=True)
        
        self.service = BackupService()
        
        # Create dummy source file
        self.source_file = os.path.join(self.test_data_dir, 'test_file.json')
        with open(self.source_file, 'w') as f:
            json.dump({'status': 'original'}, f)

    def tearDown(self):
        # Cleanup
        shutil.rmtree(self.test_data_dir)
        shutil.rmtree(self.test_backups_dir)
        
        # Restore configs
        import services.backup_service
        services.backup_service.DATA_DIR = self.original_data_dir
        services.backup_service.BACKUP_CONFIGS = self.original_configs

    def test_backup_and_restore(self):
        print("\nTesting Backup and Restore...")
        
        # 1. Perform Backup
        config = services.backup_service.BACKUP_CONFIGS['test_type']
        self.service._perform_backup('test_type', config)
        
        # Verify backup created
        backups = os.listdir(config['dest_dir'])
        self.assertTrue(len(backups) > 0, "Backup file should be created")
        backup_filename = backups[0]
        print(f"Backup created: {backup_filename}")
        
        # 2. Modify Source File (Simulate change/corruption)
        with open(self.source_file, 'w') as f:
            json.dump({'status': 'corrupted'}, f)
            
        with open(self.source_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['status'], 'corrupted')
        
        # 3. Restore
        print(f"Restoring from {backup_filename}...")
        success, msg = self.service.restore_backup('test_type', backup_filename)
        self.assertTrue(success, f"Restore failed: {msg}")
        
        # 4. Verify Restoration
        with open(self.source_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['status'], 'original', "File should be restored to original state")
        print("Restore verification successful.")

    def test_retention_policy(self):
        print("\nTesting Retention Policy...")
        config = services.backup_service.BACKUP_CONFIGS['test_type']
        dest_dir = config['dest_dir']
        
        # Create a dummy old backup manually
        old_time = time.time() - 3600 # 1 hour ago (retention is 1 minute)
        old_file = os.path.join(dest_dir, 'test_file_OLD.json')
        with open(old_file, 'w') as f:
            f.write("old")
        
        # Set mtime to past
        os.utime(old_file, (old_time, old_time))
        
        # Run cleanup
        self.service._cleanup_old_backups('test_type', config)
        
        # Verify it's gone
        self.assertFalse(os.path.exists(old_file), "Old backup should be deleted")
        print("Retention policy verification successful.")

    def test_full_system_rotation_overwrites(self):
        print("\nTesting Full System Rotation Overwrite...")

        source_dir = os.path.join(os.path.dirname(__file__), 'test_source_full_system')
        dest_dir = os.path.join(os.path.dirname(__file__), 'test_backups_full_system')
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(dest_dir, exist_ok=True)

        try:
            with open(os.path.join(source_dir, 'dummy.txt'), 'w', encoding='utf-8') as f:
                f.write("dummy")

            slot = int(time.time() // 3600) % 24
            expected_zip = os.path.join(dest_dir, f"Servidor Teste_{slot:02d}.zip")

            config = {
                'source_dir': source_dir,
                'dest_dir': dest_dir,
                'interval_seconds': 3600,
                'rotation_slots': 24,
                'base_name': 'Servidor Teste',
                'description': 'Backup Completo do Sistema (Teste)'
            }

            self.service._perform_backup('full_system', config)
            self.assertTrue(os.path.exists(expected_zip), "Expected rotated zip to be created")
            first_mtime = os.path.getmtime(expected_zip)

            time.sleep(1)
            self.service._perform_backup('full_system', config)
            second_mtime = os.path.getmtime(expected_zip)

            self.assertGreater(second_mtime, first_mtime, "Expected zip to be overwritten")
            self.assertEqual(len([p for p in os.listdir(dest_dir) if p.lower().endswith('.zip')]), 1)
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)
            shutil.rmtree(dest_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main()
