from datetime import datetime

from app.services.revenue_management_service import RevenueManagementService


def test_target_revpar_uses_season_and_weekday():
    config = RevenueManagementService.DEFAULT_ADVANCED_CONFIG
    day = datetime(2026, 1, 5)
    target = RevenueManagementService._target_revpar_for_day(day, config)
    assert target == config["revpar_target"]["alta"]["mon"]


def test_advanced_adjustment_increases_price_when_high_occupancy_below_target():
    advanced = RevenueManagementService.DEFAULT_ADVANCED_CONFIG
    result = RevenueManagementService._apply_advanced_adjustment(
        occupancy=88.0,
        current_revpar=280.0,
        target_revpar=420.0,
        base_bar=400.0,
        min_bar=250.0,
        max_bar=900.0,
        advanced=advanced,
    )
    assert result["suggested_bar"] > 400.0
    assert "ocupação alta" in result["reason_mode"]


def test_advanced_adjustment_reduces_price_when_low_occupancy_below_target():
    advanced = RevenueManagementService.DEFAULT_ADVANCED_CONFIG
    result = RevenueManagementService._apply_advanced_adjustment(
        occupancy=30.0,
        current_revpar=180.0,
        target_revpar=300.0,
        base_bar=350.0,
        min_bar=200.0,
        max_bar=800.0,
        advanced=advanced,
    )
    assert result["suggested_bar"] < 350.0
    assert "ocupação baixa" in result["reason_mode"]


def test_apply_suggestions_registers_audit_origin(monkeypatch):
    storage = []

    def fake_load_changes():
        return list(storage)

    def fake_save_changes(payload):
        storage.clear()
        storage.extend(payload)

    monkeypatch.setattr(RevenueManagementService, "_load_changes", staticmethod(fake_load_changes))
    monkeypatch.setattr(RevenueManagementService, "_save_changes", staticmethod(fake_save_changes))

    result = RevenueManagementService.apply_suggestions(
        payload_rows=[{
            "date": "2026-03-10",
            "category": "alma",
            "before_bar": 420.0,
            "suggested_bar": 480.0,
            "reason": "teste",
            "target_revpar": 500.0,
            "estimated_revpar_after": 470.0,
            "estimated_revpar_impact": 35.0
        }],
        justification="Ajuste operacional",
        user="tester",
        origin="manual",
    )

    assert result["applied_count"] == 1
    assert storage[0]["origin"] == "manual"
    assert storage[0]["before_bar"] == 420.0
    assert storage[0]["after_bar"] == 480.0


def test_audit_report_filters_by_user_and_period(monkeypatch):
    rows = [
        {
            "applied_at": "2026-03-01T10:00:00",
            "user": "ana",
            "date": "2026-03-01",
            "category": "alma",
            "before_bar": 400,
            "after_bar": 420,
            "origin": "suggestion",
            "justification": "ok"
        },
        {
            "applied_at": "2026-03-02T10:00:00",
            "user": "bruno",
            "date": "2026-03-02",
            "category": "mar",
            "before_bar": 300,
            "after_bar": 310,
            "origin": "manual",
            "justification": "ok"
        },
    ]
    monkeypatch.setattr(RevenueManagementService, "_load_changes", staticmethod(lambda: rows))
    report = RevenueManagementService.get_audit_report("2026-03-01", "2026-03-01", "ana")
    assert len(report) == 1
    assert report[0]["user"] == "ana"
