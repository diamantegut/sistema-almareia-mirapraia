import unittest
import json
import os
import sys
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.fiscal_ai_service import FiscalAIAnalysisService

class TestFiscalAIAnalysis(unittest.TestCase):
    
    @patch('app.services.fiscal_ai_service.get_config_value')
    @patch('app.services.fiscal_ai_service.requests.post')
    def test_analyze_error_success(self, mock_post, mock_config):
        # Setup Mocks
        mock_config.return_value = "TEST_API_KEY"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"cause": "CNPJ inválido", "action": "Verifique o cadastro", "technical_note": "Erro 234"}'
                    }]
                }
            }]
        }
        mock_post.return_value = mock_response
        
        # Test
        result = FiscalAIAnalysisService.analyze_error(
            entry_id="TEST_ENTRY",
            error_message="Rejeição: CNPJ Emitente Inválido",
            context_data={"cnpj": "00000000000000"}
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['data']['cause'], "CNPJ inválido")
        
        # Verify History Saved
        history = FiscalAIAnalysisService.get_history("TEST_ENTRY")
        self.assertTrue(len(history) > 0)
        self.assertEqual(history[-1]['entry_id'], "TEST_ENTRY")

    @patch('app.services.fiscal_ai_service.get_config_value')
    def test_analyze_error_no_key(self, mock_config):
        mock_config.return_value = None
        
        result = FiscalAIAnalysisService.analyze_error("TEST", "Error")
        self.assertFalse(result['success'])
        self.assertIn("Chave de API", result['message'])

if __name__ == '__main__':
    unittest.main()
