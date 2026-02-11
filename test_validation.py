
import os
import sys
import json
import html

# Setup path
sys.path.append(os.getcwd())

from app.services.user_service import load_users

def sanitize_input(text):
    """Sanitizes input against XSS (Copy from validators.py)."""
    if not text: return ""
    return html.escape(str(text))

def test_validation_logic():
    print("--- Testing Validation Logic ---")
    users = load_users()
    print(f"Loaded {len(users)} users.")
    
    # Pick a real user from keys
    if not users:
        print("No users loaded.")
        return

    real_user_key = next(iter(users.keys()))
    print(f"Testing with user key: '{real_user_key}'")
    
    # Simulate form input
    form_input = real_user_key 
    staff_name = sanitize_input(form_input)
    print(f"Sanitized input: '{staff_name}'")
    
    # Logic from route
    valid_user = False
    for u_id, u_data in users.items():
        # Debug print
        # print(f"Checking against: ID='{u_id}', Username='{u_data.get('username')}'")
        
        if u_data.get('username') == staff_name or u_id == staff_name:
            valid_user = True
            print(f"MATCH FOUND! ID='{u_id}'")
            break
            
    if valid_user:
        print("VALIDATION SUCCESS")
    else:
        print("VALIDATION FAILED")

if __name__ == "__main__":
    test_validation_logic()
