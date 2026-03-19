from flask import Flask, session
from datetime import datetime

from app.blueprints.reception import routes as reception_routes


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    return app


def _set_user():
    session.clear()
    session.update({"user": "rec1", "role": "supervisor", "department": "Recepção", "permissions": ["recepcao"]})


def _stub_service_for_guest_details(reservation):
    class _ServiceStub:
        def get_reservation_by_id(self, rid):
            return dict(reservation)

        def merge_overrides_into_reservation(self, rid, res):
            return dict(res)

        def get_guest_details(self, rid):
            return {"personal_info": {"name": reservation.get("guest_name", "Hóspede")}, "history": [], "operational_info": {}}

        def build_unified_reservation_record(self, reservation_id):
            return {"id": reservation_id}

    return _ServiceStub


def test_guest_details_financial_filters_old_room_charges_outside_stay(monkeypatch):
    app = _make_app()
    reservation = {"id": "RES-901", "guest_name": "Hóspede", "amount": "1200.00", "paid_amount": "200.00", "to_receive": "1000.00", "room": "11", "checkin": "20/03/2026", "checkout": "22/03/2026"}
    monkeypatch.setattr(reception_routes, "ReservationService", _stub_service_for_guest_details(reservation))
    monkeypatch.setattr(
        reception_routes,
        "load_room_occupancy",
        lambda: {"11": {"reservation_id": "RES-901", "guest_name": "Hóspede", "checkin": "20/03/2026", "checkout": "22/03/2026"}},
    )
    monkeypatch.setattr(
        reception_routes,
        "load_room_charges",
        lambda: [
            {"id": "C_OLD", "room_number": "11", "status": "paid", "total": 500.0, "date": "10/03/2026 10:00", "items": [{"name": "Antigo"}]},
            {"id": "C_CUR", "room_number": "11", "status": "pending", "total": 120.0, "date": "21/03/2026 11:00", "items": [{"name": "Atual"}]},
        ],
    )
    with app.test_request_context("/api/guest/details?reservation_id=RES-901"):
        _set_user()
        response = reception_routes.api_guest_details.__wrapped__(None)
    payload = response.get_json()
    data = payload["data"]
    assert data["consumption_financial"]["total"] == 120.0
    assert data["consumption_financial"]["pending"] == 120.0


def test_guest_update_saves_personal_fiscal_and_operational(monkeypatch):
    app = _make_app()
    captured = {}

    class _ServiceUpdateStub:
        def update_guest_details(self, rid, payload):
            captured["rid"] = rid
            captured["payload"] = payload
            return True

    monkeypatch.setattr(reception_routes, "ReservationService", _ServiceUpdateStub)
    with app.test_request_context(
        "/api/guest/update",
        method="POST",
        json={
            "reservation_id": "RES-902",
            "personal_info": {"name": "Maria", "doc_id": "123"},
            "fiscal_info": {"cpf_cnpj": "12345678900", "razao_social": "Maria LTDA"},
            "operational_info": {"allergies": "Lactose"},
        },
    ):
        _set_user()
        response = reception_routes.api_guest_update.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert captured["rid"] == "RES-902"
    assert captured["payload"]["guest_name"] == "Maria"
    assert "fiscal_info" in captured["payload"]
    assert "operational_info" in captured["payload"]


def test_reservation_payment_method_filter_supports_aliases():
    method_a = {"id": "pix", "name": "PIX", "available_in": "reservation"}
    method_b = {"id": "cartao", "name": "Cartão", "available_in": ["reservas"]}
    assert reception_routes._payment_method_enabled_for(method_a, "reservations") is True
    assert reception_routes._payment_method_enabled_for(method_b, "reservations") is True


def test_unified_modal_has_edit_fields_for_operational_and_fiscal():
    with open("app/templates/partials/guest_unified_modal.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "vg_edit_panel" in html
    assert "vg_edit_fiscal_doc" in html
    assert "vg_edit_fiscal_name" in html
    assert "vg_edit_allergies" in html
    assert "vg_edit_dietary" in html
    assert "vg_edit_vip" in html


def test_guest_view_js_supports_unified_edit_save_flow():
    with open("app/static/js/guest_view.js", "r", encoding="utf-8") as f:
        js = f.read()
    assert "function saveUnifiedGuestData()" in js
    assert "fetch('/api/guest/update'" in js
    assert "function cancelGuestEdit()" in js
    assert "function switchToEdit()" in js


def test_checkin_script_has_room_preselection_and_payment_method_fallback():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "let preselectedCheckinRoom = ''" in html
    assert "else if (preselectedCheckinRoom)" in html
    assert "fetch('/api/payment-methods')" in html


def test_build_ready_checkin_preloads_only_when_room_is_inspected_and_today():
    today = datetime.now().date()
    upcoming = [
        {"id": "R1", "guest_name": "Ana", "room": "12", "checkin": today.strftime("%d/%m/%Y"), "status": "Confirmada"},
        {"id": "R2", "guest_name": "Bruno", "room": "14", "checkin": today.strftime("%d/%m/%Y"), "status": "Confirmada"},
        {"id": "R3", "guest_name": "Caio", "room": "15", "checkin": today.strftime("%d/%m/%Y"), "status": "Cancelada"},
    ]
    occupancy = {"14": {"guest_name": "Oc"}}  # occupied blocks preload
    cleaning = {"12": {"status": "inspected"}, "14": {"status": "inspected"}, "15": {"status": "inspected"}}
    out = reception_routes._build_ready_checkin_preloads(upcoming, occupancy, cleaning, today_date=today)
    assert out["ready_preloads"]["12"]["id"] == "R1"
    assert "14" not in out["ready_preloads"]
    assert "R3" in out["skipped"]["cancelled_or_noshow"]


def test_build_ready_checkin_preloads_blocks_conflicting_same_room():
    today = datetime.now().date()
    upcoming = [
        {"id": "A", "guest_name": "A", "room": "12", "checkin": today.strftime("%d/%m/%Y"), "status": "Confirmada"},
        {"id": "B", "guest_name": "B", "room": "12", "checkin": today.strftime("%d/%m/%Y"), "status": "Confirmada"},
    ]
    out = reception_routes._build_ready_checkin_preloads(upcoming, {}, {"12": {"status": "inspected"}}, today_date=today)
    assert "12" not in out["ready_preloads"]
    assert "12" in out["conflicts"]


def test_rooms_template_has_preload_ui_and_action():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Pré-carregada para check-in" in html
    assert "Check-in (Reserva Sugerida)" in html
    assert "openCheckinModalWithReservation" in html
