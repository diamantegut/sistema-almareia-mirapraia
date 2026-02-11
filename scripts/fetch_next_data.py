import requests
import json

BUILD_ID = "hdktznwqMGE7xnpUYcbRK"
BASE_URL = "https://mirapraia.menudino.com"

url = f"{BASE_URL}/_next/data/{BUILD_ID}/index.json"

print(f"Fetching {url}...", flush=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "x-nextjs-data": "1",
}

try:
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}", flush=True)
    print(f"Content-Type: {resp.headers.get('Content-Type')}", flush=True)
    
    if resp.status_code == 200:
        data = resp.json()
        print("Success! Found JSON data.", flush=True)
        
        # Save it
        with open("next_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        # Check for products
        page_props = data.get("pageProps", {})
        print(f"Keys in pageProps: {list(page_props.keys())}", flush=True)
        
        # Look for deeper keys
        if "initialState" in page_props:
             print(f"Keys in initialState: {list(page_props['initialState'].keys())}", flush=True)
        
    else:
        print(f"Body: {resp.text[:200]}", flush=True)

except Exception as e:
    print(f"Error: {e}", flush=True)
