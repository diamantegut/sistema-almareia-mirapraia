from flask import Flask, session
import json
from pathlib import Path

from app.blueprints.restaurant import routes as restaurant_routes
from app.services import permission_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/login", endpoint="auth.login", view_func=lambda: "login")
    app.add_url_rule(
        "/reception/authz-requests/create",
        endpoint="reception.reception_create_operational_authz_request",
        view_func=lambda: "ok",
    )
    return app


def _set_profile(role: str, department: str = "Serviço", permissions=None):
    session.clear()
    session.update(
        {
            "user": f"{role}_u",
            "role": role,
            "department": department,
            "permissions": permissions if isinstance(permissions, list) else [],
        }
    )


def test_restaurant_tables_negado_retorna_bloqueio_padronizado(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(permission_service, "_pilot_enforcement_enabled", lambda area, runtime_flags: True)
    monkeypatch.setattr(permission_service, "_wants_json_response", lambda: True)
    monkeypatch.setattr(restaurant_routes, "_has_restaurant_or_reception_access", lambda: False)
    with app.test_request_context("/restaurant/tables", method="GET", headers={"Accept": "application/json"}):
        _set_profile("colaborador", department="Serviço", permissions=[])
        blocked = restaurant_routes.restaurant_tables.__wrapped__()
    response, status = blocked
    payload = response.get_json()
    assert status == 403
    assert payload["authorization_required"] is True
    assert payload["authorization_request_available"] is True
    assert payload["authorization_request"]["route_key"] == "restaurant.restaurant_tables"
    assert payload["authorization_request"]["module"] == "restaurant"


def test_restaurant_tables_nao_regrede_para_perfil_gerencial(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(restaurant_routes, "load_table_orders", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_room_occupancy", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_users", lambda: {})
    monkeypatch.setattr(restaurant_routes, "load_restaurant_table_settings", lambda: {"disabled_tables": []})
    monkeypatch.setattr(restaurant_routes, "load_restaurant_settings", lambda: {"live_music_active": False})
    monkeypatch.setattr(restaurant_routes, "get_current_cashier", lambda cashier_type=None: None)
    monkeypatch.setattr(restaurant_routes.CashierService, "_load_sessions", staticmethod(lambda: []))
    monkeypatch.setattr(restaurant_routes, "render_template", lambda *args, **kwargs: "ok")
    with app.test_request_context("/restaurant/tables", method="GET"):
        _set_profile("gerente", department="Restaurante", permissions=["restaurante_mirapraia"])
        response = restaurant_routes.restaurant_tables.__wrapped__()
    assert response == "ok"


def test_restaurant_wave_policy_minima_presente():
    policy_path = Path(__file__).resolve().parents[1] / "data" / "authz" / "policies_v1.json"
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    by_endpoint = {str(item.get("endpoint")): item for item in payload.get("policies", []) if isinstance(item, dict)}
    expected = {
        "restaurant.restaurant_tables",
        "restaurant.open_staff_table",
        "restaurant.restaurant_table_order",
        "restaurant.toggle_live_music",
        "restaurant.toggle_table_disabled",
        "restaurant.close_special_table",
    }
    missing = [key for key in expected if key not in by_endpoint]
    assert missing == []
