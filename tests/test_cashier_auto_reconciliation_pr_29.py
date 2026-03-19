import json
from datetime import datetime
from flask import Flask, session

from app.blueprints.finance import routes as finance_routes
from app.services import pagseguro_daily_pull_service as pull_service
from app.services import cashier_service


def _make_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.add_url_rule("/", endpoint="main.index", view_func=lambda: "index")
    app.add_url_rule("/finance/reconciliation", endpoint="finance.finance_reconciliation", view_func=lambda: "recon")
    return app


def _set_admin():
    session.clear()
    session.update({"user": "admin", "role": "admin"})


def _set_non_admin():
    session.clear()
    session.update({"user": "ger1", "role": "gerente"})


def _base_session():
    return {
        "id": "S1",
        "status": "closed",
        "type": "restaurant_service",
        "user": "admin",
        "closed_by": "admin",
        "opened_at": "17/03/2026 08:00",
        "closed_at": "17/03/2026 10:00",
        "transactions": [
            {
                "id": "SYS-1",
                "type": "sale",
                "timestamp": "17/03/2026 09:00",
                "amount": 100.0,
                "payment_method": "Cartão de Crédito",
                "description": "Conta 1",
                "details": {"payment_group_id": "G1"},
            }
        ],
    }


def _write_snapshot(tmp_path, items):
    file_path = tmp_path / "pagseguro_daily_pull.json"
    file_path.write_text(
        json.dumps(
            [
                {
                    "date_ref": "2026-03-17",
                    "period_start": "2026-03-17 00:00:00",
                    "period_end": "2026-03-17 23:59:59",
                    "pulled_at": "18/03/2026 06:10:00",
                    "raw_count": len(items),
                    "normalized_count": len(items),
                    "raw_transactions": [],
                    "normalized_transactions": items,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return file_path


def _set_pull_files(monkeypatch, tmp_path):
    data_file = tmp_path / "pagseguro_daily_pull.json"
    status_file = tmp_path / "pagseguro_daily_pull_status.json"
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_FILE", str(data_file))
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_STATUS_FILE", str(status_file))
    return data_file, status_file


def test_daily_pull_persists_raw_and_normalized(monkeypatch, tmp_path):
    data_file, status_file = _set_pull_files(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pull_service,
        "fetch_pagseguro_transactions_detailed",
        lambda start_dt, end_dt: {
            "transactions": [
                {
                    "provider": "PagSeguro (Conta 1)",
                    "date": datetime.strptime("2026-03-17 09:00:00", "%Y-%m-%d %H:%M:%S"),
                    "amount": 25.0,
                    "type": "1",
                    "status": "3",
                    "original_row": {"code": "PG-RAW-1"},
                }
            ],
            "errors": [],
            "total_accounts": 1,
            "processed_accounts": 1
        },
    )
    monkeypatch.setattr(pull_service, "log_system_action", lambda *args, **kwargs: None)
    out = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="test", requested_by="qa")
    snapshot = out["snapshot"]
    assert out["success"] is True
    assert snapshot["date_ref"] == "2026-03-17"
    assert snapshot["raw_count"] == 1
    assert snapshot["normalized_count"] == 1
    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert saved[0]["raw_transactions"][0]["original_row"]["code"] == "PG-RAW-1"
    assert saved[0]["normalized_transactions"][0]["payment_method"] == "card"
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["status"] == "success"


def test_daily_pull_external_failure_sets_error_status(monkeypatch, tmp_path):
    _, status_file = _set_pull_files(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pull_service,
        "fetch_pagseguro_transactions_detailed",
        lambda start_dt, end_dt: {"transactions": [], "errors": [{"alias": "Conta 1", "error": "HTTP 500"}], "total_accounts": 1, "processed_accounts": 1},
    )
    monkeypatch.setattr(pull_service, "log_system_action", lambda *args, **kwargs: None)
    out = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="scheduler", requested_by="scheduler")
    assert out["success"] is False
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["status"] == "error"
    assert "HTTP 500" in status["error"]


def test_daily_pull_idempotent_same_day(monkeypatch, tmp_path):
    data_file, status_file = _set_pull_files(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pull_service,
        "fetch_pagseguro_transactions_detailed",
        lambda start_dt, end_dt: {"transactions": [], "errors": [], "total_accounts": 1, "processed_accounts": 1},
    )
    monkeypatch.setattr(pull_service, "log_system_action", lambda *args, **kwargs: None)
    out1 = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="scheduler", requested_by="scheduler")
    out2 = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="scheduler", requested_by="scheduler")
    assert out1["success"] is True
    assert out2["success"] is True
    assert out2.get("idempotent") is True
    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["status"] == "success"


def test_daily_pull_force_reprocess_same_day(monkeypatch, tmp_path):
    data_file, _ = _set_pull_files(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_fetch(start_dt, end_dt):
        calls["n"] += 1
        amount = 10.0 if calls["n"] == 1 else 20.0
        return {
            "transactions": [
                {
                    "provider": "PagSeguro (Conta 1)",
                    "date": datetime.strptime("2026-03-17 09:00:00", "%Y-%m-%d %H:%M:%S"),
                    "amount": amount,
                    "type": "1",
                    "status": "3",
                    "original_row": {"code": f"PG-{calls['n']}"},
                }
            ],
            "errors": [],
            "total_accounts": 1,
            "processed_accounts": 1
        }

    monkeypatch.setattr(pull_service, "fetch_pagseguro_transactions_detailed", _fake_fetch)
    monkeypatch.setattr(pull_service, "log_system_action", lambda *args, **kwargs: None)
    out1 = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="scheduler", requested_by="scheduler")
    out2 = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="manual_admin", requested_by="admin", force=True)
    assert out1["success"] is True
    assert out2["success"] is True
    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["normalized_transactions"][0]["amount"] == 20.0


def test_daily_pull_concurrency_protection(monkeypatch, tmp_path):
    _, status_file = _set_pull_files(monkeypatch, tmp_path)
    monkeypatch.setattr(pull_service, "log_system_action", lambda *args, **kwargs: None)
    acquired = pull_service._PULL_LOCK.acquire(blocking=False)
    assert acquired is True
    try:
        out = pull_service.run_pagseguro_daily_pull(date_ref="2026-03-17", source="scheduler", requested_by="scheduler")
        assert out["success"] is False
        status = json.loads(status_file.read_text(encoding="utf-8"))
        assert status["error"] == "PULL_ALREADY_RUNNING"
    finally:
        pull_service._PULL_LOCK.release()


def test_payment_conciliated_correctly(monkeypatch, tmp_path):
    file_path = _write_snapshot(
        tmp_path,
        [
            {
                "id": "PG-1",
                "provider": "PagSeguro (Conta 1)",
                "timestamp": "2026-03-17 09:00:00",
                "amount": 100.0,
                "payment_method": "card",
                "status": "3",
                "type": "1",
            }
        ],
    )
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_FILE", str(file_path))
    out = pull_service.compare_session_with_daily_snapshot(_base_session())
    assert out["status"] == "ok"
    assert out["summary"]["matched_count"] == 1
    assert out["summary"]["declared_not_found_count"] == 0
    assert out["summary"]["pagseguro_not_declared_count"] == 0


def test_declared_and_missing_in_pagseguro(monkeypatch, tmp_path):
    file_path = _write_snapshot(tmp_path, [])
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_FILE", str(file_path))
    out = pull_service.compare_session_with_daily_snapshot(_base_session())
    assert out["status"] == "ok"
    assert out["summary"]["matched_count"] == 0
    assert out["summary"]["declared_not_found_count"] == 1


def test_pagseguro_without_system_launch(monkeypatch, tmp_path):
    base = _base_session()
    base["transactions"] = []
    file_path = _write_snapshot(
        tmp_path,
        [
            {
                "id": "PG-2",
                "provider": "PagSeguro (Conta 1)",
                "timestamp": "2026-03-17 09:05:00",
                "amount": 80.0,
                "payment_method": "card",
                "status": "3",
                "type": "1",
            }
        ],
    )
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_FILE", str(file_path))
    out = pull_service.compare_session_with_daily_snapshot(base)
    assert out["status"] == "ok"
    assert out["summary"]["pagseguro_not_declared_count"] == 1


def test_multiple_same_account_grouped_match(monkeypatch, tmp_path):
    base = _base_session()
    base["transactions"] = [
        {
            "id": "SYS-1",
            "type": "sale",
            "timestamp": "17/03/2026 09:00",
            "amount": 60.0,
            "payment_method": "Cartão de Crédito",
            "description": "Conta 2 A",
            "details": {"payment_group_id": "G2"},
        },
        {
            "id": "SYS-2",
            "type": "sale",
            "timestamp": "17/03/2026 09:01",
            "amount": 40.0,
            "payment_method": "Cartão de Crédito",
            "description": "Conta 2 B",
            "details": {"payment_group_id": "G2"},
        },
    ]
    file_path = _write_snapshot(
        tmp_path,
        [
            {
                "id": "PG-3",
                "provider": "PagSeguro (Conta 1)",
                "timestamp": "2026-03-17 09:02:00",
                "amount": 100.0,
                "payment_method": "card",
                "status": "3",
                "type": "1",
            }
        ],
    )
    monkeypatch.setattr(pull_service, "PAGSEGURO_DAILY_PULL_FILE", str(file_path))
    out = pull_service.compare_session_with_daily_snapshot(base)
    assert out["status"] == "ok"
    assert out["summary"]["matched_count"] == 1
    assert out["summary"]["declared_not_found_count"] == 0
    assert out["summary"]["pagseguro_not_declared_count"] == 0


def test_balances_details_exposes_daily_comparison(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(cashier_service.CashierService, "get_session_details", staticmethod(lambda sid: _base_session()))
    monkeypatch.setattr(
        finance_routes,
        "_build_daily_pull_comparison_for_session",
        lambda session_obj: {"status": "ok", "summary": {"matched_count": 1}, "matched": [], "declared_not_found": [], "pagseguro_not_declared": []},
    )
    with app.test_request_context("/api/finance/session/S1", method="GET", headers={"Accept": "application/json"}):
        _set_admin()
        response = finance_routes.api_finance_session_details.__wrapped__("S1")
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["card_comparison"]["status"] == "ok"


def test_admin_only_preserved_on_balances_details():
    app = _make_test_app()
    with app.test_request_context("/api/finance/session/S1", method="GET", headers={"Accept": "application/json"}):
        _set_non_admin()
        response, status = finance_routes.api_finance_session_details.__wrapped__("S1")
    assert status == 403
    assert response.get_json()["success"] is False


def test_manual_retry_route_uses_force(monkeypatch):
    app = _make_test_app()
    captured = {"force": None}

    def _fake_pull(**kwargs):
        captured["force"] = kwargs.get("force")
        return {"success": True, "snapshot": {"date_ref": "2026-03-17", "normalized_count": 2}, "status": {"status": "success"}}

    monkeypatch.setattr(finance_routes, "run_pagseguro_daily_pull", _fake_pull)
    with app.test_request_context("/admin/reconciliation/pagseguro/daily-pull", method="POST"):
        _set_admin()
        response = finance_routes.finance_reconciliation_daily_pull.__wrapped__()
    assert response.status_code == 302
    assert captured["force"] is True


def test_manual_retry_route_admin_only():
    app = _make_test_app()
    with app.test_request_context("/admin/reconciliation/pagseguro/daily-pull", method="POST"):
        _set_non_admin()
        response = finance_routes.finance_reconciliation_daily_pull.__wrapped__()
    assert response.status_code == 302


def test_daily_pull_status_endpoint_admin_only_and_payload(monkeypatch):
    app = _make_test_app()
    monkeypatch.setattr(finance_routes, "get_pull_status", lambda: {"status": "partial", "date_ref": "2026-03-17", "pulled_count": 10, "error": "HTTP 500"})
    with app.test_request_context("/admin/reconciliation/pagseguro/daily-pull/status", method="GET", headers={"Accept": "application/json"}):
        _set_admin()
        response = finance_routes.finance_reconciliation_daily_pull_status.__wrapped__()
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "partial"
    with app.test_request_context("/admin/reconciliation/pagseguro/daily-pull/status", method="GET", headers={"Accept": "application/json"}):
        _set_non_admin()
        response2, status2 = finance_routes.finance_reconciliation_daily_pull_status.__wrapped__()
    assert status2 == 403
    assert response2.get_json()["success"] is False
