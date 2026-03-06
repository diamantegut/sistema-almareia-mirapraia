from app.services.weekday_base_rate_service import WeekdayBaseRateService


def test_save_and_get_weekday_rates(monkeypatch):
    store = {}
    monkeypatch.setattr(WeekdayBaseRateService, "_load_json", staticmethod(lambda path, fallback: dict(store) if store else fallback))
    monkeypatch.setattr(WeekdayBaseRateService, "_save_json", staticmethod(lambda path, payload: store.update(payload)))
    monkeypatch.setattr(
        WeekdayBaseRateService,
        "_default_from_rules",
        staticmethod(
            lambda: {
                "alma": {"mon": 450, "tue": 450, "wed": 450, "thu": 450, "fri": 450, "sat": 450, "sun": 450},
                "mar": {"mon": 380, "tue": 380, "wed": 380, "thu": 380, "fri": 380, "sat": 380, "sun": 380},
                "areia": {"mon": 320, "tue": 320, "wed": 320, "thu": 320, "fri": 320, "sat": 320, "sun": 320},
            }
        ),
    )

    saved = WeekdayBaseRateService.save_rates(
        {
            "mar": {"weekday_rate": 450, "weekend_rate": 580, "sun": 420},
        },
        user="tester",
    )
    assert saved["mar"]["mon"] == 450.0
    assert saved["mar"]["sat"] == 580.0
    assert saved["mar"]["sun"] == 580.0

    loaded = WeekdayBaseRateService.get_rates()
    assert loaded["mar"]["fri"] == 450.0


def test_base_for_day_fallback():
    value = WeekdayBaseRateService.base_for_day("mar", "2026-06-12", fallback=500.0)
    assert isinstance(value, float)
