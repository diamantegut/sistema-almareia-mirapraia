import json
from pathlib import Path

from flask import Flask

from app.services import data_cleanup_monitor_service as monitor_service
from app.services import data_service


def test_record_data_cleanup_event_generates_log_and_summary(tmp_path, monkeypatch):
    log_file = tmp_path / "data_cleanup_monitor.log"
    summary_file = tmp_path / "data_cleanup_monitor_summary.json"
    monkeypatch.setattr(monitor_service, "MONITOR_LOG_FILE", str(log_file))
    monkeypatch.setattr(monitor_service, "MONITOR_SUMMARY_FILE", str(summary_file))

    monitor_service.record_data_cleanup_event(
        event_type="file_not_found",
        requested_file=r"E:\Sistema Mirapraia\data\cashier_sessions.json",
        error_message="arquivo ausente",
    )
    monitor_service.record_data_cleanup_event(
        event_type="file_not_found",
        requested_file=r"E:\Sistema Mirapraia\data\ngrok_status.json",
        error_message="arquivo ausente",
    )

    assert log_file.exists()
    lines = [line.strip() for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["event_type"] == "file_not_found"
    assert payload["severity"] in {"critico", "medio", "baixo"}

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["events_count"] == 2
    assert any("cashier_sessions.json" in row["path"] for row in summary["arquivos_ainda_necessarios"])


def test_load_json_missing_file_triggers_monitor(monkeypatch, tmp_path):
    called = []

    def _capture(**kwargs):
        called.append(kwargs)
        return kwargs

    monkeypatch.setattr(data_service, "record_data_cleanup_event", _capture)
    missing = tmp_path / "inexistente.json"
    result = data_service._load_json(str(missing), default={"ok": True}, strict=False)
    assert result == {"ok": True}
    assert len(called) == 1
    assert called[0]["event_type"] == "file_not_found"
    assert str(missing) in called[0]["requested_file"]


def test_record_event_includes_route_context(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "ok")
    log_file = tmp_path / "route_monitor.log"
    summary_file = tmp_path / "route_monitor_summary.json"
    monkeypatch.setattr(monitor_service, "MONITOR_LOG_FILE", str(log_file))
    monkeypatch.setattr(monitor_service, "MONITOR_SUMMARY_FILE", str(summary_file))
    with app.test_request_context("/", method="GET"):
        monitor_service.record_data_cleanup_event(
            event_type="config_read_failure",
            requested_file=r"E:\Sistema Mirapraia\data\settings.json",
            error_message="falha leitura",
        )
    payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert payload["impact"]["route"] == "/"
