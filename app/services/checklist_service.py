import json
import os
from datetime import datetime
import uuid
import re
from app.services.system_config_manager import (
    CHECKLIST_ITEMS_FILE, DAILY_CHECKLISTS_FILE, CHECKLIST_SETTINGS_FILE
)

def load_checklist_items():
    if not os.path.exists(CHECKLIST_ITEMS_FILE):
        return []
    try:
        with open(CHECKLIST_ITEMS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Migration: Convert strings to dicts
        migrated = False
        new_data = []
        for item in data:
            if isinstance(item, str):
                migrated = True
                new_data.append({
                    'id': str(uuid.uuid4()),
                    'name': item,
                    'category': 'Outros',
                    'unit': 'un',
                    'department': 'Governança',
                    'active': True
                })
            elif isinstance(item, dict):
                new_data.append(item)
                
        if migrated:
            save_checklist_items(new_data)
            return new_data
            
        return data
    except:
        return []

def save_checklist_items(items):
    with open(CHECKLIST_ITEMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=4, ensure_ascii=False)

def load_daily_checklists():
    if not os.path.exists(DAILY_CHECKLISTS_FILE):
        return {}
    try:
        with open(DAILY_CHECKLISTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_daily_checklists(checklists):
    with open(DAILY_CHECKLISTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(checklists, f, indent=4, ensure_ascii=False)

def get_average_qty(item_id, checklists):
    total_qty = 0.0
    count = 0
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    for date, checklist in checklists.items():
        # Skip today to avoid skewing with current empty/partial values
        if date == today_str:
            continue
            
        for item in checklist.get('items', []):
            if item['id'] == item_id and item.get('checked'):
                try:
                    # Parse qty, handle strings like "2 kg" if they exist
                    q_str = str(item.get('qty', '')).replace(',', '.')
                    # Extract first number found
                    match = re.search(r"[\d\.]+", q_str)
                    if match:
                        qty = float(match.group())
                        total_qty += qty
                        count += 1
                except:
                    pass
                    
    if count == 0:
        return ''
        
    avg = total_qty / count
    # Format: if int, return int, else 1 decimal
    if avg.is_integer():
        return str(int(avg))
    return f"{avg:.1f}"

def get_todays_checklist(department='Governança'):
    today = datetime.now().strftime('%Y-%m-%d')
    # Use composite key for department separation
    key = f"{today}_{department}"
    
    checklists = load_daily_checklists()
    
    # Backward compatibility: if today exists as a key (old format), migrate it to 'Governança'
    if today in checklists and department == 'Governança':
        checklists[key] = checklists.pop(today)
        save_daily_checklists(checklists)
    
    if key not in checklists:
        # Create new based on items
        items = load_checklist_items()
        
        new_items = []
        
        # 1. Add Manual Items (filtered by department)
        for i in items:
            # Default to Governança if not specified
            item_dept = i.get('department', 'Governança')
            
            if item_dept == department and i.get('active', True):
                suggested_qty = get_average_qty(i['id'], checklists)
                
                new_items.append({
                    'id': i['id'], 
                    'name': i['name'], 
                    'category': i.get('category', 'Outros'), 
                    'checked': False, 
                    'qty': suggested_qty, 
                    'unit': i.get('unit', 'un'),
                    'source': 'manual'
                })
        
        # 2. Add Auto Items from Stock (Cozinha)
        if department == 'Cozinha':
            try:
                from app.services.data_service import load_products
                products = load_products()
                # Filter products for Cozinha
                # You can adjust this filter based on your exact "Cozinha" definition
                kitchen_products = [p for p in products if p.get('department') == 'Cozinha']
                
                for p in kitchen_products:
                    suggested_qty = get_average_qty(p['id'], checklists)
                    new_items.append({
                        'id': p['id'],
                        'name': p['name'],
                        'category': p.get('category', 'Outros'),
                        'checked': False,
                        'qty': suggested_qty,
                        'unit': p.get('unit', 'un'),
                        'source': 'auto'
                    })
            except ImportError:
                pass
        
        new_checklist = {
            'date': today,
            'department': department,
            'items': new_items,
            'status': 'open',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        checklists[key] = new_checklist
        save_daily_checklists(checklists)
        
    return checklists[key]

def update_checklist_item(date, item_id, checked, qty, department='Governança'):
    checklists = load_daily_checklists()
    # Handle composite key
    key = f"{date}_{department}"
    
    # Fallback to old key if not found and department is Governança
    if key not in checklists and date in checklists and department == 'Governança':
        key = date
        
    if key in checklists:
        for item in checklists[key]['items']:
            if item['id'] == item_id:
                item['checked'] = checked
                item['qty'] = qty
                break
        save_daily_checklists(checklists)
        return True
    return False

def add_catalog_item(name, category, unit='un', department='Governança'):
    items = load_checklist_items()
    new_item = {
        'id': str(uuid.uuid4()),
        'name': name,
        'category': category,
        'unit': unit,
        'department': department,
        'active': True
    }
    items.append(new_item)
    save_checklist_items(items)
    return new_item

def load_checklist_settings():
    if not os.path.exists(CHECKLIST_SETTINGS_FILE):
        return {'whatsapp_number': ''}
    try:
        with open(CHECKLIST_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'whatsapp_number': ''}

def save_checklist_settings(settings):
    with open(CHECKLIST_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)

def update_catalog_item(item_id, name, category, unit):
    items = load_checklist_items()
    for item in items:
        if item['id'] == item_id:
            item['name'] = name
            item['category'] = category
            item['unit'] = unit
            break
    save_checklist_items(items)

def remove_catalog_item(item_id):
    items = load_checklist_items()
    items = [i for i in items if i['id'] != item_id]
    save_checklist_items(items)

def toggle_catalog_item(item_id):
    items = load_checklist_items()
    for item in items:
        if item['id'] == item_id:
            item['active'] = not item.get('active', True)
            break
    save_checklist_items(items)
