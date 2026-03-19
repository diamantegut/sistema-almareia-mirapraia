from copy import deepcopy
from flask import Flask, session

from app.blueprints.main import routes_payment


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/payment-methods", endpoint="main.payment_methods", view_func=lambda: "pm")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _set_non_admin():
    session.clear()
    session.update({"user": "operador", "role": "atendente"})


def test_payment_methods_route_requires_admin():
    app = _make_app()
    with app.test_request_context("/payment-methods", method="GET"):
        _set_non_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302


def test_payment_methods_route_renders_with_methods(monkeypatch):
    app = _make_app()
    captured = {}
    methods = [{"id": "dinheiro", "name": "Dinheiro", "available_in": ["restaurant"], "is_fiscal": False, "pagseguro_alias": ""}]
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods))
    monkeypatch.setattr(routes_payment, "load_fiscal_settings", lambda: {"integrations": [{"cnpj_emitente": "28952732000109", "provider": "plug4market"}]})
    monkeypatch.setattr(routes_payment, "render_template", lambda tpl, **kwargs: captured.update({"tpl": tpl, "kwargs": kwargs}) or "ok")
    with app.test_request_context("/payment-methods", method="GET"):
        _set_admin()
        output = routes_payment.payment_methods.__wrapped__()
    assert output == "ok"
    assert captured["tpl"] == "payment_methods.html"
    assert captured["kwargs"]["methods"][0]["name"] == "Dinheiro"


def test_add_payment_method_with_optional_pagseguro_alias(monkeypatch):
    app = _make_app()
    methods_state = []
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods_state))
    monkeypatch.setattr(routes_payment, "save_payment_methods", lambda methods: methods_state.clear() or methods_state.extend(deepcopy(methods)) or True)
    with app.test_request_context(
        "/payment-methods",
        method="POST",
        data={
            "action": "add",
            "name": "Crédito Frota",
            "available_restaurant": "on",
            "is_fiscal": "on",
            "fiscal_cnpj": "28952732000109",
            "pagseguro_alias": "Mirapraia",
        },
    ):
        _set_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302
    assert len(methods_state) == 1
    saved = methods_state[0]
    assert saved["available_in"] == ["restaurant"]
    assert saved["is_fiscal"] is True
    assert saved["fiscal_cnpj"] == "28952732000109"
    assert saved["pagseguro_alias"] == "Mirapraia"


def test_edit_payment_method_updates_flags_and_optional_alias(monkeypatch):
    app = _make_app()
    methods_state = [
        {
            "id": "creditofrota",
            "name": "Crédito Frota",
            "available_in": ["restaurant"],
            "is_fiscal": True,
            "fiscal_cnpj": "28952732000109",
            "pagseguro_alias": "Mirapraia",
        }
    ]
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods_state))
    monkeypatch.setattr(routes_payment, "save_payment_methods", lambda methods: methods_state.clear() or methods_state.extend(deepcopy(methods)) or True)
    with app.test_request_context(
        "/payment-methods",
        method="POST",
        data={
            "action": "edit",
            "id": "creditofrota",
            "name": "Crédito Frota Empresarial",
            "available_reception": "on",
            "available_reservas": "on",
            "pagseguro_alias": "",
        },
    ):
        _set_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302
    updated = methods_state[0]
    assert updated["name"] == "Crédito Frota Empresarial"
    assert sorted(updated["available_in"]) == ["reception", "reservations"]
    assert updated["is_fiscal"] is False
    assert updated["pagseguro_alias"] == ""


def test_add_payment_method_without_alias_still_works(monkeypatch):
    app = _make_app()
    methods_state = []
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods_state))
    monkeypatch.setattr(routes_payment, "save_payment_methods", lambda methods: methods_state.clear() or methods_state.extend(deepcopy(methods)) or True)
    with app.test_request_context(
        "/payment-methods",
        method="POST",
        data={
            "action": "add",
            "name": "Convênio Local",
            "available_reception": "on",
        },
    ):
        _set_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302
    assert len(methods_state) == 1
    saved = methods_state[0]
    assert saved["pagseguro_alias"] == ""


def test_payment_methods_template_has_optional_pagseguro_alias_fields():
    with open("app/templates/payment_methods.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Alias da Conta PagSeguro (Opcional)" in html
    assert "name=\"pagseguro_alias\"" in html
    assert "Não bloqueia a conciliação global" in html


def test_add_payment_method_requires_at_least_one_cashier(monkeypatch):
    app = _make_app()
    methods_state = []
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods_state))
    monkeypatch.setattr(routes_payment, "save_payment_methods", lambda methods: methods_state.clear() or methods_state.extend(deepcopy(methods)) or True)
    with app.test_request_context(
        "/payment-methods",
        method="POST",
        data={"action": "add", "name": "Sem Caixa"},
    ):
        _set_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302
    assert methods_state == []


def test_add_payment_method_fiscal_requires_cnpj(monkeypatch):
    app = _make_app()
    methods_state = []
    monkeypatch.setattr(routes_payment, "load_payment_methods", lambda: deepcopy(methods_state))
    monkeypatch.setattr(routes_payment, "save_payment_methods", lambda methods: methods_state.clear() or methods_state.extend(deepcopy(methods)) or True)
    with app.test_request_context(
        "/payment-methods",
        method="POST",
        data={"action": "add", "name": "Fiscal Sem CNPJ", "available_restaurant": "on", "is_fiscal": "on"},
    ):
        _set_admin()
        response = routes_payment.payment_methods.__wrapped__()
    assert response.status_code == 302
    assert methods_state == []
