import json
from pathlib import Path

from flask import Flask, session

from app.blueprints.admin import routes as admin_routes
from app.blueprints.reception import routes as reception_routes
from app.services.authz import policy_registry
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


def test_request_idempotencia_e_aprovacao_por_departamento(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    first = operational_request_service.create_request(
        requester_user="oper6",
        requester_role="colaborador",
        requester_department="Recepção",
        route_key="finance.finance_balances",
        endpoint="finance.finance_balances",
        http_method="GET",
        module_key="finance",
        sensitivity="financeiro_critico",
        reason="acesso urgente",
    )
    second = operational_request_service.create_request(
        requester_user="oper6",
        requester_role="colaborador",
        requester_department="Recepção",
        route_key="finance.finance_balances",
        endpoint="finance.finance_balances",
        http_method="GET",
        module_key="finance",
        sensitivity="financeiro_critico",
        reason="acesso urgente",
    )
    assert first["id"] == second["id"]
    operational_request_service.decide_request(
        request_id=first["id"],
        approver_user="admin1",
        approver_role="admin",
        decision="approve_department_temporary",
        decision_reason="janela controlada",
        ttl_minutes=30,
        target_department="Recepção",
    )
    assert operational_request_service.authorize_by_grant_with_scope(user="qualquer", route_key="finance.finance_balances", department="Recepção") is True


def test_aprovacao_por_classe_funcional(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    created = operational_request_service.create_request(
        requester_user="oper8",
        requester_role="supervisor",
        requester_department="Restaurante",
        requester_class="supervisor",
        route_key="restaurant.restaurant_tables",
        endpoint="restaurant.restaurant_tables",
        http_method="GET",
        module_key="restaurant",
        sensitivity="operacional_sensivel",
        reason="liberação por classe",
    )
    assert created.get("suggested_scope") == ""
    assert created.get("suggested_duration") == ""
    operational_request_service.decide_request(
        request_id=created["id"],
        approver_user="admin1",
        approver_role="admin",
        decision="approve_role_temporary",
        decision_reason="turno supervisionado",
        ttl_minutes=30,
        target_role="supervisor",
    )
    assert operational_request_service.authorize_by_grant_with_scope(
        user="x",
        route_key="restaurant.restaurant_tables",
        department="Qualquer",
        role="supervisor",
    ) is True
    assert operational_request_service.authorize_by_grant_with_scope(
        user="x",
        route_key="restaurant.restaurant_tables",
        department="Qualquer",
        role="colaborador",
    ) is False


def test_sugestao_automatica_por_departamento(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    for idx in range(5):
        created = operational_request_service.create_request(
            requester_user=f"u{idx}",
            requester_role="colaborador",
            requester_department="Restaurante",
            requester_class="colaborador",
            route_key="restaurant.restaurant_tables",
            endpoint="restaurant.restaurant_tables",
            http_method="GET",
            module_key="restaurant",
            sensitivity="operacional_sensivel",
            reason="hist",
        )
        operational_request_service.decide_request(
            request_id=created["id"],
            approver_user="admin1",
            approver_role="admin",
            decision="approve_department_temporary",
            decision_reason="padrão",
            ttl_minutes=120,
            target_department="Restaurante",
        )
    next_request = operational_request_service.create_request(
        requester_user="novo",
        requester_role="colaborador",
        requester_department="Restaurante",
        requester_class="colaborador",
        route_key="restaurant.restaurant_tables",
        endpoint="restaurant.restaurant_tables",
        http_method="GET",
        module_key="restaurant",
        sensitivity="operacional_sensivel",
        reason="novo pedido",
    )
    assert next_request.get("suggested_scope") == "department"
    assert next_request.get("suggested_duration") == "temporary"
    assert int(next_request.get("suggested_duration_value") or 0) >= 1
    assert float(next_request.get("suggestion_confidence") or 0) >= 0.5
    assert "departamento Restaurante" in str(next_request.get("suggestion_reason") or "")


def test_auditoria_sugestao_usada_e_modificada(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    created = operational_request_service.create_request(
        requester_user="oper9",
        requester_role="supervisor",
        requester_department="Restaurante",
        requester_class="supervisor",
        route_key="restaurant.restaurant_tables",
        endpoint="restaurant.restaurant_tables",
        http_method="GET",
        module_key="restaurant",
        sensitivity="operacional_sensivel",
        reason="uso sugestão",
    )
    decided = operational_request_service.decide_request(
        request_id=created["id"],
        approver_user="admin1",
        approver_role="admin",
        decision="approve_role_temporary",
        decision_reason="aprovado",
        ttl_minutes=60,
        target_role="supervisor",
        suggestion_used=True,
        suggested_scope="role",
        suggested_duration="temporary",
        suggested_duration_value=120,
    )
    assert decided.get("suggestion_used") is True
    assert decided.get("suggestion_modified") is True


def test_promocao_candidata_detectada_e_aplicada(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    for idx in range(10):
        created = operational_request_service.create_request(
            requester_user=f"rest{idx}",
            requester_role="supervisor",
            requester_department="Restaurante",
            requester_class="supervisor",
            route_key="restaurant.restaurant_tables",
            endpoint="restaurant.restaurant_tables",
            http_method="GET",
            module_key="restaurant",
            sensitivity="operacional_sensivel",
            reason="rotina",
        )
        operational_request_service.decide_request(
            request_id=created["id"],
            approver_user="admin1",
            approver_role="admin",
            decision="approve_department_temporary",
            decision_reason="histórico recorrente",
            ttl_minutes=120,
            target_department="Restaurante",
            suggestion_used=True,
            suggested_scope="department",
            suggested_duration="temporary",
            suggested_duration_value=120,
        )
    candidates = operational_request_service.list_promotion_candidates(limit=20)
    assert candidates
    candidate = candidates[0]
    assert candidate.get("permission_key") == "restaurant.restaurant_tables|GET|restaurant"
    assert int(candidate.get("total_approvals") or 0) >= 10
    assert float(candidate.get("suggestion_used_rate") or 0) >= 0.6
    applied = operational_request_service.apply_promotion_candidate(
        permission_key=str(candidate.get("permission_key") or ""),
        module=str(candidate.get("module") or ""),
        promoted_by="admin1",
        promotion_scope="department",
        promotion_duration="temporary",
        duration_minutes=120,
        target_department="Restaurante",
    )
    assert applied.get("promotion_applied") is True
    assert operational_request_service.authorize_by_grant_with_scope(
        user="qualquer",
        route_key="restaurant.restaurant_tables",
        department="Restaurante",
        role="colaborador",
    ) is True


def test_promocao_tem_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(operational_request_service, "REQUESTS_FILE", str(tmp_path / "authz_requests.json"))
    created = operational_request_service.create_request(
        requester_user="restx",
        requester_role="supervisor",
        requester_department="Restaurante",
        requester_class="supervisor",
        route_key="restaurant.restaurant_tables",
        endpoint="restaurant.restaurant_tables",
        http_method="GET",
        module_key="restaurant",
        sensitivity="operacional_sensivel",
        reason="base",
    )
    operational_request_service.decide_request(
        request_id=created["id"],
        approver_user="admin1",
        approver_role="admin",
        decision="approve_role_permanent",
        decision_reason="base",
        target_role="supervisor",
        suggestion_used=True,
        suggested_scope="role",
        suggested_duration="permanent",
        suggested_duration_value=0,
    )
    for idx in range(9):
        another = operational_request_service.create_request(
            requester_user=f"restz{idx}",
            requester_role="supervisor",
            requester_department="Restaurante",
            requester_class="supervisor",
            route_key="restaurant.restaurant_tables",
            endpoint="restaurant.restaurant_tables",
            http_method="GET",
            module_key="restaurant",
            sensitivity="operacional_sensivel",
            reason="hist",
        )
        operational_request_service.decide_request(
            request_id=another["id"],
            approver_user="admin1",
            approver_role="admin",
            decision="approve_role_permanent",
            decision_reason="hist",
            target_role="supervisor",
            suggestion_used=True,
            suggested_scope="role",
            suggested_duration="permanent",
            suggested_duration_value=0,
        )
    candidate = operational_request_service.list_promotion_candidates(limit=20)[0]
    rule = operational_request_service.apply_promotion_candidate(
        permission_key=str(candidate.get("permission_key") or ""),
        module=str(candidate.get("module") or ""),
        promoted_by="admin1",
        promotion_scope="role",
        promotion_duration="permanent",
        target_role="supervisor",
    )
    rolled = operational_request_service.rollback_promoted_rule(rule_id=str(rule.get("id") or ""), revoked_by="admin1")
    assert rolled.get("active") is False
    reactivated = operational_request_service.reactivate_promoted_rule(
        rule_id=str(rule.get("id") or ""),
        reactivated_by="admin1",
        duration_minutes=90,
    )
    assert reactivated.get("active") is True


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


def test_admin_permissions_denied_payload_padronizado():
    app = _make_test_app()
    with app.test_request_context("/admin/system/permissions", method="GET", headers={"Accept": "application/json"}):
        session.clear()
        session.update({"user": "oper7", "role": "colaborador", "department": "Serviço"})
        response, status = admin_routes.admin_system_permissions.__wrapped__()
    assert status == 403
    body = response.get_json()
    assert body["authorization_required"] is True
    assert body["authorization_request_available"] is True
    assert body["authorization_request"]["route_key"] == "admin.admin_system_permissions"


def test_authz_policy_reception_rooms_sem_scope_obrigatorio():
    policy_file = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(policy_file.read_text(encoding="utf-8"))
    policies = payload.get("policies", [])
    by_endpoint = {str(item.get("endpoint")): item for item in policies if isinstance(item, dict)}
    reception_policy = by_endpoint.get("reception.reception_rooms")
    assert isinstance(reception_policy, dict)
    scope = reception_policy.get("scope", {})
    assert scope.get("scopes_any", []) == []
    assert scope.get("scopes_all", []) == []
    service_click = by_endpoint.get("main.service_click")
    assert isinstance(service_click, dict)
    kitchen_data = by_endpoint.get("kitchen.kitchen_breakfast_kds_data")
    assert isinstance(kitchen_data, dict)
    kitchen_scope = kitchen_data.get("scope", {})
    assert kitchen_scope.get("scopes_any", []) == []
    assert kitchen_scope.get("scopes_all", []) == []


def test_policy_registry_usa_fallback_embutido_quando_arquivo_padrao_nao_existe(tmp_path, monkeypatch):
    missing_policy = tmp_path / "missing" / "policies_v1.json"
    missing_public = tmp_path / "missing" / "public_endpoints_v1.json"
    monkeypatch.setattr(policy_registry, "DEFAULT_POLICY_FILE", missing_policy)
    monkeypatch.setattr(policy_registry, "DEFAULT_PUBLIC_FILE", missing_public)
    fallback_policy = Path(policy_registry.__file__).resolve().parent / "defaults" / "policies_v1.json"
    fallback_public = Path(policy_registry.__file__).resolve().parent / "defaults" / "public_endpoints_v1.json"
    monkeypatch.setattr(policy_registry, "FALLBACK_POLICY_FILE", fallback_policy)
    monkeypatch.setattr(policy_registry, "FALLBACK_PUBLIC_FILE", fallback_public)
    registry = policy_registry.PolicyRegistry.from_files(policy_file=missing_policy, public_file=missing_public)
    assert registry.get_policy("restaurant.get_paused_products") is not None
    assert registry.is_public_endpoint("menu.get_public_paused_products") is True
