import requests

url = "https://mirapraia.menudino.com/_next/static/chunks/app/page-d0c446a4147a48dd.js"
resp = requests.get(url)
with open("page.js", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Downloaded page.js", flush=True)
