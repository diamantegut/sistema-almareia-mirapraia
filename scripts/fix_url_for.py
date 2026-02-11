import os

path = r"f:\Sistema Almareia Mirapraia\app.py"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

new_content = content.replace("url_for('index')", "url_for('main.index')")

if content != new_content:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Updated app.py")
else:
    print("No changes made")
