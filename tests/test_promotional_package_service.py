from app.services.promotional_package_service import PromotionalPackageService


def test_create_package_and_preview_applies_best_price(monkeypatch):
    package_store = []
    log_store = []

    monkeypatch.setattr(PromotionalPackageService, "_load_packages", staticmethod(lambda: list(package_store)))
    monkeypatch.setattr(PromotionalPackageService, "_save_packages", staticmethod(lambda rows: package_store.__init__(rows)))
    monkeypatch.setattr(PromotionalPackageService, "_load_logs", staticmethod(lambda: list(log_store)))
    monkeypatch.setattr(PromotionalPackageService, "_save_logs", staticmethod(lambda rows: log_store.__init__(rows)))

    package_fixed = PromotionalPackageService.create_package(
        payload={
            "name": "Pacote Ano Novo",
            "description": "Fixo para alta temporada",
            "categories": ["Suíte Mar"],
            "price_type": "package_fixed",
            "special_price": 900.0,
            "status": "active",
            "sale_period": {"start_date": "2026-12-01", "end_date": "2026-12-31", "weekdays": []},
            "stay_period": {"start_date": "2026-12-20", "end_date": "2027-01-05", "weekdays": []},
        },
        user="tester",
    )
    assert package_fixed["name"] == "Pacote Ano Novo"

    PromotionalPackageService.create_package(
        payload={
            "name": "Pacote Desconto",
            "description": "Desconto percentual",
            "categories": ["Suíte Mar"],
            "price_type": "percent_discount",
            "special_price": 20.0,
            "status": "active",
            "sale_period": {"start_date": "2026-12-01", "end_date": "2026-12-31", "weekdays": []},
            "stay_period": {"start_date": "2026-12-20", "end_date": "2027-01-05", "weekdays": []},
        },
        user="tester",
    )

    preview = PromotionalPackageService.preview_price(
        category="Suíte Mar",
        checkin="2026-12-25",
        checkout="2026-12-28",
        sale_date="2026-12-10",
        base_total=1200.0,
    )
    assert preview["applied"] is True
    assert preview["final_total"] == 900.0
    assert preview["package"]["name"] == "Pacote Ano Novo"
    assert len(log_store) == 2


def test_preview_ignores_inactive_or_outside_period(monkeypatch):
    monkeypatch.setattr(
        PromotionalPackageService,
        "_load_packages",
        staticmethod(
            lambda: [
                {
                    "id": "p1",
                    "name": "Pacote Inativo",
                    "description": "",
                    "categories": ["Suíte Areia"],
                    "price_type": "daily_fixed",
                    "special_price": 200.0,
                    "status": "inactive",
                    "sale_period": {"start_date": "2026-07-01", "end_date": "2026-07-31", "weekdays": []},
                    "stay_period": {"start_date": "2026-07-01", "end_date": "2026-07-31", "weekdays": []},
                }
            ]
        ),
    )
    preview = PromotionalPackageService.preview_price(
        category="Suíte Areia",
        checkin="2026-08-01",
        checkout="2026-08-03",
        sale_date="2026-08-01",
        base_total=700.0,
    )
    assert preview["applied"] is False
    assert preview["final_total"] == 700.0
