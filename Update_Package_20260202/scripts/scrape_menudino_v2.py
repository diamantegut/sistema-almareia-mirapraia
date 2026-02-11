import requests
import re
import json
import os

def extract_stream_data(html):
    # Regex to find self.__next_f.push(...)
    # The content inside push is often a list like [1, "string"]
    regex = r'self\.__next_f\.push\((.*?)\)'
    matches = re.findall(regex, html)
    
    combined_data = ""
    chunks = []
    
    for match in matches:
        try:
            # The match might be a JSON string or a JS array structure
            # self.__next_f.push([1,"..."])
            # We want the string part.
            # Using json.loads might fail if it's not valid JSON yet (e.g. JS syntax)
            # But usually it is valid JSON inside the push
            data = json.loads(match)
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], str):
                chunk = data[1]
                chunks.append(chunk)
                combined_data += chunk
        except Exception as e:
            # print(f"Error parsing match: {e}")
            pass
            
    return chunks, combined_data

def find_products(text):
    # Look for patterns like "id":1000 or "id":"1000"
    # Also look for "price":... "name":...
    
    # Let's try to find a list of objects that look like products
    # This is heuristic.
    
    # Pattern for product ID and name
    # "id":1000,"name":"..."
    # "id":1013,"name":"..."
    
    # We can search for the IDs we know exist in the photos
    known_ids = [1000, 1013, 200, 202]
    found_products = []
    
    for pid in known_ids:
        # Search for "id":pid or "id":"pid"
        pattern1 = f'"id":{pid}'
        pattern2 = f'"id":"{pid}"'
        
        if pattern1 in text or pattern2 in text:
            print(f"Found known ID {pid} in text!")
            # Try to extract context
            idx = text.find(pattern1)
            if idx == -1: idx = text.find(pattern2)
            
            start = max(0, idx - 100)
            end = min(len(text), idx + 500)
            print(f"Context for {pid}: {text[start:end]}")

    return found_products

def main():
    url = "https://mirapraia.menudino.com"
    print(f"Fetching {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch page: {response.status_code}")
        return

    html = response.text
    print(f"Page size: {len(html)} bytes")
    
    # Save for debugging
    with open("latest_menudino.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    chunks, combined = extract_stream_data(html)
    print(f"Extracted {len(chunks)} chunks. Combined size: {len(combined)} bytes")
    
    with open("latest_stream_chunks.txt", "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            f.write(f"Chunk {i}:\n{c}\n\n")
            
    find_products(combined)
    
    # Also search in the raw HTML just in case
    print("Searching in raw HTML...")
    find_products(html)

if __name__ == "__main__":
    main()
