import json
import os
import uuid
from datetime import datetime
from app.services.data_service import load_products

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
KITCHEN_CHECKLISTS_FILE = os.path.join(DATA_DIR, 'kitchen_checklists.json')

class KitchenChecklistService:
    @staticmethod
    def _ensure_data_dir():
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

    @staticmethod
    def load_lists():
        KitchenChecklistService._ensure_data_dir()
        if not os.path.exists(KITCHEN_CHECKLISTS_FILE):
            return []
        try:
            with open(KITCHEN_CHECKLISTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    @staticmethod
    def save_lists(lists):
        KitchenChecklistService._ensure_data_dir()
        with open(KITCHEN_CHECKLISTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(lists, f, indent=4, ensure_ascii=False)

    @staticmethod
    def create_list(name, list_type, items):
        """
        items: list of dicts {'name': str, 'unit': str|None, 'is_custom': bool}
        """
        lists = KitchenChecklistService.load_lists()
        
        new_list = {
            'id': str(uuid.uuid4()),
            'name': name,
            'type': list_type, # 'quantity' or 'checklist'
            'items': items,
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        
        lists.append(new_list)
        KitchenChecklistService.save_lists(lists)
        return new_list

    @staticmethod
    def get_list(list_id):
        lists = KitchenChecklistService.load_lists()
        return next((l for l in lists if l['id'] == list_id), None)

    @staticmethod
    def delete_list(list_id):
        lists = KitchenChecklistService.load_lists()
        lists = [l for l in lists if l['id'] != list_id]
        KitchenChecklistService.save_lists(lists)
        return True

    @staticmethod
    def update_list(list_id, data):
        lists = KitchenChecklistService.load_lists()
        for i, l in enumerate(lists):
            if l['id'] == list_id:
                lists[i].update(data)
                lists[i]['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                KitchenChecklistService.save_lists(lists)
                return lists[i]
        return None

    @staticmethod
    def get_insumos():
        # Helper to get available products for selection
        products = load_products()
        # Filter relevant ones? Or all? User said "insumos disponíveis".
        # Maybe just return simplified list
        return sorted([{'name': p['name'], 'unit': p.get('unit')} for p in products], key=lambda x: x['name'])
