import requests
import json

BASE_URL = "https://mirapraia.menudino.com"
SLUG = "mirapraia"

endpoints = [
    f"{BASE_URL}/api/products",
    f"{BASE_URL}/api/cardapio",
    f"https://app.menudino.com/api/cardapio/{SLUG}",
    f"https://app.menudino.com/api/restaurant/{SLUG}/menu",
    f"https://api.menudino.com/v1/restaurants/{SLUG}/menu",
    f"https://delivery-app.menudino.com/api/v1/{SLUG}/products",
    # Common Next.js API routes
    f"{BASE_URL}/api/hello",
    f"{BASE_URL}/_next/data/index.json",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE_URL,
}

print(f"Testing endpoints for {SLUG}...", flush=True)

for url in endpoints:
    try:
        print(f"Trying {url}...", flush=True)
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"  Status: {resp.status_code}", flush=True)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "")
            print(f"  Content-Type: {ct}", flush=True)
            print(f"  Body: {resp.text[:200]}", flush=True)
            if "json" in ct or (resp.text.startswith("{") or resp.text.startswith("[")):
                try:
                    data = resp.json()
                    keys = list(data.keys())[:5]
                    print(f"  SUCCESS! Keys: {keys}", flush=True)
                    # Save a sample
                    with open("api_sample.json", "w") as f:
                        json.dump(data, f, indent=2)
                    break
                except:
                    print("  Not valid JSON", flush=True)
    except Exception as e:
        print(f"  Error: {e}", flush=True)
