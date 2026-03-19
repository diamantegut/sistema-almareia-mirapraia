from copy import deepcopy
import inspect

from flask import Flask, session

from app.blueprints.governance import routes as governance_routes
from app.blueprints.reception import routes as reception_routes
from app.services import governance_auto_deduct_service as auto_service


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/governance/rooms", endpoint="governance.governance_rooms", view_func=lambda: "gov")
    app.add_url_rule("/reception/rooms", endpoint="reception.reception_rooms", view_func=lambda: "rec")
    app.add_url_rule("/restaurant/table/<int:table_id>", endpoint="restaurant.restaurant_table_order", view_func=lambda table_id=None: "table")
    return app


def _set_governance_user(role="supervisor"):
    session.clear()
    session.update({"user": "gov1", "role": role, "department": "Governança", "permissions": ["governanca"]})


def _set_reception_user():
    session.clear()
    session.update({"user": "recep1", "role": "recepcao", "department": "Recepção", "permissions": ["recepcao"]})


def _set_non_governance():
    session.clear()
    session.update({"user": "colab1", "role": "atendente", "department": "Recepção"})


def test_auto_deduction_checkin_applies_stock_and_audits(monkeypatch):
    audits = []
    added = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(auto_service, "load_auto_deduct_config", lambda: {"checkin": [{"product_id": "1", "product_name": "Amenity A", "qty": 2.0, "active": True}], "daily_cleaning": [], "checkout_cleaning": []})
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 10.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: added.extend(deepcopy(entries)) or len(entries))
    out = auto_service.apply_auto_deduction("checkin", "101", "recep1", "reception_checkin", event_ref="2026-03-18")
    assert out["success"] is True
    assert out["applied_count"] == 1
    assert out["dedup_scope"] == "stay"
    assert out["dedup_key"] == "checkin|101|stay|2026-03-18"
    assert added[0]["qty"] == -2.0
    assert audits[-1]["event_type"] == "checkin"


def test_auto_deduction_prevents_duplicate_for_same_event(monkeypatch):
    existing = [{"dedup_key": "checkin|101|stay|2026-03-18", "success": True}]
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(existing))
    out = auto_service.apply_auto_deduction("checkin", "101", "recep1", "reception_checkin", event_ref="2026-03-18")
    assert out["success"] is True
    assert out["duplicate"] is True
    assert out["applied_count"] == 0


def test_auto_deduction_insufficient_stock_generates_warning(monkeypatch):
    audits = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(auto_service, "load_auto_deduct_config", lambda: {"checkin": [{"product_id": "1", "product_name": "Amenity A", "qty": 3.0, "active": True}], "daily_cleaning": [], "checkout_cleaning": []})
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 1.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: len(entries))
    out = auto_service.apply_auto_deduction("checkin", "101", "recep1", "reception_checkin", event_ref="2026-03-18")
    assert out["success"] is True
    assert out["applied_count"] == 0
    assert any("Estoque insuficiente" in w for w in out["warnings"])


def test_governance_finish_cleaning_triggers_checkout_auto_deduction(monkeypatch):
    app = _make_app()
    cleaning_state = {
        "101": {
            "status": "in_progress",
            "previous_status": "dirty_checkout",
            "maid": "gov1",
            "start_time": "18/03/2026 10:00:00",
            "cleaning_cycle_ref": "CYCLE-101-A",
            "last_update": "18/03/2026 10:00",
        }
    }
    captured = {}
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: deepcopy(cleaning_state))
    monkeypatch.setattr(governance_routes, "save_cleaning_status", lambda payload: True)
    monkeypatch.setattr(governance_routes, "save_cleaning_log", lambda payload: True)
    monkeypatch.setattr(governance_routes, "apply_auto_deduction", lambda **kwargs: captured.update(kwargs) or {"applied_count": 1, "warnings": []})
    with app.test_request_context("/governance/rooms", method="POST", data={"action": "finish_cleaning", "room_number": "101"}):
        _set_governance_user()
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302
    assert captured["event_type"] == "checkout_cleaning"
    assert captured["room_number"] == "101"
    assert captured["event_context"]["cleaning_cycle_ref"] == "CYCLE-101-A"


def test_governance_auto_rule_change_requires_supervisor(monkeypatch):
    app = _make_app()
    called = {"value": False}
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {})
    monkeypatch.setattr(governance_routes, "load_auto_deduct_config", lambda: {"checkin": [], "daily_cleaning": [], "checkout_cleaning": []})
    monkeypatch.setattr(governance_routes, "list_governance_candidate_products", lambda: [])
    monkeypatch.setattr(governance_routes, "low_stock_alerts_for_auto_deduct", lambda: [])
    monkeypatch.setattr(governance_routes, "upsert_auto_rule", lambda *args, **kwargs: called.update({"value": True}) or (True, ""))
    with app.test_request_context("/governance/rooms", method="POST", data={"action": "auto_rule_add", "event_type": "checkin", "product_id": "1", "qty": "1"}):
        _set_governance_user(role="atendente")
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302
    assert called["value"] is False


def test_reception_checkin_triggers_checkin_auto_deduction(monkeypatch):
    app = _make_app()
    occupancy_state = {}
    orders_state = {}
    called = {}

    class _ReservationStub:
        ROOM_CAPACITIES = {"11": 4}

        def get_upcoming_checkins(self):
            return []

        def create_manual_reservation(self, payload):
            return {"id": "RES-1"}

        def update_guest_details(self, rid, payload):
            return True

        def save_manual_allocation(self, reservation_id, room_number, checkin, checkout):
            return True

        def update_reservation_status(self, reservation_id, status):
            return True

    monkeypatch.setattr(reception_routes, "ReservationService", _ReservationStub)
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: deepcopy(occupancy_state))
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: occupancy_state.clear() or occupancy_state.update(deepcopy(payload)) or True)
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: deepcopy(orders_state))
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: orders_state.clear() or orders_state.update(deepcopy(payload)) or True)
    monkeypatch.setattr(reception_routes, "apply_auto_deduction", lambda **kwargs: called.update(kwargs) or {"applied_count": 1, "warnings": []})
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    with app.test_request_context(
        "/reception/checkin",
        method="POST",
        data={
            "room_number": "11",
            "guest_name": "Hospede Teste",
            "checkin_date": "2026-03-18",
            "checkout_date": "2026-03-20",
            "num_adults": "2",
        },
    ):
        _set_reception_user()
        response = reception_routes.reception_checkin.__wrapped__()
    assert response.status_code == 302
    assert called["event_type"] == "checkin"
    assert called["room_number"] == "11"
    assert called["event_context"]["stay_ref"] == "RES-1"


def test_daily_cleaning_allows_legit_rework_with_new_cycle(monkeypatch):
    audits = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(auto_service, "load_auto_deduct_config", lambda: {"checkin": [], "daily_cleaning": [{"product_id": "1", "product_name": "Amenity A", "qty": 1.0, "active": True}], "checkout_cleaning": []})
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 10.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: len(entries))
    first = auto_service.apply_auto_deduction("daily_cleaning", "101", "gov1", "governance_rooms.finish_cleaning", event_context={"cleaning_cycle_ref": "CYCLE-A"})
    second_same_cycle = auto_service.apply_auto_deduction("daily_cleaning", "101", "gov1", "governance_rooms.finish_cleaning", event_context={"cleaning_cycle_ref": "CYCLE-A"})
    third_new_cycle = auto_service.apply_auto_deduction("daily_cleaning", "101", "gov1", "governance_rooms.finish_cleaning", event_context={"cleaning_cycle_ref": "CYCLE-B"})
    assert first["applied_count"] == 1
    assert second_same_cycle["duplicate"] is True
    assert third_new_cycle["applied_count"] == 1


def test_multiple_triggers_same_room_do_not_conflict(monkeypatch):
    audits = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(
        auto_service,
        "load_auto_deduct_config",
        lambda: {
            "checkin": [{"product_id": "1", "product_name": "Amenity A", "qty": 1.0, "active": True}],
            "daily_cleaning": [{"product_id": "1", "product_name": "Amenity A", "qty": 1.0, "active": True}],
            "checkout_cleaning": [{"product_id": "1", "product_name": "Amenity A", "qty": 1.0, "active": True}],
        },
    )
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 10.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: len(entries))
    out_checkin = auto_service.apply_auto_deduction("checkin", "101", "recep1", "reception_checkin", event_context={"stay_ref": "RES-1"})
    out_daily = auto_service.apply_auto_deduction("daily_cleaning", "101", "gov1", "governance_rooms.finish_cleaning", event_context={"cleaning_cycle_ref": "CYCLE-1"})
    out_checkout = auto_service.apply_auto_deduction("checkout_cleaning", "101", "gov1", "governance_rooms.finish_cleaning", event_context={"cleaning_cycle_ref": "CYCLE-2"})
    assert out_checkin["applied_count"] == 1
    assert out_daily["applied_count"] == 1
    assert out_checkout["applied_count"] == 1


def test_auto_deduction_audit_has_scope_ref_and_consistent_items(monkeypatch):
    audits = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(auto_service, "load_auto_deduct_config", lambda: {"checkin": [{"product_id": "1", "product_name": "Amenity A", "qty": 2.0, "active": True}], "daily_cleaning": [], "checkout_cleaning": []})
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 10.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: len(entries))
    auto_service.apply_auto_deduction("checkin", "101", "recep1", "reception_checkin", event_context={"stay_ref": "RES-99"})
    assert len(audits) == 1
    row = audits[0]
    assert row["dedup_scope"] == "stay"
    assert row["dedup_ref"] == "RES-99"
    assert row["items"][0]["product"] == "Amenity A"


def test_auto_paths_use_central_service_without_direct_stock_write():
    reception_src = inspect.getsource(reception_routes.reception_checkin)
    governance_src = inspect.getsource(governance_routes.governance_rooms)
    assert "apply_auto_deduction(" in reception_src
    assert "apply_auto_deduction(" in governance_src
    assert "save_stock_entry(" not in reception_src
    assert "save_stock_entry(" not in governance_src


def test_manual_stock_movement_integrity_and_insufficient(monkeypatch):
    audits = []
    captured_entries = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: deepcopy(audits))
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: audits.clear() or audits.extend(deepcopy(rows)) or True)
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 1.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: captured_entries.extend(deepcopy(entries)) or len(entries))
    out = auto_service.apply_manual_stock_movement(
        room_number="101",
        triggered_by="gov1",
        source="test",
        movement_type="frigobar_sale",
        items=[{"product_id": "1", "qty": -2.0}, {"product_id": "1", "qty": 1.0}],
        metadata={"invoice": "Teste Manual"},
    )
    assert out["success"] is True
    assert out["applied_count"] == 1
    assert captured_entries[0]["manual_event_type"] == "frigobar_sale"
    assert captured_entries[0]["invoice"] == "Teste Manual"
    assert len(out["insufficient"]) == 1


def test_manual_stock_movement_strict_blocks_insufficient(monkeypatch):
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 1.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: len(entries))
    out = auto_service.apply_manual_stock_movement(
        room_number="101",
        triggered_by="gov1",
        source="test",
        movement_type="frigobar_sale",
        items=[{"product_id": "1", "qty": -2.0}],
        strict=True,
    )
    assert out["success"] is False
    assert out["applied_count"] == 0


def test_manual_stock_movement_allows_negative_when_enabled(monkeypatch):
    captured_entries = []
    monkeypatch.setattr(auto_service, "load_auto_deduct_audit", lambda: [])
    monkeypatch.setattr(auto_service, "save_auto_deduct_audit", lambda rows: True)
    monkeypatch.setattr(auto_service, "load_products", lambda: [{"id": "1", "name": "Amenity A", "price": 5.0}])
    monkeypatch.setattr(auto_service, "_balance_map", lambda products: {"Amenity A": 0.0})
    monkeypatch.setattr(auto_service, "add_stock_entries_batch", lambda entries: captured_entries.extend(deepcopy(entries)) or len(entries))
    out = auto_service.apply_manual_stock_movement(
        room_number="101",
        triggered_by="gov1",
        source="test",
        movement_type="frigobar_sale",
        items=[{"product_id": "1", "qty": -2.0}],
        allow_negative_stock=True,
    )
    assert out["success"] is True
    assert out["applied_count"] == 1
    assert captured_entries[0]["qty"] == -2.0
    assert len(out["insufficient"]) == 1


def test_governance_deduct_coffee_uses_central_manual_service(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "492", "name": "Café Capsula (GOVERNANÇA)", "price": 3.0}])
    captured = {}
    monkeypatch.setattr(
        governance_routes,
        "apply_manual_stock_movement",
        lambda **kwargs: captured.update(kwargs) or {"success": True, "applied_count": 1, "warnings": [], "insufficient": []},
    )
    monkeypatch.setattr(governance_routes.LoggerService, "log_acao", lambda *args, **kwargs: None)
    with app.test_request_context("/governance/deduct_coffee", method="POST", json={"room_number": "101"}):
        _set_governance_user()
        response = governance_routes.governance_deduct_coffee.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert captured["movement_type"] == "coffee_capsule_deduction"
    assert captured["room_number"] == "101"


def test_governance_undo_coffee_uses_central_manual_service(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "492", "name": "Café Capsula (GOVERNANÇA)", "price": 3.0}])
    captured = {}
    monkeypatch.setattr(
        governance_routes,
        "apply_manual_stock_movement",
        lambda **kwargs: captured.update(kwargs) or {"success": True, "applied_count": 1, "warnings": [], "insufficient": []},
    )
    monkeypatch.setattr(governance_routes.LoggerService, "log_acao", lambda *args, **kwargs: None)
    with app.test_request_context("/governance/undo_deduct_coffee", method="POST", json={"room_number": "101"}):
        _set_governance_user()
        response = governance_routes.governance_undo_deduct_coffee.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert captured["movement_type"] == "coffee_capsule_reversal"
    assert captured["room_number"] == "101"


def test_governance_launch_frigobar_uses_central_manual_service(monkeypatch):
    app = _make_app()
    captured_calls = []
    room_charges_state = []
    monkeypatch.setattr(
        governance_routes,
        "load_menu_items",
        lambda: [
            {"id": "M1", "name": "Água Frigobar", "price": 10.0, "category": "Frigobar", "recipe": [{"ingredient_id": "1", "qty": 1}]}
        ],
    )
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "1", "name": "Água 500ml (GOVERNANÇA)", "price": 2.0}])
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {"101": {"guest_name": "Hospede"}})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {})
    monkeypatch.setattr(governance_routes, "load_room_charges", lambda: deepcopy(room_charges_state))
    monkeypatch.setattr(governance_routes, "save_room_charges", lambda payload: room_charges_state.clear() or room_charges_state.extend(deepcopy(payload)) or True)
    monkeypatch.setattr(
        governance_routes,
        "apply_manual_stock_movement",
        lambda **kwargs: captured_calls.append(deepcopy(kwargs)) or {"success": True, "applied_count": 1, "warnings": [], "insufficient": [], "applied_items": [{"product_id": "1", "product_name": "Água 500ml (GOVERNANÇA)", "qty": -2.0}]},
    )
    monkeypatch.setattr(governance_routes.LoggerService, "log_acao", lambda *args, **kwargs: None)
    with app.test_request_context(
        "/governance/launch_frigobar",
        method="POST",
        json={"room_number": "101", "items": [{"id": "M1", "qty": 2}]},
    ):
        _set_governance_user()
        response = governance_routes.governance_launch_frigobar.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert len(captured_calls) == 1
    assert captured_calls[0]["allow_negative_stock"] is True
    assert captured_calls[0]["movement_type"] == "frigobar_sale"
    assert captured_calls[0]["room_number"] == "101"
    assert captured_calls[0]["items"][0]["qty"] == -2.0
    assert room_charges_state[0]["type"] == "minibar"


def test_governance_launch_frigobar_allows_when_stock_insufficient_with_warning(monkeypatch):
    app = _make_app()
    room_charges_state = []
    monkeypatch.setattr(governance_routes, "load_menu_items", lambda: [{"id": "M1", "name": "Água Frigobar", "price": 10.0, "category": "Frigobar", "recipe": [{"ingredient_id": "1", "qty": 1}]}])
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "1", "name": "Água 500ml (GOVERNANÇA)", "price": 2.0}])
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {"101": {"guest_name": "Hospede"}})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {})
    monkeypatch.setattr(governance_routes, "load_room_charges", lambda: deepcopy(room_charges_state))
    monkeypatch.setattr(governance_routes, "save_room_charges", lambda payload: room_charges_state.clear() or room_charges_state.extend(deepcopy(payload)) or True)
    monkeypatch.setattr(
        governance_routes,
        "apply_manual_stock_movement",
        lambda **kwargs: {"success": True, "warnings": ["Estoque insuficiente para Água 500ml (GOVERNANÇA): saldo 1.0, necessário 2.0"], "insufficient": [{"product": "Água 500ml (GOVERNANÇA)", "needed": 2.0, "balance": 1.0}], "applied_count": 1, "applied_items": [{"product_id": "1", "product_name": "Água 500ml (GOVERNANÇA)", "qty": -2.0}]},
    )
    with app.test_request_context("/governance/launch_frigobar", method="POST", json={"room_number": "101", "items": [{"id": "M1", "qty": 2}]}):
        _set_governance_user()
        response = governance_routes.governance_launch_frigobar.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["stock_warning"] is True
    assert len(payload["warnings"]) == 1
    assert len(room_charges_state) == 1
    assert room_charges_state[0]["type"] == "minibar"


def test_governance_launch_frigobar_blocks_item_without_recipe(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(governance_routes, "load_menu_items", lambda: [{"id": "M1", "name": "Água Frigobar", "price": 10.0, "category": "Frigobar"}])
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "1", "name": "Água 500ml (GOVERNANÇA)", "price": 2.0}])
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {"101": {"guest_name": "Hospede"}})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {})
    with app.test_request_context("/governance/launch_frigobar", method="POST", json={"room_number": "101", "items": [{"id": "M1", "qty": 1}]}):
        _set_governance_user()
        response, status = governance_routes.governance_launch_frigobar.__wrapped__()
    payload = response.get_json()
    assert status == 400
    assert payload["success"] is False
    assert "sem ficha técnica" in payload["error"]


def test_governance_launch_frigobar_blocks_room_out_of_context(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {"101": {"status": "clean"}})
    with app.test_request_context("/governance/launch_frigobar", method="POST", json={"room_number": "101", "items": [{"id": "M1", "qty": 1}]}):
        _set_governance_user()
        response, status = governance_routes.governance_launch_frigobar.__wrapped__()
    payload = response.get_json()
    assert status == 400
    assert payload["success"] is False
    assert "fora de contexto operacional" in payload["error"]


def test_governance_launch_frigobar_allows_dirty_checkout_context(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(governance_routes, "load_menu_items", lambda: [{"id": "M1", "name": "Água Frigobar", "price": 10.0, "category": "Frigobar", "recipe": [{"ingredient_id": "1", "qty": 1}]}])
    monkeypatch.setattr(governance_routes, "load_products", lambda: [{"id": "1", "name": "Água 500ml (GOVERNANÇA)", "price": 2.0}])
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: {"101": {"status": "dirty_checkout"}})
    monkeypatch.setattr(governance_routes, "load_room_charges", lambda: [])
    monkeypatch.setattr(governance_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(governance_routes.LoggerService, "log_acao", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        governance_routes,
        "apply_manual_stock_movement",
        lambda **kwargs: calls.append(kwargs) or {"success": True, "applied_count": 1, "warnings": [], "insufficient": [], "applied_items": [{"product_id": "1", "product_name": "Água 500ml (GOVERNANÇA)", "qty": -1.0}]},
    )
    with app.test_request_context("/governance/launch_frigobar", method="POST", json={"room_number": "101", "items": [{"id": "M1", "qty": 1}]}):
        _set_governance_user()
        response = governance_routes.governance_launch_frigobar.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert len(calls) == 1


def test_governance_launch_frigobar_requires_governance_access():
    app = _make_app()
    with app.test_request_context("/governance/launch_frigobar", method="POST", json={"room_number": "101", "items": [{"id": "M1", "qty": 1}]}):
        _set_non_governance()
        response, status = governance_routes.governance_launch_frigobar.__wrapped__()
    assert status == 403
    assert response.get_json()["success"] is False


def test_manual_governance_flows_do_not_write_stock_directly():
    deduct_src = inspect.getsource(governance_routes.governance_deduct_coffee)
    undo_src = inspect.getsource(governance_routes.governance_undo_deduct_coffee)
    frigobar_src = inspect.getsource(governance_routes.governance_launch_frigobar)
    assert "apply_manual_stock_movement(" in deduct_src
    assert "apply_manual_stock_movement(" in undo_src
    assert "apply_manual_stock_movement(" in frigobar_src
    assert "save_stock_entry(" not in deduct_src
    assert "save_stock_entry(" not in undo_src
    assert "save_stock_entry(" not in frigobar_src
