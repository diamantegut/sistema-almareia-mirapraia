import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.services import data_service


def _configure_table_orders_path(monkeypatch, tmp_path):
    table_orders_file = tmp_path / "table_orders.json"
    table_orders_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(data_service, "TABLE_ORDERS_FILE", str(table_orders_file))
    return table_orders_file


def test_save_table_orders_serializa_escrita(monkeypatch, tmp_path):
    _configure_table_orders_path(monkeypatch, tmp_path)
    tracker = {"active": 0, "max_active": 0}
    original_save_atomic = data_service._save_json_atomic

    def _spy_save_atomic(filepath, payload):
        tracker["active"] += 1
        tracker["max_active"] = max(tracker["max_active"], tracker["active"])
        time.sleep(0.05)
        try:
            return original_save_atomic(filepath, payload)
        finally:
            tracker["active"] -= 1

    monkeypatch.setattr(data_service, "_save_json_atomic", _spy_save_atomic)

    def _writer(i):
        return data_service.save_table_orders({str(i): {"items": [f"item-{i}"]}})

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_writer, range(12)))

    assert all(results)
    assert tracker["max_active"] == 1


def test_save_table_orders_mitiga_lost_update_com_merge(monkeypatch, tmp_path):
    table_orders_file = _configure_table_orders_path(monkeypatch, tmp_path)
    assert data_service.save_table_orders({"base": {"items": ["start"]}})
    barrier = threading.Barrier(2)

    def _worker(table_id):
        snapshot = data_service.load_table_orders()
        snapshot[table_id] = {"items": [table_id]}
        barrier.wait()
        return data_service.save_table_orders(snapshot)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(_worker, ["A", "B"]))

    assert all(results)
    final_payload = json.loads(table_orders_file.read_text(encoding="utf-8"))
    assert "A" in final_payload
    assert "B" in final_payload
    assert "base" in final_payload


def test_owner_unico_permanece_data_service_save_table_orders():
    source = __import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "services" / "data_service.py"
    content = source.read_text(encoding="utf-8")
    assert "def save_table_orders(data):" in content
