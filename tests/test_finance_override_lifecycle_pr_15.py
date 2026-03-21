import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.authz.compatibility_adapter import build_grant_from_session
from app.services.authz.override_service import OVERRIDE_APPROVED, OVERRIDE_DENIED, OVERRIDE_EXPIRED, OVERRIDE_PENDING, OverrideService, OverrideServiceError
from app.services.authz.permission_engine import evaluate
from app.services.authz.policy_registry import PolicyRegistry
from app.services.authz.runtime_flags import RuntimeFlags


CRITICAL_ENDPOINTS = [
    ("finance.close_staff_month", "POST", "gerente", "gerente"),
    ("finance.finance_commission_delete", "POST", "gerente", "gerente"),
    ("finance.finance_commission_approve", "POST", "admin", "admin"),
]


def _policy_by_endpoint():
    path = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("endpoint")): item for item in payload.get("policies", []) if isinstance(item, dict)}


def _grant_for_role(role: str, registry: PolicyRegistry):
    profile = {
        "version": 2,
        "areas": {"financeiro": {"all": True, "pages": {}}},
        "level_pages": [],
    }
    permissions = ["administracao_sistema"] if role == "admin" else ["financeiro"]
    return build_grant_from_session(
        {
            "user": f"{role}_u",
            "role": role,
            "department": "Financeiro",
            "permissions": permissions,
            "permissions_v2": profile,
        },
        policy_registry=registry,
    )


def _request_context(endpoint: str, method: str):
    return {
        "endpoint": endpoint,
        "method": method,
        "action": method,
        "authenticated": True,
        "executor_user": "executor_finance",
        "request_id": f"req_{endpoint.replace('.', '_')}",
    }


def test_finance_override_policy_contract_for_critical_endpoints():
    by = _policy_by_endpoint()
    for endpoint, method, minimum_role, approver_minimum_role in CRITICAL_ENDPOINTS:
        item = by.get(endpoint)
        assert isinstance(item, dict)
        assert item.get("minimum_role") == minimum_role
        action = item.get("action", {})
        assert action.get("required") is True
        assert action.get("name_by_method", {}).get(method) == f"action.{endpoint}.{method.lower()}"
        override = item.get("override", {})
        assert override.get("required") is True
        assert override.get("approver_minimum_role") == approver_minimum_role
        assert int(override.get("ttl_seconds")) == 300
        assert override.get("reason_required") is True


def test_finance_override_requires_override_without_approval():
    registry = PolicyRegistry.from_files()
    flags = RuntimeFlags(authz_mode="enforce")
    for endpoint, method, role, _approver in CRITICAL_ENDPOINTS:
        grant = _grant_for_role(role, registry)
        decision = evaluate(_request_context(endpoint, method), registry.get_policy(endpoint), grant, flags)
        assert decision.decision == "REQUIRE_OVERRIDE"
        assert decision.reason_code == "AUTHZ_REQUIRE_OVERRIDE"


def test_finance_override_lifecycle_approve_then_expire():
    registry = PolicyRegistry.from_files()
    flags = RuntimeFlags(authz_mode="enforce")
    audit_events = []
    service = OverrideService(sink=lambda event: audit_events.append(event))
    for endpoint, method, role, approver_minimum_role in CRITICAL_ENDPOINTS:
        grant = _grant_for_role(role, registry)
        context = _request_context(endpoint, method)
        decision = evaluate(context, registry.get_policy(endpoint), grant, flags)
        record = service.create_from_engine_decision(
            decision=decision,
            request_context=context,
            executor_user="executor_finance",
            request_reason="janela operacional",
        )
        assert record.status == OVERRIDE_PENDING
        approver_role = "admin" if approver_minimum_role == "admin" else "gerente"
        approved = service.approve_override(
            override_id=record.override_id,
            approver_user="manager_override",
            approver_role=approver_role,
            reason="aprovação controlada",
        )
        assert approved.status == OVERRIDE_APPROVED
        allow_decision = evaluate(
            {**context, "override_approved": True, "override_age_seconds": 120},
            registry.get_policy(endpoint),
            grant,
            flags,
        )
        assert allow_decision.decision == "ALLOW"
        expired_decision = evaluate(
            {**context, "override_approved": True, "override_age_seconds": 301},
            registry.get_policy(endpoint),
            grant,
            flags,
        )
        assert expired_decision.decision == "REQUIRE_OVERRIDE"
        assert expired_decision.reason_code == "AUTHZ_REQUIRE_OVERRIDE"
    assert any(event.get("event_type") == "authz_override" and event.get("result") == OVERRIDE_APPROVED for event in audit_events)


def test_finance_commission_approve_override_rejects_gerente_and_accepts_admin():
    registry = PolicyRegistry.from_files()
    flags = RuntimeFlags(authz_mode="enforce")
    service = OverrideService(sink=lambda event: None)
    endpoint = "finance.finance_commission_approve"
    method = "POST"
    grant = _grant_for_role("admin", registry)
    context = _request_context(endpoint, method)
    decision = evaluate(context, registry.get_policy(endpoint), grant, flags)
    record = service.create_from_engine_decision(
        decision=decision,
        request_context=context,
        executor_user="executor_finance",
        request_reason="aprovação final mensal",
    )
    with pytest.raises(OverrideServiceError):
        service.approve_override(
            override_id=record.override_id,
            approver_user="manager_override",
            approver_role="gerente",
            reason="tentativa de aprovação",
        )
    approved = service.approve_override(
        override_id=record.override_id,
        approver_user="admin_override",
        approver_role="admin",
        reason="aprovação válida",
    )
    assert approved.status == OVERRIDE_APPROVED


def test_finance_override_expiration_and_denial_audit():
    audit_events = []
    service = OverrideService(sink=lambda event: audit_events.append(event))
    created_at = datetime.now(tz=timezone.utc)
    record = service.create_override_request(
        request_id="req_expire",
        endpoint="finance.close_staff_month",
        action="POST",
        executor_user="executor_finance",
        policy_version="2026.03",
        policy_hash="a81f29d",
        approver_minimum_role="gerente",
        ttl_seconds=30,
        request_reason="fechamento emergencial",
        reason_required=True,
        created_at=created_at.isoformat().replace("+00:00", "Z"),
    )
    with pytest.raises(OverrideServiceError):
        service.approve_override(
            override_id=record.override_id,
            approver_user="manager_override",
            approver_role="gerente",
            reason="aprovando tarde",
            at_time=(created_at + timedelta(seconds=31)).isoformat().replace("+00:00", "Z"),
        )
    assert service.get(record.override_id).status == OVERRIDE_EXPIRED

    denied = service.create_override_request(
        request_id="req_deny",
        endpoint="finance.finance_commission_delete",
        action="POST",
        executor_user="executor_finance",
        policy_version="2026.03",
        policy_hash="a81f29d",
        approver_minimum_role="gerente",
        ttl_seconds=300,
        request_reason="pedido sem respaldo",
        reason_required=True,
    )
    denied_record = service.deny_override(
        override_id=denied.override_id,
        approver_user="manager_override",
        reason="sem justificativa financeira",
    )
    assert denied_record.status == OVERRIDE_DENIED
    override_events = [event for event in audit_events if event.get("event_type") == "authz_override"]
    assert any(event.get("result") == OVERRIDE_EXPIRED for event in override_events)
    assert any(event.get("result") == OVERRIDE_DENIED for event in override_events)
    required_fields = {"endpoint", "action", "executor_user", "approver_user", "reason", "result", "timestamp", "request_id", "policy_version", "policy_hash", "ttl_seconds"}
    assert all(required_fields.issubset(set(event.keys())) for event in override_events)
