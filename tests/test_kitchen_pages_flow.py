import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from flask import Blueprint, Flask

import app.blueprints.kitchen as kitchen_module
import app.services.breakfast_kds_service as breakfast_kds_service
from app.blueprints.kitchen import kitchen_bp


def _build_test_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"

    auth_bp = Blueprint("auth", __name__)
    main_bp = Blueprint("main", __name__)

    @auth_bp.route("/auth/login")
    def login():
        return "login", 200

    @main_bp.route("/service/<service_id>")
    def service_page(service_id):
        return f"service:{service_id}", 200

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(kitchen_bp)
    return app


@pytest.fixture
def app_client():
    app = _build_test_app()
    with app.test_client() as client:
        yield client


def _login(client, role="admin", department="Cozinha", user="tester"):
    with client.session_transaction() as sess:
        sess["user"] = user
        sess["role"] = role
        sess["department"] = department
        sess["permissions"] = ["cozinha"]


def test_kitchen_pages_require_login(app_client):
    for route in ["/kitchen/portion", "/kitchen/kds", "/kitchen/reports", "/kitchen/breakfast-kds"]:
        resp = app_client.get(route)
        assert resp.status_code == 302
        assert "/auth/login" in resp.location


def test_kitchen_authorization_blocks_non_kitchen_users(app_client):
    _login(app_client, role="colaborador", department="Recepção")
    for route in ["/kitchen/portion", "/kitchen/kds", "/kitchen/reports", "/kitchen/breakfast-kds"]:
        resp = app_client.get(route)
        assert resp.status_code == 302
        assert "/service/cozinha" in resp.location
    resp_api = app_client.get("/kitchen/kds/data?station=cozinha")
    assert resp_api.status_code == 403
    payload = resp_api.get_json()
    assert payload["success"] is False
    resp_breakfast_api = app_client.get("/kitchen/breakfast-kds/data")
    assert resp_breakfast_api.status_code == 403


def test_kitchen_pages_load_for_desktop_and_mobile(app_client, monkeypatch):
    _login(app_client)
    monkeypatch.setattr(kitchen_module, "render_template", lambda template, **kwargs: f"TEMPLATE:{template}")
    monkeypatch.setattr(kitchen_module, "load_products", lambda: [{"name": "Picanha", "category": "Carnes", "unit": "g", "price": 10, "status": "Ativo"}])
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor A", "active": True}])
    monkeypatch.setattr(kitchen_module, "load_stock_entries", lambda: [])

    desktop_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    mobile_headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    resp_portion_desktop = app_client.get("/kitchen/portion", headers=desktop_headers)
    resp_portion_mobile = app_client.get("/kitchen/portion", headers=mobile_headers)
    assert resp_portion_desktop.status_code == 200
    assert resp_portion_mobile.status_code == 200
    assert "TEMPLATE:portion_item.html" in resp_portion_desktop.get_data(as_text=True)

    resp_kds_desktop = app_client.get("/kitchen/kds?station=cozinha", headers=desktop_headers)
    resp_kds_mobile = app_client.get("/kitchen/kds?station=cozinha", headers=mobile_headers)
    assert resp_kds_desktop.status_code == 200
    assert resp_kds_mobile.status_code == 200
    assert "TEMPLATE:kitchen_kds.html" in resp_kds_desktop.get_data(as_text=True)

    resp_reports_desktop = app_client.get("/kitchen/reports", headers=desktop_headers)
    resp_reports_mobile = app_client.get("/kitchen/reports", headers=mobile_headers)
    assert resp_reports_desktop.status_code == 200
    assert resp_reports_mobile.status_code == 200
    assert "TEMPLATE:kitchen_reports.html" in resp_reports_desktop.get_data(as_text=True)


def test_kitchen_templates_have_expected_overlays_and_popovers():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    kds_html = (root / "kitchen_kds.html").read_text(encoding="utf-8")
    reports_html = (root / "kitchen_reports.html").read_text(encoding="utf-8")
    portion_html = (root / "portion_item.html").read_text(encoding="utf-8")

    assert 'id="kds-overlay"' in kds_html
    assert 'id="kds-overlay-content"' in kds_html
    assert 'data-bs-toggle="popover"' in reports_html
    assert 'data-bs-toggle="modal"' not in portion_html
    assert 'class="modal' not in portion_html


def test_portion_template_has_ux_refinements_for_two_entry_paths():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    portion_html = (root / "portion_item.html").read_text(encoding="utf-8")
    assert 'id="flow-origin-card"' in portion_html
    assert 'id="flow-kit-card"' in portion_html
    assert 'id="portion-validation-banner"' in portion_html
    assert 'id="metric-loss-total"' in portion_html
    assert 'id="metric-cost"' in portion_html
    assert 'id="metric-balance"' in portion_html
    assert "function showValidationMessage" in portion_html
    assert "classList.toggle('selected-path'" in portion_html


def test_kds_template_touchscreen_optimizations():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    kds_html = (root / "kitchen_kds.html").read_text(encoding="utf-8")
    assert "const pollingIntervalMs = 8000;" in kds_html
    assert "function requestKdsFullscreen()" in kds_html
    assert "function setupAutoFullscreenHooks()" in kds_html
    assert "grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));" in kds_html
    assert "overflow-x: hidden;" in kds_html
    assert ".kds-card-details" in kds_html
    assert "runCardStatusTransition" in kds_html
    assert "min-height: 48px;" in kds_html


def test_breakfast_kds_template_has_tablet_and_modal_patterns():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    html = (root / "kitchen_breakfast_kds.html").read_text(encoding="utf-8")
    assert "KDS Café da Manhã" in html
    assert "breakfast-kds-card" in html
    assert 'id="breakfastKdsDetailsModal"' in html
    assert "data-next-status=\"in_preparo\"" in html
    assert "data-next-status=\"pronto\"" in html
    assert "card-footer-row" in html
    assert "breakfast-card-action" in html
    assert "requestBreakfastFullscreen" in html
    assert "PEDIDOS RESTAURANTE DO CAFÉ (07:00–11:00)" in html
    assert "breakfast-restaurant-ticket" in html
    assert "breakfast-restaurant-action" in html
    assert "flex-wrap: nowrap;" in html
    assert "overflow-x: auto;" in html
    assert "overflow-y: hidden;" in html
    assert "flex: 0 0 clamp(232px, 20.2%, 304px);" in html
    assert "title=\"${escapeHtml(order.item_full || order.item)}\"" in html
    assert "title=\"${escapeHtml(order.observation_full || order.observation || '')}\"" in html
    assert "applyOptimisticRestaurantStatus" in html
    assert "breakfastActionInFlight" in html
    assert "Gerar teste DEV" not in html
    assert "Limpar teste DEV" not in html
    assert "data-dev-breakfast-action" not in html


def test_breakfast_kds_template_landscape_touch_first_hierarchy():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    html = (root / "kitchen_breakfast_kds.html").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in html
    assert "kds-status-accent" in html
    assert "alert-critical" in html
    assert "Check-in" not in html
    assert "--kds-bg-main" in html
    assert "--kds-burnt-orange" in html
    assert "--kds-blue-deep" in html
    assert "--kds-bg-main: #171c24;" in html
    assert ".status-pending { background: rgba(244, 191, 50, 0.3);" in html
    assert ".status-preparing { background: rgba(242, 139, 60, 0.3);" in html
    assert ".status-ready { background: rgba(53, 190, 104, 0.28);" in html
    assert "card-top-row" in html
    assert "card-body-row" in html
    assert "metric-inline" in html
    assert "compact-alert" in html
    assert "summary-line" in html
    assert "card-footer-row" in html
    assert "align-self: flex-end;" in html
    assert "summarizeList" in html
    assert "min-height: 82px;" in html
    assert "min-height: 86px;" in html


def test_kds_data_and_status_flow(app_client, monkeypatch):
    _login(app_client)
    orders = {
        "12": {
            "status": "open",
            "opened_at": "19/03/2026 10:00",
            "waiter": "Carlos",
            "items": [
                {
                    "id": "item-1",
                    "name": "Filé",
                    "qty": 1,
                    "category": "Pratos",
                    "created_at": "19/03/2026 10:01",
                    "kds_status": "pending",
                }
            ],
        }
    }
    saved_snapshots = []

    monkeypatch.setattr(kitchen_module, "load_table_orders", lambda: orders)
    monkeypatch.setattr(kitchen_module, "save_table_orders", lambda updated: saved_snapshots.append(json.loads(json.dumps(updated))))
    monkeypatch.setattr(kitchen_module, "load_menu_items", lambda: [])
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"kds_sla": {"Pratos": 30}})
    monkeypatch.setattr(kitchen_module, "load_printers", lambda: [])
    monkeypatch.setattr(kitchen_module, "get_default_printer", lambda _: None)

    resp_data = app_client.get("/kitchen/kds/data?station=cozinha")
    assert resp_data.status_code == 200
    payload = resp_data.get_json()
    assert payload["success"] is True
    assert payload["data"]["orders"][0]["table_id"] == "12"
    assert payload["data"]["orders"][0]["wait_minutes"] >= 0

    resp_update = app_client.post(
        "/kitchen/kds/update_status",
        json={"table_id": "12", "item_id": "item-1", "status": "preparing", "station": "kitchen"},
    )
    assert resp_update.status_code == 200
    assert orders["12"]["items"][0]["kds_status"] == "preparing"

    resp_done = app_client.post(
        "/kitchen/kds/update_status",
        json={"table_id": "12", "item_id": "item-1", "status": "done", "station": "kitchen"},
    )
    assert resp_done.status_code == 200
    assert orders["12"]["items"][0]["kds_status"] == "done"
    assert "kds_preparing_duration_sec" in orders["12"]["items"][0]

    resp_received = app_client.post(
        "/kitchen/kds/mark_received",
        json={"table_id": "12", "item_ids": ["item-1"]},
    )
    assert resp_received.status_code == 200
    assert orders["12"]["items"][0]["kds_status"] == "archived"
    assert len(saved_snapshots) >= 3


def test_breakfast_kds_data_and_status_flow(app_client, monkeypatch):
    _login(app_client)
    current_day = kitchen_module.datetime.now().strftime("%d/%m/%Y")
    occupancy = {
        "12": {"reservation_id": "RES-12", "guest_name": "Ana"},
        "2": {"reservation_id": "RES-2", "guest_name": "Bia"},
    }
    saved_store = {}

    class _BreakfastServiceStub:
        def get_reservation_by_id(self, rid):
            return {"id": rid, "guest_name": "Ana" if rid == "RES-12" else "Bia", "room": "12" if rid == "RES-12" else "2"}

        def build_operational_sheet(self, rid):
            if rid == "RES-2":
                return {
                    "base_cafe_manha": {
                        "quarto": "2",
                        "hospede_principal": "Bia",
                        "numero_hospedes": 3,
                        "horario_cafe": "07:30",
                        "frutas_preferidas": ["Mamão", "Banana", "Uva"],
                        "alergias_restricoes": ["Alergia a Leite", "Sem Glúten"],
                        "aniversariante": True,
                        "comemoracao": "Aniversário",
                        "observacoes_especiais": "Mesa sem lactose",
                        "demais_hospedes": [{"nome": "Carlos", "relacao": "Filho"}],
                    },
                    "alergias": ["Leite"],
                    "restricoes_alimentares": ["Sem Glúten"],
                }
            return {
                "base_cafe_manha": {
                    "quarto": "12",
                    "hospede_principal": "Ana",
                    "numero_hospedes": 1,
                    "horario_cafe": "",
                },
                "alergias": [],
                "restricoes_alimentares": [],
            }

    monkeypatch.setattr(kitchen_module, "load_room_occupancy", lambda: occupancy)
    monkeypatch.setattr(
        kitchen_module,
        "load_table_orders",
        lambda: {
            "10": {
                "status": "open",
                "is_breakfast": True,
                "opened_at": f"{current_day} 07:40",
                "items": [
                    {
                        "id": "ord-1",
                        "name": "Tapioca",
                        "qty": 1,
                        "category": "Café da Manhã",
                        "created_at": f"{current_day} 07:45",
                        "observations": ["Sem queijo"],
                        "kds_status": "pending",
                    }
                ],
            },
            "11": {
                "status": "open",
                "is_breakfast": True,
                "opened_at": f"{current_day} 12:10",
                "items": [
                    {
                        "id": "ord-2",
                        "name": "Omelete",
                        "qty": 1,
                        "category": "Café da Manhã",
                        "created_at": f"{current_day} 12:15",
                        "observations": [],
                        "kds_status": "pending",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(kitchen_module, "ReservationService", lambda: _BreakfastServiceStub())
    monkeypatch.setattr(
        kitchen_module,
        "_load_breakfast_kds_store",
        lambda: {
            "status_by_date": {},
            "history_by_date": {},
            "restaurant_status_by_date": {},
            "restaurant_history_by_date": {},
        },
    )
    monkeypatch.setattr(kitchen_module, "_svc_get_statuses_for_day", lambda store, date_key: {"2": {"status": "pronto"}})
    monkeypatch.setattr(
        kitchen_module,
        "_svc_get_room_history_for_day",
        lambda store, date_key, room: [{"status": "in_preparo", "at": "19/03/2026 07:10", "by": "carlos", "source": "manual"}] if room == "12" else [],
    )
    monkeypatch.setattr(
        kitchen_module,
        "_svc_update_breakfast_status",
        lambda room, status, user, source="manual", context=None: (
            saved_store.update({"room": room, "status": status, "user": user, "source": source, "context": context})
            or {"success": True, "room": room, "status": status, "previous_status": "pending", "changed": True}
        ),
    )
    monkeypatch.setattr(
        kitchen_module,
        "_svc_update_breakfast_restaurant_status",
        lambda ticket_key, status, user, source="manual", context=None: (
            saved_store.update({"ticket_key": ticket_key, "restaurant_status": status, "restaurant_user": user, "restaurant_source": source, "restaurant_context": context})
            or {"success": True, "ticket_key": ticket_key, "status": status, "previous_status": "pending", "changed": True}
        ),
    )

    resp = app_client.get("/kitchen/breakfast-kds/data")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    rooms = payload["data"]["rooms"]
    assert len(rooms) == 1
    assert rooms[0]["room"] == "12"
    assert rooms[0]["status"] == "pending"
    assert rooms[0]["status_history"][0]["status"] == "in_preparo"
    assert payload["data"]["summary"]["visible_rooms"] == 1
    assert payload["data"]["summary"]["statuses"]["pronto"] == 1
    assert payload["data"]["summary"]["restaurant_orders"] == 1
    assert payload["data"]["restaurant_orders"][0]["table_id"] == "10"
    assert payload["data"]["restaurant_orders"][0]["item"] == "Tapioca"
    assert payload["data"]["restaurant_orders"][0]["item_full"] == "Tapioca"
    assert payload["data"]["restaurant_orders"][0]["status"] == "pending"

    resp_update = app_client.post("/kitchen/breakfast-kds/update_status", json={"room": "12", "status": "ready"})
    assert resp_update.status_code == 200
    out = resp_update.get_json()
    assert out["success"] is True
    assert out["status"] == "pronto"
    assert saved_store["room"] == "12"
    assert saved_store["status"] == "pronto"
    assert saved_store["source"] == "kitchen_breakfast_manual"

    resp_restaurant_update = app_client.post(
        "/kitchen/breakfast-kds/update_restaurant_status",
        json={"ticket_key": "10:ord-1", "table_id": "10", "item_id": "ord-1", "status": "in_preparo"},
    )
    assert resp_restaurant_update.status_code == 200
    restaurant_out = resp_restaurant_update.get_json()
    assert restaurant_out["success"] is True
    assert restaurant_out["status"] == "in_preparo"
    assert saved_store["ticket_key"] == "10:ord-1"
    assert saved_store["restaurant_status"] == "in_preparo"


def test_collect_breakfast_restaurant_orders_oculta_prontos_persistidos(monkeypatch):
    now_ref = kitchen_module.datetime(2026, 3, 19, 9, 0)
    monkeypatch.setattr(
        kitchen_module,
        "load_table_orders",
        lambda: {
            "21": {
                "status": "open",
                "is_breakfast": True,
                "opened_at": "19/03/2026 08:00",
                "items": [
                    {
                        "id": "i-1",
                        "name": "Tapioca",
                        "qty": 1,
                        "category": "Café da Manhã",
                        "created_at": "19/03/2026 08:12",
                        "observations": [],
                        "kds_status": "pending",
                    },
                    {
                        "id": "i-2",
                        "name": "Cuscuz",
                        "qty": 1,
                        "category": "Café da Manhã",
                        "created_at": "19/03/2026 08:14",
                        "observations": [],
                        "kds_status": "pending",
                    },
                ],
            },
        },
    )
    store = {
        "restaurant_status_by_date": {
            "2026-03-19": {
                "21:i-1": {"status": "pronto"},
                "21:i-2": {"status": "in_preparo"},
            }
        },
        "restaurant_history_by_date": {},
    }
    rows = kitchen_module._collect_breakfast_restaurant_orders(now=now_ref, store=store)
    assert len(rows) == 1
    assert rows[0]["ticket_key"] == "21:i-2"
    assert rows[0]["status"] == "in_preparo"


def test_collect_breakfast_restaurant_orders_applies_time_window_and_match(monkeypatch):
    now_ref = kitchen_module.datetime(2026, 3, 19, 9, 0)
    monkeypatch.setattr(
        kitchen_module,
        "load_table_orders",
        lambda: {
            "21": {
                "status": "open",
                "is_breakfast": False,
                "opened_at": "19/03/2026 08:00",
                "items": [
                    {
                        "id": "i-1",
                        "name": "Tapioca de queijo",
                        "qty": 1,
                        "category": "Lanches",
                        "created_at": "19/03/2026 08:12",
                        "observations": [],
                        "kds_status": "pending",
                    },
                    {
                        "id": "i-2",
                        "name": "Filé",
                        "qty": 1,
                        "category": "Pratos",
                        "created_at": "19/03/2026 08:14",
                        "observations": [],
                        "kds_status": "pending",
                    },
                ],
            },
            "22": {
                "status": "open",
                "is_breakfast": True,
                "opened_at": "19/03/2026 11:10",
                "items": [
                    {
                        "id": "i-3",
                        "name": "Cuscuz",
                        "qty": 1,
                        "category": "Café da Manhã",
                        "created_at": "19/03/2026 11:12",
                        "observations": [],
                        "kds_status": "pending",
                    }
                ],
            },
        },
    )

    rows = kitchen_module._collect_breakfast_restaurant_orders(now=now_ref)
    assert len(rows) == 1
    assert rows[0]["table_id"] == "21"
    assert rows[0]["item"] == "Tapioca de queijo"
    assert rows[0]["item_full"] == "Tapioca de queijo"
    assert rows[0]["time"] == "08:12"


def test_breakfast_dev_test_orders_route_is_dev_only_and_reversible(app_client, monkeypatch):
    _login(app_client)
    app_client.application.config["ALMAREIA_RUNTIME_ENV"] = "production"
    denied = app_client.post("/kitchen/breakfast-kds/dev-test-orders", json={"action": "seed"})
    assert denied.status_code == 403

    app_client.application.config["ALMAREIA_RUNTIME_ENV"] = "development"
    state = {}
    saved = []

    monkeypatch.setattr(kitchen_module, "load_table_orders", lambda: state)
    monkeypatch.setattr(
        kitchen_module,
        "save_table_orders",
        lambda payload: (
            saved.append(json.loads(json.dumps(payload))) or
            state.clear() or
            state.update(saved[-1])
        ),
    )

    seeded = app_client.post("/kitchen/breakfast-kds/dev-test-orders", json={"action": "seed"})
    assert seeded.status_code == 200
    seeded_payload = seeded.get_json()
    assert seeded_payload["success"] is True
    assert len(seeded_payload["tables"]) == 4
    assert all(str(t).startswith("DEV_CAFE_TEST_") for t in seeded_payload["tables"])
    assert len(state) == 4

    seeded_stress = app_client.post("/kitchen/breakfast-kds/dev-test-orders", json={"action": "seed_stress"})
    assert seeded_stress.status_code == 200
    seeded_stress_payload = seeded_stress.get_json()
    assert seeded_stress_payload["success"] is True
    assert seeded_stress_payload["seed_mode"] == "stress"
    assert len(seeded_stress_payload["tables"]) == 3
    assert all(str(t).startswith("DEV_CAFE_TEST_1") for t in seeded_stress_payload["tables"])
    assert all((state.get(t) or {}).get("dev_seed_mode") == "stress" for t in seeded_stress_payload["tables"])
    assert all(len((state.get(t) or {}).get("items") or []) >= 6 for t in seeded_stress_payload["tables"])

    cleared = app_client.post("/kitchen/breakfast-kds/dev-test-orders", json={"action": "clear"})
    assert cleared.status_code == 200
    cleared_payload = cleared.get_json()
    assert cleared_payload["success"] is True
    assert len(cleared_payload["removed_tables"]) == 7
    assert state == {}
    assert len(saved) >= 2


def test_breakfast_kds_service_auto_set_in_preparo_safe_matching(monkeypatch):
    now_ref = kitchen_module.datetime(2026, 3, 20, 7, 30)
    monkeypatch.setattr(breakfast_kds_service, "build_today_breakfast_candidates", lambda now=None: [
        {"room": "12", "guest_main": "Ana Clara", "guest_key": "ana clara", "reservation_id": "R12"},
        {"room": "13", "guest_main": "Ana Clara", "guest_key": "ana clara", "reservation_id": "R13"},
    ])
    monkeypatch.setattr(
        breakfast_kds_service,
        "load_breakfast_kds_store",
        lambda: {"status_by_date": {now_ref.strftime("%Y-%m-%d"): {}}, "history_by_date": {}},
    )
    updates = []
    monkeypatch.setattr(
        breakfast_kds_service,
        "update_breakfast_status",
        lambda room, status, user, source="manual", context=None, now=None: (
            updates.append({"room": room, "status": status, "user": user, "source": source, "context": context}) or
            {"success": True, "room": room, "status": status, "changed": True}
        ),
    )

    by_room = breakfast_kds_service.auto_set_in_preparo_from_table_open(
        customer_type="hospede",
        customer_name="Ana Clara",
        room_number="12",
        user="operador",
        now=now_ref,
    )
    assert by_room["result"] == "updated"
    assert updates[0]["room"] == "12"
    assert updates[0]["status"] == "in_preparo"

    ambiguous = breakfast_kds_service.auto_set_in_preparo_from_table_open(
        customer_type="passante",
        customer_name="Ana Clara",
        room_number="",
        user="operador",
        now=now_ref,
    )
    assert ambiguous["result"] == "ambiguous"
    assert len(updates) == 1


def test_kds_visual_lane_by_print_destination(app_client, monkeypatch):
    _login(app_client)
    orders = {
        "21": {
            "status": "open",
            "opened_at": "19/03/2026 11:00",
            "waiter": "Operador",
            "items": [
                {
                    "id": "it-main",
                    "name": "Prato Principal",
                    "qty": 1,
                    "category": "Pratos",
                    "created_at": "19/03/2026 11:00",
                    "kds_status": "pending",
                    "printer_id": "1",
                },
                {
                    "id": "it-entry",
                    "name": "Entrada",
                    "qty": 1,
                    "category": "Entradas",
                    "created_at": "19/03/2026 11:01",
                    "kds_status": "pending",
                    "printer_id": "2",
                },
                {
                    "id": "it-dessert",
                    "name": "Sobremesa",
                    "qty": 1,
                    "category": "Sobremesas",
                    "created_at": "19/03/2026 11:02",
                    "kds_status": "pending",
                    "printer_id": "3",
                },
            ],
        }
    }

    monkeypatch.setattr(kitchen_module, "load_table_orders", lambda: orders)
    monkeypatch.setattr(kitchen_module, "save_table_orders", lambda updated: None)
    monkeypatch.setattr(kitchen_module, "load_menu_items", lambda: [])
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"kds_sla": {}})
    monkeypatch.setattr(
        kitchen_module,
        "load_printers",
        lambda: [
            {"id": "1", "name": "Cozinha"},
            {"id": "2", "name": "Cozinha Entradas"},
            {"id": "3", "name": "Cozinha Sobremesa"},
        ],
    )
    monkeypatch.setattr(kitchen_module, "get_default_printer", lambda _: None)

    resp = app_client.get("/kitchen/kds/data?station=cozinha")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    sections = payload["data"]["orders"][0]["sections"]
    by_name = {section["name"]: section for section in sections}
    assert by_name["Cozinha"]["visual_lane"] == "primary"
    assert by_name["Cozinha Entradas"]["visual_lane"] == "secondary"
    assert by_name["Cozinha Sobremesa"]["visual_lane"] == "secondary"


def test_reports_consistency_and_export_csv(app_client, monkeypatch):
    _login(app_client, role="gerente", department="Cozinha")
    entries = [
        {
            "id": "20260319120000_PORT_OUT",
            "product": "Picanha Bruta",
            "qty": -2.0,
            "price": 40.0,
            "supplier": "PORCIONAMENTO (SAÍDA)",
            "origin_supplier": "Frigorífico XPTO",
            "invoice": "Fornecedor: Frigorífico XPTO | Degelo: 0.200kg | Aparas: 0.100kg | Descarte: 0.050kg | Cocção: 0.100kg",
            "date": "19/03/2026",
            "entry_date": "19/03/2026 12:00",
            "user": "Chef 1",
        },
        {
            "id": "20260319120000_PORT_IN_Bife",
            "product": "Bife",
            "qty": 10,
            "price": 6.5,
            "supplier": "PORCIONAMENTO (ENTRADA)",
            "date": "19/03/2026",
            "entry_date": "19/03/2026 12:01",
        },
        {
            "id": "20260319120000_PORT_TRIM_RETURN",
            "product": "Picanha Bruta",
            "qty": 0.1,
            "price": 40.0,
            "supplier": "PORCIONAMENTO (RETORNO APARAS)",
            "date": "19/03/2026",
            "entry_date": "19/03/2026 12:02",
        },
    ]

    monkeypatch.setattr(kitchen_module, "load_products", lambda: [{"name": "Picanha Bruta"}])
    monkeypatch.setattr(kitchen_module, "load_stock_entries", lambda: entries)
    monkeypatch.setattr(
        kitchen_module,
        "render_template",
        lambda template, **kwargs: json.dumps({"template": template, "stats": kwargs.get("stats"), "data_count": len(kwargs.get("data", []))}, default=str),
    )

    resp = app_client.get("/kitchen/reports?start_date=19/03/2026&end_date=19/03/2026")
    assert resp.status_code == 200
    payload = json.loads(resp.get_data(as_text=True))
    assert payload["template"] == "kitchen_reports.html"
    assert payload["data_count"] == 1
    assert payload["stats"]["count"] == 1
    assert payload["stats"]["total_kg"] == pytest.approx(2.0)
    assert payload["stats"]["total_value"] == pytest.approx(76.0)

    csv_resp = app_client.get("/kitchen/reports/export?format=csv&start_date=19/03/2026&end_date=19/03/2026")
    assert csv_resp.status_code == 200
    csv_text = csv_resp.get_data(as_text=True)
    assert "Produto" in csv_text
    assert "Picanha Bruta" in csv_text
    assert "Frigorífico XPTO" in csv_text


def test_portion_post_integrates_stock_and_label_print(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 2")
    products = [
        {"name": "Frango Inteiro", "category": "Carnes", "unit": "g", "price": 20.0, "status": "Ativo"},
        {"name": "Frango Porção", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    saved_products_payload = []
    printed_labels = []

    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor A", "active": True}])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))
    monkeypatch.setattr(kitchen_module, "secure_save_products", lambda payload, user_id=None: saved_products_payload.append((payload, user_id)))
    monkeypatch.setattr(kitchen_module, "print_portion_labels", lambda labels: printed_labels.extend(labels))
    monkeypatch.setattr(kitchen_module, "file_lock", lambda _: nullcontext())
    monkeypatch.setattr(kitchen_module, "LoggerService", type("L", (), {"log_acao": staticmethod(lambda **kwargs: None)}))
    monkeypatch.setattr(kitchen_module, "get_product_balances", lambda: {"Frango Inteiro": 10.0})

    resp = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "Frango Inteiro",
            "origin_supplier": "Fornecedor A",
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "discard_weight": "100",
            "cooked_weight": "1500",
            "dest_product[]": ["Frango Porção"],
            "dest_count[]": ["10"],
            "final_qty[]": ["1500"],
        },
    )
    assert resp.status_code == 302
    assert "/service/cozinha" in resp.location
    assert any("PORCIONAMENTO (SAÍDA)" in str(e.get("supplier")) for e in stock_entries)
    assert any("PORCIONAMENTO (ENTRADA)" in str(e.get("supplier")) for e in stock_entries)
    assert len(printed_labels) == 10
    assert saved_products_payload


def test_portion_can_start_from_step2_without_origin_field(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 3")
    products = [
        {"name": "Carne Base", "category": "Carnes", "unit": "g", "price": 20.0, "status": "Ativo"},
        {"name": "Carne Porcionada", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    printed_labels = []

    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor A", "active": True}])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))
    monkeypatch.setattr(kitchen_module, "secure_save_products", lambda payload, user_id=None: None)
    monkeypatch.setattr(kitchen_module, "print_portion_labels", lambda labels: printed_labels.extend(labels))
    monkeypatch.setattr(kitchen_module, "file_lock", lambda _: nullcontext())
    monkeypatch.setattr(kitchen_module, "LoggerService", type("L", (), {"log_acao": staticmethod(lambda **kwargs: None)}))
    monkeypatch.setattr(kitchen_module, "get_product_balances", lambda: {"Carne Base": 5.0})

    resp = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "",
            "origin_supplier": "Fornecedor A",
            "component_product[]": ["Carne Base"],
            "component_weight[]": ["2000"],
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "discard_weight": "100",
            "cooked_weight": "1500",
            "dest_product[]": ["Carne Porcionada"],
            "dest_count[]": ["10"],
            "final_qty[]": ["1500"],
        },
    )
    assert resp.status_code == 302
    assert "/service/cozinha" in resp.location
    assert any(e.get("product") == "Carne Base" and e.get("qty") < 0 for e in stock_entries)
    in_entries = [e for e in stock_entries if e.get("supplier") == "PORCIONAMENTO (ENTRADA)"]
    assert len(in_entries) == 1
    assert in_entries[0]["price"] == pytest.approx(3.8)
    assert len(printed_labels) == 10


def test_portion_rejects_without_step1_and_without_valid_step2(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 4")
    products = [
        {"name": "Carne Base", "category": "Carnes", "unit": "g", "price": 20.0, "status": "Ativo"},
        {"name": "Carne Porcionada", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))

    resp = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "",
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "discard_weight": "100",
            "cooked_weight": "1500",
            "dest_product[]": ["Carne Porcionada"],
            "dest_count[]": ["10"],
            "final_qty[]": ["1500"],
        },
    )
    assert resp.status_code == 302
    assert "/kitchen/portion" in resp.location
    assert stock_entries == []


def test_portion_high_loss_and_unexpected_yield_scenarios(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 5")
    products = [
        {"name": "Peixe Inteiro", "category": "Carnes", "unit": "g", "price": 30.0, "status": "Ativo"},
        {"name": "Peixe Porcionado", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor B", "active": True}])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))
    monkeypatch.setattr(kitchen_module, "secure_save_products", lambda payload, user_id=None: None)
    monkeypatch.setattr(kitchen_module, "print_portion_labels", lambda labels: None)
    monkeypatch.setattr(kitchen_module, "file_lock", lambda _: nullcontext())
    monkeypatch.setattr(kitchen_module, "LoggerService", type("L", (), {"log_acao": staticmethod(lambda **kwargs: None)}))
    monkeypatch.setattr(kitchen_module, "get_product_balances", lambda: {"Peixe Inteiro": 10.0})

    high_loss = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "Peixe Inteiro",
            "origin_supplier": "Fornecedor B",
            "frozen_weight": "2000",
            "thawed_weight": "1300",
            "trim_weight": "100",
            "discard_weight": "200",
            "cooked_weight": "800",
            "dest_product[]": ["Peixe Porcionado"],
            "dest_count[]": ["8"],
            "final_qty[]": ["800"],
        },
    )
    assert high_loss.status_code == 302
    assert "/service/cozinha" in high_loss.location
    assert any(e.get("supplier") == "PORCIONAMENTO (ENTRADA)" for e in stock_entries)

    stock_entries.clear()
    unexpected_yield = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "Peixe Inteiro",
            "origin_supplier": "Fornecedor B",
            "frozen_weight": "2000",
            "thawed_weight": "1300",
            "trim_weight": "100",
            "discard_weight": "200",
            "cooked_weight": "1200",
            "dest_product[]": ["Peixe Porcionado"],
            "dest_count[]": ["8"],
            "final_qty[]": ["1200"],
        },
    )
    assert unexpected_yield.status_code == 302
    assert "/kitchen/portion" in unexpected_yield.location
    assert stock_entries == []


def test_portion_blocks_when_single_origin_stock_is_insufficient(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 6")
    products = [
        {"name": "Costela", "category": "Carnes", "unit": "g", "price": 35.0, "status": "Ativo"},
        {"name": "Costela Porcionada", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor C", "active": True}])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))
    monkeypatch.setattr(kitchen_module, "get_product_balances", lambda: {"Costela": 1.0})

    resp = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "Costela",
            "origin_supplier": "Fornecedor C",
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "discard_weight": "100",
            "cooked_weight": "1500",
            "dest_product[]": ["Costela Porcionada"],
            "dest_count[]": ["10"],
            "final_qty[]": ["1500"],
        },
    )
    assert resp.status_code == 302
    assert "/kitchen/portion" in resp.location
    assert stock_entries == []


def test_portion_blocks_when_kit_component_stock_is_insufficient(app_client, monkeypatch):
    _login(app_client, role="admin", department="Cozinha", user="Chef 7")
    products = [
        {"name": "Proteína X", "category": "Carnes", "unit": "g", "price": 20.0, "status": "Ativo"},
        {"name": "Temperado X", "category": "Carnes", "unit": "g", "price": 0.0, "status": "Ativo"},
    ]
    stock_entries = []
    monkeypatch.setattr(kitchen_module, "load_products", lambda: products)
    monkeypatch.setattr(kitchen_module, "load_settings", lambda: {"portioning_rules": [], "product_portioning_rules": []})
    monkeypatch.setattr(kitchen_module, "load_suppliers", lambda: [{"name": "Fornecedor C", "active": True}])
    monkeypatch.setattr(kitchen_module, "save_stock_entry", lambda entry: stock_entries.append(entry))
    monkeypatch.setattr(kitchen_module, "get_product_balances", lambda: {"Proteína X": 0.5})

    resp = app_client.post(
        "/kitchen/portion",
        data={
            "origin_product": "",
            "origin_supplier": "Fornecedor C",
            "component_product[]": ["Proteína X"],
            "component_weight[]": ["1200"],
            "frozen_weight": "1200",
            "thawed_weight": "1000",
            "trim_weight": "50",
            "discard_weight": "50",
            "cooked_weight": "900",
            "dest_product[]": ["Temperado X"],
            "dest_count[]": ["9"],
            "final_qty[]": ["900"],
        },
    )
    assert resp.status_code == 302
    assert "/kitchen/portion" in resp.location
    assert stock_entries == []
