from flask import Flask, session

from app.blueprints.reception import routes as reception_routes


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    return app


def _set_user():
    session.clear()
    session.update({"user": "rec1", "role": "supervisor", "department": "Recepção", "permissions": ["recepcao"]})


def _stub_service(reservation):
    class _ServiceStub:
        def get_reservation_by_id(self, rid):
            return dict(reservation)

        def merge_overrides_into_reservation(self, rid, res):
            return dict(res)

        def get_guest_details(self, rid):
            return {"personal_info": {"name": reservation.get("guest_name", "Hóspede")}, "history": []}

        def build_unified_reservation_record(self, reservation_id):
            return {"id": reservation_id}

    return _ServiceStub


def test_guest_details_financial_split_daily_only(monkeypatch):
    app = _make_app()
    reservation = {"id": "RES-1", "guest_name": "Hospede", "amount": "1000.00", "paid_amount": "200.00", "to_receive": "800.00", "room": "11"}
    monkeypatch.setattr(reception_routes, "ReservationService", _stub_service(reservation))
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"reservation_id": "RES-1", "guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [])
    with app.test_request_context("/api/guest/details?reservation_id=RES-1"):
        _set_user()
        response = reception_routes.api_guest_details.__wrapped__(None)
    payload = response.get_json()
    data = payload["data"]
    assert data["reservation_financial"]["total"] == 1000.0
    assert data["reservation_financial"]["pending"] == 800.0
    assert data["consumption_financial"]["total"] == 0.0
    assert data["consumption_financial"]["pending"] == 0.0


def test_guest_details_financial_split_consumption_only(monkeypatch):
    app = _make_app()
    reservation = {"id": "RES-2", "guest_name": "Hospede", "amount": "0.00", "paid_amount": "0.00", "to_receive": "0.00", "room": "12"}
    monkeypatch.setattr(reception_routes, "ReservationService", _stub_service(reservation))
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"12": {"reservation_id": "RES-2", "guest_name": "Hospede"}})
    monkeypatch.setattr(
        reception_routes,
        "load_room_charges",
        lambda: [
            {"id": "C1", "room_number": "12", "status": "pending", "total": 120.0, "items": [{"name": "Suco", "category": "Bebidas"}]},
            {"id": "C2", "room_number": "12", "status": "paid", "total": 80.0, "items": [{"name": "Água", "category": "Frigobar"}], "type": "minibar"},
        ],
    )
    with app.test_request_context("/api/guest/details?reservation_id=RES-2"):
        _set_user()
        response = reception_routes.api_guest_details.__wrapped__(None)
    payload = response.get_json()
    data = payload["data"]
    assert data["reservation_financial"]["pending"] == 0.0
    assert data["consumption_financial"]["total"] == 200.0
    assert data["consumption_financial"]["paid"] == 80.0
    assert data["consumption_financial"]["pending"] == 120.0


def test_guest_details_financial_split_daily_and_consumption(monkeypatch):
    app = _make_app()
    reservation = {"id": "RES-3", "guest_name": "Hospede", "amount": "1500.00", "paid_amount": "500.00", "to_receive": "1000.00", "room": "13"}
    monkeypatch.setattr(reception_routes, "ReservationService", _stub_service(reservation))
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"13": {"reservation_id": "RES-3", "guest_name": "Hospede"}})
    monkeypatch.setattr(
        reception_routes,
        "load_room_charges",
        lambda: [
            {"id": "C1", "room_number": "13", "status": "pending", "total": 300.0, "items": [{"name": "Jantar"}]},
            {"id": "C2", "room_number": "13", "status": "paid", "total": 50.0, "items": [{"name": "Refrigerante", "category": "Frigobar"}]},
        ],
    )
    with app.test_request_context("/api/guest/details?reservation_id=RES-3"):
        _set_user()
        response = reception_routes.api_guest_details.__wrapped__(None)
    payload = response.get_json()
    data = payload["data"]
    assert data["reservation_financial"]["pending"] == 1000.0
    assert data["consumption_financial"]["pending"] == 300.0
    assert data["consumption_financial"]["total"] == 350.0


def test_reception_guest_view_separates_cashiers_in_ui_assets():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        rooms_template = f.read()
    with open("app/templates/partials/guest_unified_modal.html", "r", encoding="utf-8") as f:
        template = f.read()
    with open("app/static/js/guest_view.js", "r", encoding="utf-8") as f:
        script = f.read()
    assert "{% include 'partials/guest_unified_modal.html' %}" in rooms_template
    assert "Hospedagem / Diárias (Caixa Reservas - NFS-e)" in template
    assert "Consumo (Caixa Recepção - NFC-e)" in template
    assert "vg_stay_total" in template
    assert "vg_cons_total" in template
    assert "reservation_financial" in script
    assert "consumption_financial" in script
