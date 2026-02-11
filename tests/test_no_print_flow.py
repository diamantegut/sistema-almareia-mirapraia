
import requests
import json
import os
import time
import sys
from datetime import datetime

raw_port = (os.environ.get('APP_PORT') or os.environ.get('PORT') or '').strip()
server_port = 5001
if raw_port:
    try:
        server_port = int(raw_port)
    except Exception:
        server_port = 5001
BASE_URL = f"http://localhost:{server_port}"
# Logs are in logs/actions/YYYY-MM-DD.json
LOGS_DIR = os.path.join(os.getcwd(), 'logs', 'actions')
MENU_ITEMS_FILE = os.path.join(os.getcwd(), 'data', 'menu_items.json')
TABLE_ID = '99'

def login(session):
    print("Logging in...")
    resp = session.post(f"{BASE_URL}/login", data={'username': 'Angelo', 'password': '2006'})
    if resp.status_code != 200 and resp.status_code != 302:
        print(f"Login failed: {resp.status_code}")
        sys.exit(1)
    print("Logged in successfully.")

def open_table(session):
    print(f"Opening table {TABLE_ID}...")
    payload = {
        'action': 'open_table',
        'num_adults': '1',
        'customer_type': 'externo',
        'waiter': 'Angelo'
    }
    resp = session.post(f"{BASE_URL}/restaurant/table/{TABLE_ID}", data=payload)
    # 200 or 302 is fine
    print(f"Open table response: {resp.status_code}")

def get_product():
    with open(MENU_ITEMS_FILE, 'r', encoding='utf-8') as f:
        items = json.load(f)
    # Find a product that is active
    for item in items:
        if item.get('active', True):
            return item
    return None

def update_product_should_print(product_id, should_print):
    print(f"Updating product {product_id} should_print to {should_print}...")
    with open(MENU_ITEMS_FILE, 'r', encoding='utf-8') as f:
        items = json.load(f)
    
    for item in items:
        if item['id'] == product_id:
            item['should_print'] = should_print
            break
            
    with open(MENU_ITEMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=4, ensure_ascii=False)
    print("Product updated locally.")

def place_order(session, product_name, observations=None):
    if observations is None:
        observations = []
        
    print(f"Placing order for {product_name} with obs={observations}...")
    item_data = {
        'product': product_name,
        'qty': 1,
        'complements': [],
        'observations': observations,
        'flavor_name': None
    }
    items_json = json.dumps([item_data])
    
    payload = {
        'action': 'add_batch_items',
        'items_json': items_json,
        'waiter': 'Angelo'
    }
    
    resp = session.post(f"{BASE_URL}/restaurant/table/{TABLE_ID}", data=payload)
    if resp.status_code == 200 or resp.status_code == 302:
        print("Order placed successfully.")
    else:
        print(f"Failed to place order: {resp.status_code}")

def check_audit_log(product_name, check_text="Venda Sem Impressão"):
    print("Checking audit log...")
    time.sleep(1) # Wait for write
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(LOGS_DIR, f"{today_str}.json")
    
    if not os.path.exists(log_file):
        print(f"Log file not found: {log_file}")
        return False
        
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except Exception as e:
        print(f"Failed to load logs: {e}")
        return False
        
    # Look for latest
    logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    for log in logs[:20]:
        if log['action'] == check_text and product_name in log['details']:
            print(f"FOUND LOG: {log['details']}")
            return True
            
    print("Log entry NOT found.")
    return False

def main():
    s = requests.Session()
    login(s)
    open_table(s)
    
    product = get_product()
    if not product:
        print("No active product found.")
        return
        
    print(f"Selected product: {product['name']} (ID: {product['id']})")
    original_should_print = product.get('should_print', True)
    
    try:
        # TEST 1: Product Config Flow
        print("\n--- TEST 1: Product Config Flow ---")
        update_product_should_print(product['id'], False)
        # Wait a bit for server (if it reloads file, but here it reads per request usually)
        time.sleep(0.5) 
        
        place_order(s, product['name'])
        if check_audit_log(product['name']):
            print("SUCCESS: Product Config Flow verified.")
        else:
            print("FAILURE: Product Config Flow failed.")
            
        # Revert for Test 2
        update_product_should_print(product['id'], True)
        time.sleep(0.5)
        
        # TEST 2: Observation Flow
        print("\n--- TEST 2: Observation Flow ---")
        # should_print is True now.
        # Add "Não Imprimir" observation
        place_order(s, product['name'], observations=["Não Imprimir"])
        if check_audit_log(product['name']):
            print("SUCCESS: Observation Flow verified.")
        else:
            print("FAILURE: Observation Flow failed.")

    finally:
        # Final Revert
        update_product_should_print(product['id'], original_should_print)
        print("\nState reverted.")

if __name__ == "__main__":
    main()
