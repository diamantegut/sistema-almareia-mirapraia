
import pytest
import json
import os
from unittest.mock import MagicMock, patch
from whatsapp_chat_service import WhatsAppChatService
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user'] = 'admin_user'
            sess['role'] = 'admin'
        yield client

def test_delete_message_service():
    # Setup temporary files
    test_file = os.path.abspath("test_messages.json")
    with patch('whatsapp_chat_service.MESSAGES_FILE', test_file), \
         patch('whatsapp_chat_service.get_data_path', side_effect=lambda x: x):
        
        service = WhatsAppChatService()
        
        # Create dummy data
        data = {
            "conversations": {
                "12345": {
                    "messages": [
                        {"id": "msg1", "content": "Hello", "timestamp": "2023-01-01T10:00:00"},
                        {"id": "msg2", "content": "World", "timestamp": "2023-01-01T10:01:00"}
                    ]
                }
            }
        }
        service.save_data(data)
        
        # Test deletion
        with patch('whatsapp_chat_service.get_data_path', return_value='test_deleted_log.json'):
            result = service.delete_message("12345", "msg1", "tester")
            
            assert result == True
            
            # Verify message removed
            new_data = service.load_data()
            msgs = new_data['conversations']['12345']['messages']
            assert len(msgs) == 1
            assert msgs[0]['id'] == 'msg2'
            
            # Verify log created
            assert os.path.exists('test_deleted_log.json')
            with open('test_deleted_log.json', 'r') as f:
                logs = json.load(f)
                assert len(logs) == 1
                assert logs[0]['deleted_by'] == 'tester'
                assert logs[0]['message']['id'] == 'msg1'

        # Cleanup
        if os.path.exists('test_messages.json'):
            os.remove('test_messages.json')
        if os.path.exists('test_deleted_log.json'):
            os.remove('test_deleted_log.json')

def test_api_delete_message(client):
    with patch('app.chat_service') as mock_service:
        mock_service.delete_message.return_value = True
        
        response = client.post('/api/chat/delete_message', json={
            'phone': '12345',
            'message_id': 'msg1'
        })
        
        assert response.status_code == 200
        assert response.json['success'] == True
        mock_service.delete_message.assert_called_with('12345', 'msg1', user_deleted_by='admin_user')

def test_api_delete_message_fail(client):
    with patch('app.chat_service') as mock_service:
        mock_service.delete_message.return_value = False
        
        response = client.post('/api/chat/delete_message', json={
            'phone': '12345',
            'message_id': 'msg_invalid'
        })
        
        assert response.status_code == 404
        assert response.json['success'] == False
