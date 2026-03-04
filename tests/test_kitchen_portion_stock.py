import unittest
from unittest.mock import patch
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from app import create_app
except ImportError:
    from app import app as flask_app

    def create_app():
        return flask_app


class TestKitchenPortionStock(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Cozinha'

    @patch('app.blueprints.kitchen.print_portion_labels')
    @patch('app.blueprints.kitchen.save_stock_entry')
    @patch('app.blueprints.kitchen.load_settings')
    @patch('app.blueprints.kitchen.load_products')
    def test_kitchen_portion_creates_exit_and_entries_and_labels(self, mock_load_products, mock_load_settings, mock_save_stock, mock_print_labels):
        products = [
            {
                "name": "Frango Congelado",
                "category": "Carnes",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 20.0,
            },
            {
                "name": "Frango Porcionado",
                "category": "Carnes Porcionadas",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 0.0,
            },
        ]
        mock_load_products.return_value = products
        mock_load_settings.return_value = {
            "portioning_rules": [],
            "product_portioning_rules": [],
        }

        data = {
            "origin_product": "Frango Congelado",
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "dest_product[]": ["Frango Porcionado"],
            "final_qty[]": ["1700"],
            "dest_count[]": ["10"],
        }

        response = self.client.post(
            "/kitchen/portion", data=data, follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Porcionamento realizado com sucesso", response.data)
        self.assertGreaterEqual(len(mock_save_stock.call_args_list), 2)

        entries = [args[0] for args, _ in mock_save_stock.call_args_list]

        exit_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (SA\u00cdDA)"
            and e.get("product") == "Frango Congelado"
        ]
        self.assertEqual(len(exit_entries), 1)
        self.assertAlmostEqual(exit_entries[0]["qty"], -2.0, places=3)

        dest_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (ENTRADA)"
            and e.get("product") == "Frango Porcionado"
        ]
        self.assertEqual(len(dest_entries), 1)
        self.assertAlmostEqual(dest_entries[0]["qty"], 10.0, places=3)

        mock_print_labels.assert_called_once()
        labels_arg = mock_print_labels.call_args[0][0]
        self.assertEqual(len(labels_arg), 10)
        for label in labels_arg:
            self.assertEqual(label["name"], "Frango Porcionado")
            self.assertIn("g", label["avg_weight"])

    @patch('app.blueprints.kitchen.print_portion_labels')
    @patch('app.blueprints.kitchen.save_stock_entry')
    @patch('app.blueprints.kitchen.load_settings')
    @patch('app.blueprints.kitchen.load_products')
    def test_kitchen_portion_grams_unit_uses_units_for_qty(self, mock_load_products, mock_load_settings, mock_save_stock, mock_print_labels):
        products = [
            {
                "name": "Frango Congelado",
                "category": "Carnes",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 20.0,
            },
            {
                "name": "Frango Porcionado 100g",
                "category": "Carnes Porcionadas",
                "unit": "Gramas",
                "status": "Ativo",
                "price": 0.0,
            },
        ]
        mock_load_products.return_value = products
        mock_load_settings.return_value = {
            "portioning_rules": [],
            "product_portioning_rules": [],
        }

        data = {
            "origin_product": "Frango Congelado",
            "frozen_weight": "2000",
            "thawed_weight": "1800",
            "trim_weight": "100",
            "dest_product[]": ["Frango Porcionado 100g"],
            "final_qty[]": ["1700"],
            "dest_count[]": ["10"],
        }

        response = self.client.post(
            "/kitchen/portion", data=data, follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Porcionamento realizado com sucesso", response.data)

        entries = [args[0] for args, _ in mock_save_stock.call_args_list]

        exit_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (SA\u00cdDA)"
            and e.get("product") == "Frango Congelado"
        ]
        self.assertEqual(len(exit_entries), 1)
        self.assertAlmostEqual(exit_entries[0]["qty"], -2.0, places=3)

        dest_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (ENTRADA)"
            and e.get("product") == "Frango Porcionado 100g"
        ]
        self.assertEqual(len(dest_entries), 1)
        dest_entry = dest_entries[0]
        self.assertAlmostEqual(dest_entry["qty"], 10.0, places=3)
        self.assertAlmostEqual(dest_entry["price"], 40.0 / 10.0, places=3)

    @patch('app.blueprints.kitchen.print_portion_labels')
    @patch('app.blueprints.kitchen.secure_save_products')
    @patch('app.blueprints.kitchen.save_stock_entry')
    @patch('app.blueprints.kitchen.load_settings')
    @patch('app.blueprints.kitchen.load_products')
    def test_kitchen_portion_multi_origin_kit_paella(self, mock_load_products, mock_load_settings, mock_save_stock, mock_secure_save_products, mock_print_labels):
        products = [
            {
                "name": "Kit Paella Base",
                "category": "Kits",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 0.0,
            },
            {
                "name": "Anéis de Lula Congelados",
                "category": "Bruto Frutos do mar",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 40.0,
            },
            {
                "name": "Marisco Congelado",
                "category": "Bruto Frutos do mar",
                "unit": "Kilogramas",
                "status": "Ativo",
                "price": 30.0,
            },
            {
                "name": "Kit Paella Porcionado",
                "category": "Porcionados Frutos do mar",
                "unit": "Unidade",
                "status": "Ativo",
                "price": 0.0,
            },
        ]
        mock_load_products.return_value = products
        mock_load_settings.return_value = {
            "portioning_rules": [],
            "product_portioning_rules": [],
        }

        data = {
            "origin_product": "Kit Paella Base",
            "frozen_weight": "2000",
            "thawed_weight": "1900",
            "trim_weight": "100",
            "component_product[]": [
                "Anéis de Lula Congelados",
                "Marisco Congelado",
            ],
            "component_weight[]": [
                "1000",
                "800",
            ],
            "dest_product[]": ["Kit Paella Porcionado"],
            "final_qty[]": ["1800"],
            "dest_count[]": ["16"],
        }

        response = self.client.post(
            "/kitchen/portion", data=data, follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Porcionamento realizado com sucesso", response.data)

        entries = [args[0] for args, _ in mock_save_stock.call_args_list]

        exit_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (SA\u00cdDA)"
        ]
        self.assertEqual(len(exit_entries), 2)
        product_names = {e.get("product") for e in exit_entries}
        self.assertIn("Anéis de Lula Congelados", product_names)
        self.assertIn("Marisco Congelado", product_names)
        self.assertNotIn("Kit Paella Base", product_names)

        dest_entries = [
            e
            for e in entries
            if e.get("supplier") == "PORCIONAMENTO (ENTRADA)"
            and e.get("product") == "Kit Paella Porcionado"
        ]
        self.assertEqual(len(dest_entries), 1)
        dest_entry = dest_entries[0]
        self.assertAlmostEqual(dest_entry["qty"], 16.0, places=3)
        self.assertAlmostEqual(dest_entry["price"], 4.0, places=3)

        mock_print_labels.assert_called_once()
        labels_arg = mock_print_labels.call_args[0][0]
        self.assertEqual(len(labels_arg), 16)
        for label in labels_arg:
            self.assertEqual(label["name"], "Kit Paella Porcionado")
            self.assertIn("g", label["avg_weight"])

        self.assertTrue(mock_secure_save_products.called)
        saved_products = mock_secure_save_products.call_args[0][0]
        updated_dest = next((p for p in saved_products if p["name"] == "Kit Paella Porcionado"), None)
        self.assertIsNotNone(updated_dest)
        self.assertAlmostEqual(float(updated_dest["price"]), 4.0, places=3)

    @patch('app.blueprints.kitchen.load_products')
    @patch('app.blueprints.kitchen.load_stock_entries')
    def test_kitchen_reports_shows_portioned_final_unit_prices(self, mock_load_stock_entries, mock_load_products):
        mock_load_products.return_value = [
            {"name": "Frango Congelado", "category": "Carnes"},
            {"name": "Frango Porcionado 170g", "category": "Porcionados"},
            {"name": "Frango Porcionado 200g", "category": "Porcionados"},
        ]
        mock_load_stock_entries.return_value = [
            {
                "id": "20260304123000_PORT_OUT",
                "entry_date": "04/03/2026 12:30",
                "date": "04/03/2026",
                "product": "Frango Congelado",
                "supplier": "PORCIONAMENTO (SAÍDA)",
                "qty": -2.0,
                "price": 30.0,
                "user": "admin",
                "invoice": "Transf: Frango Porcionado 170g, Frango Porcionado 200g | Degelo: 0.100kg | Aparas: 0.050kg | Cocção: 0.000kg"
            },
            {
                "id": "20260304123000_PORT_IN_Frango Porcionado 170g",
                "entry_date": "04/03/2026 12:30",
                "date": "04/03/2026",
                "product": "Frango Porcionado 170g",
                "supplier": "PORCIONAMENTO (ENTRADA)",
                "qty": 10,
                "price": 4.20,
                "user": "admin"
            },
            {
                "id": "20260304123000_PORT_IN_Frango Porcionado 200g",
                "entry_date": "04/03/2026 12:30",
                "date": "04/03/2026",
                "product": "Frango Porcionado 200g",
                "supplier": "PORCIONAMENTO (ENTRADA)",
                "qty": 5,
                "price": 5.00,
                "user": "admin"
            }
        ]

        response = self.client.get("/kitchen/reports")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Preço Final Unitário (Porcionados)".encode("utf-8"), response.data)
        self.assertIn("Frango Porcionado 170g: R$ 4.20".encode("utf-8"), response.data)
        self.assertIn("Frango Porcionado 200g: R$ 5.00".encode("utf-8"), response.data)

    @patch('app.blueprints.kitchen.LoggerService.log_acao')
    @patch('app.blueprints.kitchen.save_settings')
    @patch('app.blueprints.kitchen.load_settings')
    def test_kitchen_portion_settings_updates_category_rule(self, mock_load_settings, mock_save_settings, mock_log_acao):
        mock_load_settings.return_value = {
            "portioning_rules": [
                {"origin": "Carnes", "destinations": ["Porcionados"]}
            ],
            "product_portioning_rules": []
        }

        response = self.client.post(
            "/kitchen/portion/settings",
            data={
                "action": "update",
                "rule_index": "0",
                "origin_category": "Aves",
                "destination_categories": ["Porcionados", "Kits"]
            },
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_save_settings.called)
        saved_settings = mock_save_settings.call_args[0][0]
        self.assertEqual(saved_settings["portioning_rules"][0]["origin"], "Aves")
        self.assertEqual(saved_settings["portioning_rules"][0]["destinations"], ["Porcionados", "Kits"])
        self.assertTrue(mock_log_acao.called)

    @patch('app.blueprints.kitchen.LoggerService.log_acao')
    @patch('app.blueprints.kitchen.save_settings')
    @patch('app.blueprints.kitchen.load_settings')
    def test_kitchen_portion_settings_updates_product_rule(self, mock_load_settings, mock_save_settings, mock_log_acao):
        mock_load_settings.return_value = {
            "portioning_rules": [],
            "product_portioning_rules": [
                {"origin": "Filé de Peixe", "destinations": ["Filé 200g"]}
            ]
        }

        response = self.client.post(
            "/kitchen/portion/settings",
            data={
                "action": "update_product_rule",
                "rule_index": "0",
                "origin_product": "Filé de Peixe Premium",
                "destination_products": ["Filé 150g", "Filé 200g"]
            },
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_save_settings.called)
        saved_settings = mock_save_settings.call_args[0][0]
        self.assertEqual(saved_settings["product_portioning_rules"][0]["origin"], "Filé de Peixe Premium")
        self.assertEqual(saved_settings["product_portioning_rules"][0]["destinations"], ["Filé 150g", "Filé 200g"])
        self.assertTrue(mock_log_acao.called)


if __name__ == "__main__":
    unittest.main()
