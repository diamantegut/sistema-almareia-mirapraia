from contextlib import contextmanager
import copy
import json

from flask import Flask, session

from app.blueprints.restaurant import routes as restaurant_routes
from app.services import fiscal_pool_service
import app.services.stock_service as stock_service
import app.services.reservation_service as reservation_service


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


def _setup_close_order_mocks(
    monkeypatch,
    *,
    order_total=100.0,
    customer_type="passante",
    room_number=None,
    emit_result=None,
    pool_entry_state=None,
):
    grand_total = round(float(order_total) * 1.1, 2)
    orders_state = {
        "80": {
            "items": [
                {
                    "id": "it1",
                    "name": "Prato Teste",
                    "product_id": "p1",
                    "qty": 1,
                    "price": float(order_total),
                    "complements": [],
                    "accompaniments": [],
                }
            ],
            "total": float(order_total),
            "status": "open",
            "customer_type": customer_type,
            "waiter": "adailton",
            "opened_by": "adailton",
            "total_paid": 0.0,
            "room_number": room_number,
            "customer_name": "Cliente Teste",
        }
    }
    sales_history_state = []
    stock_entries_state = []
    cashier_sessions_state = [{"id": "CX1", "type": "restaurant", "status": "open", "transactions": []}]
    tracking = {
        "process_calls": 0,
        "print_calls": 0,
        "pool_add_calls": 0,
        "last_pool_customer_info": None,
        "grand_total": grand_total,
    }

    @contextmanager
    def _dummy_lock(*args, **kwargs):
        yield

    def _load_table_orders():
        return orders_state

    def _save_table_orders(payload):
        orders_state.clear()
        orders_state.update(copy.deepcopy(payload))
        return True

    def _load_sales_history():
        return copy.deepcopy(sales_history_state)

    def _secure_save_sales_history(new_data, user_id="Sistema"):
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
        for entry in new_entries:
            stock_entries_state.append(copy.deepcopy(entry))
        return len(new_entries)

    def _cashier_add_transaction(**kwargs):
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

    pool_id = "POOL_80"
    pool_entry = {
        "id": pool_id,
        "status": "emitted",
        "items": [{"id": "it1", "name": "Prato Teste", "qty": 1, "price": float(order_total), "total": float(order_total)}],
        "total_amount": grand_total,
        "last_error": None,
    }
    if isinstance(pool_entry_state, dict):
        pool_entry.update(pool_entry_state)

    def _add_to_pool(**kwargs):
        tracking["pool_add_calls"] += 1
        tracking["last_pool_customer_info"] = copy.deepcopy(kwargs.get("customer_info"))
        return pool_id

    def _get_pool_entry(entry_id):
        if entry_id != pool_id:
            return {}
        return copy.deepcopy(pool_entry)

    def _process_pending_emissions(**kwargs):
        tracking["process_calls"] += 1
        if isinstance(emit_result, dict):
            return emit_result
        return {"processed": 1, "success": 1, "failed": 0}

    def _print_fiscal_receipt(*args, **kwargs):
        tracking["print_calls"] += 1
        return True, None

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
    monkeypatch.setattr(restaurant_routes, "load_payment_methods", lambda: [{"id": "dinheiro", "name": "Dinheiro", "is_fiscal": True}])
    monkeypatch.setattr(restaurant_routes, "get_current_cashier", lambda **kwargs: {"id": "CX1"})
    monkeypatch.setattr(restaurant_routes.CashierService, "add_transaction", staticmethod(_cashier_add_transaction))
    monkeypatch.setattr(restaurant_routes.CashierService, "list_sessions", staticmethod(_cashier_list_sessions))
    monkeypatch.setattr(restaurant_routes.CashierService, "persist_sessions", staticmethod(_cashier_persist_sessions))
    monkeypatch.setattr(
        restaurant_routes,
        "expand_order_item_stock_components",
        lambda item: [{"product_id": "p1", "name": item.get("name"), "qty": 1, "origin": "produto", "parent_name": item.get("name")}],
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
    monkeypatch.setattr(restaurant_routes.FiscalPoolService, "add_to_pool", staticmethod(_add_to_pool))
    monkeypatch.setattr(restaurant_routes.FiscalPoolService, "get_entry", staticmethod(_get_pool_entry))
    monkeypatch.setattr(restaurant_routes, "load_fiscal_settings", lambda: {})
    monkeypatch.setattr(restaurant_routes, "process_pending_emissions", _process_pending_emissions)
    monkeypatch.setattr(restaurant_routes, "print_fiscal_receipt", _print_fiscal_receipt)
    return tracking, pool_entry


def _execute_close_order(app, *, emit_invoice=False, doc_value="", payment_amount=110.0):
    payload = [{"method": "Dinheiro", "amount": float(payment_amount)}]
    form_data = {"action": "close_order", "payment_data": json.dumps(payload)}
    if emit_invoice:
        form_data["emit_invoice"] = "on"
        form_data["customer_cpf_cnpj"] = doc_value
    with app.test_request_context("/restaurant/table/80", method="POST", data=form_data):
        _set_profile()
        return restaurant_routes.restaurant_table_order.__wrapped__("80")


def test_close_order_without_immediate_emission(monkeypatch, tmp_path):
    app = _make_test_app()
    tracking, _ = _setup_close_order_mocks(monkeypatch, order_total=100.0)
    response = _execute_close_order(app, emit_invoice=False, payment_amount=tracking["grand_total"])
    assert response.status_code == 302
    assert tracking["pool_add_calls"] == 1
    assert tracking["process_calls"] == 0
    assert tracking["print_calls"] == 0
    (tmp_path / "evidence_close_without_emit.json").write_text(
        json.dumps(tracking, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_close_order_with_immediate_emission_success(monkeypatch, tmp_path):
    app = _make_test_app()
    tracking, _ = _setup_close_order_mocks(monkeypatch, order_total=1200.0)
    response = _execute_close_order(app, emit_invoice=True, doc_value="12345678901", payment_amount=tracking["grand_total"])
    assert response.status_code == 302
    assert tracking["pool_add_calls"] == 1
    assert tracking["process_calls"] == 1
    assert tracking["print_calls"] == 1
    (tmp_path / "evidence_close_with_emit_success.json").write_text(
        json.dumps(
            {
                "tracking": tracking,
                "pool_customer_info": tracking["last_pool_customer_info"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_close_order_with_immediate_emission_above_999_without_document(monkeypatch, tmp_path):
    app = _make_test_app()
    tracking, pool_entry = _setup_close_order_mocks(
        monkeypatch,
        order_total=1200.0,
        emit_result={"processed": 1, "success": 0, "failed": 1},
        pool_entry_state={"status": "manual_retry_required", "last_error": "CPF/CNPJ obrigatório para emissão acima de R$ 999,00."},
    )
    response = _execute_close_order(app, emit_invoice=True, doc_value="", payment_amount=tracking["grand_total"])
    assert response.status_code == 302
    assert tracking["process_calls"] == 1
    assert pool_entry["status"] == "manual_retry_required"
    (tmp_path / "evidence_close_above_999_without_doc.json").write_text(
        json.dumps({"tracking": tracking, "pool_entry": pool_entry}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_close_order_rejected_goes_to_rejected_state(monkeypatch, tmp_path):
    app = _make_test_app()
    tracking, pool_entry = _setup_close_order_mocks(
        monkeypatch,
        order_total=400.0,
        emit_result={"processed": 1, "success": 0, "failed": 1},
        pool_entry_state={"status": "rejected", "last_error": "Rejeição: 539 Duplicidade"},
    )
    response = _execute_close_order(app, emit_invoice=True, doc_value="12345678901", payment_amount=tracking["grand_total"])
    assert response.status_code == 302
    assert tracking["process_calls"] == 1
    assert pool_entry["status"] == "rejected"
    (tmp_path / "evidence_close_rejected.json").write_text(
        json.dumps({"tracking": tracking, "pool_entry": pool_entry}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_restaurant_context_blocks_excluded_consumption():
    ctx = restaurant_routes._build_restaurant_fiscal_context(
        {"table_id": "80", "customer_type": "funcionario", "items": [{"name": "Prato"}]},
        80.0,
    )
    assert ctx["can_offer"] is False
    assert ctx["block_reason"] == "consumo_funcionario"


def test_restaurant_context_guest_above_999_autofills_document(monkeypatch, tmp_path):
    monkeypatch.setattr(fiscal_pool_service, "load_room_occupancy", lambda: {"101": {"reservation_id": "R100"}})

    class _ReservationServiceFake:
        def get_reservation_by_id(self, reservation_id):
            return {"id": reservation_id, "doc_id": "123.456.789-01"}

        def get_guest_details(self, reservation_id):
            return {}

    monkeypatch.setattr(reservation_service, "ReservationService", _ReservationServiceFake)
    ctx = restaurant_routes._build_restaurant_fiscal_context(
        {"table_id": "81", "customer_type": "hospede", "room_number": "101", "items": [{"name": "Jantar"}]},
        1200.0,
    )
    assert ctx["doc_required"] is True
    assert ctx["auto_document"] == "12345678901"
    (tmp_path / "evidence_guest_auto_document.json").write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
