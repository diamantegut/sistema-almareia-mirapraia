from app.services.revenue_management_service import RevenueManagementService


def test_save_and_list_local_events(monkeypatch):
    store = []
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_events_raw",
        classmethod(lambda cls: list(store)),
    )
    monkeypatch.setattr(
        RevenueManagementService,
        "_save_events_raw",
        classmethod(lambda cls, rows: store.__init__(rows)),
    )

    saved = RevenueManagementService.save_event(
        {
            "name": "Carnaval Regional",
            "city": "Ilhéus",
            "impact": "alto",
            "start_date": "2027-02-10",
            "end_date": "2027-02-14",
        },
        user="tester",
    )
    assert saved["name"] == "Carnaval Regional"
    rows = RevenueManagementService.list_events(start_date="2027-02-01", end_date="2027-02-28", city="Ilhéus")
    assert len(rows) == 1
    assert rows[0]["factor"] > 1.0


def test_events_index_expands_period(monkeypatch):
    monkeypatch.setattr(
        RevenueManagementService,
        "_load_events",
        classmethod(
            lambda cls: [
                {
                    "id": "evt1",
                    "name": "Evento Local",
                    "city": "Itacaré",
                    "start_date": "2027-01-02",
                    "end_date": "2027-01-03",
                    "impact": "medio",
                    "status": "active",
                }
            ]
        ),
    )
    index = RevenueManagementService._events_index()
    assert "2027-01-02" in index
    assert "2027-01-03" in index
    assert float(index["2027-01-02"]["factor"]) > 1.0
