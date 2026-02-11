import os

TEMPLATES_DIR = r"f:\Sistema Almareia Mirapraia\app\templates"

for filename in os.listdir(TEMPLATES_DIR):
    if filename.endswith(".html"):
        filepath = os.path.join(TEMPLATES_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = content.replace("url_for('index')", "url_for('main.index')")
        
        if content != new_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated {filename}")
