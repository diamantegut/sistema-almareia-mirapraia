from datetime import datetime, timedelta
from copy import deepcopy

import pandas as pd
from flask import Flask, session

from app.blueprints.reception import routes as reception_routes
from app.services.reservation_service import ReservationService
import app.services.reservation_service as reservation_service_module


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/reception/rooms", endpoint="reception.reception_rooms", view_func=lambda: "rooms")
    app.add_url_rule("/reception/checkin", endpoint="reception.reception_checkin", view_func=lambda: "checkin")
    app.add_url_rule("/reception/cashier", endpoint="reception.reception_cashier", view_func=lambda: "cashier")
    return app


def _set_reception_user():
    session.clear()
    session.update({"user": "rec1", "role": "supervisor", "department": "Recepção", "permissions": ["recepcao"]})


def test_transfer_room_blocks_when_future_reservation_collision(monkeypatch):
    app = _make_app()
    occupancy = {"11": {"guest_name": "Hóspede A", "checkin": "20/03/2026", "checkout": "22/03/2026", "reservation_id": "RES-1"}}
    monkeypatch.setattr(reception_routes, "verify_reception_integrity", lambda: (True, "ok"))
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: deepcopy(occupancy))
    monkeypatch.setattr(reception_routes, "load_cleaning_status", lambda: {})
    monkeypatch.setattr(reception_routes.checklist_service, "load_checklist_items", lambda: [])
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [])
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [])
    monkeypatch.setattr(reception_routes, "load_printers", lambda: [])
    monkeypatch.setattr(reception_routes, "load_printer_settings", lambda: {})
    monkeypatch.setattr(reception_routes.ExperienceService, "get_all_experiences", lambda only_active=True: [])
    monkeypatch.setattr(reception_routes.ExperienceService, "get_unique_collaborators", lambda: [])
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: True)
    monkeypatch.setattr(reception_routes, "save_cleaning_status", lambda payload: True)
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)

    def _raise_collision(self, reservation_id, room_number, checkin, checkout, occupancy_data=None):
        raise ValueError("Conflito com reserva futura no quarto 12.")

    monkeypatch.setattr(reception_routes.ReservationService, "check_collision", _raise_collision)
    with app.test_request_context("/reception/rooms", method="POST", data={"action": "transfer_guest", "old_room": "11", "new_room": "12", "reason": "Teste"}):
        _set_reception_user()
        response = reception_routes.reception_rooms.__wrapped__()
    assert response.status_code == 302
    assert "/reception/rooms" in response.location


def test_transfer_room_without_collision_keeps_flow(monkeypatch):
    app = _make_app()
    occupancy = {"11": {"guest_name": "Hóspede A", "checkin": "20/03/2026", "checkout": "22/03/2026", "reservation_id": "RES-1"}}
    saved_occupancy = {}
    monkeypatch.setattr(reception_routes, "verify_reception_integrity", lambda: (True, "ok"))
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: deepcopy(occupancy))
    monkeypatch.setattr(reception_routes, "load_cleaning_status", lambda: {})
    monkeypatch.setattr(reception_routes.checklist_service, "load_checklist_items", lambda: [])
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [])
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [])
    monkeypatch.setattr(reception_routes, "load_printers", lambda: [])
    monkeypatch.setattr(reception_routes, "load_printer_settings", lambda: {})
    monkeypatch.setattr(reception_routes.ExperienceService, "get_all_experiences", lambda only_active=True: [])
    monkeypatch.setattr(reception_routes.ExperienceService, "get_unique_collaborators", lambda: [])
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: saved_occupancy.update(deepcopy(payload)) or True)
    monkeypatch.setattr(reception_routes, "save_cleaning_status", lambda payload: True)
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: True)
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(reception_routes.ReservationService, "check_collision", lambda self, reservation_id, room_number, checkin, checkout, occupancy_data=None: True)
    monkeypatch.setattr(reception_routes.ReservationService, "save_manual_allocation", lambda self, **kwargs: True)
    with app.test_request_context("/reception/rooms", method="POST", data={"action": "transfer_guest", "old_room": "11", "new_room": "12", "reason": "Teste"}):
        _set_reception_user()
        response = reception_routes.reception_rooms.__wrapped__()
    assert response.status_code == 302
    assert "12" in saved_occupancy


def test_checkin_with_pending_daily_requires_decision(monkeypatch):
    app = _make_app()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(reception_routes.ReservationService, "get_upcoming_checkins", lambda self: [])
    monkeypatch.setattr(reception_routes.ReservationService, "get_reservation_by_id", lambda self, rid: {"id": rid, "amount": "500.00", "paid_amount": "0.00", "source_type": "manual"})
    monkeypatch.setattr(reception_routes.ReservationService, "update_reservation_status", lambda self, rid, status: True)
    monkeypatch.setattr(reception_routes.ReservationService, "update_guest_details", lambda self, rid, updates: True)
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: True)
    monkeypatch.setattr(reception_routes, "apply_auto_deduction", lambda **kwargs: {"applied_count": 0, "warnings": []})
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: True)
    with app.test_request_context(
        "/reception/checkin",
        method="POST",
        data={"room_number": "12", "guest_name": "Hóspede", "checkin_date": today_iso, "checkout_date": today_iso, "num_adults": "2", "reservation_id": "RES-100"},
    ):
        _set_reception_user()
        response = reception_routes.reception_checkin.__wrapped__()
    assert response.status_code == 302
    assert "open_checkin=true" in response.location


def test_checkin_defer_one_day_persists_followup(monkeypatch):
    app = _make_app()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    expected_due = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    saved = {}
    captured_updates = {}
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(reception_routes.ReservationService, "get_upcoming_checkins", lambda self: [])
    monkeypatch.setattr(reception_routes.ReservationService, "get_reservation_by_id", lambda self, rid: {"id": rid, "amount": "500.00", "paid_amount": "0.00", "source_type": "manual"})
    monkeypatch.setattr(reception_routes.ReservationService, "update_reservation_status", lambda self, rid, status: True)
    monkeypatch.setattr(
        reception_routes.ReservationService,
        "update_guest_details",
        lambda self, rid, updates: captured_updates.update({"rid": rid, "updates": deepcopy(updates)}) or True,
    )
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: saved.update(deepcopy(payload)) or True)
    monkeypatch.setattr(reception_routes, "apply_auto_deduction", lambda **kwargs: {"applied_count": 0, "warnings": []})
    monkeypatch.setattr(reception_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(reception_routes, "save_table_orders", lambda payload: True)
    with app.test_request_context(
        "/reception/checkin",
        method="POST",
        data={
            "room_number": "12",
            "guest_name": "Hóspede",
            "checkin_date": today_iso,
            "checkout_date": today_iso,
            "num_adults": "2",
            "reservation_id": "RES-200",
            "reservation_payment_decision": "defer_one_day",
            "reservation_payment_defer_reason": "Cliente pediu para amanhã",
        },
    ):
        _set_reception_user()
        response = reception_routes.reception_checkin.__wrapped__()
    assert response.status_code == 302
    assert saved["12"]["reservation_payment_due_date"] == expected_due
    assert saved["12"]["reservation_payment_state"] == "none"
    assert captured_updates["updates"]["payment_followup"]["decision"] == "defer_one_day"


def test_rooms_template_shows_upcoming_checkin_and_payment_badge():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Próximo Check-in" in html
    assert "Diária pendente" in html
    assert "Diária (Reserva)" in html


def test_import_preview_parser_keeps_excel_standard_columns(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "Id": "ABC-1",
                "Responsável": "Maria",
                "Checkin/out": "20/03/2026 - 22/03/2026",
                "Categoria": "Suíte Mar",
                "Status do pagamento": "Pendente",
                "Canais": "Booking.com",
                "Valor": "1.000,00",
                "Valor pago": "200,00",
                "Valor a receber": "800,00",
            }
        ]
    )
    monkeypatch.setattr(reservation_service_module.pd, "read_excel", lambda file_path: df)
    service = ReservationService()
    out = service._parse_excel_file("dummy.xlsx")
    assert len(out) == 1
    assert out[0]["guest_name"] == "Maria"
    assert out[0]["checkin"] == "20/03/2026"
    assert out[0]["checkout"] == "22/03/2026"
    assert out[0]["paid_amount_val"] == 200.0
