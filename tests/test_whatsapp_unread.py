import pytest

pytest.skip("Integração de chat WhatsApp interno removida; testes desativados.", allow_module_level=True)

from unittest.mock import MagicMock, patch
from whatsapp_chat_service import WhatsAppChatService

def test_get_unread_count():
    # Mock data
    mock_data = {
        'conversations': {
            '123456789': {
                'messages': [
                    {'type': 'received', 'timestamp': '2023-01-01T10:00:00'}, # Old
                    {'type': 'received', 'timestamp': '2023-01-01T10:05:00'}  # Old
                ]
            },
            '987654321': {
                'messages': [
                    {'type': 'received', 'timestamp': '2023-01-01T10:00:00'}
                ]
            }
        }
    }
    
    with patch.object(WhatsAppChatService, 'load_data', return_value=mock_data):
        service = WhatsAppChatService()
        
        # 1. No last check time -> count all received
        # But actually logic usually counts messages AFTER a certain time if provided?
        # Let's check implementation. 
        # Implementation: count messages where timestamp > last_check_time
        
        # Case A: last_check_time is None -> Return 0 (or all? Implementation usually returns 0 if no reference)
        # Actually my implementation returns 0 if no last_check_time provided?
        # Let's check the code or just test behavior.
        
        count = service.get_unread_count('2023-01-01T10:01:00')
        # Should count '123456789' msg 2 (10:05)
        # '987654321' msg (10:00) is older
        assert count == 1
        
        count = service.get_unread_count('2023-01-01T09:00:00')
        assert count == 3
        
        count = service.get_unread_count('2023-01-01T11:00:00')
        assert count == 0

def test_api_unread_count_endpoint(client):
    # We need to mock the service used by the app
    with patch('app.chat_service') as mock_service:
        mock_service.get_unread_count.return_value = 5
        
        # Test with last_check param
        response = client.get('/api/chat/unread_count?last_check=2023-01-01T10:00:00')
        assert response.status_code == 200
        assert response.json['count'] == 5
        
        # Verify service called with correct param
        mock_service.get_unread_count.assert_called_with('2023-01-01T10:00:00')

@pytest.fixture
def client():
    from app import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user'] = 'test_user'
        yield client
