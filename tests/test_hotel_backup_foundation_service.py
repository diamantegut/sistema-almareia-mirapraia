import json
import os
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime, timedelta

from app.services.hotel_backup_foundation_service import HotelBackupFoundationService
import app.services.hotel_backup_foundation_service as foundation_module


def test_ensure_backup_structure_idempotent(tmp_path):
    root = tmp_path / "HotelBackups"
    first = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    second = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    assert first["full"] == second["full"]
    assert (root / "dev" / "full").exists()
    assert (root / "dev" / "operational").exists()
    assert (root / "dev" / "manifests").exists()
    assert (root / "dev" / "health").exists()


def test_create_consistent_full_backup_with_manifest_and_scheduler_pause(monkeypatch, tmp_path):
    project = tmp_path / "project"
    data_dir = project / "data"
    logs_dir = project / "logs"
    uploads_dir = project / "uploads"
    fiscal_dir = project / "fiscal_documents"
    config_dir = project / "config"
    permissions_dir = project / "permissions"
    for path in [data_dir, logs_dir, uploads_dir, fiscal_dir, config_dir, permissions_dir]:
        path.mkdir(parents=True, exist_ok=True)

    (data_dir / "users.json").write_text('[{"id":"1"}]', encoding="utf-8")
    (data_dir / "department_permissions.json").write_text("{}", encoding="utf-8")
    (logs_dir / "app.log").write_text("ok", encoding="utf-8")
    (uploads_dir / "file.txt").write_text("upload", encoding="utf-8")
    (fiscal_dir / "nf.txt").write_text("fiscal", encoding="utf-8")
    (config_dir / "runtime.json").write_text('{"mode":"test"}', encoding="utf-8")
    (permissions_dir / "roles.json").write_text("{}", encoding="utf-8")
    (project / "system_config.json").write_text('{"backups_dir":"x"}', encoding="utf-8")

    monkeypatch.setattr(foundation_module, "BASE_DIR", str(project))
    monkeypatch.setattr(foundation_module, "CONFIG_FILE", str(project / "system_config.json"))
    monkeypatch.setattr(foundation_module, "USERS_FILE", str(data_dir / "users.json"))
    monkeypatch.setattr(foundation_module, "DEPARTMENT_PERMISSIONS_FILE", str(data_dir / "department_permissions.json"))
    monkeypatch.setattr(foundation_module, "get_data_path", lambda sub="": str(data_dir / sub))
    monkeypatch.setattr(foundation_module, "get_log_path", lambda sub="": str(logs_dir / sub))
    monkeypatch.setattr(foundation_module, "get_fiscal_path", lambda sub="": str(fiscal_dir / sub))
    monkeypatch.setattr(foundation_module, "load_system_config", lambda: {"uploads_dir": str(uploads_dir)})

    calls = {"pause": 0, "resume": 0}
    monkeypatch.setattr(
        foundation_module.HotelBackupFoundationService,
        "_call_scheduler_control",
        classmethod(
            lambda cls, action: calls.__setitem__(
                "pause" if action == "pause_scheduler" else "resume",
                calls["pause" if action == "pause_scheduler" else "resume"] + 1,
            )
            or True
        ),
    )

    result = HotelBackupFoundationService.create_consistent_full_backup(
        environment="dev",
        root_path=str(tmp_path / "HotelBackups"),
        consistency_mode="write_lock",
        pause_scheduler_during_backup=True,
    )

    backup_file = Path(result["backup_file"])
    manifest_file = Path(result["manifest_file"])
    assert backup_file.exists()
    assert manifest_file.exists()
    assert backup_file.name.startswith("full_dev_")
    assert backup_file.suffix == ".zip"
    assert calls["pause"] == 1
    assert calls["resume"] == 1

    with ZipFile(backup_file) as archive:
        names = set(archive.namelist())
        assert "data/users.json" in names
        assert "logs/app.log" in names
        assert "uploads/file.txt" in names
        assert "fiscal_documents/nf.txt" in names
        assert "system_config.json" in names
        assert "permissions/roles.json" in names

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["environment"] == "dev"
    assert manifest["backup_type"] == "full"
    assert manifest["archived_count"] >= 6
    assert manifest["sha256"] == result["sha256"]


def test_full_backup_requires_explicit_app_stop_confirmation(tmp_path):
    try:
        HotelBackupFoundationService.create_consistent_full_backup(
            environment="dev",
            root_path=str(tmp_path / "HotelBackups"),
            consistency_mode="app_stopped",
            app_confirmed_stopped=False,
            pause_scheduler_during_backup=False,
        )
        assert False, "Expected ValueError for app_stopped without confirmation"
    except ValueError:
        assert True


def test_health_is_ok_after_valid_full(monkeypatch, tmp_path):
    project = tmp_path / "project"
    data_dir = project / "data"
    logs_dir = project / "logs"
    uploads_dir = project / "uploads"
    fiscal_dir = project / "fiscal_documents"
    for path in [data_dir, logs_dir, uploads_dir, fiscal_dir]:
        path.mkdir(parents=True, exist_ok=True)

    (data_dir / "users.json").write_text("[]", encoding="utf-8")
    (data_dir / "department_permissions.json").write_text("{}", encoding="utf-8")
    (logs_dir / "app.log").write_text("ok", encoding="utf-8")
    (uploads_dir / "f.txt").write_text("u", encoding="utf-8")
    (fiscal_dir / "n.txt").write_text("f", encoding="utf-8")
    (project / "system_config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(foundation_module, "BASE_DIR", str(project))
    monkeypatch.setattr(foundation_module, "CONFIG_FILE", str(project / "system_config.json"))
    monkeypatch.setattr(foundation_module, "USERS_FILE", str(data_dir / "users.json"))
    monkeypatch.setattr(foundation_module, "DEPARTMENT_PERMISSIONS_FILE", str(data_dir / "department_permissions.json"))
    monkeypatch.setattr(foundation_module, "get_data_path", lambda sub="": str(data_dir / sub))
    monkeypatch.setattr(foundation_module, "get_log_path", lambda sub="": str(logs_dir / sub))
    monkeypatch.setattr(foundation_module, "get_fiscal_path", lambda sub="": str(fiscal_dir / sub))
    monkeypatch.setattr(foundation_module, "load_system_config", lambda: {"uploads_dir": str(uploads_dir)})
    monkeypatch.setattr(
        foundation_module.HotelBackupFoundationService,
        "_call_scheduler_control",
        classmethod(lambda cls, action: True),
    )

    root = tmp_path / "HotelBackups"
    result = HotelBackupFoundationService.create_consistent_full_backup(
        environment="dev",
        root_path=str(root),
        consistency_mode="write_lock",
        pause_scheduler_during_backup=True,
    )
    assert result["health_status"] == "OK"
    latest_health = root / "dev" / "health" / "health_full_dev_latest.json"
    payload = json.loads(latest_health.read_text(encoding="utf-8"))
    assert payload["status"] == "OK"
    assert payload["manifest_present"] is True
    assert payload["hash_present"] is True
    assert payload["hash_valid"] is True


def test_health_is_critical_without_manifest(tmp_path):
    root = tmp_path / "HotelBackups"
    structure = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    full_dir = Path(structure["full"])
    backup = full_dir / f"full_dev_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with ZipFile(backup, "w") as archive:
        temp_file = tmp_path / "x.txt"
        temp_file.write_text("x", encoding="utf-8")
        archive.write(temp_file, arcname="x.txt")

    health = HotelBackupFoundationService.evaluate_full_backup_health(environment="dev", root_path=str(root))
    assert health["status"] == "CRÍTICO"
    assert health["manifest_present"] is False


def test_health_is_alert_for_old_full_with_valid_manifest(tmp_path):
    root = tmp_path / "HotelBackups"
    structure = HotelBackupFoundationService.ensure_backup_structure(environment="production", root_path=str(root))
    full_dir = Path(structure["full"])
    manifests_dir = Path(structure["manifests"])
    old_stamp = (datetime.now() - timedelta(hours=30)).strftime("%Y%m%d_%H%M%S")
    backup = full_dir / f"full_production_{old_stamp}.zip"
    source = tmp_path / "payload.txt"
    source.write_text("payload", encoding="utf-8")
    with ZipFile(backup, "w") as archive:
        archive.write(source, arcname="payload.txt")
    sha = HotelBackupFoundationService._sha256_file(backup)
    manifest = {
        "environment": "production",
        "backup_type": "full",
        "timestamp": old_stamp,
        "file_name": backup.name,
        "file_path": str(backup),
        "size_bytes": backup.stat().st_size,
        "sha256": sha,
        "archived_files": [],
    }
    manifest_path = manifests_dir / f"manifest_full_production_{old_stamp}.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    health = HotelBackupFoundationService.evaluate_full_backup_health(environment="production", root_path=str(root))
    assert health["status"] == "ALERTA"
    assert health["manifest_present"] is True
    assert health["hash_valid"] is True


def test_read_latest_health_from_latest_pointer(tmp_path):
    root = tmp_path / "HotelBackups"
    structure = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    health_dir = Path(structure["health"])
    payload = {
        "timestamp": datetime.now().isoformat(),
        "environment": "dev",
        "backup_file": "x.zip",
        "manifest_file": "m.json",
        "status": "OK",
    }
    latest_file = health_dir / "health_full_dev_latest.json"
    latest_file.write_text(json.dumps(payload), encoding="utf-8")

    result = HotelBackupFoundationService.get_latest_health(environment="dev", root_path=str(root))
    assert result["found"] is True
    assert result["latest"]["status"] == "OK"
    assert result["latest"]["manifest_file"] == "m.json"


def test_read_health_history_ordering_and_limit(tmp_path):
    root = tmp_path / "HotelBackups"
    structure = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    health_dir = Path(structure["health"])
    stamps = ["20260101_000001", "20260101_000002", "20260101_000003"]
    payload_timestamps = [
        "2026-01-01T00:00:03",
        "2026-01-01T00:00:01",
        "2026-01-01T00:00:02",
    ]
    for i, stamp in enumerate(stamps, start=1):
        payload = {
            "timestamp": payload_timestamps[i - 1],
            "environment": "dev",
            "backup_file": f"f{i}.zip",
            "manifest_file": f"m{i}.json",
            "status": "OK",
        }
        file_path = health_dir / f"health_full_dev_{stamp}.json"
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        dt = datetime(2026, 1, 1, 0, 0, 10 - i).timestamp()
        os.utime(file_path, (dt, dt))

    history = HotelBackupFoundationService.list_health_history(environment="dev", root_path=str(root), limit=2)
    assert history["count"] == 2
    assert history["items"][0]["backup_file"] == "f1.zip"
    assert history["items"][1]["backup_file"] == "f3.zip"


def test_read_health_without_files_returns_empty_and_critical(tmp_path):
    root = tmp_path / "HotelBackups"
    result_latest = HotelBackupFoundationService.get_latest_health(environment="dev", root_path=str(root))
    result_history = HotelBackupFoundationService.list_health_history(environment="dev", root_path=str(root), limit=5)
    read_model = HotelBackupFoundationService.get_health_read_model(environment="dev", root_path=str(root), history_limit=5)
    assert result_latest["found"] is False
    assert result_history["count"] == 0
    assert read_model["consolidated_status"] == "CRÍTICO"
    assert read_model["latest_health"] is None


def test_health_read_model_payload_consistency(tmp_path):
    root = tmp_path / "HotelBackups"
    structure = HotelBackupFoundationService.ensure_backup_structure(environment="dev", root_path=str(root))
    health_dir = Path(structure["health"])

    payload = {
        "timestamp": datetime.now().isoformat(),
        "environment": "dev",
        "last_full_backup": datetime.now().isoformat(),
        "backup_file": "full_dev_20260101_010101.zip",
        "manifest_file": "manifest_full_dev_20260101_010101.json",
        "status": "ALERTA",
    }
    (health_dir / "health_full_dev_20260101_010101.json").write_text(json.dumps(payload), encoding="utf-8")
    (health_dir / "health_full_dev_latest.json").write_text(json.dumps(payload), encoding="utf-8")

    model = HotelBackupFoundationService.get_health_read_model(environment="dev", root_path=str(root), history_limit=10)
    assert model["environment"] == "dev"
    assert model["consolidated_status"] == "ALERTA"
    assert model["backup_file"] == payload["backup_file"]
    assert model["manifest_file"] == payload["manifest_file"]
    assert model["history_count"] >= 1


def _prepare_full_backup_fixture(monkeypatch, tmp_path):
    project = tmp_path / "project_restore"
    data_dir = project / "data"
    logs_dir = project / "logs"
    uploads_dir = project / "uploads"
    fiscal_dir = project / "fiscal_documents"
    permissions_dir = project / "permissions"
    for path in [data_dir, logs_dir, uploads_dir, fiscal_dir, permissions_dir]:
        path.mkdir(parents=True, exist_ok=True)

    (data_dir / "users.json").write_text("[]", encoding="utf-8")
    (data_dir / "department_permissions.json").write_text("{}", encoding="utf-8")
    (logs_dir / "app.log").write_text("ok", encoding="utf-8")
    (uploads_dir / "f.txt").write_text("u", encoding="utf-8")
    (fiscal_dir / "n.txt").write_text("f", encoding="utf-8")
    (permissions_dir / "roles.json").write_text("{}", encoding="utf-8")
    (project / "system_config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(foundation_module, "BASE_DIR", str(project))
    monkeypatch.setattr(foundation_module, "CONFIG_FILE", str(project / "system_config.json"))
    monkeypatch.setattr(foundation_module, "USERS_FILE", str(data_dir / "users.json"))
    monkeypatch.setattr(foundation_module, "DEPARTMENT_PERMISSIONS_FILE", str(data_dir / "department_permissions.json"))
    monkeypatch.setattr(foundation_module, "get_data_path", lambda sub="": str(data_dir / sub))
    monkeypatch.setattr(foundation_module, "get_log_path", lambda sub="": str(logs_dir / sub))
    monkeypatch.setattr(foundation_module, "get_fiscal_path", lambda sub="": str(fiscal_dir / sub))
    monkeypatch.setattr(foundation_module, "load_system_config", lambda: {"uploads_dir": str(uploads_dir)})
    monkeypatch.setattr(
        foundation_module.HotelBackupFoundationService,
        "_call_scheduler_control",
        classmethod(lambda cls, action: True),
    )

    root = tmp_path / "HotelBackups"
    created = HotelBackupFoundationService.create_consistent_full_backup(
        environment="dev",
        root_path=str(root),
        consistency_mode="write_lock",
        pause_scheduler_during_backup=True,
    )
    return root, Path(created["backup_file"]), Path(created["manifest_file"])


def test_restore_full_backup_dev_valid(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="restore_case_ok",
        overwrite_confirmed=False,
    )
    assert result["success"] is True
    assert result["status"] == "OK"
    restored = Path(result["restore_target_dir"])
    assert (restored / "data").exists()
    assert (restored / "system_config.json").exists()


def test_restore_full_backup_dev_fails_when_backup_missing(tmp_path):
    root = tmp_path / "HotelBackups"
    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference="full_dev_20990101_000000.zip",
        root_path=str(root),
        restore_target_dir="missing_case",
    )
    assert result["success"] is False
    assert result["status"] == "CRÍTICO"


def test_restore_full_backup_dev_fails_when_manifest_missing(monkeypatch, tmp_path):
    root, backup_path, manifest_path = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    manifest_path.unlink()
    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="manifest_missing_case",
        overwrite_confirmed=True,
        require_manifest=True,
    )
    assert result["success"] is False
    assert result["manifest_present"] is False


def test_restore_full_backup_dev_fails_when_manifest_invalid(monkeypatch, tmp_path):
    root, backup_path, manifest_path = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    manifest_path.write_text("{invalid json", encoding="utf-8")
    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="manifest_invalid_case",
        overwrite_confirmed=True,
        require_manifest=True,
    )
    assert result["success"] is False
    assert result["status"] == "CRÍTICO"


def test_restore_full_backup_dev_requires_controlled_directory(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    outside = tmp_path / "outside_restore_target"
    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir=str(outside),
        overwrite_confirmed=True,
    )
    assert result["success"] is False
    assert result["status"] == "CRÍTICO"


def test_restore_full_backup_dev_safe_failure_without_overwrite_confirmation(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    target_name = "restore_non_empty_case"
    controlled_target = root / "dev" / "restore_tests" / target_name
    controlled_target.mkdir(parents=True, exist_ok=True)
    marker = controlled_target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    result = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir=target_name,
        overwrite_confirmed=False,
    )
    assert result["success"] is False
    assert marker.exists()


def test_smoke_validation_dev_success(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    restore = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="smoke_ok_case",
        overwrite_confirmed=True,
        run_smoke_validation=False,
    )
    smoke = HotelBackupFoundationService.run_restore_smoke_validation_dev(
        restore_target_dir=restore["restore_target_dir"],
        smoke_port=5601,
        enforce_app_boot=False,
    )
    assert smoke["success"] is True
    assert smoke["status"] == "OK"
    assert smoke["checks"]["system_config_readable"] is True
    assert smoke["checks"]["login_validation_ok"] is True
    assert smoke["checks"]["main_data_readable"] is True


def test_smoke_validation_dev_fails_when_essential_missing(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    restore = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="smoke_missing_case",
        overwrite_confirmed=True,
        run_smoke_validation=False,
    )
    users_file = Path(restore["restore_target_dir"]) / "data" / "users.json"
    users_file.unlink()
    smoke = HotelBackupFoundationService.run_restore_smoke_validation_dev(
        restore_target_dir=restore["restore_target_dir"],
        smoke_port=5602,
    )
    assert smoke["success"] is False
    assert smoke["status"] == "CRÍTICO"


def test_smoke_validation_dev_fails_when_config_invalid(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    restore = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="smoke_invalid_config_case",
        overwrite_confirmed=True,
        run_smoke_validation=False,
    )
    config_file = Path(restore["restore_target_dir"]) / "system_config.json"
    config_file.write_text("{invalid", encoding="utf-8")
    smoke = HotelBackupFoundationService.run_restore_smoke_validation_dev(
        restore_target_dir=restore["restore_target_dir"],
        smoke_port=5603,
    )
    assert smoke["success"] is False
    assert smoke["status"] == "CRÍTICO"


def test_smoke_validation_dev_returns_structured_error_on_boot_failure(monkeypatch, tmp_path):
    root, backup_path, _ = _prepare_full_backup_fixture(monkeypatch, tmp_path)
    restore = HotelBackupFoundationService.restore_full_backup_dev(
        backup_reference=backup_path.name,
        root_path=str(root),
        restore_target_dir="smoke_boot_fail_case",
        overwrite_confirmed=True,
        run_smoke_validation=False,
    )
    monkeypatch.setattr(
        foundation_module.HotelBackupFoundationService,
        "_run_app_boot_probe",
        classmethod(lambda cls, restore_target, smoke_port: (False, "boot failed")),
    )
    smoke = HotelBackupFoundationService.run_restore_smoke_validation_dev(
        restore_target_dir=restore["restore_target_dir"],
        smoke_port=5604,
        enforce_app_boot=True,
    )
    assert smoke["success"] is False
    assert smoke["status"] == "CRÍTICO"
    assert "details" in smoke
    assert "checks" in smoke
