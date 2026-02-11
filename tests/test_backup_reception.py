import json
import os
import shutil
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.backup_service import BackupService
import services.backup_service


class TestReceptionBackup(unittest.TestCase):
    def setUp(self):
        self.test_data_dir = os.path.join(os.path.dirname(__file__), 'test_data_reception')
        self.test_backups_dir = os.path.join(os.path.dirname(__file__), 'test_backups_reception')

        os.makedirs(self.test_data_dir, exist_ok=True)
        os.makedirs(self.test_backups_dir, exist_ok=True)

        self.original_data_dir = services.backup_service.DATA_DIR
        self.original_configs = services.backup_service.BACKUP_CONFIGS.copy()

        services.backup_service.DATA_DIR = self.test_data_dir
        services.backup_service.BACKUP_CONFIGS = {
            'reception': {
                'source_files': [
                    'room_occupancy.json',
                    'room_charges.json',
                    'cleaning_status.json',
                    'guest_notifications.json'
                ],
                'dest_dir': os.path.join(self.test_backups_dir, 'Recepcao'),
                'interval_seconds': 1,
                'retention_hours': 1,
                'description': 'Backup da Recepção e Hóspedes (Teste)'
            }
        }

        os.makedirs(services.backup_service.BACKUP_CONFIGS['reception']['dest_dir'], exist_ok=True)
        self.service = BackupService()

        for fname in services.backup_service.BACKUP_CONFIGS['reception']['source_files']:
            with open(os.path.join(self.test_data_dir, fname), 'w', encoding='utf-8') as f:
                json.dump({'file': fname}, f, ensure_ascii=False)

    def tearDown(self):
        shutil.rmtree(self.test_data_dir)
        shutil.rmtree(self.test_backups_dir)

        services.backup_service.DATA_DIR = self.original_data_dir
        services.backup_service.BACKUP_CONFIGS = self.original_configs

    def test_reception_backup_creates_files(self):
        config = services.backup_service.BACKUP_CONFIGS['reception']
        self.service._perform_backup('reception', config)

        backups = os.listdir(config['dest_dir'])
        self.assertGreater(len(backups), 0, "Expected at least one backup file")


if __name__ == '__main__':
    unittest.main()
