import os
import json
import shutil
from datetime import datetime

import pytest
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as flask_app
from app.services import system_config_manager as scm
from app.services import data_service as ds


class TestAdminSalesRoomTransfers:
    def setup_method(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.test_dir = os.path.join(base_dir, "tmp_admin_sales_dashboard")
        if os.path.isdir(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        self.sales_file = os.path.join(self.test_dir, "sales_history.json")
        self.cashier_file = os.path.join(self.test_dir, "cashier_sessions.json")

        with open(self.sales_file, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(self.cashier_file, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)

        scm.SALES_HISTORY_FILE = self.sales_file
        ds.SALES_HISTORY_FILE = self.sales_file
        self.original_get_cashier_path = ds._get_cashier_sessions_path
        ds._get_cashier_sessions_path = lambda: self.cashier_file

        self.app = flask_app.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "admin"

    def teardown_method(self):
        ds._get_cashier_sessions_path = self.original_get_cashier_path
        if os.path.isdir(self.test_dir):
            shutil.rmtree(self.test_dir)

    def write_sales_history(self, data):
        with open(self.sales_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def test_room_transfer_summary_and_items(self):
        day = datetime.now().strftime("%d/%m/%Y")
        closed_at = f"{day} 12:00"
        data = [
            {
                "id": "ORD1",
                "closed_at": closed_at,
                "status": "closed",
                "customer_type": "hospede",
                "room_number": "101",
                "customer_name": "Hospede Teste",
                "payment_method": "Room Charge",
                "room_charge": "101",
                "final_total": 40.0,
                "items": [
                    {"product_id": "P1", "name": "Hamburguer", "qty": 2, "price": 10.0, "complements": []},
                    {"product_id": "P2", "name": "Refrigerante", "qty": 1, "price": 20.0, "complements": []},
                ],
            }
        ]
        self.write_sales_history(data)

        iso_date = datetime.now().strftime("%Y-%m-%d")
        resp = self.client.get(
            "/admin/api/sales/analysis",
            query_string={"start_date": iso_date, "end_date": iso_date},
        )
        assert resp.status_code == 200
        payload = resp.get_json()

        assert "room_transfers" in payload
        rt = payload["room_transfers"]
        summary = rt["summary"]
        assert summary["orders_count"] == 1
        assert summary["items_count"] == pytest.approx(3.0)
        assert summary["revenue"] == pytest.approx(40.0)

        items = rt["items"]
        assert len(items) == 3
        rooms = {it["room_number"] for it in items}
        assert rooms == {"101"}
        guests = {it["guest_name"] for it in items}
        assert guests == {"Hospede Teste"}

    def test_room_transfer_deduplicates_orders(self):
        day = datetime.now().strftime("%d/%m/%Y")
        closed_at = f"{day} 13:00"
        order = {
            "id": "ORD_DUP",
            "closed_at": closed_at,
            "status": "closed",
            "customer_type": "hospede",
            "room_number": "102",
            "customer_name": "Hospede Duplicado",
            "payment_method": "Room Charge",
            "room_charge": "102",
            "final_total": 30.0,
            "items": [
                {"product_id": "PX", "name": "Prato X", "qty": 1, "price": 30.0, "complements": []},
            ],
        }
        data = [order, dict(order)]
        self.write_sales_history(data)

        iso_date = datetime.now().strftime("%Y-%m-%d")
        resp = self.client.get(
            "/admin/api/sales/analysis",
            query_string={"start_date": iso_date, "end_date": iso_date},
        )
        assert resp.status_code == 200
        payload = resp.get_json()

        rt = payload["room_transfers"]
        summary = rt["summary"]
        assert summary["orders_count"] == 1
        assert summary["items_count"] == pytest.approx(1.0)
        assert summary["revenue"] == pytest.approx(30.0)

        items = rt["items"]
        assert len(items) == 1
        assert items[0]["order_id"] == "ORD_DUP"
