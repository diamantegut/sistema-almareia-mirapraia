from datetime import datetime
from flask import Flask, session

from app.blueprints.finance import routes as finance_routes
from app.services.card_reconciliation_service import build_card_transaction_signature, build_system_transaction_signature, reconcile_transactions


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/admin/reconciliation", endpoint="finance.finance_reconciliation", view_func=lambda: "recon")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _session_with_sales(ts_amounts):
    transactions = []
    for idx, (ts, amount, method) in enumerate(ts_amounts, start=1):
        transactions.append({
            "id": f"T{idx}-{ts}",
            "type": "sale",
            "timestamp": ts,
            "amount": amount,
            "description": "Venda",
            "payment_method": method,
            "details": {},
        })
    return {"type": "restaurant_service", "transactions": transactions}


def test_sync_uses_all_pagseguro_accounts_and_matches_globally(monkeypatch):
    app = _make_test_app()
    captured = {}
    sessions = [
        _session_with_sales([("16/03/2026 10:00", 100.0, "Cartão de Crédito"), ("16/03/2026 10:10", 150.0, "Cartão de Crédito")]),
        _session_with_sales([("16/03/2026 11:00", 200.0, "Cartão de Crédito")]),
    ]
    monkeypatch.setattr(finance_routes, "_load_cashier_sessions", lambda: sessions)
    monkeypatch.setattr(
        finance_routes,
        "fetch_pagseguro_transactions_detailed",
        lambda start, end: {
            "transactions": [
                {"id": "PA-1", "provider": "PagSeguro (Conta A)", "date": datetime.strptime("2026-03-16 10:01:00", "%Y-%m-%d %H:%M:%S"), "amount": 100.0, "type": "1"},
                {"id": "PB-1", "provider": "PagSeguro (Conta B)", "date": datetime.strptime("2026-03-16 11:00:30", "%Y-%m-%d %H:%M:%S"), "amount": 200.0, "type": "1"},
                {"id": "PB-2", "provider": "PagSeguro (Conta B)", "date": datetime.strptime("2026-03-16 12:00:00", "%Y-%m-%d %H:%M:%S"), "amount": 50.0, "type": "1"},
            ],
            "errors": [],
            "total_accounts": 2,
            "processed_accounts": 2,
        },
    )
    monkeypatch.setattr(finance_routes, "load_card_settings", lambda: {"pagseguro": [{"alias": "Conta A"}, {"alias": "Conta B"}]})
    monkeypatch.setattr(finance_routes, "_normalize_pagseguro_configs", lambda settings: settings.get("pagseguro", []))
    monkeypatch.setattr(finance_routes, "load_card_consumption_map", lambda: {})
    monkeypatch.setattr(finance_routes, "register_consumed_card_matches", lambda matches, **kwargs: len(matches))
    monkeypatch.setattr(finance_routes, "_annotate_reconciliation_results", lambda results, settings: results)
    monkeypatch.setattr(finance_routes, "_load_manual_approval_signatures", lambda: set())
    monkeypatch.setattr(finance_routes, "_build_suspected_time_gap_matches", lambda us, uc: [])
    monkeypatch.setattr(finance_routes, "_apply_manual_approved_suspects", lambda results, suspects, approved: suspects)
    monkeypatch.setattr(finance_routes, "_save_reconciliation_audit", lambda **kwargs: None)
    monkeypatch.setattr(finance_routes, "log_system_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(finance_routes, "flash", lambda *args, **kwargs: None)
    monkeypatch.setattr(finance_routes, "get_pull_status", lambda: {"status": "success"})
    monkeypatch.setattr(
        finance_routes,
        "render_template",
        lambda template, **kwargs: captured.update({"template": template, "kwargs": kwargs}) or "ok",
    )
    with app.test_request_context("/admin/reconciliation/sync", method="POST", data={"provider": "pagseguro", "start_date": "2026-03-16", "end_date": "2026-03-16"}):
        _set_admin()
        out = finance_routes.finance_reconciliation_sync.__wrapped__()
    assert out == "ok"
    summary = captured["kwargs"]["summary"]
    assert summary["pagseguro_total_accounts"] == 2
    assert summary["pagseguro_processed_accounts"] == 2
    assert summary["matched_count"] == 2
    assert summary["unmatched_system_count"] == 1
    assert summary["unmatched_card_count"] == 1


def test_consumed_card_is_not_reused_for_other_system_transaction():
    system = [
        {"id": "S-NEW", "timestamp": datetime.strptime("2026-03-16 10:00:00", "%Y-%m-%d %H:%M:%S"), "amount": 180.0, "details": {}}
    ]
    card = [
        {"id": "P-1", "provider": "PagSeguro (Matriz)", "date": datetime.strptime("2026-03-16 10:00:10", "%Y-%m-%d %H:%M:%S"), "amount": 180.0}
    ]
    other_system = {"id": "S-OLD", "timestamp": datetime.strptime("2026-03-15 10:00:00", "%Y-%m-%d %H:%M:%S"), "amount": 180.0, "details": {}}
    c_sig = build_card_transaction_signature(card[0])
    consumption_map = {c_sig: {"system_signature": build_system_transaction_signature(other_system)}}
    out = reconcile_transactions(system, card, consumption_map=consumption_map)
    assert len(out["matched"]) == 0
    assert len(out["unmatched_system"]) == 1
    assert out["skipped_consumed_card_count"] == 1


def test_consumed_card_can_match_same_system_signature_idempotent():
    system = [
        {"id": "S-1", "timestamp": datetime.strptime("2026-03-16 10:00:00", "%Y-%m-%d %H:%M:%S"), "amount": 220.0, "details": {}}
    ]
    card = [
        {"id": "P-1", "provider": "PagSeguro (Matriz)", "date": datetime.strptime("2026-03-16 10:00:15", "%Y-%m-%d %H:%M:%S"), "amount": 220.0}
    ]
    c_sig = build_card_transaction_signature(card[0])
    s_sig = build_system_transaction_signature(system[0])
    out = reconcile_transactions(system, card, consumption_map={c_sig: {"system_signature": s_sig}})
    assert len(out["matched"]) == 1
    assert len(out["unmatched_system"]) == 0
    assert out["skipped_consumed_card_count"] == 0
