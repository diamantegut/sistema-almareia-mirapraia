with open("debug_menudino.html", "r", encoding="utf-8") as f:
    html = f.read()

target = "Restaurante Mirapraia"
idx = html.find(target)

if idx != -1:
    print(f"Found '{target}' at index {idx}", flush=True)
    # Print 2000 chars before and after to see the context
    start = max(0, idx - 2000)
    end = min(len(html), idx + 10000) # Print more after to hopefully catch products
    
    snippet = html[start:end]
    
    with open("snippet.txt", "w", encoding="utf-8") as f:
        f.write(snippet)
        
    print("Saved snippet.txt", flush=True)
else:
    print("Target not found", flush=True)
