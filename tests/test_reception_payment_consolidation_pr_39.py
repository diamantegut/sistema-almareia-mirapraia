import inspect
from copy import deepcopy

from flask import Flask, session

from app.blueprints.reception import routes as reception_routes


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/reception/cashier", endpoint="reception.reception_cashier", view_func=lambda: "cashier")
    app.add_url_rule("/reception/rooms", endpoint="reception.reception_rooms", view_func=lambda: "rooms")
    return app


def _set_user():
    session.clear()
    session.update({"user": "rec1", "role": "supervisor", "department": "Recepção", "permissions": ["recepcao"]})


def test_process_charge_payment_multi_and_fiscal(monkeypatch):
    room_charges = [{
        "id": "C1",
        "room_number": "11",
        "status": "pending",
        "total": 100.0,
        "items": [{"name": "Suco", "qty": 1, "price": 100.0}],
        "waiter_breakdown": [{"waiter": "Adailton", "amount": 100.0}],
        "service_fee_removed": False,
    }]
    saved = {"value": False}
    pool_calls = []
    cashier_calls = []
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: saved.update({"value": True}) or True)
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(
        reception_routes.FiscalPoolService,
        "add_to_pool",
        lambda **kwargs: pool_calls.append(deepcopy(kwargs)) or True,
    )
    monkeypatch.setattr(
        reception_routes.CashierService,
        "add_transaction",
        lambda **kwargs: cashier_calls.append(deepcopy(kwargs)) or True,
    )
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    out = reception_routes._process_charge_payment(
        charge=room_charges[0],
        payments_to_process=[
            {"method_id": "pix", "method_name": "PIX", "amount": 60.0, "is_fiscal": True},
            {"method_id": "cartao", "method_name": "Cartão", "amount": 40.0, "is_fiscal": True},
        ],
        room_charges_ref=room_charges,
        cashier_session={"id": "S1"},
        current_user="rec1",
        require_exact_total=True,
        add_cashier_transactions=True,
        add_fiscal_pool=True,
    )
    assert out["success"] is True
    assert room_charges[0]["status"] == "paid"
    assert room_charges[0]["payment_method"] == "Múltiplos"
    assert saved["value"] is True
    assert len(cashier_calls) == 2
    assert len(pool_calls) == 1
    assert cashier_calls[0]["details"]["waiter_breakdown"][0]["waiter"] == "Adailton"
    assert cashier_calls[0]["details"]["commission_eligible"] is True


def test_reception_pay_charge_route_uses_consolidated_core(monkeypatch):
    app = _make_app()
    room_charges = [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": []}]
    called = {"value": False}
    monkeypatch.setattr(reception_routes, "_has_reception_authorized_access", lambda: True)
    monkeypatch.setattr(reception_routes, "_get_active_guest_consumption_session", lambda: {"id": "S1"})
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: deepcopy(room_charges))
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [{"id": "pix", "name": "PIX", "is_fiscal": True, "available_in": ["reception"]}])
    monkeypatch.setattr(
        reception_routes,
        "_process_charge_payment",
        lambda **kwargs: called.update({"value": True}) or {"success": True, "paid_total": 100.0, "fiscal_error": None},
    )
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    with app.test_request_context("/reception/pay_charge/C1", method="POST", json={"room_num": "11", "payments": [{"method": "pix", "amount": 100.0}]}):
        _set_user()
        response = reception_routes.reception_pay_charge.__wrapped__("C1")
    payload = response.get_json()
    assert payload["success"] is True
    assert called["value"] is True


def test_reception_close_account_uses_consolidated_core(monkeypatch):
    app = _make_app()
    room_charges = [
        {"id": "C1", "room_number": "11", "status": "pending", "total": 70.0, "items": [{"name": "A", "qty": 1, "price": 70.0}]},
        {"id": "C2", "room_number": "11", "status": "pending", "total": 30.0, "items": [{"name": "B", "qty": 1, "price": 30.0}]},
    ]
    calls = []
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes, "_get_active_guest_consumption_session", lambda: {"id": "S1"})
    monkeypatch.setattr(reception_routes.CashierService, "get_active_session", lambda cashier_type: {"id": "S1"})
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: deepcopy(room_charges))
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [{"id": "pix", "name": "PIX", "is_fiscal": True, "available_in": ["reception"]}])
    monkeypatch.setattr(
        reception_routes,
        "_process_charge_payment",
        lambda **kwargs: calls.append(kwargs) or {"success": True, "fiscal_error": None},
    )
    monkeypatch.setattr(reception_routes.CashierService, "add_transaction", lambda **kwargs: True)
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    with app.test_request_context(
        "/reception/close_account/11",
        method="POST",
        json={"payments": [{"method_id": "pix", "amount": 100.0}]},
    ):
        _set_user()
        response = reception_routes.reception_close_account.__wrapped__("11")
    payload = response.get_json()
    assert payload["success"] is True
    assert len(calls) == 2


def test_consolidated_core_is_used_in_all_payment_paths():
    src_rooms = inspect.getsource(reception_routes.reception_rooms)
    src_pay_charge = inspect.getsource(reception_routes.reception_pay_charge)
    src_close = inspect.getsource(reception_routes.reception_close_account)
    assert "_process_charge_payment(" in src_rooms
    assert "_process_charge_payment(" in src_pay_charge
    assert "_process_charge_payment(" in src_close


def test_process_charge_payment_blocks_overpay_without_cash(monkeypatch):
    room_charges = [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": []}]
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    out = reception_routes._process_charge_payment(
        charge=room_charges[0],
        payments_to_process=[{"method_id": "pix", "method_name": "PIX", "amount": 120.0, "is_fiscal": True}],
        room_charges_ref=room_charges,
        cashier_session={"id": "S1"},
        current_user="rec1",
        require_exact_total=True,
        add_cashier_transactions=False,
        add_fiscal_pool=False,
    )
    assert out["success"] is False
    assert "dinheiro" in out["error"].lower()


def test_process_charge_payment_allows_overpay_with_cash_and_records_change(monkeypatch):
    room_charges = [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": []}]
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    out = reception_routes._process_charge_payment(
        charge=room_charges[0],
        payments_to_process=[{"method_id": "dinheiro", "method_name": "Dinheiro", "amount": 120.0, "is_fiscal": False}],
        room_charges_ref=room_charges,
        cashier_session={"id": "S1"},
        current_user="rec1",
        require_exact_total=True,
        add_cashier_transactions=False,
        add_fiscal_pool=False,
    )
    assert out["success"] is True
    assert out["change_amount"] == 20.0
    assert room_charges[0]["change_amount"] == 20.0


def test_pay_charge_rejects_payment_method_not_allowed_for_reception(monkeypatch):
    app = _make_app()
    room_charges = [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": []}]
    monkeypatch.setattr(reception_routes, "_has_reception_authorized_access", lambda: True)
    monkeypatch.setattr(reception_routes, "_get_active_guest_consumption_session", lambda: {"id": "S1"})
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: deepcopy(room_charges))
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [{"id": "pixrest", "name": "PIX Restaurante", "is_fiscal": True, "available_in": ["restaurant"]}])
    with app.test_request_context("/reception/pay_charge/C1", method="POST", json={"room_num": "11", "payments": [{"method": "pixrest", "amount": 100.0}]}):
        _set_user()
        response = reception_routes.reception_pay_charge.__wrapped__("C1")
    payload = response.get_json()
    assert payload["success"] is False


def test_close_account_rejects_overpay_without_cash(monkeypatch):
    app = _make_app()
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes.CashierService, "get_active_session", lambda cashier_type: {"id": "S1"})
    monkeypatch.setattr(reception_routes, "load_room_charges", lambda: [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": []}])
    monkeypatch.setattr(reception_routes, "load_payment_methods", lambda: [{"id": "pix", "name": "PIX", "is_fiscal": True, "available_in": ["reception"]}])
    with app.test_request_context("/reception/close_account/11", method="POST", json={"payments": [{"method_id": "pix", "amount": 120.0}]}):
        _set_user()
        response, status = reception_routes.reception_close_account.__wrapped__("11")
    payload = response.get_json()
    assert status == 400
    assert payload["success"] is False
    assert "dinheiro" in payload["error"].lower()


def test_close_account_allows_overpay_with_cash(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(reception_routes, "load_room_occupancy", lambda: {"11": {"guest_name": "Hospede"}})
    monkeypatch.setattr(reception_routes.CashierService, "get_active_session", lambda cashier_type: {"id": "S1"})
    monkeypatch.setattr(
        reception_routes,
        "load_room_charges",
        lambda: [{"id": "C1", "room_number": "11", "status": "pending", "total": 100.0, "items": [{"name": "A", "qty": 1, "price": 100.0}]}],
    )
    monkeypatch.setattr(
        reception_routes,
        "load_payment_methods",
        lambda: [{"id": "dinheiro", "name": "Dinheiro", "is_fiscal": False, "available_in": ["reception"]}],
    )
    monkeypatch.setattr(
        reception_routes,
        "_process_charge_payment",
        lambda **kwargs: calls.append(kwargs) or {"success": True, "fiscal_error": None},
    )
    monkeypatch.setattr(reception_routes.CashierService, "add_transaction", lambda **kwargs: True)
    monkeypatch.setattr(reception_routes, "save_room_charges", lambda payload: True)
    monkeypatch.setattr(reception_routes, "log_action", lambda *args, **kwargs: None)
    with app.test_request_context("/reception/close_account/11", method="POST", json={"payments": [{"method_id": "dinheiro", "amount": 120.0}]}):
        _set_user()
        response = reception_routes.reception_close_account.__wrapped__("11")
    payload = response.get_json()
    assert payload["success"] is True
    assert len(calls) == 1
