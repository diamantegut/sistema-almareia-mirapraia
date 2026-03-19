from pathlib import Path
from flask import Flask, session

from app.blueprints.finance import routes as finance_routes


def _read_template(name):
    root = Path(__file__).resolve().parents[1]
    return (root / "app" / "templates" / name).read_text(encoding="utf-8")


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def test_restaurant_close_modal_hides_expected_value():
    html = _read_template("restaurant_cashier.html")
    assert "Saldo Calculado em Dinheiro pelo Sistema" not in html
    assert 'name="closing_cash"' in html
    assert 'name="closing_non_cash"' in html


def test_reception_close_modal_hides_expected_value():
    html = _read_template("reception_cashier.html")
    assert "Saldo Calculado em Dinheiro pelo Sistema" not in html
    assert 'name="closing_cash"' in html
    assert 'name="closing_non_cash"' in html


def test_reservations_close_modal_hides_expected_value_and_requires_two_inputs():
    html = _read_template("reception_reservations_cashier.html")
    assert "Saldo Calculado" not in html
    assert 'name="closing_cash"' in html
    assert 'name="closing_non_cash"' in html
    assert html.count('name="closing_non_cash"') >= 1


def test_balances_keeps_discrepancy_for_admin_dashboard(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(
        finance_routes,
        "_load_cashier_sessions",
        lambda: [
            {
                "id": "S1",
                "status": "closed",
                "type": "restaurant_service",
                "opened_at": "10/03/2026 08:00",
                "closed_at": "10/03/2026 12:00",
                "opening_balance": 100.0,
                "closing_balance": 250.0,
                "closing_cash": 140.0,
                "closing_non_cash": 110.0,
                "difference": 20.0,
                "difference_approved": False,
                "transactions": [
                    {"type": "sale", "amount": 20.0, "payment_method": "Dinheiro"},
                    {"type": "sale", "amount": 130.0, "payment_method": "Crédito"},
                ],
            }
        ],
    )
    with app.test_request_context(
        "/finance/balances/data?period_type=monthly&year=2026&specific_value=3",
        method="GET",
        headers={"Accept": "application/json"},
    ):
        session.clear()
        session.update({"user": "admin", "role": "admin"})
        response = finance_routes.finance_balances_data.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert len(payload["data"]) == 1
    first = payload["data"][0]
    assert first["has_anomaly"] is True
    assert abs(float(first["difference"])) > 0.01
