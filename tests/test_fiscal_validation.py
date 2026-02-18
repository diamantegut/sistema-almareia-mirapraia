
import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.services.fiscal_service import emit_invoice

class TestFiscalValidation(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        
    def tearDown(self):
        self.app_context.pop()

    @patch('app.services.fiscal_service.get_access_token')
    @patch('requests.post')
    def test_emit_invoice_validation_and_split(self, mock_post, mock_get_token):
        # Mock Auth
        mock_get_token.return_value = "fake_token"
        
        # Mock Success Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': '123', 'status': 'autorizado'}
        mock_post.return_value = mock_response
        
        # Settings
        settings = {
            'provider': 'nuvem_fiscal',
            'client_id': 'abc',
            'client_secret': '123',
            'cnpj_emitente': '12345678901234',
            'environment': 'homologation'
        }
        
        # Transaction
        transaction = {
            'id': 'test_trans_1',
            'amount': 20.0,
            'payment_method': 'Dinheiro'
        }
        
        # Items with Qty > 1 to test split
        items = [
            {
                'id': 'item1',
                'name': 'Coca Cola',
                'price': 5.0,
                'qty': 2.0, # Should generate 2 items
                'ncm': '22021000',
                'cest': '0300700',
                'cfop': '5102',
                'origin': 0
            },
            {
                'id': 'item2',
                'name': 'Coxinha',
                'price': 10.0,
                'qty': 1.0, # Should generate 1 item
                'ncm': '19023000',
                'cfop': '5102',
                'origin': 0
            }
        ]
        
        # Execute
        result = emit_invoice(transaction, settings, items)
        
        self.assertTrue(result['success'])
        
        # Verify Payload sent to API
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        # Check Items Count (2 cokes + 1 coxinha = 3 items)
        nfe_items = payload['infNFe']['det']
        self.assertEqual(len(nfe_items), 3)
        
        # Verify Items Content
        # Item 1: Coca Cola
        self.assertEqual(nfe_items[0]['prod']['xProd'], 'Coca Cola')
        self.assertEqual(nfe_items[0]['prod']['qCom'], 1.0)
        self.assertEqual(nfe_items[0]['prod']['vProd'], 5.0)
        
        # Item 2: Coca Cola (Split)
        self.assertEqual(nfe_items[1]['prod']['xProd'], 'Coca Cola')
        self.assertEqual(nfe_items[1]['prod']['qCom'], 1.0)
        
        # Item 3: Coxinha
        self.assertEqual(nfe_items[2]['prod']['xProd'], 'Coxinha')
        self.assertEqual(nfe_items[2]['prod']['qCom'], 1.0)
        
        # Verify Fiscal Fields
        self.assertEqual(nfe_items[0]['prod']['NCM'], '22021000')
        self.assertEqual(nfe_items[0]['prod']['CEST'], '0300700')
        self.assertEqual(nfe_items[0]['prod']['CFOP'], '5102')

        # Verify Sandbox Environment configuration
        self.assertEqual(args[0], "https://api.sandbox.nuvemfiscal.com.br/nfce")
        self.assertEqual(payload['ambiente'], 'homologacao')
        self.assertEqual(payload['infNFe']['ide']['tpAmb'], 2)

    @patch('app.services.fiscal_service.get_access_token')
    def test_emit_invoice_missing_data_fallback(self, mock_get_token):
        mock_get_token.return_value = "fake_token"
        
        # Items missing NCM
        items = [
            {
                'id': 'item1',
                'name': 'Bolo',
                'price': 5.0,
                'qty': 1.0
            }
        ]
        
        settings = {
            'provider': 'nuvem_fiscal',
            'client_id': 'abc',
            'client_secret': '123',
            'cnpj_emitente': '12345678901234'
        }
        
        # We need to mock requests.post to avoid error, but we want to check payload before
        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {}
            
            emit_invoice({'id':'t1', 'amount':5.0}, settings, items)
            
            args, kwargs = mock_post.call_args
            payload = kwargs['json']
            item = payload['infNFe']['det'][0]
            
            # Check Fallback NCM
            self.assertEqual(item['prod']['NCM'], '21069090')

if __name__ == '__main__':
    unittest.main()
