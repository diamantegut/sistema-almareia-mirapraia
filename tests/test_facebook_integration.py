import pytest

pytest.skip("Integração de chat WhatsApp interno removida; testes desativados.", allow_module_level=True)

from unittest.mock import MagicMock, patch
from app import app
from whatsapp_chat_service import WhatsAppChatService
from facebook_service import FacebookService

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user'] = 'test_user'
        yield client

@pytest.fixture
def mock_fb_service():
    with patch('facebook_service.FacebookService') as MockService:
        instance = MockService.return_value
        instance.send_message.return_value = {"recipient_id": "123", "message_id": "mid.456"}
        yield instance

@pytest.fixture
def mock_wa_service():
    # Patching where it is used in app.py because it is likely imported at top level
    with patch('app.WhatsAppService') as MockService:
        instance = MockService.return_value
        instance.send_message.return_value = {"messages": [{"id": "wamid.789"}]}
        yield instance

@pytest.fixture
def mock_chat_service():
    with patch('app.chat_service') as mock:
        yield mock

def test_api_chat_send_facebook(client, mock_fb_service, mock_chat_service):
    # Mock environment variables
    with patch.dict('os.environ', {'FACEBOOK_PAGE_ACCESS_TOKEN': 'fake_token'}):
        response = client.post('/api/chat/send', json={
            'phone': '123456789',
            'message': 'Hello Facebook',
            'channel': 'facebook'
        })
        
        assert response.status_code == 200
        assert response.json['success'] == True
        
        # Verify FacebookService was used
        mock_fb_service.send_message.assert_called_with('123456789', 'Hello Facebook')
        
        # Verify message was added to chat service with correct channel
        mock_chat_service.add_message.assert_called()
        args, kwargs = mock_chat_service.add_message.call_args
        assert args[0] == '123456789' # phone
        assert args[1]['content'] == 'Hello Facebook'
        assert kwargs['channel'] == 'facebook'

def test_api_chat_send_whatsapp_default(client, mock_wa_service, mock_chat_service):
    # Mock settings for WhatsApp
    with patch('waiting_list_service.get_settings', return_value={'whatsapp_api_token': 't', 'whatsapp_phone_id': 'p'}):
        response = client.post('/api/chat/send', json={
            'phone': '987654321',
            'message': 'Hello WhatsApp'
            # No channel specified, should default to whatsapp
        })
        
        assert response.status_code == 200
        
        # Verify WhatsAppService was used (not Facebook)
        mock_wa_service.send_message.assert_called_with('987654321', 'Hello WhatsApp')
        
        # Verify message added with channel='whatsapp'
        mock_chat_service.add_message.assert_called()
        args, kwargs = mock_chat_service.add_message.call_args
        assert kwargs['channel'] == 'whatsapp'

def test_chat_service_add_message_channel():
    # Test the actual ChatService logic for channel persistence
    # We'll use a temporary file for this test
    test_file = 'tests/temp_whatsapp_messages.json'
    import json
    import os
    
    if os.path.exists(test_file):
        os.remove(test_file)
        
    try:
        with patch('whatsapp_chat_service.MESSAGES_FILE', test_file):
            service = WhatsAppChatService()
            
            # Add Facebook message
            service.add_message('111', {'content': 'fb msg'}, channel='facebook')
            
            # Load and verify
            with open(test_file, 'r') as f:
                data = json.load(f)
                assert data['conversations']['111']['channel'] == 'facebook'
                
            # Add WhatsApp message to new number
            service.add_message('222', {'content': 'wa msg'}, channel='whatsapp')
            
            with open(test_file, 'r') as f:
                data = json.load(f)
                assert data['conversations']['222']['channel'] == 'whatsapp'
                
            # Update existing channel (e.g. if we want to switch or ensure it stays)
            # If we send a message to '111' with channel='facebook', it should stay facebook
            service.add_message('111', {'content': 'fb msg 2'}, channel='facebook')
            with open(test_file, 'r') as f:
                data = json.load(f)
                assert data['conversations']['111']['channel'] == 'facebook'
                
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
