import requests
from bs4 import BeautifulSoup
import json
import os

URL = "https://mirapraia.menudino.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

print(f"Fetching {URL}...", flush=True)
resp = requests.get(URL, headers=HEADERS)
print(f"Status: {resp.status_code}", flush=True)

with open("debug_menudino.html", "w", encoding="utf-8") as f:
    f.write(resp.text)

print("Saved to debug_menudino.html", flush=True)

# Try to find __NEXT_DATA__
soup = BeautifulSoup(resp.text, "html.parser")
next_data = soup.find("script", {"id": "__NEXT_DATA__"})
if next_data:
    print("Found __NEXT_DATA__!", flush=True)
    try:
        data = json.loads(next_data.string)
        with open("debug_menudino_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print("Saved data to debug_menudino_data.json", flush=True)
    except Exception as e:
        print(f"Error parsing JSON: {e}", flush=True)
else:
    print("No __NEXT_DATA__ found.", flush=True)

# Look for other scripts that might contain data
scripts = soup.find_all("script")
for i, s in enumerate(scripts):
    if s.string and "products" in s.string:
        print(f"Script {i} contains 'products'", flush=True)
