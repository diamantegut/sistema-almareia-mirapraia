import requests
import json

BASE_URL = "https://mirapraia.menudino.com"
SLUG = "mirapraia"
UUID = "c5fa7de8-2faf-11ee-9964-0022483864db"
CODE = "16598"

endpoints = [
    f"https://app.menudino.com/api/cardapio/{SLUG}", # returned 200 "not found"
    f"https://app.menudino.com/api/cardapio/{UUID}",
    f"https://app.menudino.com/api/restaurant/{SLUG}/menu",
    f"https://app.menudino.com/api/restaurant/{UUID}/menu",
    f"https://delivery-app.menudino.com/api/v1/restaurant/{UUID}",
    f"https://delivery-app.menudino.com/api/v1/restaurant/{CODE}",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE_URL,
}

print(f"Testing endpoints for {SLUG} / {UUID}...", flush=True)

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
                    # Check if it has categories or products
                    if isinstance(data, list) or "categories" in data or "products" in data or "menu" in data:
                        print(f"  SUCCESS! Found potential menu data.", flush=True)
                        with open("api_menu_data.json", "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        break
                except:
                    print("  Not valid JSON", flush=True)
    except Exception as e:
        print(f"  Error: {e}", flush=True)
