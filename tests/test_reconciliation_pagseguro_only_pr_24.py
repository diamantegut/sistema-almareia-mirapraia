from pathlib import Path

from flask import Flask, session

from app.blueprints.finance import routes as finance_routes


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/admin/reconciliation", endpoint="finance.finance_reconciliation", view_func=lambda: "reconciliation")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _set_non_admin():
    session.clear()
    session.update({"user": "sup", "role": "supervisor"})


def _template_text(name):
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "templates" / name).read_text(encoding="utf-8")


def test_reconciliation_template_has_no_rede_dependency():
    html = _template_text("finance_reconciliation.html")
    assert "Sincronizar Rede" not in html
    assert 'value="rede"' not in html
    assert "#cfg-rede" not in html
    assert "finance_reconciliation_edit_account" in html


def test_reconciliation_screen_is_admin_only():
    app = _make_test_app()
    with app.test_request_context("/admin/reconciliation", method="GET"):
        _set_non_admin()
        response = finance_routes.finance_reconciliation.__wrapped__()
    assert response.status_code == 302


def test_reconciliation_route_exposes_pagseguro_accounts_with_health(monkeypatch):
    app = _make_test_app()
    captured = {}

    monkeypatch.setattr(
        finance_routes,
        "load_card_settings",
        lambda: {
            "pagseguro": [
                {
                    "alias": "Matriz",
                    "email": "matriz@mirapraia.com",
                    "token": "ABCDEFGHIJKLMNOP",
                    "environment": "production",
                    "health_status": "ok",
                    "last_test_at": "17/03/2026 10:00:00",
                    "last_error": "",
                }
            ]
        },
    )

    def _fake_render(template, **kwargs):
        captured["template"] = template
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(finance_routes, "render_template", _fake_render)
    with app.test_request_context("/admin/reconciliation", method="GET"):
        _set_admin()
        out = finance_routes.finance_reconciliation.__wrapped__()
    assert out == "ok"
    accounts = captured["kwargs"]["pagseguro_accounts"]
    assert len(accounts) == 1
    assert accounts[0]["alias"] == "Matriz"
    assert accounts[0]["status"] == "ok"
    assert accounts[0]["token_masked"].startswith("ABCD")
    assert accounts[0]["token_masked"].endswith("MNOP")


def test_reconciliation_sync_rejects_non_pagseguro_provider():
    app = _make_test_app()
    with app.test_request_context(
        "/admin/reconciliation/sync",
        method="POST",
        data={"provider": "rede", "start_date": "2026-03-01", "end_date": "2026-03-02"},
    ):
        _set_admin()
        response = finance_routes.finance_reconciliation_sync.__wrapped__()
    assert response.status_code == 302


def test_health_check_success_updates_account_and_audits(monkeypatch):
    app = _make_test_app()
    state = {
        "pagseguro": [
            {"alias": "Matriz", "email": "matriz@mirapraia.com", "token": "TOK123456", "environment": "production"}
        ]
    }
    audits = []
    monkeypatch.setattr(finance_routes, "load_card_settings", lambda: state)
    monkeypatch.setattr(finance_routes, "save_card_settings", lambda new_state: state.update(new_state))
    monkeypatch.setattr(
        finance_routes,
        "_check_pagseguro_account_health",
        lambda acc: {"status": "ok", "tested_at": "17/03/2026 10:10:00", "error_message": "", "http_status": 200},
    )
    monkeypatch.setattr(finance_routes, "append_reconciliation_audit", lambda entry: audits.append(entry))

    with app.test_request_context("/admin/reconciliation/health-check", method="POST"):
        _set_admin()
        response = finance_routes.finance_reconciliation_health_check.__wrapped__()
    assert response.status_code == 302
    assert state["pagseguro"][0]["health_status"] == "ok"
    assert state["pagseguro"][0]["last_http_status"] == 200
    assert len(audits) == 1
    assert audits[0]["source"] == "health_check"


def test_health_check_failure_does_not_break_and_stores_error(monkeypatch):
    app = _make_test_app()
    state = {
        "pagseguro": [
            {"alias": "Filial", "email": "filial@mirapraia.com", "token": "XYZTOKEN123", "environment": "sandbox"}
        ]
    }
    monkeypatch.setattr(finance_routes, "load_card_settings", lambda: state)
    monkeypatch.setattr(finance_routes, "save_card_settings", lambda new_state: state.update(new_state))
    monkeypatch.setattr(
        finance_routes,
        "_check_pagseguro_account_health",
        lambda acc: {"status": "error", "tested_at": "17/03/2026 11:00:00", "error_message": "Falha de autorização na API PagSeguro (HTTP 401).", "http_status": 401},
    )
    monkeypatch.setattr(finance_routes, "append_reconciliation_audit", lambda entry: None)

    with app.test_request_context("/admin/reconciliation/health-check", method="POST", data={"index": "0"}):
        _set_admin()
        response = finance_routes.finance_reconciliation_health_check.__wrapped__()
        flashes = session.get("_flashes") or []
    assert response.status_code == 302
    assert state["pagseguro"][0]["health_status"] == "error"
    assert "autorização" in state["pagseguro"][0]["last_error"].lower()
    messages = [msg for _, msg in flashes]
    assert any("Health check finalizado" in m for m in messages)
    assert any("Falha PagSeguro - Filial" in m for m in messages)


def test_update_pagseguro_account_keeps_token_when_blank_and_resets_health(monkeypatch):
    app = _make_test_app()
    state = {
        "pagseguro": [
            {
                "alias": "Conta antiga",
                "email": "old@mirapraia.com",
                "token": "TOKEN_OLD",
                "environment": "production",
                "health_status": "error",
                "last_error": "Falha anterior",
                "last_test_at": "17/03/2026 10:00:00",
                "last_http_status": 401,
            }
        ]
    }
    monkeypatch.setattr(finance_routes, "load_card_settings", lambda: state)
    monkeypatch.setattr(finance_routes, "save_card_settings", lambda new_state: state.update(new_state))
    with app.test_request_context(
        "/admin/reconciliation/account/update",
        method="POST",
        data={
            "provider": "pagseguro",
            "index": "0",
            "alias": "Conta nova",
            "ps_email": "new@mirapraia.com",
            "ps_environment": "sandbox",
            "ps_token": "",
        },
    ):
        _set_admin()
        response = finance_routes.finance_reconciliation_update_account.__wrapped__()
    assert response.status_code == 302
    updated = state["pagseguro"][0]
    assert updated["alias"] == "Conta nova"
    assert updated["email"] == "new@mirapraia.com"
    assert updated["token"] == "TOKEN_OLD"
    assert updated["sandbox"] is True
    assert updated["health_status"] == "not_tested"
    assert updated["last_error"] == ""


def test_update_pagseguro_account_rejects_non_admin():
    app = _make_test_app()
    with app.test_request_context(
        "/admin/reconciliation/account/update",
        method="POST",
        data={"provider": "pagseguro", "index": "0", "alias": "A", "ps_email": "a@a.com", "ps_environment": "production"},
    ):
        _set_non_admin()
        response = finance_routes.finance_reconciliation_update_account.__wrapped__()
    assert response.status_code == 302


def test_edit_pagseguro_account_route_renders(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes,
        "load_card_settings",
        lambda: {"pagseguro": [{"alias": "Conta A", "email": "a@mirapraia.com", "token": "TOK", "sandbox": False}]},
    )
    monkeypatch.setattr(finance_routes, "render_template", lambda *args, **kwargs: "ok")
    with app.test_request_context("/admin/reconciliation/account/edit/0", method="GET"):
        _set_admin()
        response = finance_routes.finance_reconciliation_edit_account.__wrapped__(0)
    assert response == "ok"
