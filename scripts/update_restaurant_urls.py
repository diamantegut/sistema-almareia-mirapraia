import os
import re

TEMPLATES_DIR = r"f:\Sistema Almareia Mirapraia\app\templates"

REPLACEMENTS = {
    r"url_for\('restaurant_tables'": "url_for('restaurant.restaurant_tables'",
    r"url_for\('restaurant_cashier'": "url_for('restaurant.restaurant_cashier'",
    r"url_for\('restaurant_dashboard'": "url_for('restaurant.restaurant_dashboard'",
    r"url_for\('restaurant_table_order'": "url_for('restaurant.restaurant_table_order'",
    r"url_for\('restaurant_observations'": "url_for('restaurant.restaurant_observations'",
    r"url_for\('restaurant_complements'": "url_for('restaurant.restaurant_complements'",
    r"url_for\('breakfast_report'": "url_for('restaurant.breakfast_report'",
    r"url_for\('open_staff_table'": "url_for('restaurant.open_staff_table'",
    r"url_for\('toggle_table_disabled'": "url_for('restaurant.toggle_table_disabled'",
    r"url_for\('toggle_live_music'": "url_for('restaurant.toggle_live_music'",
    r"url_for\('restaurant_transfer_item'": "url_for('restaurant.restaurant_transfer_item'",
    r"url_for\('payment_methods'": "url_for('restaurant.payment_methods'"
}

def update_templates():
    for root, dirs, files in os.walk(TEMPLATES_DIR):
        for file in files:
            if file.endswith('.html'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                for pattern, replacement in REPLACEMENTS.items():
                    new_content = re.sub(pattern, replacement, new_content)
                
                if new_content != content:
                    print(f"Updating {file}")
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

if __name__ == "__main__":
    update_templates()
