from flask import Flask, session
from unittest.mock import patch
from contextlib import contextmanager
import copy
import pytest

from app.blueprints.restaurant import routes as restaurant_routes
from app.services import transfer_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/restaurant/cashier", endpoint="restaurant.restaurant_cashier", view_func=lambda: "cashier")
    app.add_url_rule("/restaurant/tables", endpoint="restaurant.restaurant_tables", view_func=lambda: "tables")
    app.add_url_rule(
        "/restaurant/table/<table_id>",
        endpoint="restaurant.restaurant_table_order",
        view_func=lambda table_id: f"table-{table_id}",
    )
    return app


def _set_profile(**kwargs):
    session.clear()
    session.update(kwargs)


def test_restaurant_operations_access_matrix():
    app = _make_test_app()
    with app.test_request_context("/restaurant/tables"):
        _set_profile(user="admin", role="admin", department="Diretoria", permissions=[])
        assert restaurant_routes._has_restaurant_or_reception_access() is True

        _set_profile(
            user="recepcao1",
            role="atendente",
            department="Recepção",
            permissions=[],
        )
        assert restaurant_routes._has_restaurant_or_reception_access() is True

        _set_profile(
            user="rest1",
            role="colaborador",
            department="Serviço",
            permissions=["restaurante_mirapraia", "restaurante_full_access"],
        )
        assert restaurant_routes._has_restaurant_or_reception_access() is True

        _set_profile(
            user="recepcao2",
            role="colaborador",
            department="Administrativo",
            permissions=["recepcao"],
        )
        assert restaurant_routes._has_restaurant_or_reception_access() is True

        _set_profile(
            user="externo",
            role="colaborador",
            department="Financeiro",
            permissions=["financeiro"],
        )
        assert restaurant_routes._has_restaurant_or_reception_access() is False


def test_restaurant_tables_route_blocks_external_profile():
    app = _make_test_app()
    with app.test_request_context("/restaurant/tables"):
        _set_profile(
            user="externo",
            role="colaborador",
            department="Financeiro",
            permissions=["financeiro"],
        )
        response = restaurant_routes.restaurant_tables.__wrapped__()
        assert response.status_code == 302
        assert response.location.endswith("/")


def test_restaurant_table_route_blocks_external_profile():
    app = _make_test_app()
    with app.test_request_context("/restaurant/table/44"):
        _set_profile(
            user="externo",
            role="colaborador",
            department="Financeiro",
            permissions=["financeiro"],
        )
        response = restaurant_routes.restaurant_table_order.__wrapped__("44")
        assert response.status_code == 302
        assert response.location.endswith("/")


def test_cashier_policy_matrix_operational_rule():
    app = _make_test_app()
    with app.test_request_context("/restaurant/cashier"):
        _set_profile(user="admin", role="admin", department="Diretoria", permissions=[])
        assert restaurant_routes._has_restaurant_cashier_access() is True

        _set_profile(
            user="operacional_principal",
            role="colaborador",
            department="Serviço",
            permissions=["restaurante_mirapraia"],
        )
        assert restaurant_routes._has_restaurant_cashier_access() is True

        _set_profile(
            user="recepcao_colab",
            role="colaborador",
            department="Recepção",
            permissions=["recepcao"],
        )
        assert restaurant_routes._has_restaurant_cashier_access() is True

        _set_profile(
            user="externo",
            role="colaborador",
            department="Financeiro",
            permissions=["financeiro"],
        )
        assert restaurant_routes._has_restaurant_cashier_access() is False


def test_cashier_advanced_operations_require_supervisor_plus():
    app = _make_test_app()
    with app.test_request_context("/restaurant/cashier"):
        _set_profile(user="colab", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        assert restaurant_routes._is_restaurant_cashier_supervisor_or_above() is False

        _set_profile(user="superv", role="supervisor", department="Governança", permissions=[])
        assert restaurant_routes._is_restaurant_cashier_supervisor_or_above() is True


def test_cashier_open_is_blocked_for_non_supervisor_profile():
    app = _make_test_app()
    with app.test_request_context(
        "/restaurant/cashier",
        method="POST",
        data={"action": "open_cashier", "opening_balance": "100"},
    ):
        _set_profile(user="colab", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_cashier.__wrapped__()
        assert response.status_code == 302
        assert response.location.endswith("/restaurant/cashier")


def test_cashier_open_allows_supervisor_plus():
    app = _make_test_app()
    with app.test_request_context(
        "/restaurant/cashier",
        method="POST",
        data={"action": "open_cashier", "opening_balance": "150"},
    ):
        _set_profile(user="superv", role="supervisor", department="Governança", permissions=[])
        with patch.object(restaurant_routes.CashierService, "_load_sessions", return_value=[]):
            with patch.object(restaurant_routes.CashierService, "open_session", return_value={"id": "S"}):
                response = restaurant_routes.restaurant_cashier.__wrapped__()
        assert response.status_code == 302
        assert response.location.endswith("/restaurant/cashier")


def test_cashier_advanced_transaction_is_blocked_for_non_supervisor_profile():
    app = _make_test_app()
    with app.test_request_context(
        "/restaurant/cashier",
        method="POST",
        data={
            "action": "add_transaction",
            "type": "deposit",
            "amount": "25",
            "description": "Teste",
        },
    ):
        _set_profile(user="colab", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        with patch.object(restaurant_routes.CashierService, "_load_sessions", return_value=[{"id": "S", "user": "u", "status": "open", "type": "restaurant", "transactions": [], "opening_balance": 0}]):
            response = restaurant_routes.restaurant_cashier.__wrapped__()
        assert response.status_code == 302
        assert response.location.endswith("/restaurant/cashier")


def test_transfer_service_allows_room_charge_only_for_hospede_positive(monkeypatch):
    state = {
        "table_orders.json": {
            "101": {
                "items": [
                    {"id": "i1", "product_id": "2", "name": "Acai", "price": 19.9, "qty": 1, "category": "Sobremesas"}
                ],
                "total": 19.9,
                "customer_type": "hospede",
                "room_number": "01",
                "waiter": "adailton",
                "opened_by": "adailton",
            }
        },
        "room_occupancy.json": {"01": {"guest_name": "Teste"}},
        "room_charges.json": [],
    }
    archived = []

    @contextmanager
    def _noop_lock(_):
        yield

    def _load_json(name, default=None):
        return copy.deepcopy(state.get(name, default if default is not None else {}))

    def _save_json(name, payload):
        state[name] = copy.deepcopy(payload)
        return True

    monkeypatch.setattr(transfer_service, "file_lock", _noop_lock)
    monkeypatch.setattr(transfer_service, "load_json", _load_json)
    monkeypatch.setattr(transfer_service, "save_json", _save_json)
    monkeypatch.setattr(transfer_service, "get_data_path", lambda x: x)
    monkeypatch.setattr(transfer_service, "load_sales_history", lambda: [])
    monkeypatch.setattr(transfer_service, "secure_save_sales_history", lambda data, user_id=None: archived.extend(copy.deepcopy(data)))
    monkeypatch.setattr(transfer_service, "load_products", lambda: [])
    monkeypatch.setattr(transfer_service, "load_menu_items", lambda: [])
    monkeypatch.setattr(transfer_service, "expand_order_item_stock_components", lambda item: [])
    monkeypatch.setattr(transfer_service, "save_stock_entry", lambda payload: True)
    monkeypatch.setattr(transfer_service, "log_stock_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfer_service.LoggerService, "log_acao", staticmethod(lambda **kwargs: None))

    ok, msg = transfer_service.transfer_table_to_room("101", "01", "adailton", mode="restaurant")
    assert ok is True
    assert "sucesso" in msg.lower()
    assert "101" not in state["table_orders.json"]
    assert len(state["room_charges.json"]) == 1
    assert state["room_charges.json"][0]["table_id"] == "101"
    assert archived
    assert archived[-1]["payment_method"] == "Room Charge"
    assert archived[-1]["customer_type"] == "hospede"


def test_transfer_service_blocks_room_charge_for_passante_negative(monkeypatch):
    state = {
        "table_orders.json": {
            "102": {
                "items": [
                    {"id": "i1", "product_id": "2", "name": "Acai", "price": 19.9, "qty": 1, "category": "Sobremesas"}
                ],
                "total": 19.9,
                "customer_type": "passante",
                "waiter": "adailton",
                "opened_by": "adailton",
            }
        },
        "room_occupancy.json": {"01": {"guest_name": "Teste"}},
        "room_charges.json": [],
    }

    @contextmanager
    def _noop_lock(_):
        yield

    def _load_json(name, default=None):
        return copy.deepcopy(state.get(name, default if default is not None else {}))

    def _save_json(name, payload):
        state[name] = copy.deepcopy(payload)
        return True

    monkeypatch.setattr(transfer_service, "file_lock", _noop_lock)
    monkeypatch.setattr(transfer_service, "load_json", _load_json)
    monkeypatch.setattr(transfer_service, "save_json", _save_json)
    monkeypatch.setattr(transfer_service, "get_data_path", lambda x: x)
    monkeypatch.setattr(transfer_service.LoggerService, "log_acao", staticmethod(lambda **kwargs: None))

    with pytest.raises(transfer_service.TransferError, match="hóspede"):
        transfer_service.transfer_table_to_room("102", "01", "adailton", mode="restaurant")

    assert len(state["room_charges.json"]) == 0
    assert "102" in state["table_orders.json"]


def test_add_batch_items_is_blocked_when_table_is_locked(monkeypatch):
    app = _make_test_app()
    state = {
        "55": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": True,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: copy.deepcopy(state))
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))

    with app.test_request_context(
        "/restaurant/table/55",
        method="POST",
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": "r04b_locked_batch",
            "items_json": '[{"product":"2","qty":1}]',
        },
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("55")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/55")
    assert not saves


def test_pull_bill_marks_table_as_locked(monkeypatch):
    app = _make_test_app()
    state = {
        "56": {
            "items": [{"id": "i1", "name": "Acai", "qty": 1, "price": 10.0}],
            "total": 10.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    printed_calls = []
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_bill", lambda *args, **kwargs: printed_calls.append((args, kwargs)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "render_template", lambda *args, **kwargs: "ok")

    with app.test_request_context(
        "/restaurant/table/56",
        method="POST",
        data={"action": "pull_bill"},
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("56")

    assert response == "ok"
    assert state["56"]["locked"] is True
    assert len(printed_calls) == 1


def test_unlock_table_is_blocked_for_non_supervisor_profile(monkeypatch):
    app = _make_test_app()
    state = {
        "57": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": True,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/57",
        method="POST",
        data={"action": "unlock_table"},
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("57")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/57")
    assert state["57"]["locked"] is True
    assert not saves


def test_unlock_table_allows_supervisor_plus(monkeypatch):
    app = _make_test_app()
    state = {
        "58": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": True,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "render_template", lambda *args, **kwargs: "ok")

    with app.test_request_context(
        "/restaurant/table/58",
        method="POST",
        data={"action": "unlock_table"},
    ):
        _set_profile(user="guilherme", role="supervisor", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("58")

    assert response == "ok"
    assert state["58"]["locked"] is False


def test_transfer_table_to_occupied_requires_explicit_confirmation(monkeypatch):
    app = _make_test_app()
    state = {
        "61": {
            "items": [{"id": "a1", "name": "Acai", "qty": 1, "price": 10.0}],
            "total": 10.0,
            "status": "open",
            "waiter": "adailton",
            "opened_by": "adailton",
            "customer_type": "passante",
        },
        "62": {
            "items": [{"id": "b1", "name": "Suco", "qty": 1, "price": 8.0}],
            "total": 8.0,
            "status": "open",
            "waiter": "adailton",
            "opened_by": "adailton",
            "customer_type": "passante",
        },
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/61",
        method="POST",
        data={"action": "transfer_table", "target_table_id": "62"},
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("61")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/61")
    assert "61" in state
    assert len(state["62"]["items"]) == 1
    assert not saves


def test_transfer_table_to_occupied_with_confirmation_merges_orders(monkeypatch):
    app = _make_test_app()
    state = {
        "63": {
            "items": [{"id": "a2", "name": "Acai", "qty": 1, "price": 10.0}],
            "total": 10.0,
            "status": "open",
            "waiter": "adailton",
            "opened_by": "adailton",
            "customer_type": "passante",
        },
        "64": {
            "items": [{"id": "b2", "name": "Suco", "qty": 1, "price": 8.0}],
            "total": 8.0,
            "status": "open",
            "waiter": "adailton",
            "opened_by": "adailton",
            "customer_type": "passante",
        },
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/63",
        method="POST",
        data={"action": "transfer_table", "target_table_id": "64", "confirm_occupied_transfer": "1"},
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("63")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/64")
    assert "63" not in state
    assert len(state["64"]["items"]) == 2
    assert saves


def test_transfer_item_rejects_same_source_and_destination(monkeypatch):
    app = _make_test_app()
    state = {
        "65": {
            "items": [{"id": "it1", "name": "Acai", "qty": 2, "price": 10.0, "status": "pending"}],
            "total": 20.0,
            "status": "open",
            "waiter": "adailton",
            "opened_by": "adailton",
            "customer_type": "passante",
        }
    }

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)

    with app.test_request_context(
        "/restaurant/transfer_item",
        method="POST",
        json={"source_table_id": "65", "target_table_id": "65", "item_index": 0, "qty": 1},
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response, status_code = restaurant_routes.restaurant_transfer_item.__wrapped__()

    assert status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "não podem ser iguais" in body["error"]


def test_add_batch_items_blocks_missing_required_question_server_side(monkeypatch):
    app = _make_test_app()
    state = {
        "70": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(
        restaurant_routes,
        "load_menu_items",
        lambda: [
            {
                "id": 2,
                "name": "Hambúrguer",
                "category": "Lanches",
                "price": 30.0,
                "active": True,
                "paused": False,
                "mandatory_questions": [{"question": "Ponto da carne", "type": "single_choice", "options": ["ao ponto"], "required": True}],
            }
        ],
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_order_items", lambda *args, **kwargs: {"printed_ids": [], "results": {}})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/70",
        method="POST",
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": "r04d_missing_required",
            "items_json": '[{"product":"2","qty":1}]',
        },
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("70")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/70")
    assert state["70"]["items"] == []
    assert not saves


def test_add_batch_items_accompaniment_does_not_add_extra_price(monkeypatch):
    app = _make_test_app()
    state = {
        "71": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(
        restaurant_routes,
        "load_menu_items",
        lambda: [
            {
                "id": 10,
                "name": "Prato Executivo",
                "category": "Pratos",
                "price": 25.0,
                "active": True,
                "paused": False,
                "has_accompaniments": True,
                "allowed_accompaniments": ["20"],
            },
            {
                "id": 20,
                "name": "Arroz",
                "category": "Pratos",
                "price": 7.0,
                "active": True,
                "paused": False,
                "product_type": "accompaniment_only",
            },
        ],
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_printers", lambda: [])
    monkeypatch.setattr(restaurant_routes, "print_order_items", lambda *args, **kwargs: {"printed_ids": [], "results": {}})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/71",
        method="POST",
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": "r04d_acc_no_extra",
            "items_json": '[{"product":"10","qty":1,"accompaniments":["20"]}]',
        },
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("71")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/71?batch_success=1&batch_id=r04d_acc_no_extra")
    assert len(state["71"]["items"]) == 1
    assert state["71"]["items"][0]["accompaniments"][0]["price"] == 0.0
    assert state["71"]["total"] == 25.0


def test_add_batch_items_blocks_invalid_accompaniment_type(monkeypatch):
    app = _make_test_app()
    state = {
        "72": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(
        restaurant_routes,
        "load_menu_items",
        lambda: [
            {
                "id": 11,
                "name": "Prato Família",
                "category": "Pratos",
                "price": 40.0,
                "active": True,
                "paused": False,
                "has_accompaniments": True,
                "allowed_accompaniments": ["21"],
            },
            {
                "id": 21,
                "name": "Bife",
                "category": "Pratos",
                "price": 14.0,
                "active": True,
                "paused": False,
                "product_type": "standard",
            },
        ],
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/72",
        method="POST",
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": "r04d_invalid_acc_type",
            "items_json": '[{"product":"11","qty":1,"accompaniments":["21"]}]',
        },
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("72")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/72")
    assert state["72"]["items"] == []
    assert not saves


def test_add_batch_items_blocks_duplicate_persisted_batch_id(monkeypatch):
    app = _make_test_app()
    state = {
        "73": {
            "items": [
                {
                    "id": "old1",
                    "name": "Acai",
                    "qty": 1,
                    "price": 10.0,
                    "batch_id": "batch_dup_73",
                    "complements": [],
                }
            ],
            "total": 10.0,
            "status": "open",
            "locked": False,
            "customer_type": "passante",
            "waiter": "adailton",
            "opened_by": "adailton",
        }
    }
    saves = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(
        restaurant_routes,
        "load_menu_items",
        lambda: [
            {
                "id": 2,
                "name": "Hambúrguer",
                "category": "Lanches",
                "price": 30.0,
                "active": True,
                "paused": False,
            }
        ],
    )
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: saves.append(copy.deepcopy(payload)))
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/restaurant/table/73",
        method="POST",
        data={
            "action": "add_batch_items",
            "waiter": "adailton",
            "batch_id": "batch_dup_73",
            "items_json": '[{"product":"2","qty":1}]',
        },
    ):
        _set_profile(user="adailton", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("73")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/73")
    assert len(state["73"]["items"]) == 1
    assert not saves


def test_open_table_triggers_breakfast_kds_automation_with_reliable_room_match(monkeypatch):
    app = _make_test_app()
    state = {}
    automation_calls = []
    system_logs = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {"10": {"guest_name": "Ana"}})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_restaurant_settings", lambda: {"live_music_active": False})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: system_logs.append((args, kwargs)))
    monkeypatch.setattr(
        restaurant_routes,
        "auto_set_in_preparo_from_table_open",
        lambda customer_type, customer_name, room_number, user, now=None: (
            automation_calls.append(
                {
                    "customer_type": customer_type,
                    "customer_name": customer_name,
                    "room_number": room_number,
                    "user": user,
                }
            )
            or {"success": True, "result": "updated", "room": "10"}
        ),
    )

    with app.test_request_context(
        "/restaurant/table/10",
        method="POST",
        data={"action": "open_table", "num_adults": "2", "waiter": "Carlos"},
    ):
        _set_profile(user="carlos", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("10")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/10")
    assert len(automation_calls) == 1
    assert automation_calls[0]["customer_type"] == "hospede"
    assert automation_calls[0]["room_number"] == "10"
    assert any(
        kwargs.get("action") == "KDS_CAFE_AUTO_STATUS"
        for _, kwargs in system_logs
    )


def test_open_table_keeps_safe_fallback_when_breakfast_kds_match_is_ambiguous(monkeypatch):
    app = _make_test_app()
    state = {}
    system_logs = []

    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Ana"}})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_restaurant_settings", lambda: {"live_music_active": False})
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(restaurant_routes, "log_system_action", lambda *args, **kwargs: system_logs.append((args, kwargs)))
    monkeypatch.setattr(
        restaurant_routes,
        "auto_set_in_preparo_from_table_open",
        lambda customer_type, customer_name, room_number, user, now=None: {
            "success": True,
            "result": "ambiguous",
            "rooms": ["11", "21"],
        },
    )

    with app.test_request_context(
        "/restaurant/table/11",
        method="POST",
        data={"action": "open_table", "num_adults": "2", "waiter": "Carlos"},
    ):
        _set_profile(user="carlos", role="colaborador", department="Serviço", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_table_order.__wrapped__("11")

    assert response.status_code == 302
    assert response.location.endswith("/restaurant/table/11")
    assert any(
        kwargs.get("action") == "KDS_CAFE_AUTO_AMBIGUOUS"
        for _, kwargs in system_logs
    )
