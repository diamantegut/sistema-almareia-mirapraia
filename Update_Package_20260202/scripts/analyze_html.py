import re
import json

def extract_info():
    print("Reading debug_menudino.html...", flush=True)
    with open("debug_menudino.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Extract all URLs
    print("Extracting URLs...", flush=True)
    urls = re.findall(r'https?://[^\s"\'<>]+', html)
    image_urls = [u for u in urls if u.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    
    print(f"Found {len(urls)} URLs total.", flush=True)
    print(f"Found {len(image_urls)} image URLs.", flush=True)
    
    if image_urls:
        print("Sample image URLs:", flush=True)
        for url in image_urls[:10]:
            print(f"  {url}", flush=True)

    # 2. Extract Next.js stream data
    print("\nExtracting Next.js stream data...", flush=True)
    # Pattern: self.__next_f.push([1,"..."])
    
    regex = r'self\.__next_f\.push\((.*?)\)'
    matches = re.findall(regex, html)
    
    stream_data = []
    
    for match in matches:
        try:
            data = json.loads(match)
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], str):
                # The second element is the chunk string
                chunk = data[1]
                stream_data.append(chunk)
        except:
            pass

    print(f"\nFound {len(stream_data)} stream chunks.", flush=True)
    
    with open("stream_chunks.txt", "w", encoding="utf-8") as f:
        for chunk in stream_data:
            f.write(chunk + "\n" + "-"*80 + "\n")
            
            # Try to find product patterns in this chunk
            if "price" in chunk or "R$" in chunk or "name" in chunk:
                # Basic heuristic check
                pass

    # Extract all text that looks like a JSON object from chunks
    # Chunks often look like: "id:{\"key\":\"value\"}"
    # We want to find objects that contain product info.
    
    all_chunks_text = "\n".join(stream_data)
    
    # Regex for potential product objects: {"id":..., "name":"...", ...}
    # It's hard to regex generic JSON.
    # Let's look for specific keys.
    
    # Check for "items" array which usually holds products
    # "items":[...]
    
    items_regex = r'"items":\s*\[(.*?)\]'
    items_matches = re.findall(items_regex, all_chunks_text)
    
    print(f"Found {len(items_matches)} 'items' arrays.", flush=True)
    
    for i, m in enumerate(items_matches):
        print(f"Items match {i} length: {len(m)}", flush=True)
        # print(f"  Content: {m[:200]}...", flush=True)
        
    # Check for "products"
    products_regex = r'"products":\s*\[(.*?)\]'
    products_matches = re.findall(products_regex, all_chunks_text)
    print(f"Found {len(products_matches)} 'products' arrays.", flush=True)
    
    # Check for categories
    categories_regex = r'"categories":\s*\[(.*?)\]'
    categories_matches = re.findall(categories_regex, all_chunks_text)
    print(f"Found {len(categories_matches)} 'categories' arrays.", flush=True)

    # Let's also look for image URLs specifically in the chunks
    chunk_imgs = re.findall(r'https?://[^\s"\'\\]+\.(?:jpg|jpeg|png|webp)', all_chunks_text)
    # Clean slashes
    chunk_imgs = [u.replace('\\', '') for u in chunk_imgs]
    print(f"Found {len(chunk_imgs)} images in chunks.", flush=True)
    if chunk_imgs:
        print("Sample chunk images:", flush=True)
        for url in chunk_imgs[:10]:
            print(f"  {url}", flush=True)


if __name__ == "__main__":
    extract_info()
