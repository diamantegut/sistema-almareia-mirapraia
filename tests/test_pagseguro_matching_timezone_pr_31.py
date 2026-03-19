from datetime import datetime

from app.services.card_reconciliation_service import reconcile_transactions, _parse_pagseguro_datetime


def _sys(tx_id, ts, amount, method="credit_card"):
    return {
        "id": tx_id,
        "timestamp": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
        "amount": float(amount),
        "payment_method": method,
        "details": {},
    }


def _card(code, ts, amount):
    return {
        "id": code,
        "provider": "PagSeguro (Mirapraia)",
        "date": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
        "amount": float(amount),
        "type": "1",
    }


def test_match_748_with_about_1h_difference():
    system = [_sys("S-748", "2026-03-16 18:39:00", 748.00)]
    card = [_card("P-748", "2026-03-16 17:38:56", 748.00)]
    out = reconcile_transactions(system, card, tolerance_mins=60, tolerance_val=0.05)
    assert len(out["matched"]) == 1
    assert out["matched"][0]["status"] in ("matched", "matched_extended_time")
    assert out["unmatched_system"] == []
    assert out["unmatched_card"] == []


def test_match_369_82_with_about_1h33_difference():
    system = [_sys("S-369", "2026-03-16 18:36:00", 369.82)]
    card = [_card("P-369", "2026-03-16 17:02:52", 369.82)]
    out = reconcile_transactions(system, card, tolerance_mins=60, tolerance_val=0.05)
    assert len(out["matched"]) == 1
    assert out["matched"][0]["status"] == "matched_extended_time"
    assert out["unmatched_system"] == []
    assert out["unmatched_card"] == []


def test_match_inside_normal_tolerance():
    system = [_sys("S-100", "2026-03-16 18:10:00", 100.00)]
    card = [_card("P-100", "2026-03-16 18:12:10", 100.00)]
    out = reconcile_transactions(system, card, tolerance_mins=60, tolerance_val=0.05)
    assert len(out["matched"]) == 1
    assert out["matched"][0]["status"] == "matched"


def test_not_concilable_case_stays_unmatched():
    system = [_sys("S-500", "2026-03-16 18:10:00", 500.00)]
    card = [_card("P-500", "2026-03-16 14:00:00", 500.00)]
    out = reconcile_transactions(system, card, tolerance_mins=60, tolerance_val=0.05)
    assert len(out["matched"]) == 0
    assert len(out["unmatched_system"]) == 1
    assert len(out["unmatched_card"]) == 1


def test_does_not_duplicate_match_with_single_card():
    system = [
        _sys("S-A", "2026-03-16 18:10:00", 210.00),
        _sys("S-B", "2026-03-16 18:11:00", 210.00),
    ]
    card = [_card("P-A", "2026-03-16 18:10:30", 210.00)]
    out = reconcile_transactions(system, card, tolerance_mins=60, tolerance_val=0.05)
    assert len(out["matched"]) == 1
    assert len(out["unmatched_system"]) == 1
    assert len(out["unmatched_card"]) == 0


def test_parse_pagseguro_datetime_keeps_timezone_consistent():
    dt = _parse_pagseguro_datetime("2026-03-16T20:38:56-03:00")
    assert dt.strftime("%Y-%m-%d %H:%M:%S") == "2026-03-16 20:38:56"
