from app.services.inventory_protection_service import InventoryProtectionService


def test_apply_rule_and_validate_sale(monkeypatch):
    rules_store = []
    logs_store = []
    monkeypatch.setattr(
        InventoryProtectionService,
        "_load_rules",
        staticmethod(lambda: list(rules_store)),
    )
    monkeypatch.setattr(
        InventoryProtectionService,
        "_save_rules",
        staticmethod(lambda rows: rules_store.__init__(rows)),
    )
    monkeypatch.setattr(
        InventoryProtectionService,
        "_load_logs",
        staticmethod(lambda: list(logs_store)),
    )
    monkeypatch.setattr(
        InventoryProtectionService,
        "_save_logs",
        staticmethod(lambda rows: logs_store.__init__(rows)),
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_room_mapping",
        lambda *args, **kwargs: {"Suíte Mar": ["12", "14", "15", "16"]},
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_february_reservations",
        lambda *args, **kwargs: [
            {"category": "Suíte Mar", "status": "Pendente", "checkin": "2026-12-20", "checkout": "2026-12-22"},
            {"category": "Suíte Mar", "status": "Pendente", "checkin": "2026-12-20", "checkout": "2026-12-22"},
        ],
    )

    result = InventoryProtectionService.apply_rule(
        category="Suíte Mar",
        protected_rooms=2,
        start_date="2026-12-20",
        end_date="2026-12-20",
        status="active",
        user="tester",
    )
    assert result["updated"] == 1
    blocked = InventoryProtectionService.validate_sale(
        category="Suíte Mar",
        checkin="2026-12-20",
        checkout="2026-12-21",
    )
    assert blocked["valid"] is False
    assert "Proteção de inventário ativa" in blocked["message"]


def test_validate_sale_passes_without_rules(monkeypatch):
    monkeypatch.setattr(
        InventoryProtectionService,
        "_load_rules",
        staticmethod(lambda: []),
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_room_mapping",
        lambda *args, **kwargs: {"Suíte Mar": ["12", "14", "15"]},
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_february_reservations",
        lambda *args, **kwargs: [],
    )
    result = InventoryProtectionService.validate_sale(
        category="Suíte Mar",
        checkin="2026-12-20",
        checkout="2026-12-21",
    )
    assert result["valid"] is True
