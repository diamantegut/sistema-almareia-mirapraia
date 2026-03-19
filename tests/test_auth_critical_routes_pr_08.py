from flask import Flask, session
import pytest

from app.blueprints.admin import routes as admin_routes
from app.blueprints.reception import routes as reception_routes
from app.services.authz import operational_request_service


PROFILES = {
    "admin": {"user": "admin1", "role": "admin", "department": "Diretoria", "permissions": []},
    "gerente": {"user": "ger1", "role": "gerente", "department": "Gestao", "permissions": []},
    "supervisor": {"user": "sup1", "role": "supervisor", "department": "Recepção", "permissions": []},
    "recepcao_autorizada": {
        "user": "rec1",
        "role": "colaborador",
        "department": "Recepção",
        "permissions": ["recepcao"],
    },
    "operacional_sem_financeiro": {
        "user": "op1",
        "role": "colaborador",
        "department": "Serviço",
        "permissions": ["restaurante_mirapraia"],
    },
    "externo": {"user": "ext1", "role": "colaborador", "department": "Financeiro", "permissions": ["financeiro"]},
}


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule(
        "/reception/authz-requests/create",
        endpoint="reception.reception_create_operational_authz_request",
        view_func=lambda: "ok",
    )
    return app


def _set_profile(profile_name):
    session.clear()
    session.update(PROFILES[profile_name])


def _status_code(response):
    if isinstance(response, tuple):
        return int(response[1])
    return int(getattr(response, "status_code", 200))


@pytest.mark.parametrize(
    "profile,expected_status",
    [
        ("admin", 200),
        ("gerente", 200),
        ("supervisor", 200),
        ("recepcao_autorizada", 403),
        ("operacional_sem_financeiro", 403),
        ("externo", 403),
    ],
)
def test_api_fiscal_receive_auth_matrix(profile, expected_status, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "authorize_by_grant", lambda **kwargs: False)
    monkeypatch.setattr(admin_routes.FiscalPoolService, "_load_pool", staticmethod(lambda: []))
    monkeypatch.setattr(admin_routes.FiscalPoolService, "save_pool", staticmethod(lambda pool: True))
    monkeypatch.setattr(admin_routes.LoggerService, "log_acao", staticmethod(lambda **kwargs: True))

    with app.test_request_context("/api/fiscal/receive", method="POST", json={"id": "FISC-1"}):
        _set_profile(profile)
        response = admin_routes.api_fiscal_receive()
    assert _status_code(response) == expected_status


@pytest.mark.parametrize(
    "profile,expected_status",
    [
        ("admin", 200),
        ("gerente", 200),
        ("supervisor", 200),
        ("recepcao_autorizada", 200),
        ("operacional_sem_financeiro", 403),
        ("externo", 403),
    ],
)
def test_reception_pay_charge_auth_matrix(profile, expected_status, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "authorize_by_grant", lambda **kwargs: False)
    monkeypatch.setattr(
        reception_routes,
        "load_room_charges",
        lambda: [{"id": "ch1", "status": "pending", "total": 10.0, "room_number": "12", "items": []}],
    )
    monkeypatch.setattr(
        reception_routes.CashierService,
        "list_sessions",
        staticmethod(lambda: [{"id": "cx1", "status": "open", "type": "reception_room_billing", "transactions": []}]),
    )
    monkeypatch.setattr(reception_routes.CashierService, "persist_sessions", staticmethod(lambda sessions, trigger_backup=False: True))
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [{"id": "dinheiro", "name": "Dinheiro"}])
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda charges: True)
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)

    payload = {"payments": [{"method": "dinheiro", "amount": 10.0}], "room_num": "12"}
    with app.test_request_context("/reception/pay_charge/ch1", method="POST", json=payload):
        _set_profile(profile)
        response = reception_routes.reception_pay_charge.__wrapped__("ch1")
    assert _status_code(response) == expected_status


@pytest.mark.parametrize(
    "profile,expected_status",
    [
        ("admin", 200),
        ("gerente", 200),
        ("supervisor", 200),
        ("recepcao_autorizada", 403),
        ("operacional_sem_financeiro", 403),
        ("externo", 403),
    ],
)
def test_debug_report_calc_auth_matrix(profile, expected_status, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "authorize_by_grant", lambda **kwargs: False)
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [])

    with app.test_request_context("/debug/report_calc/12", method="GET"):
        _set_profile(profile)
        response = reception_routes.debug_report_calc_route.__wrapped__("12")
    assert _status_code(response) == expected_status


def test_api_fiscal_receive_requires_login():
    app = _make_test_app()
    with app.test_request_context(
        "/api/fiscal/receive",
        method="POST",
        json={"id": "FISC-2"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    ):
        session.clear()
        response = admin_routes.api_fiscal_receive()
    assert _status_code(response) == 401


def test_debug_report_calc_requires_login_redirect():
    app = _make_test_app()
    with app.test_request_context("/debug/report_calc/12", method="GET"):
        session.clear()
        response = reception_routes.debug_report_calc_route("12")
    assert _status_code(response) == 302


def test_reception_pay_charge_requires_login():
    app = _make_test_app()
    payload = {"payments": [{"method": "dinheiro", "amount": 10.0}], "room_num": "12"}
    with app.test_request_context(
        "/reception/pay_charge/ch1",
        method="POST",
        json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    ):
        session.clear()
        response = reception_routes.reception_pay_charge("ch1")
    assert _status_code(response) == 401
