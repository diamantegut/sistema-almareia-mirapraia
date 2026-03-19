from flask import Flask, session

from app.blueprints.finance import routes as finance_routes


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _set_non_admin():
    session.clear()
    session.update({"user": "ger1", "role": "gerente"})


def test_balances_data_filters_by_user(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes,
        "_load_cashier_sessions",
        lambda: [
            {
                "id": "S1",
                "status": "closed",
                "type": "restaurant_service",
                "user": "alice",
                "opened_at": "01/03/2026 10:00",
                "closed_at": "01/03/2026 11:00",
                "opening_balance": 0.0,
                "closing_balance": 100.0,
                "closing_cash": 100.0,
                "difference": 0.0,
                "difference_approved": True,
                "transactions": [{"type": "sale", "amount": 100.0, "payment_method": "Dinheiro"}],
            },
            {
                "id": "S2",
                "status": "closed",
                "type": "restaurant_service",
                "user": "bob",
                "opened_at": "02/03/2026 10:00",
                "closed_at": "02/03/2026 11:00",
                "opening_balance": 0.0,
                "closing_balance": 40.0,
                "closing_cash": 40.0,
                "difference": 0.0,
                "difference_approved": True,
                "transactions": [{"type": "sale", "amount": 40.0, "payment_method": "Dinheiro"}],
            },
        ],
    )
    with app.test_request_context(
        "/finance/balances/data?period_type=monthly&year=2026&specific_value=3&user_filter=alice",
        method="GET",
        headers={"Accept": "application/json"},
    ):
        _set_admin()
        response = finance_routes.finance_balances_data.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert len(payload["data"]) == 1
    item = payload["data"][0]
    assert item["sessions"][0]["user"] == "alice"
    assert item["total_in"] == 100.0


def test_balances_data_filters_by_payment_method(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes,
        "_load_cashier_sessions",
        lambda: [
            {
                "id": "S1",
                "status": "closed",
                "type": "restaurant_service",
                "user": "alice",
                "opened_at": "05/03/2026 10:00",
                "closed_at": "05/03/2026 11:00",
                "opening_balance": 0.0,
                "closing_balance": 150.0,
                "closing_cash": 50.0,
                "difference": 0.0,
                "difference_approved": True,
                "transactions": [
                    {"type": "sale", "amount": 100.0, "payment_method": "Cartão"},
                    {"type": "sale", "amount": 50.0, "payment_method": "Pix"},
                ],
            }
        ],
    )
    with app.test_request_context(
        "/finance/balances/data?period_type=monthly&year=2026&specific_value=3&payment_method_filter=Pix",
        method="GET",
        headers={"Accept": "application/json"},
    ):
        _set_admin()
        response = finance_routes.finance_balances_data.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert len(payload["data"]) == 1
    item = payload["data"][0]
    assert item["total_in"] == 50.0
    assert item["sessions"][0]["transactions_count"] == 1


def test_closed_accounts_endpoint_and_reopen_are_admin_only():
    app = _make_test_app()
    with app.test_request_context("/api/closed_accounts", method="GET", headers={"Accept": "application/json"}):
        _set_non_admin()
        response, status = finance_routes.api_closed_accounts.__wrapped__()
    assert status == 403
    with app.test_request_context("/admin/reopen_account", method="POST", json={"id": "A1", "reason": "x"}, headers={"Accept": "application/json"}):
        _set_non_admin()
        response2, status2 = finance_routes.admin_reopen_account.__wrapped__()
    assert status2 == 403
    assert response.get_json()["success"] is False
    assert response2.get_json()["success"] is False


def test_closed_accounts_endpoint_returns_expected_payload(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes.ClosedAccountService,
        "search_closed_accounts",
        staticmethod(lambda filters=None, page=None, per_page=20: {
            "items": [{"id": "C1", "timestamp": "10/03/2026 12:00:00", "user": "alice", "total": "10.5"}],
            "page": 1,
            "pages": 1,
            "total": 1
        }),
    )
    with app.test_request_context("/api/closed_accounts?page=1&per_page=20&origin=restaurant_table", method="GET", headers={"Accept": "application/json"}):
        _set_admin()
        response = finance_routes.api_closed_accounts.__wrapped__()
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["items"][0]["closed_at"] == "10/03/2026 12:00:00"
    assert payload["items"][0]["closed_by"] == "alice"
    assert payload["items"][0]["status"] == "closed"


def test_reopen_account_marks_history(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes.ClosedAccountService,
        "get_closed_account",
        staticmethod(lambda closed_id: {"id": closed_id, "status": "closed"}),
    )
    marked = {"ok": False}
    monkeypatch.setattr(
        finance_routes,
        "_apply_closed_account_reopen",
        lambda target, reason, user: (marked.update({"ok": True}) or True, ""),
    )
    with app.test_request_context("/admin/reopen_account", method="POST", json={"id": "C1", "reason": "Conferência"}, headers={"Accept": "application/json"}):
        _set_admin()
        response = finance_routes.admin_reopen_account.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert marked["ok"] is True
