import json
from pathlib import Path

import pytest
from flask import Flask, session

from app.blueprints.restaurant import routes as restaurant_routes
from app.services import printing_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/restaurant/tables", endpoint="restaurant.restaurant_tables", view_func=lambda: "tables")
    app.add_url_rule("/restaurant/table/<table_id>", endpoint="restaurant.restaurant_table_order", view_func=lambda table_id: f"table-{table_id}")
    return app


def _set_profile():
    session.clear()
    session.update(
        {
            "user": "adailton",
            "role": "colaborador",
            "department": "Serviço",
            "permissions": ["restaurante_mirapraia"],
        }
    )


def _latest_txt(path: Path) -> Path:
    files = sorted(path.glob("*.txt"))
    assert files
    return files[-1]


def _configure_common_mocks(monkeypatch, tmp_path, orders_state):
    stock_entries = []

    menu_items = [
        {
            "id": 10,
            "name": "Prato Executivo",
            "category": "Pratos",
            "price": 25.0,
            "active": True,
            "paused": False,
            "has_accompaniments": True,
            "allowed_accompaniments": ["20"],
            "printer_id": "2",
            "should_print": True,
        },
        {
            "id": 20,
            "name": "Arroz de Alho",
            "category": "Pratos",
            "price": 7.0,
            "active": True,
            "paused": False,
            "product_type": "accompaniment_and_order",
            "recipe": [{"ingredient_id": 500, "qty": 1}],
            "printer_id": "2",
            "should_print": True,
        },
    ]

    products = [
        {"id": 500, "name": "Arroz Cru", "unit": "un", "price": 2.0, "min_stock": 0},
        {"id": 700, "name": "Insumo Prato Executivo", "unit": "un", "price": 4.0, "min_stock": 0},
    ]

    def _save_stock_entry(entry):
        stock_entries.append(entry)
        return True

    monkeypatch.setenv("ALMAREIA_ENV", "development")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: menu_items)
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: products)
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    printers = [{"id": "2", "name": "Cozinha", "type": "network", "ip": "10.10.10.2", "port": 9100}]
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: printers)
    monkeypatch.setattr(printing_service, "load_printers", lambda: printers)
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "save_stock_entry", _save_stock_entry)

    return stock_entries


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"),
    ],
)
def test_scenario_a_linked_accompaniment_no_extra_charge_with_stock_and_temp_print(tmp_path, monkeypatch, client_type, user_agent):
    app = _make_test_app()
    state = {
        "88": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    stock_entries = _configure_common_mocks(monkeypatch, tmp_path, state)

    with app.test_request_context(
        "/restaurant/table/88",
        method="POST",
        headers={"User-Agent": user_agent},
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": f"r04e_a_{client_type}",
            "items_json": json.dumps([{"product": "10", "qty": 1, "accompaniments": ["20"]}]),
        },
    ):
        _set_profile()
        response = restaurant_routes.restaurant_table_order.__wrapped__("88")

    assert response.status_code == 302
    assert len(state["88"]["items"]) == 1
    item = state["88"]["items"][0]
    assert item["name"] == "Prato Executivo"
    assert item["accompaniments"][0]["name"] == "Arroz de Alho"
    assert item["accompaniments"][0]["price"] == 0.0
    assert state["88"]["total"] == 25.0
    assert item["accompaniments_deducted_ids"] == ["20"]
    assert item["accompaniments_deduction_trace"][0]["deducted"] is True
    assert item["accompaniments_deduction_trace"][0]["mode"] == "recipe"
    assert any("Acomp Arroz de Alho de Prato Executivo" in str(entry.get("invoice", "")) for entry in stock_entries)

    output_dir = tmp_path / "temp_print" / "Cozinha"
    output_file = _latest_txt(output_dir)
    content = output_file.read_text(encoding="utf-8")
    assert "Prato Executivo" in content
    assert "- Arroz de Alho" in content
    assert "table_id: 88" in content


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36"),
    ],
)
def test_scenario_b_accompaniment_and_order_standalone_charges_normally_with_stock_and_temp_print(tmp_path, monkeypatch, client_type, user_agent):
    app = _make_test_app()
    state = {
        "89": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    stock_entries = _configure_common_mocks(monkeypatch, tmp_path, state)

    with app.test_request_context(
        "/restaurant/table/89",
        method="POST",
        headers={"User-Agent": user_agent},
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": f"r04e_b_{client_type}",
            "items_json": json.dumps([{"product": "20", "qty": 1}]),
        },
    ):
        _set_profile()
        response = restaurant_routes.restaurant_table_order.__wrapped__("89")

    assert response.status_code == 302
    assert len(state["89"]["items"]) == 1
    item = state["89"]["items"][0]
    assert item["name"] == "Arroz de Alho"
    assert item["accompaniments"] == []
    assert state["89"]["total"] == 7.0
    assert item["accompaniments_deducted_ids"] == []
    assert any("Venda Restaurante: Arroz de Alho" in str(entry.get("invoice", "")) for entry in stock_entries)

    output_dir = tmp_path / "temp_print" / "Cozinha"
    output_file = _latest_txt(output_dir)
    content = output_file.read_text(encoding="utf-8")
    assert "Arroz de Alho" in content
    assert "table_id: 89" in content
