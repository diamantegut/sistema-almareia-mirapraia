from pathlib import Path

import pytest
from flask import Flask

import app.blueprints.reception.routes as reception_module
from app.blueprints.reception import reception_bp
from app.services.payment_allocation_service import allocate_payments_with_change


def test_allocate_payments_exact_cash():
    result = allocate_payments_with_change(
        [{"method": "Dinheiro", "amount": 100.0}],
        100.0,
    )
    assert result["total_applied"] == pytest.approx(100.0)
    assert result["total_received"] == pytest.approx(100.0)
    assert result["total_change"] == pytest.approx(0.0)


def test_allocate_payments_cash_with_change():
    result = allocate_payments_with_change(
        [{"method": "Dinheiro", "amount": 120.0}],
        100.0,
    )
    payment = result["payments"][0]
    assert payment["amount_applied"] == pytest.approx(100.0)
    assert payment["amount_input"] == pytest.approx(120.0)
    assert payment["change_amount"] == pytest.approx(20.0)
    assert result["total_change"] == pytest.approx(20.0)


def test_allocate_payments_mixed_with_cash_change():
    result = allocate_payments_with_change(
        [
            {"method": "Cartão", "amount": 80.0},
            {"method": "Dinheiro", "amount": 40.0},
        ],
        100.0,
    )
    assert result["total_applied"] == pytest.approx(100.0)
    assert result["total_received"] == pytest.approx(120.0)
    assert result["total_change"] == pytest.approx(20.0)
    cash = next(p for p in result["payments"] if p["is_cash"])
    assert cash["amount_applied"] == pytest.approx(20.0)
    assert cash["change_amount"] == pytest.approx(20.0)


def test_allocate_payments_blocks_overpay_without_cash():
    with pytest.raises(ValueError):
        allocate_payments_with_change(
            [{"method": "Cartão", "amount": 110.0}],
            100.0,
        )


def test_reception_reservation_pay_allows_cash_change(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    app.register_blueprint(reception_bp)

    calls = {}

    class _ResService:
        def get_reservation_by_id(self, _):
            return {"id": "R1", "guest_name": "Hóspede", "amount": "100.00", "paid_amount": "0.00", "source_type": "manual"}

        def get_reservation_payments(self):
            return {}

        def add_payment(self, reservation_id, amount, details):
            calls["add_payment"] = {"reservation_id": reservation_id, "amount": amount, "details": details}

    monkeypatch.setattr(reception_module, "ReservationService", lambda: _ResService())
    monkeypatch.setattr(reception_module.CashierService, "get_active_session", staticmethod(lambda _: {"id": "S1", "status": "open"}))
    monkeypatch.setattr(
        reception_module.CashierService,
        "add_transaction",
        staticmethod(lambda **kwargs: calls.setdefault("add_transaction", kwargs)),
    )
    monkeypatch.setattr(
        reception_module,
        "load_payment_methods",
        lambda: [{"id": "dinheiro", "name": "Dinheiro", "available_in": ["reservations"]}],
    )
    monkeypatch.setattr(reception_module.FiscalPoolService, "add_to_pool", staticmethod(lambda **kwargs: None))
    monkeypatch.setattr(reception_module, "log_action", lambda *args, **kwargs: None)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "tester"
            sess["role"] = "admin"
            sess["department"] = "Recepção"
        resp = client.post(
            "/reception/reservation/pay",
            json={
                "reservation_id": "R1",
                "amount": 120,
                "payment_method_id": "dinheiro",
                "payment_method_name": "Dinheiro",
                "origin": "reservations",
            },
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        assert payload["change_amount"] == pytest.approx(20.0)
        assert calls["add_transaction"]["amount"] == pytest.approx(100.0)
        assert calls["add_transaction"]["details"]["amount_received"] == pytest.approx(120.0)
        assert calls["add_transaction"]["details"]["change_amount"] == pytest.approx(20.0)


def test_reception_reservation_pay_blocks_overpay_without_cash(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    app.register_blueprint(reception_bp)

    class _ResService:
        def get_reservation_by_id(self, _):
            return {"id": "R1", "guest_name": "Hóspede", "amount": "100.00", "paid_amount": "0.00", "source_type": "manual"}

        def get_reservation_payments(self):
            return {}

    monkeypatch.setattr(reception_module, "ReservationService", lambda: _ResService())
    monkeypatch.setattr(reception_module.CashierService, "get_active_session", staticmethod(lambda _: {"id": "S1", "status": "open"}))
    monkeypatch.setattr(
        reception_module,
        "load_payment_methods",
        lambda: [{"id": "cartao", "name": "Cartão", "available_in": ["reservations"]}],
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "tester"
            sess["role"] = "admin"
            sess["department"] = "Recepção"
        resp = client.post(
            "/reception/reservation/pay",
            json={
                "reservation_id": "R1",
                "amount": 120,
                "payment_method_id": "cartao",
                "payment_method_name": "Cartão",
                "origin": "reservations",
            },
        )
        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload["success"] is False


def test_templates_show_change_feedback_and_history_columns():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    restaurant_html = (root / "restaurant_table_order.html").read_text(encoding="utf-8")
    restaurant_cashier_html = (root / "restaurant_cashier.html").read_text(encoding="utf-8")
    reception_cashier_html = (root / "reception_cashier.html").read_text(encoding="utf-8")
    reservations_cashier_html = (root / "reception_reservations_cashier.html").read_text(encoding="utf-8")
    reception_rooms_html = (root / "reception_rooms.html").read_text(encoding="utf-8")
    reception_reservations_html = (root / "reception_reservations.html").read_text(encoding="utf-8")

    assert "Troco" in restaurant_html
    assert "received_amount" in restaurant_html
    assert "Pagamento exato" in restaurant_cashier_html
    assert "Com troco" in restaurant_cashier_html
    assert "Troco: R$" in reception_cashier_html
    assert "Pagamento exato" in reception_cashier_html
    assert "Com troco" in reception_cashier_html
    assert "Troco: R$" in reservations_cashier_html
    assert "Pagamento exato" in reservations_cashier_html
    assert 'id="resPayChangePreview"' in reception_rooms_html
    assert 'id="resPayChangePreview"' in reception_reservations_html
    assert "Pagamento exato (sem troco)." in reception_rooms_html
    assert "Pagamento exato (sem troco)." in reception_reservations_html
    assert "<th>Recebido</th>" in reception_reservations_html
    assert "<th>Troco</th>" in reception_reservations_html


def test_routes_use_allocation_service_for_change_control():
    root = Path(__file__).resolve().parents[1] / "app" / "blueprints"
    restaurant_routes = (root / "restaurant" / "routes.py").read_text(encoding="utf-8")
    reception_routes = (root / "reception" / "routes.py").read_text(encoding="utf-8")
    assert "allocate_payments_with_change" in restaurant_routes
    assert "allocate_payments_with_change" in reception_routes
