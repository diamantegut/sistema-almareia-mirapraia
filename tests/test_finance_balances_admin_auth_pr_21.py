from flask import Flask, session

from app.blueprints.finance import routes as finance_routes


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def _set_profile(role, user="u1"):
    session.clear()
    session.update(
        {
            "user": user,
            "role": role,
            "department": "Financeiro",
            "permissions": [],
        }
    )


def test_finance_balances_denies_non_admin():
    app = _make_test_app()
    with app.test_request_context("/finance/balances", method="GET"):
        _set_profile("gerente")
        response = finance_routes.finance_balances.__wrapped__()
    assert getattr(response, "status_code", None) in {302, 403}


def test_finance_balances_allows_admin(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "render_template", lambda *args, **kwargs: "ok")
    with app.test_request_context("/finance/balances", method="GET"):
        _set_profile("admin")
        response = finance_routes.finance_balances.__wrapped__()
    assert response == "ok"


def test_finance_balances_allows_administracao_sistema(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "render_template", lambda *args, **kwargs: "ok")
    with app.test_request_context("/finance/balances", method="GET"):
        _set_profile("administracao_sistema")
        response = finance_routes.finance_balances.__wrapped__()
    assert response == "ok"


def test_finance_balances_data_denies_non_admin_json():
    app = _make_test_app()
    with app.test_request_context("/finance/balances/data", method="GET", headers={"Accept": "application/json"}):
        _set_profile("supervisor")
        response, status = finance_routes.finance_balances_data.__wrapped__()
    assert status == 403
    assert response.get_json()["success"] is False
    assert response.get_json()["authorization_required"] is True


def test_finance_balances_data_allows_admin(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "get_balance_data", lambda *args, **kwargs: {})
    with app.test_request_context("/finance/balances/data", method="GET"):
        _set_profile("admin")
        response = finance_routes.finance_balances_data.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"] == []


def test_api_finance_session_details_denies_non_admin():
    app = _make_test_app()
    with app.test_request_context("/api/finance/session/S1", method="GET", headers={"Accept": "application/json"}):
        _set_profile("financeiro")
        response, status = finance_routes.api_finance_session_details.__wrapped__("S1")
    assert status == 403
    assert response.get_json()["success"] is False
    assert response.get_json()["authorization_request_available"] is True


def test_finance_balances_export_denies_non_admin():
    app = _make_test_app()
    with app.test_request_context("/finance/balances/export", method="GET"):
        _set_profile("gerente")
        response = finance_routes.finance_balances_export.__wrapped__()
    assert getattr(response, "status_code", None) in {302, 403}


def test_approve_endpoints_deny_non_admin():
    app = _make_test_app()
    with app.test_request_context("/api/finance/session/S1/approve_divergence", method="POST", headers={"Accept": "application/json"}):
        _set_profile("gerente")
        response, status = finance_routes.api_finance_session_approve_divergence.__wrapped__("S1")
    assert status == 403
    with app.test_request_context("/api/finance/balances/approve_divergences", method="POST", json={}, headers={"Accept": "application/json"}):
        _set_profile("supervisor")
        response2, status2 = finance_routes.api_finance_approve_divergences.__wrapped__()
    assert status2 == 403
    assert response.get_json()["success"] is False
    assert response2.get_json()["success"] is False
