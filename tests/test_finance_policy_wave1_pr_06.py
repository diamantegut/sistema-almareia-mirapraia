import json
from pathlib import Path

from flask import Flask, session

from app.blueprints.finance import routes as finance_routes
from app.services.authz.compatibility_adapter import build_grant_from_session
from app.services.authz.compatibility_adapter import build_grant_from_user
from app.services.authz.permission_engine import evaluate
from app.services.authz.policy_registry import PolicyRegistry
from app.services.authz.runtime_flags import RuntimeFlags
from app.services.data_service import load_department_permissions, load_users


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/service/<service_id>", endpoint="main.service_page", view_func=lambda service_id: f"service:{service_id}")
    app.add_url_rule("/finance/commission", endpoint="finance.finance_commission", view_func=lambda: "commission")
    app.add_url_rule("/finance/commission/<cycle_id>", endpoint="finance.finance_commission_detail", view_func=lambda cycle_id: f"detail:{cycle_id}")
    return app


def _set_profile(role, user="u1", permissions=None):
    session.clear()
    session.update(
        {
            "user": user,
            "role": role,
            "department": "Financeiro",
            "permissions": permissions if isinstance(permissions, list) else [],
        }
    )


def test_finance_wave1_policy_entries_and_minimum_roles():
    policy_path = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    policies = payload.get("policies", [])
    by_endpoint = {str(item.get("endpoint")): item for item in policies if isinstance(item, dict)}
    expected = {
        "finance.finance_cashier_reports": ("gerente", 3),
        "finance.finance_balances": ("admin", 4),
        "finance.accounts_payable": ("gerente", 3),
        "finance.close_staff_month": ("gerente", 3),
        "finance.finance_commission": ("gerente", 3),
        "finance.finance_commission_new": ("gerente", 3),
        "finance.finance_commission_detail": ("gerente", 3),
        "finance.finance_commission_refresh_scores": ("gerente", 3),
        "finance.finance_commission_update_employee": ("gerente", 3),
        "finance.finance_commission_calculate": ("gerente", 3),
        "finance.finance_commission_approve": ("admin", 4),
        "finance.finance_commission_delete": ("gerente", 3),
    }
    missing = [key for key in expected if key not in by_endpoint]
    assert missing == []
    for endpoint, (role, level) in expected.items():
        item = by_endpoint[endpoint]
        assert item.get("minimum_role") == role
        assert int(item.get("minimum_role_level")) == level


def test_finance_wave1_manual_guards_remain_phase_a():
    source = Path(finance_routes.__file__).read_text(encoding="utf-8")
    assert "def accounts_payable()" in source
    assert "if session.get('role') not in ['admin', 'gerente', 'financeiro']" in source
    assert "def close_staff_month()" in source
    assert "if session.get('role') not in ['admin', 'gerente']" in source
    assert "def finance_commission_approve(cycle_id):" in source
    assert "if session.get('role') != 'admin':" in source


def test_finance_wave1_access_matrix_accounts_payable_and_close_month(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "load_payables", lambda: [])
    monkeypatch.setattr(finance_routes, "load_suppliers", lambda: [])
    monkeypatch.setattr(finance_routes, "render_template", lambda *args, **kwargs: "ok")
    with app.test_request_context("/finance/accounts_payable", method="GET"):
        _set_profile("financeiro", permissions=["financeiro"])
        response_fin = finance_routes.accounts_payable.__wrapped__()
    assert response_fin == "ok"
    with app.test_request_context("/finance/accounts_payable", method="GET"):
        _set_profile("colaborador")
        response_col = finance_routes.accounts_payable.__wrapped__()
    assert getattr(response_col, "status_code", None) == 302

    monkeypatch.setattr(finance_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(finance_routes, "_load_cashier_sessions", lambda: [])
    monkeypatch.setattr(finance_routes.CashierService, "get_active_session", staticmethod(lambda: None))
    with app.test_request_context("/finance/close_staff_month", method="POST"):
        _set_profile("gerente")
        response_manager = finance_routes.close_staff_month.__wrapped__()
    assert getattr(response_manager, "status_code", None) == 302
    with app.test_request_context("/finance/close_staff_month", method="POST"):
        _set_profile("colaborador")
        response_user = finance_routes.close_staff_month.__wrapped__()
    assert getattr(response_user, "status_code", None) == 302


def test_finance_wave1b_scope_matrix_by_role():
    profile_finance_all = {
        "version": 2,
        "areas": {"financeiro": {"all": True, "pages": {}}},
        "level_pages": [],
    }
    admin_grant = build_grant_from_session(
        {
            "user": "admin_u",
            "role": "admin",
            "department": "Admin",
            "permissions": ["administracao_sistema"],
            "permissions_v2": profile_finance_all,
        }
    )
    manager_grant = build_grant_from_session(
        {
            "user": "ger_u",
            "role": "gerente",
            "department": "Financeiro",
            "permissions": ["financeiro"],
            "permissions_v2": profile_finance_all,
        }
    )
    finance_grant = build_grant_from_session(
        {
            "user": "fin_u",
            "role": "financeiro",
            "department": "Financeiro",
            "permissions": ["financeiro"],
            "permissions_v2": profile_finance_all,
        }
    )
    common_grant = build_grant_from_session(
        {
            "user": "col_u",
            "role": "colaborador",
            "department": "Serviço",
            "permissions": [],
            "permissions_v2": {"version": 2, "areas": {}, "level_pages": []},
        }
    )
    assert "scope.department" in admin_grant.grants.scopes
    assert "scope.finance.read" in admin_grant.grants.scopes
    assert "scope.finance.write" in admin_grant.grants.scopes
    assert "scope.finance.approve" in admin_grant.grants.scopes
    assert "scope.department" in manager_grant.grants.scopes
    assert "scope.finance.read" in manager_grant.grants.scopes
    assert "scope.finance.write" in manager_grant.grants.scopes
    assert "scope.finance.approve" not in manager_grant.grants.scopes
    assert "scope.department" in finance_grant.grants.scopes
    assert "scope.finance.read" in finance_grant.grants.scopes
    assert "scope.finance.write" in finance_grant.grants.scopes
    assert "scope.finance.read" not in common_grant.grants.scopes
    assert "scope.finance.write" not in common_grant.grants.scopes


def test_finance_wave1b_no_missing_scope_for_critical_endpoints():
    registry = PolicyRegistry.from_files()
    flags = RuntimeFlags(authz_mode="enforce")
    profile_finance_all = {
        "version": 2,
        "areas": {"financeiro": {"all": True, "pages": {}}},
        "level_pages": [],
    }
    admin_grant = build_grant_from_session(
        {
            "user": "admin_u",
            "role": "admin",
            "department": "Admin",
            "permissions": ["administracao_sistema"],
            "permissions_v2": profile_finance_all,
        },
        policy_registry=registry,
    )
    manager_grant = build_grant_from_session(
        {
            "user": "ger_u",
            "role": "gerente",
            "department": "Financeiro",
            "permissions": ["financeiro"],
            "permissions_v2": profile_finance_all,
        },
        policy_registry=registry,
    )
    scenarios = [
        ("finance.finance_balances", "GET", admin_grant),
        ("finance.finance_cashier_reports", "GET", manager_grant),
        ("finance.accounts_payable", "GET", manager_grant),
    ]
    for endpoint, method, grant in scenarios:
        policy = registry.get_policy(endpoint)
        decision = evaluate(
            {"endpoint": endpoint, "method": method, "authenticated": True},
            policy,
            grant,
            flags,
        )
        assert decision.reason_code != "AUTHZ_DENY_MISSING_SCOPE"


def test_finance_wave1c_no_missing_action_for_post_critical_endpoints():
    registry = PolicyRegistry.from_files()
    flags = RuntimeFlags(authz_mode="enforce")
    profile_finance_all = {
        "version": 2,
        "areas": {"financeiro": {"all": True, "pages": {}}},
        "level_pages": [],
    }
    admin_grant = build_grant_from_session(
        {
            "user": "admin_u",
            "role": "admin",
            "department": "Admin",
            "permissions": ["administracao_sistema"],
            "permissions_v2": profile_finance_all,
        },
        policy_registry=registry,
    )
    manager_grant = build_grant_from_session(
        {
            "user": "ger_u",
            "role": "gerente",
            "department": "Financeiro",
            "permissions": ["financeiro"],
            "permissions_v2": profile_finance_all,
        },
        policy_registry=registry,
    )
    post_scenarios = [
        ("finance.close_staff_month", manager_grant),
        ("finance.finance_commission_new", manager_grant),
        ("finance.finance_commission_refresh_scores", manager_grant),
        ("finance.finance_commission_update_employee", manager_grant),
        ("finance.finance_commission_calculate", manager_grant),
        ("finance.finance_commission_delete", manager_grant),
        ("finance.finance_commission_approve", admin_grant),
    ]
    for endpoint, grant in post_scenarios:
        policy = registry.get_policy(endpoint)
        decision = evaluate(
            {"endpoint": endpoint, "method": "POST", "authenticated": True},
            policy,
            grant,
            flags,
        )
        assert decision.reason_code != "AUTHZ_DENY_MISSING_ACTION"


def test_finance_wave1b_real_users_have_finance_scopes():
    users = load_users()
    departments = load_department_permissions()
    registry = PolicyRegistry.from_files()
    admin_grant = build_grant_from_user("Angelo", users, departments, policy_registry=registry)
    manager_grant = build_grant_from_user("cicera", users, departments, policy_registry=registry)
    assert "scope.department" in admin_grant.grants.scopes
    assert "scope.finance.read" in admin_grant.grants.scopes
    assert "scope.finance.write" in admin_grant.grants.scopes
    assert "scope.department" in manager_grant.grants.scopes
    assert "scope.finance.read" in manager_grant.grants.scopes
