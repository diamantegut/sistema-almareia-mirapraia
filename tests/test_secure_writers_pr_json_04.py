import json
import re
from pathlib import Path

from app.services import data_service


def test_wrappers_legados_delegam_para_secure(monkeypatch):
    calls = {"products": 0, "menu": 0, "sales": 0}

    def _products(payload, user_id="Sistema"):
        calls["products"] += 1
        return isinstance(payload, list) and user_id == "Sistema"

    def _menu(payload, user_id="Sistema"):
        calls["menu"] += 1
        return isinstance(payload, list) and user_id == "Sistema"

    def _sales(payload, user_id="Sistema"):
        calls["sales"] += 1
        return isinstance(payload, list) and user_id == "Sistema"

    monkeypatch.setattr(data_service, "secure_save_products", _products)
    monkeypatch.setattr(data_service, "secure_save_menu_items", _menu)
    monkeypatch.setattr(data_service, "secure_save_sales_history", _sales)

    assert data_service.save_products([]) is True
    assert data_service.save_menu_items([]) is True
    assert data_service.save_sales_history([]) is True
    assert calls == {"products": 1, "menu": 1, "sales": 1}


def test_writers_seguros_persistem_arquivos_escopo(monkeypatch, tmp_path):
    products_file = tmp_path / "products.json"
    menu_file = tmp_path / "menu_items.json"
    sales_file = tmp_path / "sales_history.json"
    products_file.write_text("[]", encoding="utf-8")
    menu_file.write_text("[]", encoding="utf-8")
    sales_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(data_service, "PRODUCTS_FILE", str(products_file))
    monkeypatch.setattr(data_service, "MENU_ITEMS_FILE", str(menu_file))
    monkeypatch.setattr(data_service, "SALES_HISTORY_FILE", str(sales_file))
    monkeypatch.setattr(data_service, "_backup_before_write", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(data_service.StockSecurityService, "validate_product", lambda _p: True)
    monkeypatch.setattr(data_service.StockSecurityService, "calculate_hash", lambda _p: "hash")
    monkeypatch.setattr(data_service.StockSecurityService, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.StockSecurityService, "detect_bulk_changes", lambda _o, _n: (False, ""))
    monkeypatch.setattr(data_service.StockSecurityService, "generate_diff", lambda _o, _n: {"changed": True})

    monkeypatch.setattr(data_service.MenuSecurityService, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.MenuSecurityService, "detect_bulk_changes", lambda _o, _n: (False, ""))

    product_payload = [{"id": "P1", "name": "Produto 1", "price": 10}]
    menu_payload = [{"id": "M1", "name": "Prato 1", "price": 20}]
    sales_payload = [{"id": "S1", "total": 30}]

    assert data_service.save_products(product_payload) is True
    assert data_service.save_menu_items(menu_payload) is True
    assert data_service.save_sales_history(sales_payload) is True

    assert json.loads(products_file.read_text(encoding="utf-8"))[0]["id"] == "P1"
    assert json.loads(menu_file.read_text(encoding="utf-8"))[0]["id"] == "M1"
    assert json.loads(sales_file.read_text(encoding="utf-8"))[0]["id"] == "S1"


def test_callsites_sem_save_legado_no_escopo():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "app" / "blueprints" / "kitchen.py",
        root / "app" / "blueprints" / "menu" / "utils.py",
        root / "app" / "blueprints" / "restaurant" / "routes.py",
        root / "app" / "services" / "transfer_service.py",
        root / "app" / "services" / "import_sales.py",
    ]
    for f in files:
        content = f.read_text(encoding="utf-8")
        assert re.search(r"(?<!secure_)save_products\(", content) is None
        assert re.search(r"(?<!secure_)save_menu_items\(", content) is None
        assert re.search(r"(?<!secure_)save_sales_history\(", content) is None
