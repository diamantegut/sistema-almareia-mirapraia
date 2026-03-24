from pathlib import Path

import pytest

from app import create_app
from app.blueprints import stock as stock_module
from app.blueprints.restaurant.routes import resolve_stock_product_for_order_item
from app.services import data_service
from app.services import stock_nfe_repository_service as repo


def _client_with_login():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "tester"
        sess["role"] = "admin"
        sess["department"] = "Estoque"
        sess["permissions"] = ["estoque"]
    return client


def test_stock_products_template_has_new_operational_sections():
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "stock_products.html"
    content = template_path.read_text(encoding="utf-8")
    assert "Sem fornecedor vinculado" in content
    assert "Sem histórico de compra" in content
    assert "Sem conversão NF-e" in content
    assert "Nome padrão (compatibilidade)" in content
    assert "overflow-x: hidden" not in content
    assert "Fornecedor recente" in content
    assert "Último fornecimento</th>" not in content
    assert "table-layout: auto" in content
    assert "table-actions" in content
    assert "flex-wrap: nowrap" in content
    assert "col-actions { width: 10%; min-width: 8.8rem; }" in content


def test_menu_lookup_keeps_compatibility_with_extended_product_shape():
    products_db = [
        {
            "id": "12",
            "name": "Arroz Branco",
            "department": "Geral",
            "unit": "Kilogramas",
            "price": 8.9,
            "nome_padrao": "Arroz Branco",
            "unidade_base": "Kilogramas",
            "ativo": True,
            "supplier_profiles": [{"supplier_id": "SUP1"}],
        }
    ]
    menu_items_db = [{"id": "501", "name": "Arroz Branco", "stock_product_id": "12", "recipe": []}]
    result = resolve_stock_product_for_order_item({"product_id": "501", "name": "Arroz Branco"}, menu_items_db, products_db)
    assert result is not None
    assert str(result.get("id")) == "12"


def test_item_bind_enriches_product_supplier_extension_without_breaking_id(tmp_path, monkeypatch):
    repo_file = tmp_path / "nfe_repo.json"
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(repo_file))

    unique_name = f"Arroz Branco PR27 {Path(repo_file).stem}"
    client = _client_with_login()
    create_resp = client.post(
        "/stock/products",
        data={
            "name": unique_name,
            "department": "Geral",
            "unit": "Kilogramas",
            "price": "8.5",
            "category": "Secos",
            "min_stock": "5",
            "suppliers[]": ["Fornecedor A"],
        },
        follow_redirects=False,
    )
    assert create_resp.status_code in {302, 303}

    persisted_products = data_service.load_products()
    target_product = next((p for p in persisted_products if str(p.get("name") or "") == unique_name), None)
    assert target_product is not None
    target_product_id = str(target_product.get("id") or "")
    assert target_product_id

    repo.ingest_documents(
        documents=[
            {
                "nsu": "700",
                "access_key": "26260305429222000148550010012294091588828693",
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 20.0,
                "emitente": {"nome": "Fornecedor A", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [
                    {
                        "codigo": "SKU-ARROZ",
                        "descricao": "Arroz Branco Tipo 1",
                        "unidade": "UN",
                        "quantidade": 2,
                        "valor_unitario": 10.0,
                        "valor_total": 20.0,
                    }
                ],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-bind-enrich",
    )

    resp = client.post(
        "/stock/nfe/repository/item-bind",
        json={
            "access_key": "26260305429222000148550010012294091588828693",
            "item_index": 0,
            "supplier_id": "SUP1",
            "product_id": target_product_id,
            "supplier_product_code": "SKU-ARROZ",
            "supplier_product_name": "Fornecedor A",
            "unidade_fornecedor": "UN",
            "unidade_estoque": "Kilogramas",
            "fator_conversao": 12,
            "is_preferred": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    assert payload.get("success") is True

    products = data_service.load_products()
    product = next((p for p in products if str(p.get("id")) == target_product_id), None)
    assert product is not None
    assert str(product.get("id")) == target_product_id
    profiles = product.get("supplier_profiles") or []
    assert len(profiles) >= 1
    assert any(str(row.get("supplier_id") or "") == "SUP1" for row in profiles if isinstance(row, dict))
    assert str(product.get("ultimo_fornecedor") or "") in {"Fornecedor A", "Arroz Branco Tipo 1"}


def test_stock_products_keeps_legacy_shape_products_visible(monkeypatch):
    monkeypatch.setattr(
        stock_module,
        "load_products",
        lambda: [{"id": "99", "nome": "Produto Legado", "department": "Geral", "unidade": "Unidades", "price": 4.5, "min_stock": 1}],
    )
    monkeypatch.setattr(stock_module, "get_product_balances_by_id", lambda products: {})
    monkeypatch.setattr(stock_module, "load_suppliers", lambda: [])
    client = _client_with_login()
    resp = client.get("/stock/products")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Produto Legado" in html
    assert "Nenhum produto encontrado na lista." not in html


def test_load_products_prioritizes_canonical_when_non_empty(tmp_path, monkeypatch):
    canonical = tmp_path / "products_canonical.json"
    legacy = tmp_path / "products_legacy.json"
    canonical.write_text('[{"id":"1","name":"Canônico","department":"Geral","unit":"Unidades","price":1}]', encoding="utf-8")
    legacy.write_text('[{"id":"2","name":"Legado","department":"Geral","unit":"Unidades","price":2}]', encoding="utf-8")
    monkeypatch.setattr(data_service, "PRODUCTS_FILE", str(canonical))
    monkeypatch.setattr(data_service, "get_legacy_root_json_path", lambda filename: str(legacy))
    products = data_service.load_products()
    assert len(products) == 1
    assert str(products[0].get("name") or "") == "Canônico"


def test_load_products_falls_back_to_legacy_when_canonical_empty(tmp_path, monkeypatch):
    canonical = tmp_path / "products_canonical_empty.json"
    legacy = tmp_path / "products_legacy_nonempty.json"
    canonical.write_text("[]", encoding="utf-8")
    legacy.write_text('[{"id":"20","name":"Legado Ativo","department":"Geral","unit":"Unidades","price":3}]', encoding="utf-8")
    monkeypatch.setattr(data_service, "PRODUCTS_FILE", str(canonical))
    monkeypatch.setattr(data_service, "get_legacy_root_json_path", lambda filename: str(legacy))
    products = data_service.load_products()
    assert len(products) == 1
    assert str(products[0].get("name") or "") == "Legado Ativo"


def test_secure_save_products_blocks_empty_overwrite_without_flag(tmp_path, monkeypatch):
    canonical = tmp_path / "products_canonical_guard.json"
    legacy = tmp_path / "products_legacy_guard.json"
    canonical.write_text('[{"id":"31","name":"Produto Protegido","department":"Geral","unit":"Unidades","price":5.0}]', encoding="utf-8")
    legacy.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(data_service, "PRODUCTS_FILE", str(canonical))
    monkeypatch.setattr(data_service, "get_legacy_root_json_path", lambda filename: str(legacy))
    with pytest.raises(ValueError):
        data_service.secure_save_products([], user_id="tester")
    current = data_service.load_products()
    assert len(current) == 1
    assert str(current[0].get("name") or "") == "Produto Protegido"
