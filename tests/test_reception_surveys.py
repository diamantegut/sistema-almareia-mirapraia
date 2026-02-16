import unittest
import os
import sys
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from app import app as flask_app
from app.models.database import db
from app.models.models import SatisfactionSurvey


class TestReceptionSurveys(unittest.TestCase):
    def setUp(self):
        flask_app.config['TESTING'] = True
        self.client = flask_app.test_client()
        with flask_app.app_context():
            db.create_all()
            # Clean surveys to start fresh
            for s in SatisfactionSurvey.query.all():
                db.session.delete(s)
            db.session.commit()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['permissions'] = ['admin', 'recepcao']

    def test_surveys_page_renders(self):
        self.login_admin()
        resp = self.client.get('/reception/surveys', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Pesquisas cadastradas', resp.data)

    def test_create_and_delete_survey(self):
        self.login_admin()
        # Create
        resp = self.client.post('/reception/surveys', data={
            'action': 'create',
            'title': 'Pesquisa Hotel',
            'audience': 'hotel',
            'is_active': 'on'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Pesquisa criada com sucesso', resp.data)
        # Verify render shows the title
        resp2 = self.client.get('/reception/surveys', follow_redirects=True)
        self.assertIn(b'Pesquisa Hotel', resp2.data)
        # Find id
        with flask_app.app_context():
            s = SatisfactionSurvey.query.filter_by(title='Pesquisa Hotel').first()
            self.assertIsNotNone(s)
            survey_id = s.id
        # Delete
        resp3 = self.client.post('/reception/surveys', data={
            'action': 'delete',
            'survey_id': survey_id
        }, follow_redirects=True)
        self.assertEqual(resp3.status_code, 200)
        self.assertIn(b'Pesquisa removida', resp3.data)
        # Verify gone
        resp4 = self.client.get('/reception/surveys', follow_redirects=True)
        self.assertNotIn(b'Pesquisa Hotel', resp4.data)
