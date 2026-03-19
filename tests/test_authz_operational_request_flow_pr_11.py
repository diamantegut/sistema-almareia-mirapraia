import json

from flask import Flask, session

from app.blueprints.admin import routes as admin_routes
from app.blueprints.reception import routes as reception_routes
from app.services.authz import operational_request_service


def _status_code(response):
    if isinstance(response, tuple):
        return int(response[1])
    return int(getattr(response, "status_code", 200))


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
    app.add_url_rule("/api/fiscal/receive", endpoint="admin.api_fiscal_receive", view_func=lambda: "ok")
    return app


def test_pay_charge_denied_returns_authorization_request_option(tmp_path, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))

    payload = {"payments": [{"method": "dinheiro", "amount": 10}], "room_num": "12"}
    with app.test_request_context("/reception/pay_charge/ch1", method="POST", json=payload):
        session.clear()
        session.update({"user": "oper1", "role": "colaborador", "department": "Serviço", "permissions": ["restaurante_mirapraia"]})
        response = reception_routes.reception_pay_charge.__wrapped__("ch1")
    body = response[0].get_json()
    assert response[1] == 403
    assert body["authorization_request"]["available"] is True
    assert body["authorization_request"]["route_key"] == "reception.pay_charge"


def test_request_create_view_approve_once_and_consume(tmp_path, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    audit_calls = []
    monkeypatch.setattr(operational_request_service.LoggerService, "log_acao", staticmethod(lambda **kwargs: audit_calls.append(kwargs) or True))

    with app.test_request_context(
        "/reception/authz-requests/create",
        method="POST",
        json={"route_key": "reception.pay_charge", "reason": "fechamento urgente", "context": {"charge_id": "ch1"}},
    ):
        session.clear()
        session.update({"user": "oper1", "role": "colaborador", "department": "Serviço"})
        created = reception_routes.reception_create_operational_authz_request.__wrapped__()
    created_payload = created.get_json()
    request_id = created_payload["request_id"]

    monkeypatch.setattr(reception_routes, "render_template", lambda tpl, **ctx: ctx)
    with app.test_request_context("/reception/authz-requests", method="GET"):
        session.clear()
        session.update({"user": "sup1", "role": "supervisor", "department": "Recepção"})
        panel_ctx = reception_routes.reception_operational_authz_requests.__wrapped__()
    assert any(str(row.get("id")) == request_id for row in panel_ctx["pending"])

    with app.test_request_context(
        f"/reception/authz-requests/{request_id}/decide",
        method="POST",
        json={"decision": "approve_once", "decision_reason": "liberação pontual"},
    ):
        session.clear()
        session.update({"user": "sup1", "role": "supervisor", "department": "Recepção"})
        decided = reception_routes.reception_decide_operational_authz_request.__wrapped__(request_id)
    assert decided.get_json()["success"] is True

    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [])
    payload = {"payments": [{"method": "dinheiro", "amount": 10}], "room_num": "12"}
    with app.test_request_context("/reception/pay_charge/ch1", method="POST", json=payload):
        session.clear()
        session.update({"user": "oper1", "role": "colaborador", "department": "Serviço"})
        first_use = reception_routes.reception_pay_charge.__wrapped__("ch1")
    assert first_use.status_code == 200
    assert first_use.get_json()["message"] == "Conta não encontrada."

    with app.test_request_context("/reception/pay_charge/ch1", method="POST", json=payload):
        session.clear()
        session.update({"user": "oper1", "role": "colaborador", "department": "Serviço"})
        second_use = reception_routes.reception_pay_charge.__wrapped__("ch1")
    assert second_use[1] == 403
    assert any(call.get("acao") == "AUTHZ_OPERATIONAL_REQUEST_CREATED" for call in audit_calls)
    assert any(call.get("acao") == "AUTHZ_OPERATIONAL_REQUEST_DECIDED" for call in audit_calls)


def test_request_deny_keeps_operation_blocked(tmp_path, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))

    with app.test_request_context(
        "/reception/authz-requests/create",
        method="POST",
        json={"route_key": "reception.debug_report_calc", "reason": "preciso ver cálculo"},
    ):
        session.clear()
        session.update({"user": "oper2", "role": "colaborador", "department": "Serviço"})
        created = reception_routes.reception_create_operational_authz_request.__wrapped__()
    request_id = created.get_json()["request_id"]

    with app.test_request_context(
        f"/reception/authz-requests/{request_id}/decide",
        method="POST",
        json={"decision": "deny", "decision_reason": "sem justificativa operacional"},
    ):
        session.clear()
        session.update({"user": "sup2", "role": "supervisor", "department": "Recepção"})
        denied = reception_routes.reception_decide_operational_authz_request.__wrapped__(request_id)
    assert denied.get_json()["success"] is True

    with app.test_request_context("/debug/report_calc/12", method="GET"):
        session.clear()
        session.update({"user": "oper2", "role": "colaborador", "department": "Serviço"})
        blocked = reception_routes.debug_report_calc_route.__wrapped__("12")
    assert blocked[1] == 403
    assert blocked[0].get_json()["authorization_request"]["route_key"] == "reception.debug_report_calc"


def test_temporary_and_permanent_decisions_create_usable_grants(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))

    created_temp = operational_request_service.create_request(
        requester_user="oper3",
        requester_role="colaborador",
        route_key="reception.pay_charge",
        endpoint="reception.reception_pay_charge",
        http_method="POST",
        context={"charge_id": "ch9"},
        reason="temporário",
    )
    operational_request_service.decide_request(
        request_id=created_temp["id"],
        approver_user="sup3",
        approver_role="supervisor",
        decision="approve_temporary",
        decision_reason="janela operacional",
        ttl_minutes=30,
    )
    assert operational_request_service.authorize_by_grant(user="oper3", route_key="reception.pay_charge") is True

    created_perm = operational_request_service.create_request(
        requester_user="oper4",
        requester_role="colaborador",
        route_key="admin.api_fiscal_receive",
        endpoint="admin.api_fiscal_receive",
        http_method="POST",
        context={"fiscal_id": "abc"},
        reason="permanente",
    )
    operational_request_service.decide_request(
        request_id=created_perm["id"],
        approver_user="sup4",
        approver_role="supervisor",
        decision="approve_permanent",
        decision_reason="atividade fixa",
    )
    assert operational_request_service.authorize_by_grant(user="oper4", route_key="admin.api_fiscal_receive") is True
    assert operational_request_service.authorize_by_grant(user="oper4", route_key="admin.api_fiscal_receive") is True


def test_admin_fiscal_route_exposes_request_option_and_respects_grant(tmp_path, monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    monkeypatch.setattr(admin_routes.FiscalPoolService, "_load_pool", staticmethod(lambda: []))
    monkeypatch.setattr(admin_routes.FiscalPoolService, "save_pool", staticmethod(lambda pool: True))
    monkeypatch.setattr(admin_routes.LoggerService, "log_acao", staticmethod(lambda **kwargs: True))

    with app.test_request_context("/api/fiscal/receive", method="POST", json={"id": "f1"}):
        session.clear()
        session.update({"user": "oper5", "role": "colaborador", "department": "Serviço"})
        blocked = admin_routes.api_fiscal_receive.__wrapped__()
    assert blocked[1] == 403
    assert blocked[0].get_json()["authorization_request"]["route_key"] == "admin.api_fiscal_receive"

    created = operational_request_service.create_request(
        requester_user="oper5",
        requester_role="colaborador",
        route_key="admin.api_fiscal_receive",
        endpoint="admin.api_fiscal_receive",
        http_method="POST",
        context={"fiscal_id": "f1"},
        reason="urgência fiscal",
    )
    operational_request_service.decide_request(
        request_id=created["id"],
        approver_user="sup5",
        approver_role="supervisor",
        decision="approve_once",
        decision_reason="liberação pontual",
    )

    with app.test_request_context("/api/fiscal/receive", method="POST", json={"id": "f1"}):
        session.clear()
        session.update({"user": "oper5", "role": "colaborador", "department": "Serviço"})
        allowed = admin_routes.api_fiscal_receive.__wrapped__()
    assert _status_code(allowed) == 200
