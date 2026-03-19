import copy
from flask import Flask, session
import pytest

from app.blueprints.restaurant import routes as restaurant_routes
from app.services import special_tables_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/restaurant/tables", endpoint="restaurant.restaurant_tables", view_func=lambda: "tables")
    app.add_url_rule("/restaurant/table/<table_id>", endpoint="restaurant.restaurant_table_order", view_func=lambda table_id: f"table-{table_id}")
    return app


def _set_profile(role="colaborador", user="adailton"):
    session.clear()
    session.update(
        {
            "user": user,
            "role": role,
            "department": "Serviço",
            "permissions": ["restaurante_mirapraia"],
        }
    )


def _replace_state(state_ref, payload):
    cloned = copy.deepcopy(payload)
    state_ref.clear()
    state_ref.update(cloned)
    return True


def _setup_special_service_mocks(monkeypatch, orders_state):
    stock_entries = []
    sales_history = []
    breakfast_history = []
    menu_items = [
        {"id": "P1", "name": "Pão na Chapa", "recipe": [{"ingredient_id": "I1", "qty": 1}]},
        {"id": "A1", "name": "Manteiga Extra", "recipe": [{"ingredient_id": "I2", "qty": 1}]},
    ]
    products = [
        {"id": "I1", "name": "Pão Francês", "unit": "un", "price": 1.0},
        {"id": "I2", "name": "Manteiga", "unit": "un", "price": 0.5},
    ]

    def _load_orders():
        return orders_state

    def _save_orders(payload):
        return _replace_state(orders_state, payload)

    monkeypatch.setattr(special_tables_service, "load_table_orders", _load_orders)
    monkeypatch.setattr(special_tables_service, "save_table_orders", _save_orders)
    monkeypatch.setattr(special_tables_service, "load_products", lambda: copy.deepcopy(products))
    monkeypatch.setattr(special_tables_service, "load_menu_items", lambda: copy.deepcopy(menu_items))
    monkeypatch.setattr(special_tables_service, "save_stock_entry", lambda entry: stock_entries.append(copy.deepcopy(entry)) or True)
    monkeypatch.setattr(special_tables_service, "log_stock_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(special_tables_service, "load_breakfast_history", lambda: copy.deepcopy(breakfast_history))
    monkeypatch.setattr(special_tables_service, "save_breakfast_history", lambda payload: breakfast_history.clear() or breakfast_history.extend(copy.deepcopy(payload)) or True)
    monkeypatch.setattr(special_tables_service, "load_sales_history", lambda: copy.deepcopy(sales_history))
    monkeypatch.setattr(
        special_tables_service,
        "secure_save_sales_history",
        lambda payload, user="Sistema": sales_history.clear() or sales_history.extend(copy.deepcopy(payload)) or True,
    )
    monkeypatch.setattr(special_tables_service.SpecialTablesService, "log_special_operation", staticmethod(lambda *args, **kwargs: None))
    return stock_entries, sales_history, breakfast_history


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_scenario_a_table_36_transfer_and_close_only_stock_no_financial(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {
        "70": {
            "items": [{"id": "it1", "name": "Pão na Chapa", "product_id": "P1", "qty": 1, "price": 12.0, "complements": [], "accompaniments": []}],
            "total": 12.0,
            "status": "open",
            "opened_at": "16/03/2026 08:10",
            "customer_type": "passante",
            "opened_by": "garcom1",
        }
    }
    stock_entries, sales_history, breakfast_history = _setup_special_service_mocks(monkeypatch, orders_state)
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: _replace_state(orders_state, payload))
    monkeypatch.setattr(restaurant_routes, "load_restaurant_table_settings", lambda: {"disabled_tables": []})
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_transfer_ticket", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/70",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"action": "transfer_table", "target_table_id": "36"},
    ):
        _set_profile(role="colaborador", user=f"oper_{client_type}")
        response = restaurant_routes.restaurant_table_order.__wrapped__("70")
    assert response.status_code == 302
    assert "36" in orders_state and "70" not in orders_state

    ok, _ = special_tables_service.SpecialTablesService.process_table_36_breakfast("36", f"oper_{client_type}")
    (tmp_path / f"scenario_a_{client_type}_stock_entries.json").write_text(str(stock_entries), encoding="utf-8")
    (tmp_path / f"scenario_a_{client_type}_sales_history.json").write_text(str(sales_history), encoding="utf-8")
    (tmp_path / f"scenario_a_{client_type}_breakfast_history.json").write_text(str(breakfast_history), encoding="utf-8")
    assert ok is True
    assert "36" not in orders_state
    assert len(stock_entries) >= 1
    assert breakfast_history and breakfast_history[-1]["table_id"] == "36"
    assert sales_history and sales_history[-1]["special_table_type"] == "breakfast"
    assert float(sales_history[-1]["final_total"]) == 0.0
    assert bool(sales_history[-1]["service_fee_removed"]) is True


def test_scenario_b_and_c_tables_68_69_no_financial_with_stock(monkeypatch, tmp_path):
    orders_state = {
        "68": {
            "items": [{"id": "it68", "name": "Pão na Chapa", "product_id": "P1", "qty": 2, "price": 20.0, "complements": [], "accompaniments": []}],
            "total": 40.0,
            "status": "open",
        },
        "69": {
            "items": [{"id": "it69", "name": "Pão na Chapa", "product_id": "P1", "qty": 1, "price": 20.0, "complements": [], "accompaniments": []}],
            "total": 20.0,
            "status": "open",
        },
    }
    stock_entries, sales_history, _ = _setup_special_service_mocks(monkeypatch, orders_state)

    ok68, _ = special_tables_service.SpecialTablesService.process_table_68_courtesy("68", "sup1", "Cortesia do dia")
    ok69, _ = special_tables_service.SpecialTablesService.process_table_69_owners("69", "oper1")
    (tmp_path / "scenario_bc_stock_entries.json").write_text(str(stock_entries), encoding="utf-8")
    (tmp_path / "scenario_bc_sales_history.json").write_text(str(sales_history), encoding="utf-8")

    assert ok68 is True and ok69 is True
    assert "68" not in orders_state and "69" not in orders_state
    assert len(stock_entries) >= 2
    courtesy = next(x for x in sales_history if x.get("special_table_type") == "courtesy")
    owners = next(x for x in sales_history if x.get("special_table_type") == "owners")
    assert float(courtesy["final_total"]) == 0.0 and float(owners["final_total"]) == 0.0
    assert bool(courtesy["commission_eligible"]) is False and bool(owners["commission_eligible"]) is False
    assert bool(courtesy["service_fee_removed"]) is True and bool(owners["service_fee_removed"]) is True


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"),
    ],
)
def test_scenario_d_staff_consumption_discount_20_no_service_fee(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {
        "FUNC_JOAO": {
            "items": [{"id": "it1", "name": "Pão na Chapa", "product_id": "P1", "qty": 2, "price": 10.0, "complements": [], "accompaniments": []}],
            "total": 20.0,
            "status": "open",
            "customer_type": "funcionario",
            "staff_name": "JOAO",
        }
    }
    sales_history = []
    stock_entries = []
    cashier_transactions = []
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: _replace_state(orders_state, payload))
    monkeypatch.setattr(restaurant_routes, "load_sales_history", lambda: copy.deepcopy(sales_history))
    monkeypatch.setattr(restaurant_routes, "secure_save_sales_history", lambda payload, user="Sistema": sales_history.clear() or sales_history.extend(copy.deepcopy(payload)) or True)
    monkeypatch.setattr(
        restaurant_routes.CashierService,
        "add_transaction",
        staticmethod(lambda **kwargs: cashier_transactions.append(copy.deepcopy(kwargs)) or {"id": "tx1"}),
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [{"id": "P1", "name": "Pão na Chapa", "unit": "un", "price": 1.0}])
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: [{"id": "P1", "name": "Pão na Chapa"}])
    monkeypatch.setattr(restaurant_routes, "log_stock_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "save_stock_entry", lambda entry: stock_entries.append(copy.deepcopy(entry)) or True)

    with app.test_request_context(
        "/restaurant/table/FUNC_JOAO",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"action": "transfer_to_staff_account"},
    ):
        _set_profile(role="colaborador", user=f"oper_{client_type}")
        response = restaurant_routes.restaurant_table_order.__wrapped__("FUNC_JOAO")

    (tmp_path / f"scenario_d_{client_type}_sales_history.json").write_text(str(sales_history), encoding="utf-8")
    (tmp_path / f"scenario_d_{client_type}_stock_entries.json").write_text(str(stock_entries), encoding="utf-8")
    (tmp_path / f"scenario_d_{client_type}_cashier_transactions.json").write_text(str(cashier_transactions), encoding="utf-8")
    assert response.status_code == 302
    assert "FUNC_JOAO" not in orders_state
    assert sales_history
    sale = sales_history[-1]
    assert float(sale["total"]) == 20.0
    assert float(sale["final_total"]) == 16.0
    assert float(sale["service_fee"]) == 0.0
    assert bool(sale["service_fee_removed"]) is True
    assert sale["discounts"][-1]["percent"] == 20
    assert stock_entries
    assert cashier_transactions and float(cashier_transactions[-1]["amount"]) == 16.0
    assert bool((cashier_transactions[-1].get("details") or {}).get("service_fee_removed")) is True


def test_scenario_e_transfer_item_to_staff_and_supervisor_return(monkeypatch, tmp_path):
    app = _make_test_app()
    orders_state = {
        "70": {
            "items": [{"id": "it1", "name": "Refrigerante", "qty": 1.0, "price": 8.0, "complements": [], "printed": True}],
            "total": 8.0,
            "status": "open",
        },
        "FUNC_JOAO": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "customer_type": "funcionario",
            "staff_name": "JOAO",
        },
    }
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: _replace_state(orders_state, payload))
    monkeypatch.setattr(restaurant_routes, "load_restaurant_table_settings", lambda: {"disabled_tables": []})
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_transfer_ticket", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/transfer_item",
        method="POST",
        json={"source_table_id": "70", "target_table_id": "FUNC_JOAO", "item_index": 0, "qty": 1},
    ):
        _set_profile(role="colaborador", user="oper1")
        transfer_item_resp = restaurant_routes.restaurant_transfer_item.__wrapped__()
    assert transfer_item_resp.status_code == 200
    moved = orders_state["FUNC_JOAO"]["items"][-1]
    assert moved["transferred_from"] == "70"
    assert moved["transferred_by"] == "oper1"

    with app.test_request_context(
        "/restaurant/table/FUNC_JOAO",
        method="POST",
        data={"action": "transfer_table", "target_table_id": "71"},
    ):
        _set_profile(role="colaborador", user="oper1")
        blocked_resp = restaurant_routes.restaurant_table_order.__wrapped__("FUNC_JOAO")
    assert blocked_resp.status_code == 302
    assert "FUNC_JOAO" in orders_state

    with app.test_request_context(
        "/restaurant/table/FUNC_JOAO",
        method="POST",
        data={"action": "transfer_table", "target_table_id": "71"},
    ):
        _set_profile(role="supervisor", user="sup1")
        ok_resp = restaurant_routes.restaurant_table_order.__wrapped__("FUNC_JOAO")
    (tmp_path / "scenario_e_orders_after.json").write_text(str(orders_state), encoding="utf-8")
    assert ok_resp.status_code == 302
    assert "FUNC_JOAO" not in orders_state
    assert "71" in orders_state
    assert orders_state["71"].get("customer_type") == "passante"
    assert orders_state["71"].get("staff_name") is None


def test_close_order_is_blocked_for_special_tables(monkeypatch, tmp_path):
    app = _make_test_app()
    orders_state = {"68": {"items": [], "total": 0.0, "status": "open"}}
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)

    with app.test_request_context(
        "/restaurant/table/68",
        method="POST",
        data={"action": "close_order", "payment_data": "[]"},
    ):
        _set_profile(role="supervisor", user="sup1")
        response = restaurant_routes.restaurant_table_order.__wrapped__("68")

    (tmp_path / "special_close_order_blocked_status.txt").write_text(str(response.status_code), encoding="utf-8")
    assert response.status_code == 302
