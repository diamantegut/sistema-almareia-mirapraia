from app.services.tariff_priority_engine_service import TariffPriorityEngineService


def test_engine_blocks_closed_category(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: False,
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        checkin="2026-07-01",
        checkout="2026-07-03",
        apply_dynamic=False,
    )
    assert result["sellable"] is False
    assert "fechada para venda" in result["message"]


def test_engine_applies_priority_chain(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_blackout_for_period",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_channel_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.validate_allotment_availability",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryProtectionService.validate_sale",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ArrivalDepartureRestrictionService.validate_period",
        lambda *args, **kwargs: {"valid": True, "message": "", "restriction": None},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenueManagementService._normalize_category",
        lambda *args, **kwargs: "mar",
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenueManagementService._load_rules",
        lambda *args, **kwargs: {"mar": {"base_bar": 500.0}},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.StayRestrictionService.validate_stay",
        lambda *args, **kwargs: {"valid": True, "message": "", "rule": None},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.WeekdayBaseRateService.base_total_for_period",
        lambda *args, **kwargs: 1000.0,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.PromotionalPackageService.validate_required_package_constraint",
        lambda *args, **kwargs: {"valid": True, "required_for_sale": False},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.PromotionalPackageService.preview_price",
        lambda *args, **kwargs: {"applied": True, "final_total": 900.0, "package": {"name": "Pacote X"}},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenuePromotionService.preview_price",
        lambda *args, **kwargs: {
            "applied": True,
            "final_total": 810.0,
            "promotion": {"name": "Promo Y", "priority": 10, "apply_before_dynamic": True},
        },
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        checkin="2026-07-10",
        checkout="2026-07-12",
        apply_dynamic=False,
    )
    assert result["sellable"] is True
    assert result["pricing"]["base_weekday_total"] == 1000.0
    assert result["pricing"]["after_package_total"] == 900.0
    assert result["pricing"]["after_promotion_total"] == 810.0
    assert result["pricing"]["final_total"] == 810.0


def test_engine_blocks_cta(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_blackout_for_period",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_channel_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.validate_allotment_availability",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryProtectionService.validate_sale",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ArrivalDepartureRestrictionService.validate_period",
        lambda *args, **kwargs: {"valid": False, "message": "CTA ativo", "restriction": {"restriction_type": "cta"}},
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        checkin="2026-12-25",
        checkout="2026-12-28",
        apply_dynamic=False,
    )
    assert result["sellable"] is False
    assert result["message"] == "CTA ativo"


def test_engine_blocks_channel_closure(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_blackout_for_period",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_channel_open_for_period",
        lambda *args, **kwargs: False,
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        channel="Booking.com",
        checkin="2026-12-21",
        checkout="2026-12-24",
        apply_dynamic=False,
    )
    assert result["sellable"] is False
    assert "Canal Booking.com fechado" in result["message"]


def test_engine_blocks_inventory_protection(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_blackout_for_period",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_channel_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.validate_allotment_availability",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryProtectionService.validate_sale",
        lambda *args, **kwargs: {"valid": False, "message": "Proteção de inventário ativa"},
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        channel="Recepção",
        checkin="2026-12-21",
        checkout="2026-12-24",
        apply_dynamic=False,
    )
    assert result["sellable"] is False
    assert result["message"] == "Proteção de inventário ativa"


def test_engine_rule_order_follows_official_sequence(monkeypatch):
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryRestrictionService.is_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.validate_allotment_availability",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.InventoryProtectionService.validate_sale",
        lambda *args, **kwargs: {"valid": True, "message": ""},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_blackout_for_period",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ChannelInventoryControlService.is_channel_open_for_period",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.ArrivalDepartureRestrictionService.validate_period",
        lambda *args, **kwargs: {"valid": True, "message": "", "restriction": None},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.StayRestrictionService.validate_stay",
        lambda *args, **kwargs: {"valid": True, "message": "", "rule": None},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenueManagementService._normalize_category",
        lambda *args, **kwargs: "mar",
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenueManagementService._load_rules",
        lambda *args, **kwargs: {"mar": {"base_bar": 500.0}},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.WeekdayBaseRateService.base_total_for_period",
        lambda *args, **kwargs: 1000.0,
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.PromotionalPackageService.validate_required_package_constraint",
        lambda *args, **kwargs: {"valid": True, "required_for_sale": False},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.PromotionalPackageService.preview_price",
        lambda *args, **kwargs: {"applied": True, "final_total": 950.0, "package": {"name": "Pacote"}},
    )
    monkeypatch.setattr(
        "app.services.tariff_priority_engine_service.RevenuePromotionService.preview_price",
        lambda *args, **kwargs: {"applied": True, "final_total": 900.0, "promotion": {"name": "Promo", "apply_before_dynamic": True}},
    )
    result = TariffPriorityEngineService.evaluate(
        category="Suíte Mar",
        channel="Recepção",
        checkin="2026-10-10",
        checkout="2026-10-12",
        apply_dynamic=False,
    )
    rules = [str(item.get("rule")) for item in (result.get("rules_applied") or [])]
    assert rules.index("inventory_closed") < rules.index("blackout")
    assert rules.index("blackout") < rules.index("cta_ctd")
    assert rules.index("cta_ctd") < rules.index("min_nights")
    assert rules.index("min_nights") < rules.index("package")
    assert rules.index("package") < rules.index("promotion")
    assert rules.index("promotion") < rules.index("weekday_base_rate")
    assert rules.index("weekday_base_rate") < rules.index("dynamic_revenue")
