import json
from pathlib import Path

from app import create_app


HUB_ROUTES = [
    "/admin/system/permissions",
    "/admin/system/permissions/requests",
    "/admin/system/permissions/simulator",
    "/admin/system/permissions/roles",
    "/admin/system/permissions/users",
    "/admin/system/permissions/overrides",
    "/admin/system/permissions/audit",
    "/admin/system/permissions/pilot",
    "/admin/system/permissions/heatmap",
    "/admin/system/permissions/coverage",
]


def _client_with_profile(role: str, *, permissions=None):
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = f"{role}_user"
        sess["role"] = role
        sess["department"] = "Administracao"
        sess["permissions"] = permissions if isinstance(permissions, list) else []
    return client


def test_admin_permissions_hub_allows_admin_and_administracao_sistema():
    for role in ("admin", "administracao_sistema"):
        client = _client_with_profile(role, permissions=["administracao_sistema"])
        for route in HUB_ROUTES:
            response = client.get(route, follow_redirects=False)
            assert response.status_code in {200, 302}, f"{role} bloqueado em {route}: {response.status_code}"


def test_admin_permissions_hub_denies_non_admin_profiles():
    for role in ("gerente", "supervisor", "colaborador"):
        client = _client_with_profile(role, permissions=[])
        for route in HUB_ROUTES:
            response = client.get(route, follow_redirects=False)
            assert response.status_code in {403, 302}, f"{role} não foi bloqueado em {route}: {response.status_code}"


def test_admin_permissions_hub_policy_entries_present():
    policy_path = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    policies = payload.get("policies", [])
    by_endpoint = {str(item.get("endpoint")): item for item in policies if isinstance(item, dict)}
    expected = {
        "admin.admin_system_permissions",
        "admin.admin_system_permissions_requests",
        "admin.admin_system_permissions_simulator",
        "admin.admin_system_permissions_roles",
        "admin.admin_system_permissions_users",
        "admin.admin_system_permissions_overrides",
        "admin.admin_system_permissions_audit",
        "admin.admin_system_permissions_pilot",
        "admin.admin_system_permissions_heatmap",
        "admin.admin_system_permissions_coverage",
    }
    missing = [name for name in expected if name not in by_endpoint]
    assert missing == []
