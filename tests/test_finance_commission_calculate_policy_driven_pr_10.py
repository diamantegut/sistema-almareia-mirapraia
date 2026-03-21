import json
from pathlib import Path

from app import create_app
from app.services import permission_service


def _client_with_profile(role: str, *, permissions=None):
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = f"{role}_u"
        sess["role"] = role
        sess["department"] = "Financeiro"
        sess["permissions"] = permissions if isinstance(permissions, list) else []
    return client


def test_finance_commission_calculate_no_manual_role_gate_in_route_source():
    source = Path(__file__).resolve().parents[1] / "app" / "blueprints" / "finance" / "routes.py"
    text = source.read_text(encoding="utf-8")
    marker = "def finance_commission_calculate(cycle_id):"
    assert marker in text
    start = text.index(marker)
    next_def = text.find("\ndef ", start + len(marker))
    block = text[start:] if next_def < 0 else text[start:next_def]
    assert "if session.get('role') not in ['admin', 'gerente', 'financeiro'] and 'comissao' not in session.get('permissions', []):" not in block


def test_finance_commission_calculate_policy_has_action_scope_and_role():
    policy_path = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    by_endpoint = {str(item.get("endpoint")): item for item in payload.get("policies", []) if isinstance(item, dict)}
    policy = by_endpoint.get("finance.finance_commission_calculate")
    assert isinstance(policy, dict)
    assert policy.get("minimum_role") == "gerente"
    assert int(policy.get("minimum_role_level")) == 3
    action = policy.get("action", {})
    assert action.get("required") is True
    assert action.get("name_by_method", {}).get("POST") == "action.finance.finance_commission_calculate.post"
    scope = policy.get("scope", {})
    assert "scope.finance.write" in (scope.get("scopes_any") or [])
    assert "scope.department" in (scope.get("scopes_all") or [])


def test_finance_commission_calculate_policy_driven_access_matrix(monkeypatch):
    monkeypatch.setattr(permission_service, "_pilot_enforcement_enabled", lambda area, runtime_flags: True)
    admin_client = _client_with_profile("admin", permissions=["administracao_sistema"])
    manager_client = _client_with_profile("gerente", permissions=["financeiro"])
    finance_client = _client_with_profile("financeiro", permissions=["financeiro"])
    common_client = _client_with_profile("colaborador", permissions=[])

    admin_resp = admin_client.post(
        "/finance/commission/cycle-x/calculate",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    manager_resp = manager_client.post(
        "/finance/commission/cycle-x/calculate",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    finance_resp = finance_client.post(
        "/finance/commission/cycle-x/calculate",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    common_resp = common_client.post(
        "/finance/commission/cycle-x/calculate",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert admin_resp.status_code == 302
    assert manager_resp.status_code == 302
    assert finance_resp.status_code == 403
    assert common_resp.status_code == 403

    finance_json = finance_resp.get_json() or {}
    common_json = common_resp.get_json() or {}
    assert finance_json.get("reason_code") == "AUTHZ_DENY_INSUFFICIENT_ROLE"
    assert common_json.get("reason_code") == "AUTHZ_DENY_INSUFFICIENT_ROLE"
