from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.reservation_service import ReservationService


def test_apply_restriction_with_weekdays(monkeypatch):
    restrictions_store = []
    logs_store = []

    monkeypatch.setattr(InventoryRestrictionService, "_load_restrictions", staticmethod(lambda: list(restrictions_store)))
    monkeypatch.setattr(InventoryRestrictionService, "_save_restrictions", staticmethod(lambda rows: restrictions_store.__init__(rows)))
    monkeypatch.setattr(InventoryRestrictionService, "_load_logs", staticmethod(lambda: list(logs_store)))
    monkeypatch.setattr(InventoryRestrictionService, "_save_logs", staticmethod(lambda rows: logs_store.__init__(rows)))

    result = InventoryRestrictionService.apply_restriction(
        category="Mar",
        start_date="2026-07-01",
        end_date="2026-07-07",
        status="closed",
        user="tester",
        reason="Teste finais de semana",
        weekdays=["sat", "sun"],
        origin="manual",
    )

    assert result["status"] == "closed"
    assert result["dates"] == ["2026-07-04", "2026-07-05"]
    assert result["period"]["weekdays"] == ["sat", "sun"]
    assert len(restrictions_store) == 2
    assert restrictions_store[0]["category"] == "Suíte Mar"


def test_is_open_for_period_respects_closed_day(monkeypatch):
    monkeypatch.setattr(
        InventoryRestrictionService,
        "_load_restrictions",
        staticmethod(lambda: [{"category": "Suíte Areia", "date": "2026-12-22", "status": "closed"}]),
    )
    is_open = InventoryRestrictionService.is_open_for_period("Areia", "2026-12-20", "2026-12-24")
    assert is_open is False


def test_reservation_service_unavailable_when_category_closed(monkeypatch):
    service = ReservationService()
    monkeypatch.setattr(service, "get_room_mapping", lambda: {"Suíte Mar": ["101"]})
    monkeypatch.setattr(service, "check_collision", lambda *args, **kwargs: True)
    monkeypatch.setattr(InventoryRestrictionService, "is_open_for_period", staticmethod(lambda *args, **kwargs: False))
    assert service.has_availability_for_category("Suíte Mar", "2026-08-01", "2026-08-03") is False
