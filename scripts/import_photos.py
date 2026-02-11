import os
import json
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from system_config_manager import MENU_ITEMS_FILE, get_log_path

sys.stdout.reconfigure(encoding="utf-8")

PHOTO_DIR = r"c:\Users\Angelo Diamante\Documents\trae_projects\Back of the house\Produtos\Fotos"
MENU_ITEMS_FILE = MENU_ITEMS_FILE
LOG_FILE = get_log_path("import_log.txt")


def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def load_existing_menu_items():
    if not os.path.exists(MENU_ITEMS_FILE):
        return []
    try:
        with open(MENU_ITEMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Error loading existing menu items: {e}")
        return []


def save_menu_items(items):
    try:
        with open(MENU_ITEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        log(f"Successfully updated {MENU_ITEMS_FILE} with {len(items)} items.")
    except Exception as e:
        log(f"Error writing menu items file: {e}")


def main():
    log("Starting import script...")
    if not os.path.exists(PHOTO_DIR):
        log(f"Directory not found: {PHOTO_DIR}")
        return

    try:
        files = os.listdir(PHOTO_DIR)
        log(f"Found {len(files)} files in {PHOTO_DIR}")
    except Exception as e:
        log(f"Error listing directory: {e}")
        return

    existing_items = load_existing_menu_items()
    existing_by_id = {}
    for item in existing_items:
        if isinstance(item, dict):
            pid = str(item.get("id") or "").strip()
            if pid:
                existing_by_id[pid] = item

    new_items = []

    for filename in files:
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue

        name_part = os.path.splitext(filename)[0]

        if name_part.isdigit():
            product_id = str(int(name_part))
        else:
            product_id = name_part

        photo_url = f"/Produtos/Fotos/{filename}"

        if product_id in existing_by_id:
            item = existing_by_id[product_id]
            if not item.get("image_url"):
                item["image_url"] = photo_url
            if not item.get("image"):
                item["image"] = photo_url
            continue

        new_item = {
            "id": product_id,
            "name": f"Produto {product_id}",
            "category": "Geral",
            "price": 0.0,
            "cost_price": 0.0,
            "printer_id": "",
            "should_print": True,
            "description": "Produto importado automaticamente via foto",
            "service_fee_exempt": False,
            "visible_virtual_menu": True,
            "active": True,
            "recipe": [],
            "ncm": "",
            "cest": "",
            "transparency_tax": 0.0,
            "fiscal_benefit_code": "",
            "cfop": "",
            "origin": "0",
            "tax_situation": "",
            "icms_rate": 0.0,
            "icms_base_reduction": 0.0,
            "fcp_rate": 0.0,
            "pis_cst": "",
            "pis_rate": 0.0,
            "cofins_cst": "",
            "cofins_rate": 0.0,
            "image_url": photo_url,
            "image": photo_url,
        }
        new_items.append(new_item)

    if not new_items and existing_items == load_existing_menu_items():
        log("No new items to add or update.")
        return

    all_items = existing_items + new_items
    save_menu_items(all_items)


if __name__ == "__main__":
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")
    main()
