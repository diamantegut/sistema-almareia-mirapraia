import json
from pathlib import Path

from app.services.reservation_rateio_service import ReservationRateioService


def test_rateio_sum_matches_package_total(tmp_path, monkeypatch):
    target_file = tmp_path / "reservation_daily_splits.json"
    target_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(ReservationRateioService, "FILE_PATH", str(target_file))

    result = ReservationRateioService.generate(
        reservation_id="RES-TEST-001",
        total_package=1000.00,
        checkin="2026-03-10",
        checkout="2026-03-13",
        user="tester",
        trigger="reservation_confirmed",
        force=True
    )

    rows = result["rows"]
    assert len(rows) == 3
    assert round(sum(item["daily_value"] for item in rows), 2) == 1000.00
    assert round(rows[-1]["daily_value"], 2) == 333.34


def test_rateio_is_idempotent_without_force(tmp_path, monkeypatch):
    target_file = tmp_path / "reservation_daily_splits.json"
    target_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(ReservationRateioService, "FILE_PATH", str(target_file))

    first = ReservationRateioService.generate(
        reservation_id="RES-TEST-002",
        total_package=900.00,
        checkin="2026-03-01",
        checkout="2026-03-04",
        user="tester",
        trigger="reservation_confirmed",
        force=True
    )
    second = ReservationRateioService.generate(
        reservation_id="RES-TEST-002",
        total_package=900.00,
        checkin="2026-03-01",
        checkout="2026-03-04",
        user="tester",
        trigger="reservation_confirmed",
        force=False
    )

    assert first["created"] is True
    assert second["created"] is False
    payload = json.loads(Path(target_file).read_text(encoding="utf-8"))
    assert len([row for row in payload if row["reservation_id"] == "RES-TEST-002"]) == 3
