from app.services.arrival_departure_restriction_service import ArrivalDepartureRestrictionService


def test_apply_cta_with_weekdays_and_validate_checkin(monkeypatch):
    restrictions_store = []
    logs_store = []
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_load_restrictions",
        staticmethod(lambda: list(restrictions_store)),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_save_restrictions",
        staticmethod(lambda rows: restrictions_store.__init__(rows)),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_load_logs",
        staticmethod(lambda: list(logs_store)),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_save_logs",
        staticmethod(lambda rows: logs_store.__init__(rows)),
    )

    result = ArrivalDepartureRestrictionService.apply_restriction(
        restriction_type="cta",
        category="Mar",
        start_date="2026-12-20",
        end_date="2026-12-31",
        status="active",
        user="tester",
        reason="Bloqueio de chegadas natal",
        weekdays=["fri", "sat"],
        origin="manual",
    )
    assert result["restriction_type"] == "cta"
    assert len(result["dates"]) > 0

    blocked = ArrivalDepartureRestrictionService.validate_period(
        category="Suíte Mar",
        checkin=result["dates"][0],
        checkout="2027-01-02",
    )
    assert blocked["valid"] is False
    assert "CTA ativo" in blocked["message"]


def test_apply_ctd_blocks_checkout_only(monkeypatch):
    restrictions_store = []
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_load_restrictions",
        staticmethod(lambda: list(restrictions_store)),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_save_restrictions",
        staticmethod(lambda rows: restrictions_store.__init__(rows)),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_load_logs",
        staticmethod(lambda: []),
    )
    monkeypatch.setattr(
        ArrivalDepartureRestrictionService,
        "_save_logs",
        staticmethod(lambda rows: None),
    )

    ArrivalDepartureRestrictionService.apply_restriction(
        restriction_type="ctd",
        category="Areia",
        start_date="2027-01-01",
        end_date="2027-01-01",
        status="active",
        user="tester",
        reason="Pacote réveillon",
        weekdays=["fri"],
        origin="manual",
    )

    valid_stay = ArrivalDepartureRestrictionService.validate_period(
        category="Suíte Areia",
        checkin="2026-12-30",
        checkout="2026-12-31",
    )
    assert valid_stay["valid"] is True

    blocked = ArrivalDepartureRestrictionService.validate_period(
        category="Suíte Areia",
        checkin="2026-12-30",
        checkout="2027-01-01",
    )
    assert blocked["valid"] is False
    assert "CTD ativo" in blocked["message"]
