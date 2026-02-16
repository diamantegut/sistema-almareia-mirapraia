import pytest
import json
from datetime import datetime
import os

from app import (
    app,
    load_table_orders,
    save_table_orders,
    load_room_occupancy,
    save_room_occupancy,
    load_room_charges,
    save_room_charges,
    load_cashier_sessions,
    save_cashier_sessions,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.secret_key = "test_secret"
    with app.test_client() as client:
        with app.app_context():
            yield client


def login(client, username="admin"):
    with client.session_transaction() as sess:
        sess["user"] = username
        sess["role"] = "admin"
        sess["permissions"] = ["recepcao", "restaurante_full_access", "financeiro"]


def test_cover_does_not_generate_commission_or_service_fee(client):
    login(client)

    table_id = "50"
    room_num = "101"

    occupancy = load_room_occupancy()
    occupancy[room_num] = {"guest_name": "Cover Guest", "status": "occupied"}
    save_room_occupancy(occupancy)

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    orders = load_table_orders()
    orders[table_id] = {
        "items": [
            {
                "id": "item_food",
                "name": "Steak",
                "price": 100.0,
                "qty": 1,
                "category": "Pratos",
                "waiter": "Waiter A",
                "printed": True,
                "complements": [],
            },
            {
                "id": "item_cover",
                "name": "Couvert Artistico",
                "price": 30.0,
                "qty": 1,
                "category": "Couvert",
                "waiter": "Waiter A",
                "printed": True,
                "complements": [],
                "source": "auto_cover_activation",
            },
        ],
        "total": 130.0,
        "status": "open",
        "opened_at": now,
        "customer_type": "hospede",
        "room_number": room_num,
        "waiter": "Waiter A",
    }
    save_table_orders(orders)

    response = client.post(
        f"/restaurant/table/{table_id}",
        data={"action": "transfer_to_room", "room_number": room_num},
        follow_redirects=True,
    )
    assert response.status_code == 200

    charges = load_room_charges()
    assert len(charges) >= 1
    charge = next(c for c in charges if c["room_number"] == room_num)

    assert abs(charge["total"] - 143.0) < 0.01
    assert abs(charge.get("service_fee", 0.0) - 13.0) < 0.01

    waiter_breakdown = charge.get("waiter_breakdown", {})
    assert "Waiter A" in waiter_breakdown

    commissionable_total = waiter_breakdown["Waiter A"]
    assert commissionable_total < charge["total"]
    assert abs(commissionable_total - 110.0) < 0.01

    cashier_sessions = load_cashier_sessions()
    cashier_sessions = [s for s in cashier_sessions if s.get("type") != "guest_consumption"]
    cashier_sessions.append(
        {
            "id": "sess_gc_cover",
            "type": "guest_consumption",
            "status": "open",
            "transactions": [],
        }
    )
    save_cashier_sessions(cashier_sessions)

    response = client.post(
        f"/reception/close_account/{room_num}",
        json={"payment_method": "Dinheiro", "print_receipt": False},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True

    cashier_sessions = load_cashier_sessions()
    gc_session = next(s for s in cashier_sessions if s["type"] == "guest_consumption")
    assert len(gc_session["transactions"]) == 1
    tx = gc_session["transactions"][0]

    details = tx.get("details", {})
    wb_tx = details.get("waiter_breakdown", {})
    assert "Waiter A" in wb_tx
    assert abs(wb_tx["Waiter A"] - commissionable_total) < 0.01
