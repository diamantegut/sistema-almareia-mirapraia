import copy
import json

import pytest
from flask import Flask, session

from app.blueprints.reception import routes as reception_routes
from app.blueprints.restaurant import routes as restaurant_routes
from app.services import waiting_list_service, data_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule("/restaurant/tables", endpoint="restaurant.restaurant_tables", view_func=lambda: "tables")
    app.add_url_rule("/restaurant/table/<table_id>", endpoint="restaurant.restaurant_table_order", view_func=lambda table_id: f"table-{table_id}")
    app.add_url_rule("/fila", endpoint="restaurant.public_waiting_list", view_func=lambda: "fila")
    app.add_url_rule("/reception/dashboard", endpoint="reception.reception_dashboard", view_func=lambda: "dashboard")
    app.add_url_rule("/reception/waiting-list", endpoint="reception.reception_waiting_list", view_func=lambda: "waiting-list")
    return app


def _set_profile(role="colaborador", user="op", department="Recepção", permissions=None):
    session.clear()
    session.update(
        {
            "user": user,
            "role": role,
            "department": department,
            "permissions": permissions or [],
        }
    )


def _replace_state(state_ref, payload):
    cloned = copy.deepcopy(payload)
    state_ref.clear()
    state_ref.update(cloned)
    return True


def _bootstrap_waiting_file(monkeypatch, tmp_path):
    waiting_file = tmp_path / "waiting_list.json"
    monkeypatch.setattr(waiting_list_service, "WAITING_LIST_FILE", str(waiting_file))
    monkeypatch.setattr(waiting_list_service, "_can_use_db", lambda: False)
    waiting_list_service.save_waiting_data(
        {
            "queue": [],
            "history": [],
            "events": [],
            "settings": {
                "is_open": True,
                "average_wait_per_party": 10,
                "max_queue_size": 100,
                "cutoff_hour": 23,
                "max_party_size": 12,
            },
        }
    )


def _patch_waiting_list_dashboard_dependencies(monkeypatch):
    monkeypatch.setattr(reception_routes, "render_template", lambda tpl, **ctx: ctx)
    monkeypatch.setattr(waiting_list_service, "get_waiting_list", lambda: [])
    monkeypatch.setattr(waiting_list_service, "get_settings", lambda: {"is_open": True, "call_presence_sla_minutes": 15, "call_response_timeout_minutes": 15})
    monkeypatch.setattr(
        waiting_list_service,
        "get_queue_metrics",
        lambda: {
            "active_count": 0,
            "avg_wait_today": 0,
            "called_today": 0,
            "seated_today": 0,
            "desist_today": 0,
            "cancelled_today": 0,
            "avg_called_to_seated_today": 0,
            "conversion_to_seated_pct": 0,
        },
    )
    monkeypatch.setattr(waiting_list_service, "get_queue_events", lambda limit=200: [])
    monkeypatch.setattr(waiting_list_service, "get_queue_history_filtered", lambda filters=None, limit=2000: [])
    monkeypatch.setattr(waiting_list_service, "get_seated_customers", lambda limit=40: [])
    monkeypatch.setattr(waiting_list_service, "list_available_tables", lambda: ["70", "71"])
    monkeypatch.setattr(waiting_list_service, "get_table_status_catalog", lambda: [])
    monkeypatch.setattr(waiting_list_service, "get_supported_countries", lambda: [{"code": "BR", "dial_code": "55"}])
    monkeypatch.setattr(waiting_list_service, "get_capacity_aware_queue_reference", lambda target_capacity=4, limit=50: [])


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_scenario_a_public_queue_entry_persists(monkeypatch, tmp_path, client_type, user_agent):
    app = _make_test_app()
    _bootstrap_waiting_file(monkeypatch, tmp_path)

    with app.test_request_context(
        "/fila",
        method="POST",
        headers={"User-Agent": user_agent},
        data={
            "submission_token": "tok-1",
            "name": "Carlos Fila",
            "phone": "(11) 97777-1111",
            "party_size": "3",
            "country_code": "BR",
            "country_dial_code": "55",
        },
    ):
        session["waiting_list_submission_token"] = "tok-1"
        response = restaurant_routes.public_waiting_list()
    assert response.status_code == 302
    data = waiting_list_service.load_waiting_data()
    assert len(data.get("queue", [])) == 1
    entry = data["queue"][0]
    assert entry["name"] == "Carlos Fila"
    assert int(entry["party_size"]) == 3
    assert str(entry.get("status")).lower() == "aguardando"
    (tmp_path / f"scenario_a_{client_type}_queue.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"),
    ],
)
def test_scenario_b_call_next_updates_state(monkeypatch, tmp_path, client_type, user_agent):
    app = _make_test_app()
    _bootstrap_waiting_file(monkeypatch, tmp_path)
    created, error = waiting_list_service.add_customer(
        name="Ana Espera",
        phone="(11) 98888-0001",
        party_size=2,
        country_code="BR",
        created_by="tester",
        source="fila_virtual",
    )
    assert error is None
    with app.test_request_context(
        "/reception/waiting-list/call-next",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"channel": "whatsapp", "reason": "chamar proximo"},
    ):
        _set_profile(role="colaborador", user=f"rec_{client_type}", department="Recepção")
        response = reception_routes.call_next_queue_customer.__wrapped__()
    assert response.status_code == 302
    updated = waiting_list_service.get_customer_entry(created["entry"]["id"])
    assert str(updated.get("status")).lower() == "chamado"
    assert int(updated.get("call_count", 0)) >= 1
    (tmp_path / f"scenario_b_{client_type}_entry.json").write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_scenario_c_seat_customer_loads_table_header_data(monkeypatch, tmp_path, client_type, user_agent):
    app = _make_test_app()
    _bootstrap_waiting_file(monkeypatch, tmp_path)
    table_orders_state = {}
    monkeypatch.setattr(data_service, "load_table_orders", lambda: table_orders_state)
    monkeypatch.setattr(data_service, "save_table_orders", lambda payload: _replace_state(table_orders_state, payload))
    monkeypatch.setattr(data_service, "load_restaurant_table_settings", lambda: {"disabled_tables": []})
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: table_orders_state)
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: _replace_state(table_orders_state, payload))

    created, error = waiting_list_service.add_customer(
        name="Bruna Sentar",
        phone="(11) 97777-3333",
        party_size=4,
        country_code="BR",
        created_by="tester",
        source="fila_virtual",
    )
    assert error is None
    customer_id = created["entry"]["id"]

    with app.test_request_context(
        f"/reception/waiting-list/seat/{customer_id}",
        method="POST",
        headers={"User-Agent": user_agent},
        data={"table_id": "70", "reason": "sentar cliente da fila"},
    ):
        _set_profile(role="colaborador", user=f"rec_{client_type}", department="Recepção")
        response = reception_routes.seat_queue_customer.__wrapped__(customer_id)
    assert response.status_code == 302
    assert "70" in table_orders_state
    order = table_orders_state["70"]
    assert order["customer_name"] == "Bruna Sentar"
    assert int(order["num_adults"]) == 4
    assert order["customer_type"] == "passante"
    assert order.get("waiting_list_entry_id") == customer_id
    assert order.get("opened_by") == f"rec_{client_type}"
    assert order.get("waiting_list_phone")
    (tmp_path / f"scenario_c_{client_type}_table_order.json").write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")


def test_scenario_d_authorization_access_matrix(monkeypatch, tmp_path):
    app = _make_test_app()
    _patch_waiting_list_dashboard_dependencies(monkeypatch)

    with app.test_request_context("/reception/waiting-list", method="GET"):
        _set_profile(role="colaborador", user="rec1", department="Recepção")
        reception_ok = reception_routes.reception_waiting_list.__wrapped__()
    assert isinstance(reception_ok, dict)

    with app.test_request_context("/reception/waiting-list", method="GET"):
        _set_profile(role="colaborador", user="rest1", department="Serviço", permissions=["restaurante_mirapraia"])
        restaurant_ok = reception_routes.reception_waiting_list.__wrapped__()
    assert isinstance(restaurant_ok, dict)

    with app.test_request_context("/reception/waiting-list", method="GET"):
        _set_profile(role="colaborador", user="ext1", department="Financeiro")
        blocked = reception_routes.reception_waiting_list.__wrapped__()
    assert blocked.status_code == 302
    (tmp_path / "scenario_d_authorization_matrix.json").write_text(
        json.dumps(
            {
                "reception_access": isinstance(reception_ok, dict),
                "restaurant_access": isinstance(restaurant_ok, dict),
                "external_blocked_status_code": int(getattr(blocked, "status_code", 0)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
