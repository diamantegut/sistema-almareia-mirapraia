from pathlib import Path
from flask import Flask, session

from app.blueprints.admin import routes as admin_routes
from app.services import fiscal_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def test_fiscal_pool_template_has_operational_columns_and_mobile_support():
    template_path = Path("app/templates/fiscal_pool.html")
    content = template_path.read_text(encoding="utf-8")
    assert "Conta / Referência" in content
    assert "Origem / Caixa" in content
    assert "Elegibilidade" in content
    assert "Status Fiscal" in content
    assert "d-none d-lg-table-cell" in content
    assert "Imprimir DANFE NFC-e" in content


def test_fiscal_pool_template_has_document_confirmation_modal():
    template_path = Path("app/templates/fiscal_pool.html")
    content = template_path.read_text(encoding="utf-8")
    assert "emitDocumentModal" in content
    assert "CPF ou CNPJ na nota" in content
    assert "confirmEmitWithDocument" in content
    assert "Documento obrigatório para emissão acima de R$ 999,00." in content


def test_emit_action_saves_customer_document_before_emission(monkeypatch):
    app = _make_test_app()
    entry_id = "POOL-1"
    pool = [
        {
            "id": entry_id,
            "status": "pending",
            "customer": {"name": "Cliente X"},
            "total_amount": 1200.0,
        }
    ]
    monkeypatch.setattr(admin_routes.FiscalPoolService, "_load_pool", staticmethod(lambda: pool))
    monkeypatch.setattr(admin_routes.FiscalPoolService, "save_pool", staticmethod(lambda payload: True))
    monkeypatch.setattr(
        admin_routes.FiscalPoolService,
        "get_entry",
        staticmethod(lambda target_id: next((e for e in pool if e.get("id") == target_id), None)),
    )
    monkeypatch.setattr(fiscal_service, "process_pending_emissions", lambda specific_id=None: {"success": 1, "failed": 0})
    with app.test_request_context(
        "/admin/fiscal/pool/action",
        method="POST",
        json={"action": "emit", "id": entry_id, "customer_document": "123.456.789-01"},
    ):
        _set_admin()
        response = admin_routes.fiscal_pool_action.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert pool[0]["customer_document"] == "12345678901"
    assert pool[0]["customer"]["cpf_cnpj"] == "12345678901"
