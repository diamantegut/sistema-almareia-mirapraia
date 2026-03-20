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
    assert "Diária em aberto" in html
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


def test_allocate_reservations_exposes_financial_state_labels():
    service = ReservationService()
    start = datetime.strptime("20/03/2026", "%d/%m/%Y")
    grid = service.get_occupancy_grid({}, start, 3)
    reservations = [
        {
            "id": "R-PARTIAL",
            "guest_name": "Hóspede Parcial",
            "checkin": "20/03/2026",
            "checkout": "21/03/2026",
            "category": "Suíte Mar",
            "room": "12",
            "status": "Confirmada",
            "amount": "1000.00",
            "paid_amount": "200.00",
            "to_receive": "800.00",
            "reservation_status_label": "Confirmada",
        }
    ]
    grid = service.allocate_reservations(grid, reservations, start, 3)
    cell = next(c for c in grid["12"] if c)
    assert cell["reservation_status"] == "Confirmada"
    assert cell["payment_status"] == "Parcial"
    assert cell["payment_state"] == "partial"
    assert cell["to_receive"] == "800.00"


def test_sync_room_occupancy_financial_state_updates_room_record(monkeypatch):
    app = _make_app()
    occupancy = {
        "12": {
            "guest_name": "Hóspede",
            "reservation_id": "RES-300",
            "reservation_payment_state": "none",
            "reservation_payment_total": 0.0,
            "reservation_payment_paid": 0.0,
            "reservation_payment_remaining": 0.0,
        }
    }
    saved = {}

    class _StubService:
        def get_reservation_by_id(self, rid):
            return {"id": rid, "amount": "900.00", "paid_amount": "300.00", "source_type": "manual"}

    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: deepcopy(occupancy))
    monkeypatch.setattr(reception_routes, "save_room_occupancy", lambda payload: saved.update(deepcopy(payload)) or True)
    with app.test_request_context("/reception/reservation/pay", method="POST"):
        _set_reception_user()
        result = reception_routes._sync_room_occupancy_reservation_financial_state("RES-300", service=_StubService())
    assert result["updated"] is True
    assert result["room"] == "12"
    assert saved["12"]["reservation_payment_state"] == "partial"
    assert saved["12"]["reservation_payment_paid"] == 300.0
    assert saved["12"]["reservation_payment_remaining"] == 600.0


def test_rooms_and_reservations_use_single_reservation_payment_partial():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        rooms_html = f.read()
    with open("app/templates/reception_reservations.html", "r", encoding="utf-8") as f:
        reservations_html = f.read()
    assert "partials/reservation_payment_modal.html" in rooms_html
    assert "partials/reservation_payment_modal.html" in reservations_html
    assert "id=\"reservationPaymentModal\"" not in rooms_html
    assert "id=\"reservationPaymentModal\"" not in reservations_html


def test_reservation_payment_partial_exposes_shared_modal_and_functions():
    with open("app/templates/partials/reservation_payment_modal.html", "r", encoding="utf-8") as f:
        partial_html = f.read()
    assert "id=\"reservationPaymentModal\"" in partial_html
    assert "openReservationPaymentModal" in partial_html
    assert "submitReservationPayment" in partial_html


def test_operational_sheet_builds_breakfast_base_for_future_a4():
    service = ReservationService()
    reservation = {"id": "RES-BREAKFAST", "guest_name": "Alice", "room": "22"}
    details = {
        "personal_info": {"name": "Alice"},
        "companions": [{"id": "c1", "name": "Bob", "relationship": "Filho"}],
        "operational_info": {
            "dietary_restrictions": ["Vegano"],
            "allergies_list": ["Leite"],
            "breakfast_time_standard": "08:00",
            "breakfast_fruit_preferences": ["Mamão", "Banana"],
            "is_birthday": True,
            "special_celebration": "Lua de Mel",
            "hospitality_notes": "Montar mesa especial",
            "last_updated_at": "20/03/2026 10:30",
            "last_updated_by": "rec1",
            "last_updated_source": "rooms",
        },
    }
    service.get_reservation_by_id = lambda rid: reservation if rid == "RES-BREAKFAST" else {}
    sheet = service.build_operational_sheet("RES-BREAKFAST", guest_details=details)
    base = sheet["base_cafe_manha"]
    assert base["quarto"] == "22"
    assert base["hospede_principal"] == "Alice"
    assert base["numero_hospedes"] == 2
    assert base["horario_cafe"] == "08:00"
    assert "Mamão" in base["frutas_preferidas"]
    assert base["aniversariante"] is True
    assert base["demais_hospedes"][0]["nome"] == "Bob"
    assert base["ultima_atualizacao"]["origem"] == "rooms"


def test_breakfast_table_context_sorts_rooms_and_uses_safe_fallbacks():
    occupancy = {
        "12": {"reservation_id": "R-12", "guest_name": "Ana"},
        "2": {"reservation_id": "R-2", "guest_name": "Bia"},
    }

    class _BreakfastServiceStub:
        def get_reservation_by_id(self, rid):
            return {"id": rid, "guest_name": "Hosp", "room": "2" if rid == "R-2" else "12"}

        def build_operational_sheet(self, rid):
            if rid == "R-2":
                return {
                    "base_cafe_manha": {
                        "quarto": "2",
                        "hospede_principal": "Bia",
                        "numero_hospedes": 3,
                        "horario_cafe": "07:30",
                        "frutas_preferidas": ["Mamão", "Banana", "Uva", "Kiwi"],
                        "alergias_restricoes": ["Alergia a Leite", "Sem Glúten"],
                        "aniversariante": True,
                        "comemoracao": "Aniversário",
                        "observacoes_especiais": "Mesa sem lactose",
                    }
                }
            return {"base_cafe_manha": {"quarto": "12", "hospede_principal": "Ana", "numero_hospedes": 1}}

    ctx = reception_routes._build_breakfast_table_context(occupancy, service=_BreakfastServiceStub(), report_date="20/03/2026")
    assert ctx["report_date"] == "20/03/2026"
    assert "report_generated_at" in ctx
    assert ctx["rows"][0]["room"] == "2"
    assert ctx["rows"][0]["pax"] == 3
    assert ctx["rows"][0]["fruits"].startswith("Mamão, Banana")
    assert ctx["rows"][0]["special"] == "🎉"
    assert ctx["rows"][1]["room"] == "12"
    assert ctx["rows"][1]["restrictions"] == "Sem restrições informadas"


def test_breakfast_table_route_renders_template(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"12": {"reservation_id": "R-12", "guest_name": "Ana"}})
    monkeypatch.setattr(reception_routes, "_build_breakfast_table_context", lambda occupancy_map, service=None, report_date=None: {"report_date": "20/03/2026", "rows": [{"room": "12"}], "total_rooms": 1, "total_pax": 2})
    monkeypatch.setattr(reception_routes, "render_template", lambda tpl, **ctx: {"template": tpl, "ctx": ctx})
    with app.test_request_context("/reception/rooms/breakfast-table"):
        _set_reception_user()
        out = reception_routes.reception_rooms_breakfast_table.__wrapped__()
    assert out["template"] == "reception_breakfast_table.html"
    assert out["ctx"]["total_rooms"] == 1


def test_rooms_and_breakfast_templates_have_print_entrypoint():
    with open("app/templates/reception_rooms.html", "r", encoding="utf-8") as f:
        rooms_html = f.read()
    with open("app/templates/reception_breakfast_table.html", "r", encoding="utf-8") as f:
        breakfast_html = f.read()
    assert "Tabela Café da Manhã" in rooms_html
    assert "window.print()" in breakfast_html
    assert "size: A4 portrait" in breakfast_html
    assert "Gerado em:" in breakfast_html
    assert "display: table-header-group;" in breakfast_html


def test_breakfast_table_context_handles_legacy_and_edge_cases():
    occupancy = {
        "101": {"guest_name": "", "reservation_id": "LEG-1"},
        "102": {"guest_name": "Quarto Cheio", "reservation_id": "LEG-2"},
        "103": {"guest_name": "Sem Dados"},
    }

    class _LegacyStub:
        def get_reservation_by_id(self, rid):
            if rid == "LEG-1":
                return {"id": rid, "guest_name": "", "room": "101"}
            if rid == "LEG-2":
                return {"id": rid, "guest_name": "Quarto Cheio", "room": "102"}
            return {}

        def build_operational_sheet(self, rid):
            if rid == "LEG-1":
                return {"base_cafe_manha": {"quarto": "101", "numero_hospedes": "abc", "alergias_restricoes": "Sem Leite, Sem Leite, "}}
            if rid == "LEG-2":
                return {
                    "base_cafe_manha": {
                        "quarto": "102",
                        "hospede_principal": "Quarto Cheio",
                        "numero_hospedes": 8,
                        "frutas_preferidas": ["Mamão", "Banana", "Uva", "Kiwi", "Manga"],
                        "alergias_restricoes": ["Alergia a Amendoim", "Sem Glúten", "Sem Lactose", "Vegano"],
                        "observacoes_especiais": "Observação muito longa " * 20,
                        "comemoracao": "Aniversário",
                    }
                }
            return {}

    ctx = reception_routes._build_breakfast_table_context(occupancy, service=_LegacyStub())
    assert len(ctx["rows"]) == 3
    row_101 = next(r for r in ctx["rows"] if r["room"] == "101")
    row_102 = next(r for r in ctx["rows"] if r["room"] == "102")
    row_103 = next(r for r in ctx["rows"] if r["room"] == "103")
    assert row_101["guest_main"] == "Hóspede"
    assert row_101["pax"] == 1
    assert row_102["pax"] == 8
    assert row_102["fruits"].startswith("Mamão, Banana")
    assert row_102["special"] == "🎉"
    assert row_102["has_observation"] is True
    assert len(row_102["observations"]) <= 100
    assert row_103["breakfast_time"] == "--:--"
