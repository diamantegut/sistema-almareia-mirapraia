from contextlib import contextmanager
import copy
import json

from flask import Flask, session

from app.blueprints.restaurant import routes as restaurant_routes
import app.services.stock_service as stock_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/restaurant/tables", endpoint="restaurant.restaurant_tables", view_func=lambda: "tables")
    app.add_url_rule(
        "/restaurant/table/<table_id>",
        endpoint="restaurant.restaurant_table_order",
        view_func=lambda table_id: f"table-{table_id}",
    )
    return app


def _set_profile():
    session.clear()
    session.update(
        {
            "user": "adailton",
            "role": "supervisor",
            "department": "Serviço",
            "permissions": ["restaurante_mirapraia"],
        }
    )


def _setup_close_order_mocks(monkeypatch, *, fail_sales=False, fail_cashier=False, fail_stock=False, fail_table_save=False):
    orders_state = {
        "80": {
            "items": [
                {
                    "id": "it1",
                    "name": "Prato Teste",
                    "product_id": "p1",
                    "qty": 1,
                    "price": 10.0,
                    "complements": [],
                    "accompaniments": [],
                }
            ],
            "total": 10.0,
            "status": "open",
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
            "total_paid": 0.0,
        }
    }
    sales_history_state = []
    stock_entries_state = []
    cashier_sessions_state = [
        {"id": "CX1", "type": "restaurant", "status": "open", "transactions": []}
    ]

    @contextmanager
    def _dummy_lock(*args, **kwargs):
        yield

    def _load_table_orders():
        return orders_state

    def _save_table_orders(payload):
        if fail_table_save:
            return False
        orders_state.clear()
        orders_state.update(copy.deepcopy(payload))
        return True

    def _load_sales_history():
        return copy.deepcopy(sales_history_state)

    def _secure_save_sales_history(new_data, user_id="Sistema"):
        if fail_sales:
            raise RuntimeError("sales-history-error")
        sales_history_state.clear()
        sales_history_state.extend(copy.deepcopy(new_data))
        return True

    def _load_stock_entries():
        return copy.deepcopy(stock_entries_state)

    def _save_stock_entries(new_data):
        stock_entries_state.clear()
        stock_entries_state.extend(copy.deepcopy(new_data))
        return True

    def _add_stock_entries_batch(new_entries):
        if fail_stock:
            raise RuntimeError("stock-error")
        existing_ids = {str(e.get("id")) for e in stock_entries_state if e.get("id")}
        added = 0
        for entry in new_entries:
            entry_id = entry.get("id")
            if entry_id and str(entry_id) in existing_ids:
                continue
            stock_entries_state.append(copy.deepcopy(entry))
            if entry_id:
                existing_ids.add(str(entry_id))
            added += 1
        return added

    def _cashier_add_transaction(**kwargs):
        if fail_cashier:
            raise RuntimeError("cashier-error")
        tx_id = f"TX_{len(cashier_sessions_state[0]['transactions']) + 1}"
        tx = {"id": tx_id, "amount": kwargs.get("amount", 0), "description": kwargs.get("description", "")}
        cashier_sessions_state[0]["transactions"].append(tx)
        return tx

    def _cashier_list_sessions():
        return copy.deepcopy(cashier_sessions_state)

    def _cashier_persist_sessions(sessions, trigger_backup=False):
        cashier_sessions_state.clear()
        cashier_sessions_state.extend(copy.deepcopy(sessions))
        return True

    monkeypatch.setattr(restaurant_routes, "file_lock", _dummy_lock)
    monkeypatch.setattr(restaurant_routes, "load_table_orders", _load_table_orders)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", _save_table_orders)
    monkeypatch.setattr(restaurant_routes, "load_sales_history", _load_sales_history)
    monkeypatch.setattr(restaurant_routes, "secure_save_sales_history", _secure_save_sales_history)
    monkeypatch.setattr(restaurant_routes, "load_stock_entries", _load_stock_entries)
    monkeypatch.setattr(restaurant_routes, "save_stock_entries", _save_stock_entries)
    monkeypatch.setattr(restaurant_routes, "add_stock_entries_batch", _add_stock_entries_batch)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_payment_methods", lambda: [{"id": "dinheiro", "name": "Dinheiro"}])
    monkeypatch.setattr(restaurant_routes, "get_current_cashier", lambda **kwargs: {"id": "CX1"})
    monkeypatch.setattr(restaurant_routes.CashierService, "add_transaction", staticmethod(_cashier_add_transaction))
    monkeypatch.setattr(restaurant_routes.CashierService, "list_sessions", staticmethod(_cashier_list_sessions))
    monkeypatch.setattr(restaurant_routes.CashierService, "persist_sessions", staticmethod(_cashier_persist_sessions))
    monkeypatch.setattr(
        restaurant_routes,
        "expand_order_item_stock_components",
        lambda item: [
            {
                "product_id": "p1",
                "name": item.get("name"),
                "qty": float(item.get("qty", 1) or 1),
                "origin": "produto",
                "parent_name": item.get("name"),
            }
        ],
    )
    monkeypatch.setattr(
        restaurant_routes,
        "resolve_stock_product_for_order_item",
        lambda order_item, menu_items_db, products_db: {"id": "p1", "name": "Insumo Teste", "unit": "un", "price": 2.0, "min_stock": 0},
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [{"id": "p1", "name": "Insumo Teste", "unit": "un", "price": 2.0, "min_stock": 0}])
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: [])
    monkeypatch.setattr(restaurant_routes, "log_stock_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_consolidated_stock_warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(stock_service, "get_product_balances", lambda: {"Insumo Teste": 10})
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_security_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes.FiscalPoolService, "add_to_pool", staticmethod(lambda **kwargs: None))
    monkeypatch.setattr(restaurant_routes, "load_fiscal_settings", lambda: {})
    monkeypatch.setattr(restaurant_routes, "process_pending_emissions", lambda **kwargs: {"success": 0})
    monkeypatch.setattr(restaurant_routes, "print_fiscal_receipt", lambda *args, **kwargs: (True, None))

    return orders_state, sales_history_state, cashier_sessions_state, stock_entries_state


def _execute_close_order(app):
    payload = [{"method": "Dinheiro", "amount": 11.0}]
    with app.test_request_context(
        "/restaurant/table/80",
        method="POST",
        data={"action": "close_order", "payment_data": json.dumps(payload)},
    ):
        _set_profile()
        return restaurant_routes.restaurant_table_order.__wrapped__("80")


def test_close_order_success_keeps_consistency(monkeypatch):
    app = _make_test_app()
    orders, sales_history, cashier_sessions, stock_entries = _setup_close_order_mocks(monkeypatch)

    response = _execute_close_order(app)

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/tables")
    assert "80" not in orders
    assert len(sales_history) == 1
    assert len(cashier_sessions[0]["transactions"]) == 1
    assert len(stock_entries) == 1


def test_close_order_failure_sales_history_keeps_table_open_and_rolls_back(monkeypatch):
    app = _make_test_app()
    orders, sales_history, cashier_sessions, stock_entries = _setup_close_order_mocks(monkeypatch, fail_sales=True)

    response = _execute_close_order(app)

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/80")
    assert "80" in orders
    assert sales_history == []
    assert cashier_sessions[0]["transactions"] == []
    assert stock_entries == []


def test_close_order_failure_cashier_keeps_table_open(monkeypatch):
    app = _make_test_app()
    orders, sales_history, cashier_sessions, stock_entries = _setup_close_order_mocks(monkeypatch, fail_cashier=True)

    response = _execute_close_order(app)

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/80")
    assert "80" in orders
    assert sales_history == []
    assert cashier_sessions[0]["transactions"] == []
    assert stock_entries == []


def test_close_order_failure_stock_keeps_table_open_and_rolls_back_cashier(monkeypatch):
    app = _make_test_app()
    orders, sales_history, cashier_sessions, stock_entries = _setup_close_order_mocks(monkeypatch, fail_stock=True)

    response = _execute_close_order(app)

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/80")
    assert "80" in orders
    assert sales_history == []
    assert cashier_sessions[0]["transactions"] == []
    assert stock_entries == []


def test_close_order_failure_save_table_orders_rolls_back_all(monkeypatch):
    app = _make_test_app()
    orders, sales_history, cashier_sessions, stock_entries = _setup_close_order_mocks(monkeypatch, fail_table_save=True)

    response = _execute_close_order(app)

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/80")
    assert "80" in orders
    assert sales_history == []
    assert cashier_sessions[0]["transactions"] == []
    assert stock_entries == []
