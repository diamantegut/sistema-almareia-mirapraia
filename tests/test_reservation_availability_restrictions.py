from app.services.reservation_service import ReservationService


def test_has_availability_false_when_stay_restriction_fails(monkeypatch):
    service = ReservationService()
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.TariffPriorityEngineService.evaluate",
        lambda *args, **kwargs: {"sellable": False, "message": "mínimo 7"},
    )
    assert service.has_availability_for_category("Suíte Mar", "2026-12-28", "2027-01-01") is False
