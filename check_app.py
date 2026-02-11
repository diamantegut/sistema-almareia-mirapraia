
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from app import create_app
    app = create_app()
    print("App created successfully using factory!")
    
    endpoints_to_check = [
        'main.index',
        'reception.reception_rooms',
        'reception.reception_reservations',
        'reception.reception_waiting_list',
        'reception.reception_chat',
        'reception.reception_cashier',
        'reception.reception_reservations_cashier',
        'reception.reception_surveys'
    ]

    print(f"Checking {len(endpoints_to_check)} endpoints...")
    
    existing_endpoints = set(rule.endpoint for rule in app.url_map.iter_rules())
    
    all_found = True
    for endpoint in endpoints_to_check:
        if endpoint in existing_endpoints:
            print(f"[OK] Endpoint '{endpoint}' found.")
        else:
            print(f"[FAIL] Endpoint '{endpoint}' NOT found.")
            all_found = False
            
    if all_found:
        print("\nAll critical endpoints verified successfully.")
    else:
        print("\nSome critical endpoints are missing!")
        
except Exception as e:
    print(f"Failed to import app: {e}")
    import traceback
    traceback.print_exc()
