from app.services.revenue_management_service import RevenueManagementService


def test_revenue_scenario_simulator_comparison(monkeypatch):
    monkeypatch.setattr(
        "app.services.reservation_service.ReservationService.get_room_mapping",
        lambda *args, **kwargs: {
            "Suíte Mar": ["12", "14", "15", "16", "17"],
            "Suíte Areia": ["01", "02", "03"],
        },
    )
    result = RevenueManagementService.revenue_scenario_simulator(
        expected_occupancy_pct=70,
        average_rate_current=520,
        average_rate_suggested=580,
        average_stay_nights=2,
        horizon_days=30,
    )
    outputs = result["outputs"]
    assert outputs["estimated_total_revenue_suggested"] > outputs["estimated_total_revenue_current"]
    assert outputs["estimated_revenue_diff_pct"] > 0
    assert outputs["estimated_revpar_suggested"] > outputs["estimated_revpar_current"]
