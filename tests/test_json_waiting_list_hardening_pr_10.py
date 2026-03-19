import json
from pathlib import Path
from datetime import datetime

import pytest

from app.services import waiting_list_service
from app.services import data_service
from app.services import system_config_manager
from app.utils import lock as lock_module


def _default_waiting_payload():
    return {
        "queue": [],
        "history": [],
        "events": [],
        "marketing_contacts": {},
        "settings": {
            "is_open": True,
            "max_queue_size": 50,
            "average_wait_per_party": 15,
            "critical_wait_threshold": 45,
            "cutoff_hour": 23,
            "max_party_size": 20,
            "duplicate_block_minutes": 5,
            "call_response_timeout_minutes": 15,
            "call_presence_sla_minutes": 15,
            "call_timeout_action": "manual",
            "smart_call_enabled": False,
            "smart_call_target_capacity": 4,
            "public_queue_url": "",
            "house_rules": [
                "Todos devem estar presentes para ocupar a mesa.",
                "Tolerância de 5 minutos após chamarmos.",
            ],
        },
        "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
    }


def test_waiting_list_path_is_centralized():
    assert Path(waiting_list_service.WAITING_LIST_FILE) == Path(system_config_manager.WAITING_LIST_FILE)


def test_waiting_list_save_and_load_roundtrip(tmp_path, monkeypatch):
    waiting_file = tmp_path / "waiting_list.json"
    monkeypatch.setattr(waiting_list_service, "WAITING_LIST_FILE", str(waiting_file))
    payload = _default_waiting_payload()
    payload["queue"] = [{"id": "q1", "name": "Ana", "status": "aguardando", "entry_time": "2026-01-01T10:00:00"}]

    waiting_list_service.save_waiting_data(payload)
    loaded = waiting_list_service.load_waiting_data()
    queue = waiting_list_service.get_waiting_list()

    assert loaded["queue"][0]["id"] == "q1"
    assert queue[0]["id"] == "q1"


def test_waiting_list_lock_prevents_concurrent_write(tmp_path, monkeypatch):
    waiting_file = tmp_path / "waiting_list.json"
    monkeypatch.setattr(waiting_list_service, "WAITING_LIST_FILE", str(waiting_file))
    original_lock = lock_module.file_lock

    def fast_lock(path, timeout=10):
        return original_lock(path, timeout=0.1)

    monkeypatch.setattr(waiting_list_service, "file_lock", fast_lock)
    waiting_list_service.save_waiting_data(_default_waiting_payload())

    with original_lock(str(waiting_file), timeout=0.1):
        with pytest.raises(TimeoutError):
            waiting_list_service.save_waiting_data(_default_waiting_payload())


def test_waiting_list_invalid_json_returns_safe_default_and_snapshot(tmp_path, monkeypatch):
    waiting_file = tmp_path / "waiting_list.json"
    waiting_file.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(waiting_list_service, "WAITING_LIST_FILE", str(waiting_file))

    loaded = waiting_list_service.load_waiting_data()
    snapshots = list(tmp_path.glob("waiting_list.json.corrupt_*.json"))

    assert loaded.get("_integrity_error") == "json_invalid"
    assert loaded["queue"] == []
    assert len(snapshots) == 1


def test_waiting_list_functional_regression_add_and_update(tmp_path, monkeypatch):
    waiting_file = tmp_path / "waiting_list.json"
    monkeypatch.setattr(waiting_list_service, "WAITING_LIST_FILE", str(waiting_file))
    monkeypatch.setattr(waiting_list_service, "_is_after_cutoff", lambda **kwargs: False)
    waiting_list_service.save_waiting_data(_default_waiting_payload())
    waiting_list_service.update_settings({"is_open": True, "cutoff_hour": 23, "updated_by": "tester"})

    result, error = waiting_list_service.add_customer(
        name="Cliente Teste",
        phone="(11) 98888-7777",
        party_size=3,
        country_code="BR",
        created_by="tester",
        source="fila_virtual",
    )

    assert error is None
    entry_id = result["entry"]["id"]
    updated = waiting_list_service.update_customer_status(entry_id, "chamado", reason="teste", user="tester")
    loaded = waiting_list_service.load_waiting_data()
    queue_ids = {row.get("id") for row in loaded.get("queue", [])}

    assert updated is not None
    assert entry_id in queue_ids


def test_data_service_strict_load_raises_on_invalid_json(tmp_path):
    target = tmp_path / "sales_history.json"
    target.write_text("{invalid", encoding="utf-8")

    with pytest.raises(RuntimeError):
        data_service._load_json(str(target), [], strict=True)

    assert len(list(tmp_path.glob("sales_history.json.corrupt_*.json"))) == 1


def test_data_service_save_json_critical_uses_atomic(monkeypatch):
    called = {"atomic": 0}

    def fake_atomic(path, data):
        called["atomic"] += 1
        return True

    monkeypatch.setattr(data_service, "_save_json_atomic", fake_atomic)
    ok = data_service._save_json(data_service.SALES_HISTORY_FILE, [{"id": "1"}])

    assert ok is True
    assert called["atomic"] == 1
