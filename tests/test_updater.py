import pytest
import os
import shutil
import json
from scripts import automated_updater

@pytest.fixture
def setup_environment(tmp_path):
    # Setup mock project structure
    project_root = tmp_path / "project"
    project_root.mkdir()
    
    # Mock data dir
    data_dir = project_root / "data"
    data_dir.mkdir()
    (data_dir / "valid.json").write_text('{"key": "value"}', encoding='utf-8')
    
    # Mock version
    (project_root / "version.txt").write_text("1.0.0")
    
    # Mock app.py
    (project_root / "app.py").write_text("# App code")
    
    # Mock update source
    update_source = project_root / "update_source"
    update_source.mkdir()
    (update_source / "version.txt").write_text("1.0.1")
    (update_source / "new_file.txt").write_text("New content")
    
    # Mock backups
    backups_dir = project_root / "backups"
    backups_dir.mkdir()
    
    # Patch paths in automated_updater
    original_root = automated_updater.PROJECT_ROOT
    original_update_source = automated_updater.UPDATE_SOURCE_DIR
    original_backup_base = automated_updater.BACKUP_BASE_DIR
    original_version_file = automated_updater.VERSION_FILE
    
    automated_updater.PROJECT_ROOT = str(project_root)
    automated_updater.UPDATE_SOURCE_DIR = str(update_source)
    automated_updater.BACKUP_BASE_DIR = str(backups_dir)
    automated_updater.VERSION_FILE = str(project_root / "version.txt")
    
    yield project_root
    
    # Restore paths
    automated_updater.PROJECT_ROOT = original_root
    automated_updater.UPDATE_SOURCE_DIR = original_update_source
    automated_updater.BACKUP_BASE_DIR = original_backup_base
    automated_updater.VERSION_FILE = original_version_file

def test_check_new_version(setup_environment):
    new_ver = automated_updater.check_new_version()
    assert new_ver == "1.0.1"

def test_backup_creation(setup_environment):
    backup_path = automated_updater.create_timestamped_backup()
    assert os.path.exists(backup_path)
    assert os.path.exists(os.path.join(backup_path, "version.txt"))

def test_apply_updates(setup_environment):
    automated_updater.apply_updates()
    assert os.path.exists(os.path.join(automated_updater.PROJECT_ROOT, "new_file.txt"))

def test_json_integrity_success(setup_environment):
    assert automated_updater.validate_json_integrity() is True

def test_json_integrity_failure(setup_environment):
    # Create invalid json
    data_dir = os.path.join(automated_updater.PROJECT_ROOT, "data")
    with open(os.path.join(data_dir, "invalid.json"), "w") as f:
        f.write("{invalid_json")
        
    assert automated_updater.validate_json_integrity() is False

def test_rollback(setup_environment):
    # 1. Create initial state
    test_file = os.path.join(automated_updater.PROJECT_ROOT, "app.py")
    with open(test_file, "w") as f:
        f.write("Original App Code")
        
    # 2. Backup
    backup_path = automated_updater.create_timestamped_backup()
    
    # 3. Modify file (Simulate update)
    with open(test_file, "w") as f:
        f.write("Modified App Code")
        
    # 4. Rollback
    automated_updater.rollback(backup_path)
    
    # 5. Verify
    with open(test_file, "r") as f:
        content = f.read()
    assert content == "Original App Code"
