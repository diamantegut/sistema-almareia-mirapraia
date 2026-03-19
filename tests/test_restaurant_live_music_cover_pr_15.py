import copy
import json

import pytest
from flask import Flask, session

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


def _set_profile(role="supervisor", user="tester"):
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


def _setup_common(monkeypatch, orders_state, settings_state):
    menu_items = [
        {"id": "32", "name": "Couvert Artístico", "price": 12.0, "category": "Couverts"},
        {"id": "10", "name": "Prato", "price": 30.0, "category": "Pratos"},
    ]
    actions = []
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: orders_state)
    monkeypatch.setattr(restaurant_routes, "save_table_orders", lambda payload: _replace_state(orders_state, payload))
    monkeypatch.setattr(restaurant_routes, "load_restaurant_settings", lambda: settings_state)
    monkeypatch.setattr(restaurant_routes, "save_restaurant_settings", lambda payload: _replace_state(settings_state, payload))
    monkeypatch.setattr(restaurant_routes, "load_menu_items", lambda: copy.deepcopy(menu_items))
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {"12": {"guest_name": "Hospede 12"}})
    monkeypatch.setattr(restaurant_routes, "log_action", lambda *args, **kwargs: actions.append({"args": args, "kwargs": kwargs}))
    return actions


def _cover_items(order):
    return [item for item in order.get("items", []) if str(item.get("source")) == "auto_cover_activation" or bool(item.get("live_music_cover"))]


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_scenario_a_activate_live_music_adds_cover_to_open_passerby_tables(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {
        "70": {"items": [], "total": 0.0, "status": "open", "customer_type": "passante", "num_adults": 2},
        "71": {"items": [], "total": 0.0, "status": "open", "customer_type": "passante", "num_adults": 3},
    }
    settings_state = {"live_music_active": False}
    _setup_common(monkeypatch, orders_state, settings_state)

    with app.test_request_context("/restaurant/toggle_live_music", method="POST", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response = restaurant_routes.toggle_live_music.__wrapped__()
    assert response.status_code == 302
    assert bool(settings_state.get("live_music_active")) is True
    assert len(_cover_items(orders_state["70"])) == 1
    assert len(_cover_items(orders_state["71"])) == 1
    assert float(_cover_items(orders_state["70"])[0]["qty"]) == 2.0
    assert float(_cover_items(orders_state["71"])[0]["qty"]) == 3.0
    (tmp_path / f"scenario_a_{client_type}_orders.json").write_text(json.dumps(orders_state, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"),
    ],
)
def test_scenario_b_guest_tables_do_not_receive_cover(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {
        "5": {"items": [], "total": 0.0, "status": "open", "customer_type": "hospede", "num_adults": 2, "room_number": "05"},
        "72": {"items": [], "total": 0.0, "status": "open", "customer_type": "passante", "num_adults": 1},
    }
    settings_state = {"live_music_active": False}
    _setup_common(monkeypatch, orders_state, settings_state)

    with app.test_request_context("/restaurant/toggle_live_music", method="POST", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response = restaurant_routes.toggle_live_music.__wrapped__()
    assert response.status_code == 302
    assert len(_cover_items(orders_state["5"])) == 0
    assert len(_cover_items(orders_state["72"])) == 1
    (tmp_path / f"scenario_b_{client_type}_orders.json").write_text(json.dumps(orders_state, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_scenario_c_new_passerby_opened_with_live_music_active_gets_cover(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {}
    settings_state = {"live_music_active": True}
    _setup_common(monkeypatch, orders_state, settings_state)

    with app.test_request_context(
        "/restaurant/table/73",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"action": "open_table", "num_adults": "4", "waiter": "garcom1", "customer_type": "passante", "customer_name": "Cliente"},
    ):
        _set_profile(role="colaborador", user=f"op_{client_type}")
        response = restaurant_routes.restaurant_table_order.__wrapped__("73")
    assert response.status_code == 302
    assert "73" in orders_state
    covers = _cover_items(orders_state["73"])
    assert len(covers) == 1
    assert float(covers[0]["qty"]) == 4.0
    assert float(orders_state["73"]["total"]) == 48.0
    (tmp_path / f"scenario_c_{client_type}_orders.json").write_text(json.dumps(orders_state, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"),
    ],
)
def test_scenario_d_toggle_off_on_does_not_duplicate_and_syncs_with_adults(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    orders_state = {
        "74": {"items": [], "total": 0.0, "status": "open", "customer_type": "passante", "num_adults": 2, "customer_name": "Mesa D"},
    }
    settings_state = {"live_music_active": False}
    _setup_common(monkeypatch, orders_state, settings_state)

    with app.test_request_context("/restaurant/toggle_live_music", method="POST", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response_on = restaurant_routes.toggle_live_music.__wrapped__()
    assert response_on.status_code == 302
    assert len(_cover_items(orders_state["74"])) == 1
    first_cover_id = _cover_items(orders_state["74"])[0]["id"]

    with app.test_request_context("/restaurant/toggle_live_music", method="POST", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response_off = restaurant_routes.toggle_live_music.__wrapped__()
    assert response_off.status_code == 302
    assert bool(settings_state.get("live_music_active")) is False
    assert len(_cover_items(orders_state["74"])) == 1

    with app.test_request_context("/restaurant/toggle_live_music", method="POST", headers={"User-Agent": user_agent}):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response_on_again = restaurant_routes.toggle_live_music.__wrapped__()
    assert response_on_again.status_code == 302
    covers_after = _cover_items(orders_state["74"])
    assert len(covers_after) == 1
    assert covers_after[0]["id"] == first_cover_id

    with app.test_request_context(
        "/restaurant/table/74",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"action": "update_pax", "num_adults": "3", "customer_type": "passante", "customer_name": "Mesa D"},
    ):
        _set_profile(role="supervisor", user=f"sup_{client_type}")
        response_update = restaurant_routes.restaurant_table_order.__wrapped__("74")
    assert response_update.status_code == 302
    covers_updated = _cover_items(orders_state["74"])
    assert len(covers_updated) == 1
    assert float(covers_updated[0]["qty"]) == 3.0
    (tmp_path / f"scenario_d_{client_type}_orders.json").write_text(json.dumps(orders_state, ensure_ascii=False, indent=2), encoding="utf-8")


def test_toggle_live_music_requires_supervisor_or_above(monkeypatch):
    app = _make_test_app()
    orders_state = {"70": {"items": [], "total": 0.0, "status": "open", "customer_type": "passante", "num_adults": 2}}
    settings_state = {"live_music_active": False}
    _setup_common(monkeypatch, orders_state, settings_state)

    with app.test_request_context("/restaurant/toggle_live_music", method="POST"):
        _set_profile(role="colaborador", user="op1")
        response = restaurant_routes.toggle_live_music.__wrapped__()
    assert response.status_code == 302
    assert bool(settings_state.get("live_music_active")) is False
