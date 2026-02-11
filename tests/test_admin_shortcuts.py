
import unittest
from flask import session
from app import create_app

class TestAdminShortcuts(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        self.client = self.app.test_client()

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['department'] = 'Diretoria'
            sess['permissions'] = ['admin']

    def check_shortcut(self, name, url, expected_contents):
        print(f"Testing shortcut: {name} ({url})...")
        try:
            response = self.client.get(url, follow_redirects=True)
            if response.status_code == 200:
                missing = []
                for content in expected_contents:
                    if content.encode('utf-8') not in response.data:
                        missing.append(content)
                
                if not missing:
                    print(f"  [PASS] {name}: Status 200, All expected content found.")
                else:
                    print(f"  [FAIL] {name}: Status 200, but missing content: {', '.join(missing)}")
            else:
                print(f"  [FAIL] {name}: Status {response.status_code}")
        except Exception as e:
            print(f"  [ERROR] {name}: {str(e)}")

    def test_admin_shortcuts(self):
        self.login_as_admin()
        
        shortcuts = [
            ("Usuários", "/admin/users", ["Gerenciar Usuários", "Diretoria"]),
            ("Relatórios", "/reports", ["Relatórios", "Filtros"]),
            ("Conciliação", "/admin/reconciliation", ["Conciliação", "Resumo"]),
            ("Insumos", "/stock/products", ["Insumos", "Adicionar"]),
            ("Fiscal", "/config/fiscal", ["Configurações Fiscais", "NFC-e"]),
            ("Impressoras", "/config/printers", ["Impressoras", "Cadastradas"]),
            ("Segurança", "/admin/security/dashboard", ["Segurança", "Alertas"]),
            ("Logs", "/logs", ["Auditoria", "Logs"]),
            ("Sistema", "/admin/dashboard", ["Painel Administrativo", "Status do Sistema"]),
            ("Backups", "/admin/backups", ["Backups", "Gerenciamento"]),
            ("RH", "/hr/dashboard", ["Recursos Humanos", "Funcionários"])
        ]

        print("\n--- Starting Admin Shortcuts Verification ---")
        for name, url, contents in shortcuts:
            self.check_shortcut(name, url, contents)
        print("--- Verification Complete ---\n")

if __name__ == '__main__':
    unittest.main()
