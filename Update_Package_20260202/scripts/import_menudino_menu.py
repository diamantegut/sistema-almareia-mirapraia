import json
import os
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin


BASE_URL = "https://mirapraia.menudino.com/"


def ensure_deps():
    try:
        import requests  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        print("Instale as dependências antes de rodar: pip install requests beautifulsoup4")
        sys.exit(1)
    return requests, BeautifulSoup


def normalize(text):
    if not text:
        return ""
    text = text.replace("-", " ").replace("/", " ")
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    return " ".join(text.lower().split())


def fetch_html():
    requests, BeautifulSoup = ensure_deps()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = requests.get(BASE_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text, requests, BeautifulSoup


def parse_products(html, BeautifulSoup):
    soup = BeautifulSoup(html, "html.parser")
    products = []
    seen = set()

    # Try extracting from Next.js data
    # print all scripts for debugging
    for s in soup.find_all("script"):
        if s.get("id"):
            print(f"Script with id: {s.get('id')}", flush=True)
        # if s.string and "props" in s.string:
        #    print(f"Script with props: {s.string[:100]}", flush=True)

    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        print("Found __NEXT_DATA__", flush=True)
        try:
            data = json.loads(next_data.string)
            # Traverse JSON to find products
            # Usually in props -> pageProps -> initialState -> ... or similar
            # Let's just recursively search for objects that look like products
            
            # Helper to find products in nested dict/list
            def find_products_in_json(obj):
                found = []
                if isinstance(obj, dict):
                    # Check if this dict looks like a product
                    # Adjust keys based on Menudino API response structure
                    # Common keys: name, price, description, imageUrl
                    if "name" in obj and "price" in obj and ("id" in obj or "productId" in obj):
                        found.append(obj)
                    
                    for k, v in obj.items():
                        found.extend(find_products_in_json(v))
                elif isinstance(obj, list):
                    for item in obj:
                        found.extend(find_products_in_json(item))
                return found

            candidates = find_products_in_json(data)
            print(f"Found {len(candidates)} candidates in JSON", flush=True)
            
            for c in candidates:
                name = c.get("name")
                if not name: continue
                
                norm_name = normalize(name)
                if norm_name in seen: continue
                
                desc = c.get("description") or ""
                
                # Image URL might be partial or full
                img_url = c.get("imageUrl") or c.get("image") or c.get("coverImage")
                if img_url and not img_url.startswith("http"):
                    # Menudino often uses a CDN prefix or relative path
                    # We might need to guess or it might be full
                    if img_url.startswith("/"):
                         img_url = urljoin(BASE_URL, img_url)
                    else:
                         # Sometimes it's just a filename
                         img_url = f"https://images-menudino.s3.amazonaws.com/{img_url}" # Example guess, better to check valid url
                         # If we don't know the base, we might fail.
                         # But let's see what we get.
                         pass

                products.append({
                    "name": name,
                    "description": desc,
                    "image_url": img_url
                })
                seen.add(norm_name)
                
            if products:
                return products
                
        except Exception as e:
            print(f"Error parsing Next.js data: {e}", flush=True)

    # Fallback to HTML scraping
    print("Fallback to HTML scraping", flush=True)
    for img in soup.find_all("img"):
        img_url = img.get("src")
        if not img_url:
            continue
        
        print(f"Found img: {img_url}", flush=True)

        parent = img
        for _ in range(4):
            if not parent:
                break
            parent = parent.parent
        if not parent:
            continue

        name_el = None
        for tag in ["h1", "h2", "h3", "h4", "strong", "b", "span"]:
            cand = parent.find(tag)
            if cand and cand.get_text(strip=True):
                print(f"  Candidate name tag {tag}: {cand.get_text(strip=True)}", flush=True)
                name_el = cand
                break
        if not name_el:
            continue

        name = name_el.get_text(" ", strip=True)
        norm_name = normalize(name)
        print(f"  Name: {name} -> {norm_name}", flush=True)
        if not name or norm_name in seen:
            continue

        description = ""
        for cand in parent.find_all("p"):
            text = cand.get_text(" ", strip=True)
            if text and len(text) > 20:
                description = text
                break

        products.append(
            {
                "name": name,
                "description": description,
                "image_url": img_url,
            }
        )
        seen.add(norm_name)

    if products:
        return products

    for block in soup.find_all(["article", "div", "section"]):
        name_el = None
        for tag in ["h1", "h2", "h3", "h4"]:
            name_el = block.find(tag)
            if name_el:
                break
        if not name_el:
            continue
        name = name_el.get_text(" ", strip=True)
        if not name:
            continue
        desc_el = None
        for cand in block.find_all("p"):
            text = cand.get_text(" ", strip=True)
            if text and len(text) > 20:
                desc_el = cand
                break
        description = desc_el.get_text(" ", strip=True) if desc_el else ""
        img_el = block.find("img")
        img_url = img_el["src"] if img_el and img_el.get("src") else None
        products.append(
            {
                "name": name,
                "description": description,
                "image_url": img_url,
            }
        )

    return products


def best_match(norm_name, index):
    if not norm_name:
        return None
    if norm_name in index:
        return index[norm_name]
    best = None
    best_score = 0.0
    norm_tokens = set(norm_name.split())
    for key, item in index.items():
        if not key:
            continue
        if norm_name in key or key in norm_name:
            score = 0.9
        else:
            key_tokens = set(key.split())
            inter = norm_tokens & key_tokens
            if not inter:
                continue
            union = norm_tokens | key_tokens
            score = len(inter) / len(union)
        if score > best_score:
            best_score = score
            best = item
    if best_score >= 0.4:
        return best
    return None


def safe_slug(name):
    base = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    base = base.strip("_")
    return base or "produto"


def download_image(requests, url, dest_dir, product_name):
    full_url = urljoin(BASE_URL, url)
    resp = requests.get(full_url, stream=True, timeout=20)
    resp.raise_for_status()
    filename_hint = full_url.split("/")[-1]
    if "." in filename_hint:
        ext = "." + filename_hint.split(".")[-1].split("?")[0]
    else:
        content_type = resp.headers.get("content-type", "")
        if content_type.startswith("image/"):
            ext = "." + content_type.split("/")[-1]
        else:
            ext = ".jpg"
    slug = safe_slug(product_name)
    dest = dest_dir / f"{slug}{ext}"
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{slug}_{counter}{ext}"
        counter += 1
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)
    return dest.name


def main():
    print("Iniciando script...", flush=True)
    root = Path(__file__).resolve().parents[1]
    data_file = root / "data" / "menu_items.json"
    if not data_file.exists():
        print(f"Arquivo de produtos não encontrado: {data_file}")
        sys.exit(1)
    html, requests, BeautifulSoup = fetch_html()
    with open("debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Saved debug.html", flush=True)
    scraped = parse_products(html, BeautifulSoup)
    if not scraped:
        print("Nenhum produto foi identificado na página remota.")
        sys.exit(1)
    with open(data_file, "r", encoding="utf-8") as f:
        items = json.load(f)
    by_norm = {normalize(i.get("name", "")): i for i in items}
    upload_dir = root / "static" / "uploads" / "products"
    os.makedirs(upload_dir, exist_ok=True)
    updated_desc = 0
    updated_img = 0
    unmatched = []
    for sp in scraped:
        n = normalize(sp["name"])
        item = best_match(n, by_norm)
        if not item:
            unmatched.append(sp["name"])
            continue
        if sp["description"]:
            item["description"] = sp["description"]
            updated_desc += 1
        if sp["image_url"]:
            try:
                filename = download_image(requests, sp["image_url"], upload_dir, item.get("name", "produto"))
                item["image_url"] = f"/static/uploads/products/{filename}"
                updated_img += 1
            except Exception as e:
                print(f"Falha ao baixar imagem para {item.get('name', '')}: {e}")
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=4, ensure_ascii=False)
    print(f"Descrições atualizadas em {updated_desc} itens.")
    print(f"Imagens atualizadas em {updated_img} itens.")
    if unmatched:
        print("Sem correspondência clara para:")
        for name in unmatched:
            print(f"- {name}")


if __name__ == "__main__":
    main()
