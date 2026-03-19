from flask import Flask, session

from app.blueprints.admin import routes as admin_routes
from app.services import fiscal_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def test_reemit_creates_new_entry_and_returns_success(monkeypatch):
    app = _make_test_app()
    source_id = "OLD-1"
    pool = [
        {
            "id": source_id,
            "status": "emitted",
            "fiscal_type": "nfce",
            "fiscal_doc_uuid": "UUID-OLD",
            "access_key": "26260328952732000109650090000005821234616972",
            "items": [{"name": "Item", "qty": 1, "price": 10.0}],
            "payment_methods": [{"method": "Dinheiro", "amount": 10.0}],
            "history": [],
        }
    ]

    monkeypatch.setattr(admin_routes.FiscalPoolService, "_load_pool", staticmethod(lambda: pool))
    monkeypatch.setattr(admin_routes.FiscalPoolService, "save_pool", staticmethod(lambda p: True))
    monkeypatch.setattr(
        admin_routes.FiscalPoolService,
        "get_entry",
        staticmethod(lambda entry_id: next((e for e in pool if e.get("id") == entry_id), None)),
    )
    def _fake_emit(specific_id=None):
        for row in pool:
            if row.get("id") == specific_id:
                row["status"] = "emitted"
                row["fiscal_doc_uuid"] = "UUID-NEW"
                row["access_key"] = "26260328952732000109650090000005821234616972"
                break
        return {"success": 1, "failed": 0}

    monkeypatch.setattr(fiscal_service, "process_pending_emissions", _fake_emit)

    with app.test_request_context("/admin/fiscal/pool/action", method="POST", json={"action": "reemit", "id": source_id}):
        _set_admin()
        response = admin_routes.fiscal_pool_action.__wrapped__()
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert len(pool) == 2
    new_entry = pool[1]
    assert new_entry["status"] == "emitted"
    assert new_entry["reemitted_from"] == source_id


def test_reemit_rejects_non_emitted_entry(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        admin_routes.FiscalPoolService,
        "get_entry",
        staticmethod(lambda entry_id: {"id": entry_id, "status": "pending", "fiscal_type": "nfce"}),
    )
    with app.test_request_context("/admin/fiscal/pool/action", method="POST", json={"action": "reemit", "id": "A1"}):
        _set_admin()
        response, status = admin_routes.fiscal_pool_action.__wrapped__()
    assert status == 400
    assert response.get_json()["success"] is False
