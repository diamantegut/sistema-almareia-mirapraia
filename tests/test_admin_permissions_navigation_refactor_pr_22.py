from app import create_app


def _client_with_profile(role: str, *, runtime_env: str, permissions=None):
    app = create_app()
    app.config["TESTING"] = True
    app.config["ALMAREIA_RUNTIME_ENV"] = runtime_env
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = f"{role}_user"
        sess["role"] = role
        sess["department"] = "Administracao"
        sess["permissions"] = permissions if isinstance(permissions, list) else []
    return client


def test_permissions_access_and_redirects_work():
    client = _client_with_profile("admin", runtime_env="development", permissions=["administracao_sistema"])
    access_response = client.get("/admin/system/permissions/access", follow_redirects=False)
    assert access_response.status_code == 200
    assert "Promoções" in access_response.get_data(as_text=True)
    promotions_response = client.get("/admin/system/permissions/access?tab=promotions", follow_redirects=False)
    assert promotions_response.status_code == 200
    assert "Candidatas à promoção" in promotions_response.get_data(as_text=True)
    assert client.get("/admin/system/permissions/users", follow_redirects=False).status_code == 302
    assert "tab=users" in str(client.get("/admin/system/permissions/users", follow_redirects=False).headers.get("Location") or "")
    assert "tab=roles" in str(client.get("/admin/system/permissions/roles", follow_redirects=False).headers.get("Location") or "")
    assert "tab=overrides" in str(client.get("/admin/system/permissions/overrides", follow_redirects=False).headers.get("Location") or "")


def test_permissions_advanced_gating_between_dev_and_production():
    dev_client = _client_with_profile("admin", runtime_env="development", permissions=["administracao_sistema"])
    prod_client = _client_with_profile("admin", runtime_env="production", permissions=["administracao_sistema"])
    adv_client = _client_with_profile("admin_advanced", runtime_env="production", permissions=["administracao_sistema"])
    assert dev_client.get("/admin/system/permissions/advanced", follow_redirects=False).status_code == 200
    assert prod_client.get("/admin/system/permissions/advanced", follow_redirects=False).status_code == 404
    assert adv_client.get("/admin/system/permissions/advanced", follow_redirects=False).status_code == 200


def test_permissions_legacy_advanced_routes_redirect():
    client = _client_with_profile("admin", runtime_env="development", permissions=["administracao_sistema"])
    sim = client.get("/admin/system/permissions/simulator", follow_redirects=False)
    pilot = client.get("/admin/system/permissions/pilot", follow_redirects=False)
    coverage = client.get("/admin/system/permissions/coverage", follow_redirects=False)
    assert sim.status_code == 302
    assert "/admin/system/permissions/advanced/simulator" in str(sim.headers.get("Location") or "")
    assert pilot.status_code == 302
    assert "/admin/system/permissions/advanced/pilot" in str(pilot.headers.get("Location") or "")
    assert coverage.status_code == 302
    assert "/admin/system/permissions/advanced/coverage" in str(coverage.headers.get("Location") or "")


def test_permissions_home_has_management_kpis():
    client = _client_with_profile("admin", runtime_env="development", permissions=["administracao_sistema"])
    response = client.get("/admin/system/permissions", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Promovidas ativas" in html
    assert "Promovidas revogadas" in html
    assert "Revisar promoções" in html
