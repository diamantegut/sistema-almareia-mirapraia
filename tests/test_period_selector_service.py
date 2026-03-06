import pytest

from app.services.period_selector_service import PeriodSelectorService


def test_expand_dates_accepts_iso_and_weekday_filter():
    dates = PeriodSelectorService.expand_dates("2026-01-01", "2026-01-07", ["sat"])
    assert dates == ["2026-01-03"]


def test_expand_dates_accepts_portuguese_weekdays():
    dates = PeriodSelectorService.expand_dates("01/01/2026", "07/01/2026", ["sábado", "domingo"])
    assert dates == ["2026-01-03", "2026-01-04"]


def test_parse_payload_normalizes_weekdays_and_swaps_period():
    payload = {
        "start_date": "2026-01-10",
        "end_date": "2026-01-01",
        "weekdays": ["segunda", "mon", "segUNDa", "dom"],
    }
    parsed = PeriodSelectorService.parse_payload(payload)
    assert parsed["weekdays"] == ["mon", "sun"]
    assert parsed["dates"][0] == "2026-01-04"
    assert parsed["dates"][-1] == "2026-01-05"


def test_parse_payload_requires_start_date():
    with pytest.raises(ValueError):
        PeriodSelectorService.parse_payload({"start_date": "", "end_date": "2026-01-01"})
