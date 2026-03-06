from app.services.revenue_management_service import RevenueManagementService


def test_occupancy_forecast_generates_projection(monkeypatch):
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_room_mapping",
        lambda *args, **kwargs: {
            "Suíte Mar": ["12", "14", "15", "16"],
            "Suíte Areia": ["01", "02", "03"],
            "Suíte Alma c/ Banheira": ["31", "35"],
            "Suíte Alma": ["32", "34"],
            "Suíte Master Diamante": ["33"],
            "Suíte Mar Família": ["11"],
        },
    )
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_february_reservations",
        lambda *args, **kwargs: [
            {
                "category": "Suíte Mar",
                "status": "Confirmada",
                "checkin": "2026-06-01",
                "checkout": "2026-06-04",
                "created_at": "20/05/2026 10:00",
            },
            {
                "category": "Suíte Mar",
                "status": "Cancelada",
                "checkin": "2026-06-02",
                "checkout": "2026-06-03",
                "created_at": "20/05/2026 11:00",
            },
        ],
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_events_index",
        classmethod(lambda cls: {"2026-06-02": {"name": "Festival", "factor": 1.18}}),
    )
    result = RevenueManagementService.occupancy_forecast(start_date="2026-06-02", days=2, category="mar")
    assert result["days"] == 2
    assert len(result["rows"]) == 2
    assert "occupancy_projected_pct" in result["rows"][0]


def test_pickup_analysis_classifies_level(monkeypatch):
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_february_reservations",
        lambda *args, **kwargs: [
            {
                "category": "Suíte Mar",
                "status": "Confirmada",
                "checkin": "2026-07-10",
                "checkout": "2026-07-11",
                "created_at": "09/07/2026 09:00",
            },
            {
                "category": "Suíte Mar",
                "status": "Confirmada",
                "checkin": "2026-07-10",
                "checkout": "2026-07-11",
                "created_at": "08/07/2026 10:00",
            },
        ],
    )
    result = RevenueManagementService.pickup_analysis(start_date="2026-07-10", days=1, category="mar")
    assert result["days"] == 1
    row = result["rows"][0]
    assert row["pickup_1d"] >= 1
    assert row["pickup_level"] in ("baixo", "normal", "alto", "muito alto")


def test_auto_adjustment_respects_limits(monkeypatch):
    monkeypatch.setattr(
        RevenueManagementService,
        "occupancy_forecast",
        classmethod(
            lambda cls, **kwargs: {
                "start_date": "2026-08-01",
                "days": 1,
                "rows": [
                    {
                        "date": "2026-08-01",
                        "category": "mar",
                        "occupancy_current_pct": 70,
                        "occupancy_projected_pct": 92,
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "pickup_analysis",
        classmethod(
            lambda cls, **kwargs: {
                "rows": [{"date": "2026-08-01", "pickup_level": "alto"}]
            }
        ),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_rules",
        classmethod(lambda cls: {"mar": {"base_bar": 400.0, "min_bar": 250.0, "max_bar": 450.0}}),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_advanced_config",
        classmethod(lambda cls: RevenueManagementService.DEFAULT_ADVANCED_CONFIG),
    )
    monkeypatch.setattr(
        "app.services.weekday_base_rate_service.WeekdayBaseRateService.base_for_day",
        lambda *args, **kwargs: 440.0,
    )
    monkeypatch.setattr(
        "app.services.promotional_package_service.PromotionalPackageService.validate_required_package_constraint",
        lambda *args, **kwargs: {"required_for_sale": False, "message": ""},
    )
    result = RevenueManagementService.auto_demand_tariff_adjustment(start_date="2026-08-01", days=1, category="mar")
    row = result["rows"][0]
    assert row["suggested_bar"] <= row["max_bar"]
    assert row["suggested_bar"] >= row["min_bar"]
