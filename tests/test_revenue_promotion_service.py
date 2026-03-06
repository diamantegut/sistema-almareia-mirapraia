from app.services.revenue_promotion_service import RevenuePromotionService
from app.services.revenue_management_service import RevenueManagementService


def test_preview_promotion_respects_priority_and_combination(monkeypatch):
    monkeypatch.setattr(
        RevenuePromotionService,
        "_load_promotions",
        staticmethod(
            lambda: [
                {
                    "id": "promo-low-prio",
                    "name": "Promo baixa prioridade",
                    "categories": ["Suíte Mar"],
                    "period": {"start_date": "2026-06-01", "end_date": "2026-06-30", "weekdays": []},
                    "discount_type": "percent",
                    "discount_value": 10,
                    "combinable_with_packages": True,
                    "priority": 50,
                    "status": "active",
                    "updated_at": "2026-01-01T00:00:00",
                },
                {
                    "id": "promo-high-prio",
                    "name": "Promo alta prioridade",
                    "categories": ["Suíte Mar"],
                    "period": {"start_date": "2026-06-01", "end_date": "2026-06-30", "weekdays": []},
                    "discount_type": "percent",
                    "discount_value": 5,
                    "combinable_with_packages": False,
                    "priority": 10,
                    "status": "active",
                    "updated_at": "2026-01-02T00:00:00",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_rules",
        staticmethod(lambda: {"mar": {"base_bar": 380.0, "min_bar": 240.0, "max_bar": 950.0}}),
    )
    result_package = RevenuePromotionService.preview_price(
        category="Suíte Mar",
        checkin="2026-06-10",
        checkout="2026-06-13",
        base_total=1200.0,
        package_applied=True,
    )
    assert result_package["applied"] is True
    assert result_package["promotion"]["id"] == "promo-low-prio"

    result_no_package = RevenuePromotionService.preview_price(
        category="Suíte Mar",
        checkin="2026-06-10",
        checkout="2026-06-13",
        base_total=1200.0,
        package_applied=False,
    )
    assert result_no_package["applied"] is True
    assert result_no_package["promotion"]["id"] == "promo-high-prio"


def test_preview_promotion_clamps_to_min_max(monkeypatch):
    monkeypatch.setattr(
        RevenuePromotionService,
        "_load_promotions",
        staticmethod(
            lambda: [
                {
                    "id": "promo-closed",
                    "name": "Tarifa fechada muito baixa",
                    "categories": ["Suíte Areia"],
                    "period": {"start_date": "2026-07-01", "end_date": "2026-07-31", "weekdays": []},
                    "discount_type": "closed_rate",
                    "discount_value": 50,
                    "combinable_with_packages": True,
                    "priority": 1,
                    "status": "active",
                    "updated_at": "2026-01-01T00:00:00",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_rules",
        staticmethod(lambda: {"areia": {"base_bar": 320.0, "min_bar": 210.0, "max_bar": 780.0}}),
    )
    result = RevenuePromotionService.preview_price(
        category="Suíte Areia",
        checkin="2026-07-10",
        checkout="2026-07-13",
        base_total=900.0,
        package_applied=False,
    )
    assert result["applied"] is True
    assert result["final_total"] == 630.0
