from flask import Flask, session
import pytest
import json

from app.blueprints.restaurant import routes as restaurant_routes


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


def _configure_common_get_mocks(monkeypatch, state):
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {"12": {"guest_name": "Maria Hóspede"}})
    monkeypatch.setattr(restaurant_routes, "load_complements", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {"garcom1": {"full_name": "Garçom Um"}})
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_flavor_groups", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_observations", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_settings", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_payment_methods", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_restaurant_table_settings", lambda: {"disabled_tables": []})
    monkeypatch.setattr(restaurant_routes, "get_current_cashier", lambda **kwargs: None)


def test_remove_item_blocks_non_supervisor_ajax(monkeypatch, tmp_path):
    app = _make_test_app()
    state = {
        "90": {
            "items": [{"id": "i1", "name": "Suco", "qty": 1, "price": 10.0, "complements": []}],
            "total": 10.0,
            "status": "open",
            "customer_type": "passante",
            "customer_name": "Ana",
            "opened_by": "garcom1",
        }
    }
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)

    with app.test_request_context(
        "/restaurant/table/90",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"action": "remove_item", "item_id": "i1", "cancellation_reason": "erro"},
    ):
        _set_profile(role="colaborador", user="op1")
        response = restaurant_routes.restaurant_table_order.__wrapped__("90")

    (tmp_path / "cancel_blocked_response.json").write_text(
        json.dumps(response[0].get_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert response[1] == 403
    assert "Somente supervisor ou acima" in response[0].get_json()["error"]


def test_remove_item_allows_supervisor_and_generates_logs(monkeypatch, tmp_path):
    app = _make_test_app()
    state = {
        "91": {
            "items": [{"id": "i1", "name": "Suco", "qty": 1, "price": 10.0, "complements": [], "product_id": "10"}],
            "total": 10.0,
            "status": "open",
            "customer_type": "passante",
            "customer_name": "Ana",
            "opened_by": "garcom1",
        }
    }
    logs = []
    sec_logs = []
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: [])
    monkeypatch.setattr(restaurant_routes, "load_products", lambda: [])
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: logs.append((args, kwargs)))
    monkeypatch.setattr(restaurant_routes, "log_security_audit", lambda *args, **kwargs: sec_logs.append((args, kwargs)))

    with app.test_request_context(
        "/restaurant/table/91",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest"},
        data={"action": "remove_item", "item_id": "i1", "cancellation_reason": "pedido duplicado"},
    ):
        _set_profile(role="supervisor", user="sup1")
        response = restaurant_routes.restaurant_table_order.__wrapped__("91")

    (tmp_path / "cancel_authorized_response.json").write_text(
        json.dumps(response.get_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "cancel_authorized_order_after.json").write_text(
        json.dumps(state["91"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "cancel_authorized_audit_flags.json").write_text(
        json.dumps(
            {
                "log_action_called": any((args and args[0] == "Item Removido") for args, _ in logs),
                "security_audit_called": any(kwargs.get("event_type") == "ITEM_REMOVAL" for _, kwargs in sec_logs),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert response.status_code == 200
    assert state["91"]["items"] == []
    assert state["91"]["total"] == 0
    assert any((args and args[0] == "Item Removido") for args, _ in logs)
    assert any(kwargs.get("event_type") == "ITEM_REMOVAL" for _, kwargs in sec_logs)


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"),
    ],
)
def test_table_header_context_contains_required_fields_and_opened_by_persists(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    state = {
        "92": {
            "items": [],
            "total": 0.0,
            "status": "open",
            "num_adults": 2,
            "customer_type": "hospede",
            "customer_name": "Maria Hóspede",
            "room_number": "12",
            "opened_by": "garcom1",
        }
    }
    _configure_common_get_mocks(monkeypatch, state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(restaurant_routes, "render_template", lambda tpl, **ctx: ctx)

    with app.test_request_context(
        "/restaurant/table/92",
        method="POST",
        headers={"User-Agent": user_agent},
        data={
            "action": "update_pax",
            "num_adults": "3",
            "customer_type": "passante",
            "customer_name": "Cliente Passante",
            "opened_by": "operador_caixa",
        },
    ):
        _set_profile(role="supervisor", user="sup1")
        response = restaurant_routes.restaurant_table_order.__wrapped__("92")
    assert response.status_code == 302
    assert state["92"]["opened_by"] == "operador_caixa"
    assert state["92"]["customer_type"] == "passante"
    assert state["92"]["customer_name"] == "Cliente Passante"
    assert state["92"]["num_adults"] == 3

    with app.test_request_context("/restaurant/table/92", method="GET", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user="sup1")
        ctx = restaurant_routes.restaurant_table_order.__wrapped__("92")
    (tmp_path / f"header_{client_type}_context.json").write_text(
        json.dumps(
            {
                "customer_name": ctx["order"]["customer_name"],
                "num_adults": ctx["order"]["num_adults"],
                "customer_type": ctx["order"]["customer_type"],
                "room_number": ctx["order"].get("room_number"),
                "opened_by_display": ctx["opened_by_display"],
                "user_agent": user_agent,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / f"header_{client_type}_order_persisted.json").write_text(
        json.dumps(state["92"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert ctx["order"]["customer_name"] == "Cliente Passante"
    assert ctx["order"]["num_adults"] == 3
    assert ctx["order"]["customer_type"] == "passante"
    assert ctx["opened_by_display"] == "operador_caixa"
