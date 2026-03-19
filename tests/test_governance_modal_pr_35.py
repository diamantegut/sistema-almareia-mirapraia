from copy import deepcopy
from io import BytesIO

from flask import Flask, session

from app.blueprints.governance import routes as governance_routes
from app.blueprints.maintenance import routes as maintenance_routes


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/service/manutencao", endpoint="main.service_page", view_func=lambda service_id=None: "svc")
    app.add_url_rule("/governance/rooms", endpoint="governance.governance_rooms", view_func=lambda: "gov")
    return app


def _set_governance_user():
    session.clear()
    session.update({"user": "camareira1", "role": "supervisor", "department": "Governança"})


def _set_non_governance():
    session.clear()
    session.update({"user": "colab1", "role": "atendente", "department": "Recepção"})


def test_governance_template_has_operational_modal_and_mobile_layout():
    with open("app/templates/governance_rooms.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "roomActionsModal" in html
    assert "modal-fullscreen-sm-down" in html
    assert "openRoomActionsModal" in html
    assert "openMaintenanceFromRoom" in html
    assert "row.get('items', [])" in html


def test_governance_rooms_requires_governance_access():
    app = _make_app()
    with app.test_request_context("/governance/rooms", method="GET"):
        _set_non_governance()
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302


def test_governance_rooms_add_note_persists_in_cleaning_status(monkeypatch):
    app = _make_app()
    saved = {}
    initial = {"101": {"status": "dirty"}}
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: deepcopy(initial))
    monkeypatch.setattr(governance_routes, "save_cleaning_status", lambda payload: saved.update(deepcopy(payload)) or True)
    with app.test_request_context("/governance/rooms", method="POST", data={"action": "add_note", "room_number": "101", "note": "Torneira vazando"}):
        _set_governance_user()
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302
    assert saved["101"]["pending_note"] == "Torneira vazando"
    assert saved["101"]["note_updated_by"] == "camareira1"


def test_governance_rooms_mark_dirty_keeps_note(monkeypatch):
    app = _make_app()
    saved = {}
    initial = {"101": {"status": "clean", "pending_note": "Lâmpada queimada"}}
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: deepcopy(initial))
    monkeypatch.setattr(governance_routes, "save_cleaning_status", lambda payload: saved.update(deepcopy(payload)) or True)
    with app.test_request_context("/governance/rooms", method="POST", data={"action": "mark_dirty", "room_number": "101"}):
        _set_governance_user()
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302
    assert saved["101"]["status"] == "dirty"
    assert saved["101"]["pending_note"] == "Lâmpada queimada"


def test_governance_finish_cleaning_daily_triggers_auto_deduct(monkeypatch):
    app = _make_app()
    state = {
        "101": {
            "status": "in_progress",
            "previous_status": "dirty",
            "maid": "camareira1",
            "start_time": "18/03/2026 10:00:00",
            "cleaning_cycle_ref": "CYCLE-DAILY-1",
            "last_update": "18/03/2026 10:00",
        }
    }
    captured = {}
    monkeypatch.setattr(governance_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(governance_routes, "load_cleaning_status", lambda: deepcopy(state))
    monkeypatch.setattr(governance_routes, "save_cleaning_status", lambda payload: True)
    monkeypatch.setattr(governance_routes, "save_cleaning_log", lambda payload: True)
    monkeypatch.setattr(governance_routes, "apply_auto_deduction", lambda **kwargs: captured.update(kwargs) or {"applied_count": 1, "warnings": []})
    with app.test_request_context("/governance/rooms", method="POST", data={"action": "finish_cleaning", "room_number": "101"}):
        _set_governance_user()
        response = governance_routes.governance_rooms.__wrapped__()
    assert response.status_code == 302
    assert captured["event_type"] == "daily_cleaning"
    assert captured["event_context"]["cleaning_cycle_ref"] == "CYCLE-DAILY-1"


def test_governance_api_frigobar_items_forbidden_without_access():
    app = _make_app()
    with app.test_request_context("/api/frigobar/items", method="GET", headers={"Accept": "application/json"}):
        _set_non_governance()
        response, status = governance_routes.api_frigobar_items.__wrapped__()
    assert status == 403
    assert response.get_json()["success"] is False


def test_maintenance_new_prefills_from_governance_query(monkeypatch):
    app = _make_app()
    captured = {}
    monkeypatch.setattr(maintenance_routes, "render_template", lambda tpl, **kwargs: captured.update({"tpl": tpl, "kwargs": kwargs}) or "ok")
    with app.test_request_context("/maintenance/new?source=governance&room=101&description=Vazamento"):
        _set_governance_user()
        output = maintenance_routes.new_maintenance_request.__wrapped__()
    assert output == "ok"
    assert captured["tpl"] == "maintenance_form.html"
    assert captured["kwargs"]["prefill_location"] == "Quarto 101"
    assert captured["kwargs"]["source"] == "governance"
    assert captured["kwargs"]["return_to"] == "/governance/rooms"


def test_maintenance_submit_redirects_to_return_to(monkeypatch):
    app = _make_app()
    requests_state = []

    class _ImageMock:
        mode = "RGB"
        width = 600
        height = 400

        def resize(self, size, method):
            return self

        def save(self, filepath, optimize=True, quality=70):
            return None

    monkeypatch.setattr(maintenance_routes.Image, "open", lambda file_obj: _ImageMock())
    monkeypatch.setattr(maintenance_routes, "load_maintenance_requests", lambda: deepcopy(requests_state))
    monkeypatch.setattr(
        maintenance_routes,
        "save_maintenance_requests",
        lambda payload: requests_state.clear() or requests_state.extend(deepcopy(payload)) or True,
    )
    with app.test_request_context(
        "/maintenance/submit",
        method="POST",
        data={
            "location": "Quarto 101",
            "description": "Ar-condicionado com ruído",
            "return_to": "/governance/rooms",
            "photo": (BytesIO(b"fakeimage"), "teste.jpg"),
        },
        content_type="multipart/form-data",
    ):
        _set_governance_user()
        response = maintenance_routes.submit_maintenance.__wrapped__()
    assert response.status_code == 302
    assert response.location.endswith("/governance/rooms")
    assert len(requests_state) == 1
