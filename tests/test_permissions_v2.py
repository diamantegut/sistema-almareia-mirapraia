import json
import os
import shutil
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services import data_service
from app.services.permission_service import effective_profile_for_user, is_allowed_for_endpoint, legacy_tokens_from_profile, merge_profiles


TEST_DATA_DIR = 'tests/test_data_permissions_v2'


class TestPermissionsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)

        cls.app = create_app('testing')
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def setUp(self):
        self.original_users_file = data_service.USERS_FILE
        self.original_dept_perm_file = getattr(data_service, 'DEPARTMENT_PERMISSIONS_FILE', None)

        self.test_users_file = os.path.join(TEST_DATA_DIR, 'users.json')
        self.test_dept_perm_file = os.path.join(TEST_DATA_DIR, 'department_permissions.json')

        data_service.USERS_FILE = self.test_users_file
        data_service.DEPARTMENT_PERMISSIONS_FILE = self.test_dept_perm_file

        users = {
            'admin_tester': {
                'password': '1234',
                'role': 'admin',
                'department': '',
                'permissions': []
            },
            'rec_user': {
                'password': '1234',
                'role': 'colaborador',
                'department': 'Recepção',
                'permissions': []
            },
            'sup_user': {
                'password': '1234',
                'role': 'supervisor',
                'department': 'Serviço',
                'permissions': []
            }
        }
        with open(self.test_users_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False)

        with open(self.test_dept_perm_file, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False)

    def tearDown(self):
        data_service.USERS_FILE = self.original_users_file
        if self.original_dept_perm_file is None:
            delattr(data_service, 'DEPARTMENT_PERMISSIONS_FILE')
        else:
            data_service.DEPARTMENT_PERMISSIONS_FILE = self.original_dept_perm_file

    def test_01_middleware_allows_reception_by_department(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'rec_user'
            sess['role'] = 'colaborador'
            sess['department'] = 'Recepção'
            sess['permissions'] = []

        resp = self.client.get('/reception', follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_02_middleware_blocks_finance_without_permission(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'rec_user'
            sess['role'] = 'colaborador'
            sess['department'] = 'Recepção'
            sess['permissions'] = []

        resp = self.client.get('/accounting/emission', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_03_level_restricted_page_requires_grant(self):
        users = data_service.load_users()
        dept_perms = data_service.load_department_permissions()

        profile = effective_profile_for_user('sup_user', users, dept_perms)
        allowed, _ = is_allowed_for_endpoint(
            'menu.menu_security_dashboard',
            user='sup_user',
            user_role='supervisor',
            profile=profile,
        )
        self.assertFalse(allowed)

        users['sup_user']['permissions_v2'] = {
            'version': 2,
            'areas': {
                'restaurante_mirapraia': {
                    'all': False,
                    'pages': {'menu.menu_security_dashboard': True}
                }
            },
            'level_pages': ['menu.menu_security_dashboard']
        }
        with open(self.test_users_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False)

        profile = effective_profile_for_user('sup_user', users, dept_perms)
        allowed, _ = is_allowed_for_endpoint(
            'menu.menu_security_dashboard',
            user='sup_user',
            user_role='supervisor',
            profile=profile,
        )
        self.assertTrue(allowed)

        with self.client.session_transaction() as sess:
            sess['user'] = 'sup_user'
            sess['role'] = 'supervisor'
            sess['department'] = 'Serviço'
            sess['permissions'] = []

        resp = self.client.get('/menu/security', follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_04_api_blocks_self_permission_change(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['department'] = ''
            sess['permissions'] = []

        payload = {
            'type': 'user',
            'id': 'admin_tester',
            'profile': {'version': 2, 'areas': {'recepcao': {'all': True, 'pages': {}}}, 'level_pages': []}
        }
        resp = self.client.post('/admin/api/permissions/set', json=payload)
        self.assertEqual(resp.status_code, 400)

    def test_05_api_updates_other_user(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['department'] = ''
            sess['permissions'] = []

        payload = {
            'type': 'user',
            'id': 'rec_user',
            'profile': {'version': 2, 'areas': {'financeiro': {'all': True, 'pages': {}}}, 'level_pages': []}
        }
        resp = self.client.post('/admin/api/permissions/set', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))

        users = data_service.load_users()
        self.assertIn('permissions_v2', users['rec_user'])

    def test_06_assets_page_access_when_granted(self):
        users = data_service.load_users()
        users['rec_user']['permissions_v2'] = {
            'version': 2,
            'areas': {'conferencia': {'all': False, 'pages': {'assets.index': True}}},
            'level_pages': []
        }
        data_service.save_users(users)

        with self.client.session_transaction() as sess:
            sess['user'] = 'rec_user'
            sess['role'] = 'colaborador'
            sess['department'] = 'Recepção'
            sess['permissions'] = []

        resp = self.client.get('/service/principal/assets', follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_06_department_profile_is_merged_into_effective_profile(self):
        users = data_service.load_users()
        dept_perms = data_service.load_department_permissions()
        dept_perms['Recepção'] = {
            'version': 2,
            'areas': {'recepcao': {'all': True, 'pages': {}}},
            'level_pages': []
        }
        data_service.save_department_permissions(dept_perms)

        effective = effective_profile_for_user('rec_user', users, dept_perms)
        tokens = legacy_tokens_from_profile(effective)
        self.assertIn('recepcao', tokens)

    def test_07_merge_profiles_union(self):
        a = {'version': 2, 'areas': {'recepcao': {'all': False, 'pages': {'reception.reception_dashboard': True}}}, 'level_pages': []}
        b = {'version': 2, 'areas': {'recepcao': {'all': True, 'pages': {}}}, 'level_pages': ['menu.menu_security_dashboard']}
        m = merge_profiles(a, b)
        self.assertTrue(m['areas']['recepcao']['all'])
        self.assertIn('menu.menu_security_dashboard', m['level_pages'])

    def test_08_api_definitions_available(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin_tester'
            sess['role'] = 'admin'
            sess['department'] = ''
            sess['permissions'] = []

        resp = self.client.get('/admin/api/permissions/definitions')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('areas', data)
        self.assertIn('pages_by_area', data)


if __name__ == '__main__':
    unittest.main()
