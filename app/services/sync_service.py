import pandas as pd
import json
import os
from datetime import datetime
import time
from app.services.system_config_manager import (
    get_config_value, BASE_DIR,
    PRODUCTS_FILE, STOCK_ENTRIES_FILE, STOCK_FILE, LAST_SYNC_FILE
)

# Constants
EXCEL_PATH = get_config_value('sync_excel_path', os.path.join(BASE_DIR, 'Resumo de Estoque', 'INSUMOS (822).xlsx'))
STOCK_REQUESTS_FILE = STOCK_FILE

def load_json(path):
    if not os.path.exists(path): return []
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return []

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_product_balances(products, entries, requests):
    """
    Calcula o saldo atual de cada produto baseado em entradas e saídas.
    Réplica da lógica do app.py.
    """
    balances = {p['name']: 0.0 for p in products}
    
    # Somar entradas
    for entry in entries:
        if entry.get('product') in balances:
            try:
                balances[entry['product']] += float(entry.get('qty', 0))
            except ValueError: pass
            
    # Subtrair saídas (Requisições)
    for req in requests:
        # Status que debitam estoque: Pendente (legado) e Concluído
        if req.get('status') not in ['Pendente', 'Concluído']:
            continue

        if 'items_structured' in req:
            for item in req['items_structured']:
                if item['name'] in balances:
                    # Usa quantidade entregue se houver, senão a solicitada
                    qty = float(item.get('delivered_qty', item['qty']))
                    balances[item['name']] -= qty
        elif 'items' in req and isinstance(req['items'], str):
             parts = req['items'].split(', ')
             for part in parts:
                 try:
                     if 'x ' in part:
                         qty_str, name = part.split('x ', 1)
                         name = name.strip()
                         if name in balances:
                             balances[name] -= float(qty_str)
                 except ValueError: pass
                 
    return balances

def clean_category(cat_name):
    if not isinstance(cat_name, str): return "Geral"
    cat_name = cat_name.strip()
    # Remove leading numbers (e.g. "01 Carnes" -> "Carnes")
    if ' ' in cat_name and cat_name.split(' ', 1)[0].isdigit():
        return cat_name.split(' ', 1)[1].strip()
    return cat_name

def sync_excel_to_system():
    print(f"[{datetime.now()}] Iniciando sincronização com Excel: {EXCEL_PATH}")
    
    if not os.path.exists(EXCEL_PATH):
        print("Arquivo Excel não encontrado.")
        return False, "Arquivo Excel não encontrado"

    try:
        df = pd.read_excel(EXCEL_PATH)
    except Exception as e:
        print(f"Erro ao ler Excel: {e}")
        return False, str(e)

    products = load_json(PRODUCTS_FILE)
    entries = load_json(STOCK_ENTRIES_FILE)
    requests = load_json(STOCK_REQUESTS_FILE)
    
    # --- 1. Atualizar Produtos ---
    product_map = {p['name']: p for p in products}
    updates_count = 0
    new_products_count = 0
    
    excel_stock_map = {}
    
    for index, row in df.iterrows():
        name = str(row['Nome']).strip()
        if not name or name == 'nan': continue
        
        category_raw = row['Categoria'] if pd.notna(row['Categoria']) else "Geral"
        category = clean_category(category_raw)
        
        unit = str(row['Medida']).strip() if pd.notna(row['Medida']) else 'Un'
        min_stock = float(row['Estoque Mín']) if pd.notna(row['Estoque Mín']) else 0.0
        current_stock_excel = float(row['Estoque']) if pd.notna(row['Estoque']) else 0.0
        
        excel_stock_map[name] = current_stock_excel
        
        if name in product_map:
            prod = product_map[name]
            # Atualiza campos se mudaram
            changed = False
            if prod.get('category') != category:
                prod['category'] = category
                changed = True
            if prod.get('unit') != unit:
                prod['unit'] = unit
                changed = True
            if prod.get('min_stock') != min_stock:
                prod['min_stock'] = min_stock
                changed = True
            
            if changed:
                updates_count += 1
        else:
            # Novo produto
            new_prod = {
                'id': int(row['Cód. Sistema']) if pd.notna(row['Cód. Sistema']) else index + 900000,
                'name': name,
                'category': category,
                'unit': unit,
                'min_stock': min_stock,
                'department': 'Estoques' # Default para novos
            }
            products.append(new_prod)
            product_map[name] = new_prod
            new_products_count += 1
            
    save_json(PRODUCTS_FILE, products)
    
    # --- 2. Atualizar Estoques (Ajustes) ---
    balances = get_product_balances(products, entries, requests)
    
    adjustments = []
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    for name, excel_qty in excel_stock_map.items():
        system_qty = balances.get(name, 0.0)
        diff = excel_qty - system_qty
        
        # Se a diferença for significativa (> 0.001)
        if abs(diff) > 0.001:
            # Criar entrada de ajuste
            entry = {
                "id": f"SYNC_{int(time.time())}_{len(adjustments)}",
                "user": "Sistema (Auto)",
                "product": name,
                "supplier": "Ajuste Excel Diário",
                "qty": diff, # Se positivo adiciona, se negativo reduz (balance += qty)
                "price": 0.0,
                "invoice": "SYNC_AUTO",
                "date": date_str
            }
            adjustments.append(entry)
            entries.append(entry)
            
    if adjustments:
        save_json(STOCK_ENTRIES_FILE, entries)
    
    summary = f"Sincronização concluída. Produtos atualizados: {updates_count}, Novos: {new_products_count}. Ajustes de estoque: {len(adjustments)}."
    print(summary)
    
    # Salvar log da última sincronização
    with open(LAST_SYNC_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'last_sync': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'log': summary,
            'adjustments_count': len(adjustments)
        }, f, indent=4, ensure_ascii=False)
        
    return True, summary

if __name__ == '__main__':
    sync_excel_to_system()
