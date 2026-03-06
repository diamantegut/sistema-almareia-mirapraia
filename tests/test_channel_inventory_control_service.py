from app.services.channel_inventory_control_service import ChannelInventoryControlService


def test_channel_restriction_blocks_period(monkeypatch):
    rules_store = []
    logs_store = []
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_channel_rules",
        staticmethod(lambda: list(rules_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_channel_rules",
        staticmethod(lambda rows: rules_store.__init__(rows)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_channel_logs",
        staticmethod(lambda: list(logs_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_channel_logs",
        staticmethod(lambda rows: logs_store.__init__(rows)),
    )

    result = ChannelInventoryControlService.apply_channel_restriction(
        category="Suíte Mar",
        channel="Booking.com",
        start_date="2026-12-20",
        end_date="2026-12-26",
        status="active",
        user="tester",
        weekdays=[],
    )
    assert len(result["dates"]) == 7
    assert ChannelInventoryControlService.is_channel_open_for_period(
        category="Suíte Mar",
        channel="Booking.com",
        checkin="2026-12-22",
        checkout="2026-12-24",
    ) is False


def test_blackout_all_category_blocks_sale(monkeypatch):
    rows_store = []
    logs_store = []
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_blackouts",
        staticmethod(lambda: list(rows_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_blackouts",
        staticmethod(lambda rows: rows_store.__init__(rows)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_blackout_logs",
        staticmethod(lambda: list(logs_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_blackout_logs",
        staticmethod(lambda rows: logs_store.__init__(rows)),
    )

    ChannelInventoryControlService.apply_blackout(
        category="Todas",
        start_date="2027-01-03",
        end_date="2027-01-03",
        status="active",
        reason="Hotel fechado",
        user="tester",
    )
    assert ChannelInventoryControlService.is_blackout_for_period(
        category="Suíte Areia",
        checkin="2027-01-02",
        checkout="2027-01-05",
    ) is True


def test_allotment_never_exceeds_category_capacity(monkeypatch):
    allotment_store = []
    logs_store = []
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_allotments",
        staticmethod(lambda: list(allotment_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_allotments",
        staticmethod(lambda rows: allotment_store.__init__(rows)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_load_allotment_logs",
        staticmethod(lambda: list(logs_store)),
    )
    monkeypatch.setattr(
        ChannelInventoryControlService,
        "_save_allotment_logs",
        staticmethod(lambda rows: logs_store.__init__(rows)),
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_room_mapping",
        lambda *args, **kwargs: {"Suíte Mar": ["12", "14", "15"]},
    )
    ChannelInventoryControlService.apply_allotment(
        category="Suíte Mar",
        channel="Booking.com",
        rooms=2,
        start_date="2026-12-20",
        end_date="2026-12-20",
        user="tester",
    )
    try:
        ChannelInventoryControlService.apply_allotment(
            category="Suíte Mar",
            channel="Expedia",
            rooms=2,
            start_date="2026-12-20",
            end_date="2026-12-20",
            user="tester",
        )
        assert False
    except ValueError as exc:
        assert "excede capacidade" in str(exc)
