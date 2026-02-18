import unittest
from unittest.mock import patch
import sys
import os
import json
import shutil
import tempfile
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
import app.services.kitchen_checklist_service as kcs


class TestKitchenChecklist(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Isola o arquivo de listas em diretório temporário
        self.tmpdir = tempfile.mkdtemp(prefix="kitchen_checklists_")
        self.old_data_dir = kcs.DATA_DIR
        self.old_file = kcs.KITCHEN_CHECKLISTS_FILE
        kcs.DATA_DIR = self.tmpdir
        kcs.KITCHEN_CHECKLISTS_FILE = os.path.join(self.tmpdir, "kitchen_checklists.json")

        with self.client.session_transaction() as sess:
            sess["user"] = "cozinha_tester"
            sess["role"] = "admin"
            sess["department"] = "Cozinha"

    def tearDown(self):
        kcs.DATA_DIR = self.old_data_dir
        kcs.KITCHEN_CHECKLISTS_FILE = self.old_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- Unit tests: KitchenChecklistService ---

    def test_create_and_load_list(self):
        items = [
            {"id": "1", "name": "Arroz", "unit": "kg"},
            {"id": "2", "name": "Feijão", "unit": "kg"},
        ]
        created = kcs.KitchenChecklistService.create_list("Compras Semanais", "quantity", items)
        self.assertIn("id", created)
        self.assertEqual(created["name"], "Compras Semanais")
        self.assertEqual(created["type"], "quantity")
        self.assertEqual(len(created["items"]), 2)
        self.assertIn("created_at", created)

        all_lists = kcs.KitchenChecklistService.load_lists()
        self.assertEqual(len(all_lists), 1)
        self.assertEqual(all_lists[0]["name"], "Compras Semanais")

    def test_update_and_delete_list(self):
        base = kcs.KitchenChecklistService.create_list(
            "Original", "checklist", [{"id": "1", "name": "Item A", "unit": ""}]
        )
        list_id = base["id"]

        updated = kcs.KitchenChecklistService.update_list(
            list_id,
            {
                "name": "Atualizada",
                "type": "quantity",
                "items": [{"id": "2", "name": "Item B", "unit": "cx"}],
            },
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["name"], "Atualizada")
        self.assertEqual(updated["type"], "quantity")
        self.assertEqual(len(updated["items"]), 1)
        self.assertIn("updated_at", updated)

        ok = kcs.KitchenChecklistService.delete_list(list_id)
        self.assertTrue(ok)
        self.assertEqual(kcs.KitchenChecklistService.load_lists(), [])

    def test_load_lists_missing_file_returns_empty(self):
        # Arquivo não existe inicialmente
        if os.path.exists(kcs.KITCHEN_CHECKLISTS_FILE):
            os.remove(kcs.KITCHEN_CHECKLISTS_FILE)
        lists = kcs.KitchenChecklistService.load_lists()
        self.assertEqual(lists, [])

    @patch("app.services.kitchen_checklist_service.load_products")
    def test_get_insumos_sorted_and_simplified(self, mock_load_products):
        mock_load_products.return_value = [
            {"id": "2", "name": "Feijão", "unit": "kg"},
            {"id": "1", "name": "Arroz", "unit": "kg"},
            {"id": "3", "name": "Óleo"},
        ]
        insumos = kcs.KitchenChecklistService.get_insumos()
        self.assertEqual([i["name"] for i in insumos], ["Arroz", "Feijão", "Óleo"])
        self.assertEqual(insumos[0]["unit"], "kg")

    # --- Integration / route tests ---

    def test_manage_view_empty_state_and_responsiveness_classes(self):
        resp = self.client.get("/kitchen/checklist")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        # Estado vazio
        self.assertIn(b"Nenhuma lista encontrada", data)
        # Classes de layout responsivo
        self.assertIn(b"row-cols-1 row-cols-md-2 row-cols-lg-3", data)

    def test_create_list_success_flow(self):
        resp_get = self.client.get("/kitchen/checklist/create")
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn(b"Nome da Lista", resp_get.data)

        form_data = {
            "name": "Compras Cozinha",
            "type": "quantity",
            "item_name[]": ["Arroz", "Feijao", ""],
            "item_unit[]": ["kg", "kg", ""],
        }
        resp_post = self.client.post(
            "/kitchen/checklist/create", data=form_data, follow_redirects=True
        )
        self.assertEqual(resp_post.status_code, 200)
        self.assertIn(b"Lista criada com sucesso!", resp_post.data)
        self.assertIn(b"Compras Cozinha", resp_post.data)

        lists = kcs.KitchenChecklistService.load_lists()
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]["items"]), 2)

    def test_create_list_validation_error(self):
        form_data = {
            "name": "",
            "type": "quantity",
            "item_name[]": [""],
            "item_unit[]": [""],
        }
        resp = self.client.post(
            "/kitchen/checklist/create", data=form_data, follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Nome da lista e pelo menos um item são obrigatórios.", html)

    def test_edit_list_flow(self):
        created = kcs.KitchenChecklistService.create_list(
            "Limpeza", "checklist", [{"id": "1", "name": "Detergente", "unit": "un"}]
        )
        list_id = created["id"]

        resp_get = self.client.get(f"/kitchen/checklist/edit/{list_id}")
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn(b"Editar Lista", resp_get.data)

        form_data = {
            "name": "Limpeza Semanal",
            "type": "checklist",
            "item_name[]": ["Detergente", "Esponja"],
            "item_unit[]": ["un", "un"],
        }
        resp_post = self.client.post(
            f"/kitchen/checklist/edit/{list_id}", data=form_data, follow_redirects=True
        )
        self.assertEqual(resp_post.status_code, 200)
        self.assertIn(b"Lista atualizada com sucesso!", resp_post.data)

        updated = kcs.KitchenChecklistService.get_list(list_id)
        self.assertEqual(updated["name"], "Limpeza Semanal")
        self.assertEqual(len(updated["items"]), 2)

    def test_edit_list_not_found_redirects(self):
        resp = self.client.get(
            "/kitchen/checklist/edit/nao-existe", follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Lista não encontrada.", html)

    def test_edit_list_validation_error(self):
        created = kcs.KitchenChecklistService.create_list(
            "Limpeza", "checklist", [{"id": "1", "name": "Detergente", "unit": "un"}]
        )
        list_id = created["id"]

        form_data = {
            "name": "",
            "type": "checklist",
            "item_name[]": [""],
            "item_unit[]": [""],
        }
        resp = self.client.post(
            f"/kitchen/checklist/edit/{list_id}", data=form_data, follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Nome da lista e pelo menos um item são obrigatórios.", html)
        stored = kcs.KitchenChecklistService.get_list(list_id)
        self.assertEqual(stored["name"], "Limpeza")

    def test_delete_list_flow(self):
        created = kcs.KitchenChecklistService.create_list(
            "Descartar", "checklist", [{"id": "1", "name": "Item X", "unit": ""}]
        )
        list_id = created["id"]

        resp = self.client.post(
            f"/kitchen/checklist/delete/{list_id}", follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Lista removida.", resp.data)
        self.assertEqual(kcs.KitchenChecklistService.load_lists(), [])

    def test_use_list_view_renders_items_and_controls(self):
        created = kcs.KitchenChecklistService.create_list(
            "Pedido Semana",
            "quantity",
            [{"id": "1", "name": "Tomate", "unit": "kg"}],
        )
        list_id = created["id"]
        resp = self.client.get(f"/kitchen/checklist/use/{list_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertIn(b"Pedido Semana", data)
        self.assertIn(b"Tomate", data)
        self.assertIn(b"Gerar Pedido", data)
        # Acessibilidade: label vinculado ao checkbox
        self.assertIn(b'for="check_1"', data)

    def test_use_list_not_found_redirects(self):
        resp = self.client.get(
            "/kitchen/checklist/use/inexistente", follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Lista não encontrada.", html)

    # --- API and error handling ---

    def test_send_api_success_builds_message(self):
        now = datetime.now()
        payload = {
            "list_name": "Compras R&amp;#225;pidas",
            "items": [
                {"name": "Arroz", "qty": "2", "unit": "kg"},
                {"name": "Feijao", "qty": "1", "unit": "kg"},
            ],
        }
        resp = self.client.post(
            "/api/kitchen/checklist/send",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        text = data["text"]
        self.assertIn("*Pedido - Compras R", text)
        self.assertIn("Arroz: 2 kg", text)
        self.assertIn("Feijao: 1 kg", text)
        self.assertIn("Solicitante: cozinha_tester", text)
        self.assertIn("*Por favor, confirmar recebimento.*", text)

    def test_send_api_without_items_returns_error(self):
        payload = {"list_name": "Vazia", "items": []}
        resp = self.client.post(
            "/api/kitchen/checklist/send",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "Nenhum item selecionado.")

    @patch("app.blueprints.kitchen.datetime")
    def test_send_api_exception_path(self, mock_dt):
        class BoomDateTime:
            @classmethod
            def now(cls):
                raise RuntimeError("boom")

        mock_dt.now.side_effect = BoomDateTime.now
        payload = {
            "list_name": "Erro",
            "items": [{"name": "Teste", "qty": "1", "unit": "un"}],
        }
        resp = self.client.post(
            "/api/kitchen/checklist/send",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("boom", data["error"])

    # --- Type validation tests ---

    def test_create_list_invalid_type_shows_error_and_does_not_create(self):
        form_data = {
            "name": "Lista Invalida",
            "type": "outro",
            "item_name[]": ["Item X"],
            "item_unit[]": [""],
        }
        resp = self.client.post(
            "/kitchen/checklist/create", data=form_data, follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Tipo de lista inválido.", html)
        lists = kcs.KitchenChecklistService.load_lists()
        self.assertEqual(len(lists), 0)

    def test_edit_list_invalid_type_shows_error_and_keeps_original_type(self):
        created = kcs.KitchenChecklistService.create_list(
            "Lista Tipo", "quantity", [{"id": "1", "name": "Item", "unit": ""}]
        )
        list_id = created["id"]

        form_data = {
            "name": "Lista Tipo",
            "type": "outro",
            "item_name[]": ["Item"],
            "item_unit[]": [""],
        }
        resp = self.client.post(
            f"/kitchen/checklist/edit/{list_id}", data=form_data, follow_redirects=False
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Tipo de lista inválido.", html)
        stored = kcs.KitchenChecklistService.get_list(list_id)
        self.assertEqual(stored["type"], "quantity")


if __name__ == "__main__":
    unittest.main()
