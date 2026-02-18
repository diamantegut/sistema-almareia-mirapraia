import os
import json
import shutil
from datetime import datetime, timedelta

import pytest
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as flask_app
from app.services import system_config_manager as scm
from app.services import data_service as ds
from app.blueprints.menu import routes as menu_routes


class TestMenuSalesHistory:
    def setup_method(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.test_dir = os.path.join(base_dir, "tmp_menu_sales_history")
        if os.path.isdir(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)
        self.logs_dir = os.path.join(self.test_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.sales_file = os.path.join(self.test_dir, "sales_history.json")
        scm.SALES_HISTORY_FILE = self.sales_file
        scm.ACTION_LOGS_DIR = self.logs_dir
        ds.SALES_HISTORY_FILE = self.sales_file
        menu_routes.SALES_HISTORY_FILE = self.sales_file
        menu_routes.ACTION_LOGS_DIR = self.logs_dir
        self.app = flask_app.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "super"

    def teardown_method(self):
        if os.path.isdir(self.test_dir):
            shutil.rmtree(self.test_dir)

    def write_sales_history(self, data):
        with open(self.sales_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def write_action_log(self, date_obj, entries):
        fname = date_obj.strftime("%Y-%m-%d") + ".json"
        path = os.path.join(self.logs_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

    def test_sales_history_basic_filtering(self):
        data = [
            {
                "close_id": "CLOSE1",
                "closed_at": "16/02/2026 12:00",
                "status": "closed",
                "customer_name": "Cliente A",
                "items": [
                    {"product_id": "101", "name": "Bolo Especial", "qty": 2, "price": 10.0, "complements": []},
                    {"name": "Cafe", "qty": 1, "price": 5.0, "complements": []},
                ],
            }
        ]
        self.write_sales_history(data)
        resp = self.client.get(
            "/api/menu/sales-history",
            query_string={
                "products": "Bolo Especial",
                "status": "concluidas",
                "page": 1,
                "page_size": 10,
            },
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        assert payload["total_count"] == 1
        item = payload["items"][0]
        assert item["product"] == "Bolo Especial"
        summary = payload["summary"]
        assert summary["total_vendida"] == pytest.approx(2.0)
        assert summary["total_cancelada"] == pytest.approx(0.0)
        assert summary["quantidade_liquida"] == pytest.approx(2.0)
        assert summary["valor_total"] == pytest.approx(20.0)

    def test_sales_history_filtering_by_product_id(self):
        data = [
            {
                "close_id": "CLOSEID1",
                "closed_at": "16/02/2026 13:00",
                "status": "closed",
                "customer_name": "Cliente B",
                "items": [
                    {"product_id": "OVOS_ID", "name": "Ovos Mexidos", "qty": 1, "price": 8.0, "complements": []},
                    {"product_id": "OUTRO_ID", "name": "Cafe", "qty": 1, "price": 5.0, "complements": []},
                ],
            }
        ]
        self.write_sales_history(data)
        resp = self.client.get(
            "/api/menu/sales-history",
            query_string={
                "product_ids": "OVOS_ID",
                "status": "concluidas",
                "page": 1,
                "page_size": 10,
            },
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        assert payload["total_count"] == 1
        item = payload["items"][0]
        assert item["product"] == "Ovos Mexidos"

    def test_sales_history_cancellations_and_all(self):
        today = datetime.now()
        data = [
            {
                "close_id": "CLOSE2",
                "closed_at": today.strftime("%d/%m/%Y 10:00"),
                "status": "closed",
                "customer_name": "Cliente B",
                "items": [
                    {"name": "Bolo Especial", "qty": 1, "price": 30.0, "complements": []}
                ],
            }
        ]
        self.write_sales_history(data)
        log_entries = [
            {
                "id": "1",
                "timestamp": today.strftime("%d/%m/%Y %H:%M:%S"),
                "action": "Item Removido",
                "details": "Item Bolo Especial removido da mesa",
            }
        ]
        self.write_action_log(today, log_entries)
        resp_cancel = self.client.get(
            "/api/menu/sales-history",
            query_string={
                "products": "Bolo Especial",
                "status": "canceladas",
                "page": 1,
                "page_size": 10,
            },
        )
        assert resp_cancel.status_code == 200
        payload_cancel = resp_cancel.get_json()
        assert payload_cancel["success"] is True
        assert payload_cancel["total_count"] == 1
        item_cancel = payload_cancel["items"][0]
        assert item_cancel["status"] == "cancelada"
        resp_all = self.client.get(
            "/api/menu/sales-history",
            query_string={
                "products": "Bolo Especial",
                "status": "todas",
                "page": 1,
                "page_size": 10,
            },
        )
        assert resp_all.status_code == 200
        payload_all = resp_all.get_json()
        assert payload_all["success"] is True
        assert payload_all["total_count"] == 2
        statuses = {it["status"] for it in payload_all["items"]}
        assert {"concluída", "cancelada"} == statuses

    def test_sales_history_future_date_validation(self):
        future = datetime.now() + timedelta(days=1)
        future_str = future.strftime("%d/%m/%Y")
        resp = self.client.get(
            "/api/menu/sales-history",
            query_string={"start_date": future_str},
        )
        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload["success"] is False
        assert "futuro" in payload["error"].lower()

    def test_sales_history_export_excel_and_pdf(self):
        data = [
            {
                "close_id": "CLOSE3",
                "closed_at": "15/02/2026 18:00",
                "status": "closed",
                "customer_name": "Cliente C",
                "items": [
                    {"name": "Suco Laranja", "qty": 1, "price": 12.5, "complements": []}
                ],
            }
        ]
        self.write_sales_history(data)
        resp_xlsx = self.client.get(
            "/menu/sales-history/export",
            query_string={
                "products": "Suco Laranja",
                "status": "concluidas",
                "format": "xlsx",
            },
        )
        assert resp_xlsx.status_code == 200
        assert resp_xlsx.data[:2] == b"PK"
        resp_pdf = self.client.get(
            "/menu/sales-history/export",
            query_string={
                "products": "Suco Laranja",
                "status": "concluidas",
                "format": "pdf",
            },
        )
        assert resp_pdf.status_code == 200
        assert resp_pdf.data[:4] == b"%PDF"
