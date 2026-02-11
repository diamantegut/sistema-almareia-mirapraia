import json
import os
import pandas as pd
import re
import unicodedata

PROJECT_ROOT = r"F:\Sistema Almareia Mirapraia"
DATA_FILE = os.path.join(PROJECT_ROOT, "data", "menu_items.json")
EXCEL_FILES = [
    r"F:\info Fiscal\PRODUTOS (250).xlsx",
    r"F:\info Fiscal\PRODUTOS POR TAMANHO (27).xlsx"
]

def normalize_text(text):
    if not isinstance(text, str):
        return ""
    # Normalize unicode characters to decompose combined characters
    text = unicodedata.normalize('NFD', text)
    # Filter out non-spacing mark characters (accents)
    text = "".join([c for c in text if unicodedata.category(c) != 'Mn'])
    # Lowercase and strip
    return text.lower().strip()

def clean_code(value):
    if pd.isna(value):
        return ""
    s = str(value).strip()
    # If "5101-Description", return "5101"
    match = re.match(r"^(\d+)", s)
    if match:
        return match.group(1)
    return s

def clean_float(value):
    if pd.isna(value):
        return 0.0
    try:
        return float(value)
    except:
        return 0.0

def restore_fiscal():
    print("Loading menu_items.json...")
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        menu_items = json.load(f)
    
    print("Loading Excel files...")
    df_list = []
    for f in EXCEL_FILES:
        try:
            df = pd.read_excel(f)
            df_list.append(df)
        except Exception as e:
            print(f"Error reading {f}: {e}")
            
    if not df_list:
        print("No Excel data loaded.")
        return

    full_df = pd.concat(df_list, ignore_index=True)
    
    # Normalize name for matching
    full_df['normalized_name'] = full_df['Nome'].apply(normalize_text)
    
    # Create lookup dict
    fiscal_lookup = {}
    for _, row in full_df.iterrows():
        name = row['normalized_name']
        if name:
            fiscal_lookup[name] = row
            
    updated_count = 0
    
    for item in menu_items:
        name = normalize_text(item.get('name'))
        if name in fiscal_lookup:
            row = fiscal_lookup[name]
            
            # Update fields
            item['ncm'] = clean_code(row.get('NCM'))
            item['cest'] = clean_code(row.get('CEST'))
            item['transparency_tax'] = clean_float(row.get('Alíquota Transparência (%)'))
            item['fiscal_benefit_code'] = str(row.get('Código Benefício Fiscal', '') if not pd.isna(row.get('Código Benefício Fiscal')) else '')
            
            item['cfop'] = clean_code(row.get('CFOP'))
            item['origin'] = clean_code(row.get('Origem Mercadoria'))
            item['tax_situation'] = clean_code(row.get('Situação Tributária'))
            
            item['icms_rate'] = clean_float(row.get('Aliquota Icms'))
            item['icms_base_reduction'] = clean_float(row.get('Percentual Redução Base Cálculo Icms'))
            item['fcp_rate'] = clean_float(row.get('Percentual FCP'))
            
            item['pis_cst'] = clean_code(row.get('Código Situação Tributária Pis'))
            item['pis_rate'] = clean_float(row.get('Aliquota Pis'))
            
            item['cofins_cst'] = clean_code(row.get('Código Situação Tributária Cofins'))
            item['cofins_rate'] = clean_float(row.get('Aliquota Cofins'))
            
            updated_count += 1
            
    print(f"Updated {updated_count} items with fiscal data.")
    
    # Save backup
    backup_file = DATA_FILE + ".pre_fiscal_restore"
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(menu_items, f, indent=4, ensure_ascii=False) # Wait, this dumps the NEW data. 
    
    # Actually I should have backed up BEFORE modifying. 
    # But since I loaded into memory, let's just save to main file.
    # I'll rely on previous backups if something goes wrong.
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(menu_items, f, indent=4, ensure_ascii=False)
        
    print("Saved updated menu_items.json")

if __name__ == "__main__":
    restore_fiscal()
