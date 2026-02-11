import re
import json

with open("debug_menudino.html", "r", encoding="utf-8") as f:
    html = f.read()

# Pattern to find self.__next_f.push calls
# They look like: self.__next_f.push([1,"..."])
# The string part might be complex, so we might need to be careful.
# But usually it's a JSON array where the second element is the string data.

regex = r'self\.__next_f\.push\((.*?)\)'
matches = re.findall(regex, html)

print(f"Found {len(matches)} push calls.", flush=True)

full_data = []

for i, match in enumerate(matches):
    try:
        # The match is the arguments to push(), usually a list like [1, "data"]
        # We can try to parse it as JSON, but sometimes it's not valid JSON directly if it has undefined or other JS primitives?
        # Actually, it's usually valid JSON.
        
        # However, the match might be incomplete if the regex is too simple (handling nested parens).
        # But let's try.
        
        # In Next.js App Router, it's often: ([1, "chunk"])
        # Let's try to json.loads the match string directly? No, the match is inside parens.
        # It should be a list.
        
        # There's a catch: the string inside might contain escaped quotes.
        
        data = json.loads(match)
        if isinstance(data, list) and len(data) > 1 and isinstance(data[1], str):
            content = data[1]
            # The content itself might be a part of the HTML or JSON.
            # Next.js streams HTML segments.
            # But it also streams the RSC (React Server Component) payload.
            
            # Let's look for JSON-like structures in the content.
            if "mirapraia" in content or "R$" in content:
                print(f"Match {i} contains 'mirapraia' or 'R$'", flush=True)
                # print(content[:200], flush=True)
                full_data.append(content)
                
    except Exception as e:
        # print(f"Error parsing match {i}: {e}", flush=True)
        pass

# Concatenate all data to see if we can find the full structure
all_text = "".join(full_data)

# Save to file for inspection
with open("extracted_next_data.txt", "w", encoding="utf-8") as f:
    f.write(all_text)

print("Saved extracted data to extracted_next_data.txt", flush=True)

# Search for product patterns in the extracted text
# Products usually have a name, price, description, image.
# Example: {"name":"X-Burger","price":20...}

# Let's try to find image URLs
img_regex = r'https?://[^\s"]+\.(?:jpg|jpeg|png|webp)'
imgs = re.findall(img_regex, all_text)
print(f"Found {len(imgs)} image URLs in the extracted data.", flush=True)
if imgs:
    print(f"First 5 images: {imgs[:5]}", flush=True)
