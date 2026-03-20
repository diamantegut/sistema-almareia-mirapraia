from pathlib import Path

from app.services.path_resolver import PathResolver, get_audit_events, reset_audit_events
from app.services import system_config_manager


def test_path_resolver_legacy_foundation_and_audit(tmp_path):
    resolver = PathResolver(
        base_dir=str(tmp_path),
        config_loader=lambda: {
            "data_dir": "data",
            "logs_dir": "logs",
            "backups_dir": "backups",
            "fiscal_dir": "fiscal_documents",
            "uploads_dir": "uploads",
        },
        mode="legacy",
    )
    reset_audit_events()
    data_file = resolver.resolve_data("users.json")
    backup_dir = resolver.resolve_backup("daily")
    log_file = resolver.resolve_log("actions")
    fiscal_file = resolver.resolve_fiscal("xml")
    assert str(data_file).endswith("data\\users.json") or str(data_file).endswith("data/users.json")
    assert "backups" in str(backup_dir)
    assert "logs" in str(log_file)
    assert "fiscal_documents" in str(fiscal_file)
    events = get_audit_events()
    namespaces = [e["namespace"] for e in events]
    assert "data" in namespaces
    assert "backup" in namespaces
    assert "log" in namespaces
    assert "fiscal" in namespaces
    assert all(e["mode"] == "legacy" for e in events)


def test_system_config_manager_delegates_to_resolver_and_keeps_legacy_mode(monkeypatch, tmp_path):
    reset_audit_events()
    custom_data = tmp_path / "custom_data"
    custom_logs = tmp_path / "custom_logs"
    custom_backup = tmp_path / "custom_backups"
    custom_fiscal = tmp_path / "custom_fiscal"

    monkeypatch.setattr(
        system_config_manager,
        "load_system_config",
        lambda: {
            "data_dir": str(custom_data),
            "logs_dir": str(custom_logs),
            "backups_dir": str(custom_backup),
            "fiscal_dir": str(custom_fiscal),
        },
    )
    monkeypatch.setattr(system_config_manager, "_PATH_RESOLVER", None)
    path_data = Path(system_config_manager.get_data_path("a.json"))
    path_log = Path(system_config_manager.get_log_path("b.log"))
    path_backup = Path(system_config_manager.get_backup_path("c"))
    path_fiscal = Path(system_config_manager.get_fiscal_path("d.xml"))
    assert str(path_data).startswith(str(custom_data))
    assert str(path_log).startswith(str(custom_logs))
    assert str(path_backup).startswith(str(custom_backup))
    assert str(path_fiscal).startswith(str(custom_fiscal))
    events = get_audit_events()
    assert any(e["namespace"] == "data" for e in events)
    assert any(e["namespace"] == "backup" for e in events)
    assert any(e["namespace"] == "log" for e in events)
    assert any(e["namespace"] == "fiscal" for e in events)
    assert all(e["mode"] == "legacy" for e in events)


def test_backup_fallback_for_invalid_backup_root(tmp_path):
    broken_target = tmp_path / "blocked"
    broken_target.write_text("x", encoding="utf-8")
    resolver = PathResolver(
        base_dir=str(tmp_path),
        config_loader=lambda: {"backups_dir": "blocked"},
        mode="legacy",
    )
    reset_audit_events()
    resolved = resolver.resolve_backup("snap")
    assert "Backups" in str(resolved)
    events = get_audit_events()
    backup_events = [e for e in events if e["namespace"] == "backup"]
    assert backup_events
    assert backup_events[-1]["fallback_used"] is True


def test_critical_json_reconciliation_report_marks_divergence(monkeypatch):
    def fake_snapshot(name):
        if name == "cashier_sessions.json":
            return {
                "name": name,
                "canonical_path": "x/data/cashier_sessions.json",
                "legacy_path": "x/cashier_sessions.json",
                "canonical": {"exists": True, "size": 10, "mtime": 20.0, "sha256": "a", "valid_json": True},
                "legacy": {"exists": True, "size": 8, "mtime": 10.0, "sha256": "b", "valid_json": True},
            }
        return {
            "name": name,
            "canonical_path": f"x/data/{name}",
            "legacy_path": f"x/{name}",
            "canonical": {"exists": True, "size": 10, "mtime": 10.0, "sha256": "z", "valid_json": True},
            "legacy": {"exists": True, "size": 10, "mtime": 10.0, "sha256": "z", "valid_json": True},
        }

    monkeypatch.setattr(system_config_manager, "build_json_pair_snapshot", fake_snapshot)
    report = system_config_manager.build_critical_json_reconciliation_report()
    by_name = {item["name"]: item for item in report}
    assert by_name["cashier_sessions.json"]["divergent"] is True
    assert by_name["cashier_sessions.json"]["newer"] == "data"
    assert by_name["room_charges.json"]["divergent"] is False
