import json
from flask import Flask, session
import pytest

from app.blueprints.finance import routes as finance_routes


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    return app


def _set_profile(role="financeiro", user="fin1", permissions=None):
    session.clear()
    session.update(
        {
            "user": user,
            "role": role,
            "department": "Financeiro",
            "permissions": permissions or [],
        }
    )


def _build_sessions_for_ranking():
    return [
        {
            "id": "S1",
            "type": "restaurant",
            "status": "open",
            "transactions": [
                {
                    "id": "TX1A",
                    "type": "sale",
                    "category": "Pagamento de Conta",
                    "amount": 60.0,
                    "description": "Venda Mesa 70 - Cartão",
                    "payment_method": "Cartão",
                    "timestamp": "17/03/2026 10:00",
                    "user": "sup1",
                    "commission_reference_id": "close:CLOSE_70",
                    "waiter_breakdown": {"garcom1": 70.0, "garcom2": 30.0},
                    "service_fee_removed": False,
                    "commission_eligible": True,
                    "operator": "sup1",
                    "details": {"table_id": "70"},
                },
                {
                    "id": "TX1B",
                    "type": "sale",
                    "category": "Pagamento de Conta",
                    "amount": 40.0,
                    "description": "Venda Mesa 70 - Dinheiro",
                    "payment_method": "Dinheiro",
                    "timestamp": "17/03/2026 10:00",
                    "user": "sup1",
                    "commission_reference_id": "close:CLOSE_70",
                    "waiter_breakdown": {"garcom1": 70.0, "garcom2": 30.0},
                    "service_fee_removed": False,
                    "commission_eligible": True,
                    "operator": "sup1",
                    "details": {"table_id": "70"},
                },
                {
                    "id": "TX2A",
                    "type": "sale",
                    "category": "Pagamento de Conta",
                    "amount": 20.0,
                    "description": "Venda Mesa 71 - Pix",
                    "payment_method": "Pix",
                    "timestamp": "17/03/2026 11:00",
                    "user": "sup2",
                    "commission_reference_id": "close:CLOSE_71",
                    "waiter_breakdown": {"garcom1": 50.0},
                    "service_fee_removed": True,
                    "commission_eligible": False,
                    "operator": "sup2",
                    "details": {"table_id": "71"},
                },
                {
                    "id": "TX2B",
                    "type": "sale",
                    "category": "Pagamento de Conta",
                    "amount": 30.0,
                    "description": "Venda Mesa 71 - Cartão",
                    "payment_method": "Cartão",
                    "timestamp": "17/03/2026 11:00",
                    "user": "sup2",
                    "commission_reference_id": "close:CLOSE_71",
                    "waiter_breakdown": {"garcom1": 50.0},
                    "service_fee_removed": True,
                    "commission_eligible": False,
                    "operator": "sup2",
                    "details": {"table_id": "71"},
                },
                {
                    "id": "TX3",
                    "type": "sale",
                    "category": "Conta Funcionário",
                    "amount": 16.0,
                    "description": "Consumo Funcionário - JOAO",
                    "payment_method": "Conta Funcionário",
                    "timestamp": "17/03/2026 12:00",
                    "user": "oper1",
                    "commission_reference_id": "staff:FUNC_JOAO",
                    "service_fee_removed": True,
                    "commission_eligible": False,
                    "operator": "oper1",
                    "details": {"table_id": "FUNC_JOAO"},
                },
                {
                    "id": "TX4",
                    "type": "in",
                    "category": "Pagamento de Conta",
                    "amount": 80.0,
                    "description": "Pagamento Quarto 101 (Cartão)",
                    "payment_method": "Cartão",
                    "timestamp": "17/03/2026 13:00",
                    "user": "rec1",
                    "commission_reference_id": "charge:CHARGE_101",
                    "waiter_breakdown": {"garcom2": 80.0},
                    "service_fee_removed": False,
                    "commission_eligible": True,
                    "operator": "rec1",
                    "details": {"room_number": "101"},
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    "client_type,user_agent",
    [
        ("desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("mobile", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"),
    ],
)
def test_commission_ranking_uses_logical_reference_without_count_inflation(monkeypatch, client_type, user_agent, tmp_path):
    app = _make_test_app()
    sessions = _build_sessions_for_ranking()
    monkeypatch.setattr(finance_routes, "_load_cashier_sessions", lambda: sessions)
    monkeypatch.setattr(finance_routes, "render_template", lambda tpl, **ctx: ctx)
    monkeypatch.setattr(finance_routes, "log_system_action", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/commission_ranking?start_date=2026-03-01&end_date=2026-03-31",
        method="GET",
        headers={"User-Agent": user_agent},
    ):
        _set_profile(role="financeiro", user=f"fin_{client_type}")
        ctx = finance_routes.commission_ranking.__wrapped__()

    ranking = {row["waiter"]: row for row in ctx["ranking"]}
    assert abs(ctx["total_sales"] - 246.0) < 0.001
    assert ranking["garcom1"]["count"] == 2
    assert ranking["garcom2"]["count"] == 2
    assert abs(ranking["garcom1"]["total"] - 120.0) < 0.001
    assert abs(ranking["garcom2"]["total"] - 110.0) < 0.001
    assert abs(ranking["garcom1"]["commission"] - 7.0) < 0.001
    assert abs(ranking["garcom2"]["commission"] - 11.0) < 0.001
    assert any(ev["reference_key"] == "close:CLOSE_71" for ev in ctx["removed_events"])
    removed_close = next(ev for ev in ctx["removed_events"] if ev["reference_key"] == "close:CLOSE_71")
    assert abs(removed_close["amount"] - 50.0) < 0.001
    (tmp_path / f"commission_ranking_ctx_{client_type}.json").write_text(
        json.dumps(
            {
                "client_type": client_type,
                "total_sales": ctx["total_sales"],
                "total_commission": ctx["total_commission"],
                "ranking": ctx["ranking"],
                "removed_events": ctx["removed_events"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_commission_ranking_blocks_unauthorized_user(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "_load_cashier_sessions", lambda: [])

    with app.test_request_context("/commission_ranking", method="GET"):
        _set_profile(role="colaborador", user="op1", permissions=["restaurante_mirapraia"])
        response = finance_routes.commission_ranking.__wrapped__()

    assert response.status_code == 302
