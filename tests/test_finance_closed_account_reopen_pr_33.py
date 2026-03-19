from copy import deepcopy
from flask import Flask, session

from app.blueprints.finance import routes as finance_routes
from app.services import cashier_service


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "ok")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _set_manager():
    session.clear()
    session.update({"user": "ger", "role": "gerente"})


def _restaurant_closed_account():
    return {
        "id": "CL-1",
        "origin": "restaurant_table",
        "original_id": "10",
        "status": "closed",
        "closed_at": "16/03/2026 10:30:00",
        "total": 150.0,
        "items": [{"name": "Prato Executivo", "quantity": 1, "price": 150.0, "total": 150.0}],
        "payments": [{"method": "Cartão", "amount": 150.0}],
        "details": {"waiter": "Ana"},
    }


def test_closed_account_details_returns_items_and_reopen_context(monkeypatch):
    app = _make_app()
    acc = _restaurant_closed_account()
    sessions = [
        {
            "id": "CS-1",
            "status": "open",
            "transactions": [
                {"id": "TX-1", "type": "sale", "timestamp": "16/03/2026 10:29", "amount": 150.0, "details": {"table_id": "10"}}
            ],
        }
    ]
    monkeypatch.setattr(finance_routes, "_ensure_admin_finance_balances_access", lambda: None)
    monkeypatch.setattr(finance_routes.ClosedAccountService, "get_closed_account", staticmethod(lambda cid: deepcopy(acc)))
    monkeypatch.setattr(cashier_service.CashierService, "list_sessions", staticmethod(lambda: deepcopy(sessions)))
    monkeypatch.setattr(finance_routes, "load_room_charges", lambda: [])
    with app.test_request_context("/api/closed_accounts/CL-1", method="GET", headers={"Accept": "application/json"}):
        _set_admin()
        response = finance_routes.api_closed_account_details.__wrapped__("CL-1")
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["can_reopen"] is True
    assert len(payload["data"]["items"]) == 1


def test_reopen_restaurant_account_reverts_cashier_and_restores_order(monkeypatch):
    app = _make_app()
    acc = _restaurant_closed_account()
    sessions_state = [
        {
            "id": "CS-1",
            "status": "open",
            "transactions": [
                {"id": "TX-1", "type": "sale", "timestamp": "16/03/2026 10:29", "amount": 150.0, "details": {"table_id": "10"}}
            ],
        }
    ]
    saved_orders = {}
    mark_payload = {}
    monkeypatch.setattr(finance_routes, "_ensure_admin_finance_balances_access", lambda: None)
    monkeypatch.setattr(finance_routes.ClosedAccountService, "get_closed_account", staticmethod(lambda cid: deepcopy(acc)))
    monkeypatch.setattr(
        finance_routes.ClosedAccountService,
        "mark_as_reopened",
        staticmethod(lambda closed_id, reopened_by, reason, metadata=None: mark_payload.update({"id": closed_id, "metadata": metadata}) or True),
    )
    monkeypatch.setattr(cashier_service.CashierService, "list_sessions", staticmethod(lambda: deepcopy(sessions_state)))
    monkeypatch.setattr(
        cashier_service.CashierService,
        "persist_sessions",
        staticmethod(lambda sessions, trigger_backup=False: sessions_state.clear() or sessions_state.extend(deepcopy(sessions)) or True),
    )
    monkeypatch.setattr(finance_routes, "load_room_charges", lambda: [])
    monkeypatch.setattr(finance_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(finance_routes, "save_table_orders", lambda orders: saved_orders.update(deepcopy(orders)) or True)
    monkeypatch.setattr(finance_routes, "log_system_action", lambda *args, **kwargs: None)
    with app.test_request_context("/admin/reopen_account", method="POST", json={"id": "CL-1", "reason": "Erro no fechamento"}):
        _set_admin()
        response = finance_routes.admin_reopen_account.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert sessions_state[0]["transactions"] == []
    assert "10" in saved_orders
    assert saved_orders["10"]["status"] == "open"
    assert mark_payload["metadata"]["reversed_transaction_ids"] == ["TX-1"]


def test_reopen_is_blocked_when_original_cashier_closed(monkeypatch):
    app = _make_app()
    acc = _restaurant_closed_account()
    sessions = [
        {
            "id": "CS-1",
            "status": "closed",
            "transactions": [
                {"id": "TX-1", "type": "sale", "timestamp": "16/03/2026 10:29", "amount": 150.0, "details": {"table_id": "10"}}
            ],
        }
    ]
    monkeypatch.setattr(finance_routes, "_ensure_admin_finance_balances_access", lambda: None)
    monkeypatch.setattr(finance_routes.ClosedAccountService, "get_closed_account", staticmethod(lambda cid: deepcopy(acc)))
    monkeypatch.setattr(cashier_service.CashierService, "list_sessions", staticmethod(lambda: deepcopy(sessions)))
    monkeypatch.setattr(finance_routes, "load_room_charges", lambda: [])
    with app.test_request_context("/admin/reopen_account", method="POST", json={"id": "CL-1", "reason": "Erro"}):
        _set_admin()
        response, status = finance_routes.admin_reopen_account.__wrapped__()
    payload = response.get_json()
    assert status == 400
    assert payload["success"] is False
    assert "fechado" in payload["error"].lower()


def test_api_closed_accounts_admin_only_preserved():
    app = _make_app()
    with app.test_request_context("/api/closed_accounts", method="GET", headers={"Accept": "application/json"}):
        _set_manager()
        response, status = finance_routes.api_closed_accounts.__wrapped__()
    assert status == 403
    assert response.get_json()["success"] is False
