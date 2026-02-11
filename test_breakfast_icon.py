
import pytest
from app import create_app
from app.services.data_service import load_table_orders, save_table_orders
from unittest.mock import patch, MagicMock
from datetime import datetime

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            # Setup: Ensure Table 50 is empty
            save_table_orders({})
        yield client
        # Cleanup
        save_table_orders({})

def test_breakfast_icon_active(client):
    """Test that opening a table between 07:00 and 10:00 activates the breakfast icon"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Mock time to 08:00
    mock_dt = datetime(2025, 1, 1, 8, 0, 0)
    
    with patch('app.blueprints.restaurant.routes.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        # Open Table 50
        client.post('/restaurant/table/50', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante',
            'customer_name': 'Test Breakfast'
        }, follow_redirects=True)
        
    # Check if flag is set
    orders = load_table_orders()
    assert '50' in orders
    assert orders['50'].get('is_breakfast') is True

def test_breakfast_icon_inactive_before_7(client):
    """Test that opening a table before 07:00 does NOT activate the icon"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Mock time to 06:59
    mock_dt = datetime(2025, 1, 1, 6, 59, 59)
    
    with patch('app.blueprints.restaurant.routes.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        
        client.post('/restaurant/table/50', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante'
        }, follow_redirects=True)
        
    orders = load_table_orders()
    assert orders['50'].get('is_breakfast') is False

def test_breakfast_icon_inactive_after_10(client):
    """Test that opening a table after 10:00 does NOT activate the icon"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # Mock time to 10:00:01 (Hour is 10)
    mock_dt = datetime(2025, 1, 1, 10, 0, 1)
    
    with patch('app.blueprints.restaurant.routes.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        
        client.post('/restaurant/table/50', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante'
        }, follow_redirects=True)
        
    orders = load_table_orders()
    assert orders['50'].get('is_breakfast') is False

def test_breakfast_icon_persistence(client):
    """Test that icon persists even if checked later outside hours"""
    with client.session_transaction() as sess:
        sess['user'] = 'admin'
        sess['role'] = 'admin'

    # 1. Open table at 08:00
    mock_dt_open = datetime(2025, 1, 1, 8, 0, 0)
    with patch('app.blueprints.restaurant.routes.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt_open
        client.post('/restaurant/table/50', data={
            'action': 'open_table',
            'num_adults': '2',
            'customer_type': 'passante'
        }, follow_redirects=True)
    
    orders = load_table_orders()
    assert orders['50']['is_breakfast'] is True
    
    # 2. Access table later at 11:00 (outside breakfast hours)
    # The flag should still be there because it's stored in the order
    mock_dt_later = datetime(2025, 1, 1, 11, 0, 0)
    with patch('app.blueprints.restaurant.routes.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt_later
        client.get('/restaurant/table/50')
        
    orders = load_table_orders()
    assert orders['50']['is_breakfast'] is True
