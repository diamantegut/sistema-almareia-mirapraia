from app.services.stay_restriction_service import StayRestrictionService


def test_validate_stay_returns_minimum_nights_message(monkeypatch):
    monkeypatch.setattr(
        StayRestrictionService,
        "_load_rules",
        staticmethod(
            lambda: [
                {
                    "id": "r1",
                    "name": "Ano Novo",
                    "categories": ["Suíte Mar"],
                    "package_ids": [],
                    "period": {"start_date": "2026-12-20", "end_date": "2027-01-05", "weekdays": []},
                    "min_nights": 7,
                    "max_nights": None,
                    "status": "active",
                }
            ]
        ),
    )
    result = StayRestrictionService.validate_stay(
        category="Suíte Mar",
        checkin="2026-12-28",
        checkout="2027-01-01",
        package_id=None,
    )
    assert result["valid"] is False
    assert "estadia mínima é de 7 noites" in result["message"]


def test_validate_stay_accepts_package_target(monkeypatch):
    monkeypatch.setattr(
        StayRestrictionService,
        "_load_rules",
        staticmethod(
            lambda: [
                {
                    "id": "r2",
                    "name": "Pacote Especial",
                    "categories": [],
                    "package_ids": ["pkg-1"],
                    "period": {"start_date": "2026-08-01", "end_date": "2026-08-31", "weekdays": ["fri", "sat"]},
                    "min_nights": 2,
                    "max_nights": None,
                    "status": "active",
                }
            ]
        ),
    )
    result = StayRestrictionService.validate_stay(
        category="Suíte Areia",
        checkin="2026-08-14",
        checkout="2026-08-16",
        package_id="pkg-1",
    )
    assert result["valid"] is True
