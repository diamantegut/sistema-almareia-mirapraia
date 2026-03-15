import json
import os
import requests
import logging
from datetime import datetime
from app.services.system_config_manager import get_data_path, get_config_value

# Configure logging
logger = logging.getLogger(__name__)

FISCAL_AI_HISTORY_FILE = get_data_path('fiscal_ai_history.json')

class FiscalAIAnalysisService:
    
    @staticmethod
    def _load_history():
        if not os.path.exists(FISCAL_AI_HISTORY_FILE):
            return []
        try:
            with open(FISCAL_AI_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading fiscal AI history: {e}")
            return []

    @staticmethod
    def _save_history(history):
        try:
            with open(FISCAL_AI_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving fiscal AI history: {e}")

    @staticmethod
    def analyze_error(entry_id, error_message, context_data=None):
        """
        Analyzes a fiscal error using Google Gemini API.
        """
        api_key = get_config_value('google_ai_api_key')
        
        if not api_key:
            return {
                "success": False, 
                "message": "Chave de API do Google AI não configurada. Por favor, adicione 'google_ai_api_key' às configurações do sistema."
            }

        # Construct Prompt
        prompt_text = (
            "Você é um especialista em suporte técnico de notas fiscais eletrônicas (NFC-e/NFe/NFS-e) no Brasil. "
            "Analise o seguinte erro de rejeição retornado pela SEFAZ ou API fiscal e forneça uma resposta direta e acionável.\n\n"
            f"Mensagem de Erro: {error_message}\n"
        )
        
        if context_data:
            # Summarize context to avoid token limits
            context_summary = json.dumps(context_data, ensure_ascii=False, default=str)
            if len(context_summary) > 2000:
                context_summary = context_summary[:2000] + "... (truncated)"
            prompt_text += f"Dados da Transação (Contexto): {context_summary}\n"

        prompt_text += (
            "\nResponda estritamente no seguinte formato JSON:\n"
            "{\n"
            "  \"cause\": \"Explicação curta da causa provável\",\n"
            "  \"action\": \"Passo a passo numerado para corrigir o problema\",\n"
            "  \"technical_note\": \"Detalhe técnico se relevante (opcional)\"\n"
            "}"
        )

        # Call Google API
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            headers = {'Content-Type': 'application/json'}
            payload = {
                "contents": [{
                    "parts": [{"text": prompt_text}]
                }]
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"Google AI API Error: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "message": f"Erro na API de IA: {response.status_code}"
                }
                
            result = response.json()
            try:
                # Extract text
                ai_text = result['candidates'][0]['content']['parts'][0]['text']
                # Clean markdown code blocks if present
                if "```json" in ai_text:
                    ai_text = ai_text.replace("```json", "").replace("```", "")
                
                analysis_json = json.loads(ai_text)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse AI response: {e}. Raw: {result}")
                # Fallback if JSON parsing fails
                analysis_json = {
                    "cause": "Erro na interpretação da resposta da IA",
                    "action": "Verifique os logs para detalhes brutos.",
                    "raw_response": str(result)
                }

            # Save to History
            analysis_record = {
                "id": f"AI_{datetime.now().strftime('%Y%m%d%H%M%S')}_{entry_id}",
                "entry_id": entry_id,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "error_message": error_message,
                "analysis": analysis_json
            }
            
            history = FiscalAIAnalysisService._load_history()
            history.append(analysis_record)
            FiscalAIAnalysisService._save_history(history)
            
            return {
                "success": True,
                "data": analysis_json
            }

        except Exception as e:
            logger.error(f"Exception calling Google AI: {e}")
            return {
                "success": False,
                "message": f"Erro de conexão com serviço de IA: {str(e)}"
            }

    @staticmethod
    def get_history(entry_id=None):
        history = FiscalAIAnalysisService._load_history()
        if entry_id:
            return [h for h in history if h.get('entry_id') == entry_id]
        return history
