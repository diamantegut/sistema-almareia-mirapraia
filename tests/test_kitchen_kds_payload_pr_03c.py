from datetime import datetime, timedelta

from flask import Flask, session

from app.blueprints import kitchen as kitchen_module


def _sample_orders(now):
    created_at = (now - timedelta(minutes=8)).strftime('%d/%m/%Y %H:%M')
    opened_at = (now - timedelta(minutes=10)).strftime('%d/%m/%Y %H:%M')
    return {
        "77": {
            "status": "open",
            "opened_at": opened_at,
            "waiter": "adailton",
            "items": [
                {
                    "id": "i1",
                    "name": "Acai",
                    "qty": 1,
                    "category": "Sobremesas",
                    "created_at": created_at,
                    "kds_status": "pending",
                    "observations": [],
                    "accompaniments": [],
                    "questions_answers": [],
                }
            ],
        }
    }


def test_build_kds_payload_keeps_wait_minutes_contract(monkeypatch):
    now = datetime(2026, 3, 15, 12, 0, 0)
    monkeypatch.setattr(kitchen_module, "load_table_orders", lambda: _sample_orders(now))
    monkeypatch.setattr(kitchen_module, "load_menu_items", lambda: [])
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"kds_sla": {"Sobremesas": 20}})
    monkeypatch.setattr(kitchen_module, "load_printers", lambda: [])
    monkeypatch.setattr(kitchen_module, "get_default_printer", lambda _kind: None)

    payload = kitchen_module._build_kds_payload("kitchen", now=now)

    assert payload["station"] == "kitchen"
    assert isinstance(payload["orders"], list)
    assert payload["orders"]
    order = payload["orders"][0]
    assert "wait_minutes" in order
    assert isinstance(order["wait_minutes"], int)
    assert order["wait_minutes"] == 8
    assert "wait_bucket" in order
    assert "is_over_avg" in order


def test_kitchen_kds_data_endpoint_returns_payload_without_nameerror(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    now = datetime(2026, 3, 15, 12, 0, 0)

    monkeypatch.setattr(kitchen_module, "load_table_orders", lambda: _sample_orders(now))
    monkeypatch.setattr(kitchen_module, "load_menu_items", lambda: [])
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"kds_sla": {"Sobremesas": 20}})
    monkeypatch.setattr(kitchen_module, "load_printers", lambda: [])
    monkeypatch.setattr(kitchen_module, "get_default_printer", lambda _kind: None)

    with app.test_request_context("/kitchen/kds/data?station=kitchen"):
        session["user"] = "cicera"
        session["role"] = "gerente"
        session["department"] = "Cozinha"
        response = kitchen_module.kitchen_kds_data.__wrapped__()
        data = response.get_json()

    assert response.status_code == 200
    assert data["success"] is True
    assert "data" in data
    assert "orders" in data["data"]
    assert data["data"]["orders"][0]["table_id"] == "77"
    assert isinstance(data["data"]["orders"][0]["wait_minutes"], int)
