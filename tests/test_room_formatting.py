
import pytest
from app import format_room_number, app

def test_format_room_number():
    assert format_room_number(1) == "01"
    assert format_room_number("1") == "01"
    assert format_room_number(10) == "10"
    assert format_room_number("10") == "10"
    assert format_room_number("Room 1") == "Room 1"
    assert format_room_number(None) == ""

def test_template_filter():
    with app.app_context():
        # Check if filter is registered
        assert 'format_room' in app.jinja_env.filters
        assert app.jinja_env.filters['format_room'](1) == "01"
