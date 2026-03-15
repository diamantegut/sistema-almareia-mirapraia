import pandas as pd
import unicodedata
import re
import os
from app.services.data_service import load_menu_items, save_menu_items

def _excel_clean_value(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return value

def _excel_extract_code(value):
    value = _excel_clean_value(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            as_int = int(value)
            if float(as_int) == float(value):
                return str(as_int)
        except Exception:
            pass
        return str(value)
    s = str(value).strip()
    if not s:
        return None
    if '-' in s:
        return s.split('-', 1)[0].strip() or None
    return s

def rescue_menu_items_fiscal_from_excel(excel_paths):
    if not isinstance(excel_paths, (list, tuple)):
        excel_paths = [excel_paths]

    def normalize_name(name):
        if name is None:
            return None
        s = str(name).strip()
        if not s:
            return None
        s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
        s = s.casefold().strip()
        s = re.sub(r'\s+', ' ', s)
        return s

    def _name_variants(name):
        base = normalize_name(name)
        if not base:
            return []
        variants = {base}

        no_parens = re.sub(r'\s*\([^)]*\)\s*', ' ', base).strip()
        no_parens = re.sub(r'\s+', ' ', no_parens)
        if no_parens:
            variants.add(no_parens)

        no_dash_suffix = re.sub(r'\s*-\s*.+$', '', base).strip()
        if no_dash_suffix:
            variants.add(no_dash_suffix)

        return [v for v in variants if v]

    rows_by_id = {}
    rows_by_name = {}
    loaded_files = []
    for path in excel_paths:
        path = _excel_clean_value(path)
        if not path or not os.path.exists(path):
            continue
        try:
            df = pd.read_excel(path)
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            loaded_files.append(path)
            for _, row in df.iterrows():
                code = _excel_extract_code(row.get('Cód. Sistema'))
                if code:
                    rows_by_id[code] = row

                name = _excel_clean_value(row.get('Nome'))
                for variant in _name_variants(name):
                    existing = rows_by_name.get(variant)
                    if existing is None:
                        rows_by_name[variant] = row
                        continue

                    score_cols = [
                        'NCM',
                        'CEST',
                        'CFOP',
                        'Origem Mercadoria',
                        'Situação Tributária',
                        'Aliquota Icms',
                        'Percentual FCP',
                        'Código Benefício Fiscal',
                        'Alíquota Transparência (%)',
                        'Percentual Redução Base Cálculo Icms',
                        'Código Situação Tributária Pis',
                        'Aliquota Pis',
                        'Código Situação Tributária Cofins',
                        'Aliquota Cofins',
                    ]

                    def score(r):
                        total = 0
                        for c in score_cols:
                            v = _excel_clean_value(r.get(c))
                            if v is not None:
                                total += 1
                        return total

                    if score(row) > score(existing):
                        rows_by_name[variant] = row
        except Exception as e:
            print(f"Error reading excel {path}: {e}")
            continue

    items = load_menu_items()
    updated_items = 0
    matched_items = 0
    updated_fields = 0

    def is_missing(v):
        return v is None or (isinstance(v, str) and not v.strip())

    for item in items:
        if not isinstance(item, dict):
            continue
        item_code = _excel_extract_code(item.get('id'))
        row = None
        if item_code:
            row = rows_by_id.get(item_code)
        if row is None:
            item_name = item.get('name')
            for variant in _name_variants(item_name):
                row = rows_by_name.get(variant)
                if row is not None:
                    break
        
        if row is not None:
            matched_items += 1
            changed = False
            
            # Map Excel columns to Item fields
            mapping = {
                'NCM': 'ncm',
                'CEST': 'cest',
                'CFOP': 'cfop',
                'Origem Mercadoria': 'origin',
                'Situação Tributária': 'tax_situation',
                'Aliquota Icms': 'icms_rate',
                'Percentual FCP': 'fcp_rate',
                'Código Benefício Fiscal': 'fiscal_benefit_code',
                'Alíquota Transparência (%)': 'transparency_tax',
                'Percentual Redução Base Cálculo Icms': 'icms_base_reduction',
                'Código Situação Tributária Pis': 'pis_cst',
                'Aliquota Pis': 'pis_rate',
                'Código Situação Tributária Cofins': 'cofins_cst',
                'Aliquota Cofins': 'cofins_rate',
            }

            for excel_col, item_field in mapping.items():
                if is_missing(item.get(item_field)):
                    new_val = _excel_clean_value(row.get(excel_col))
                    if new_val is not None:
                        # Convert float/int to suitable types
                        if item_field in ['icms_rate', 'fcp_rate', 'transparency_tax', 'icms_base_reduction', 'pis_rate', 'cofins_rate']:
                            try:
                                item[item_field] = float(new_val)
                                changed = True
                                updated_fields += 1
                            except: pass
                        else:
                            item[item_field] = str(new_val)
                            changed = True
                            updated_fields += 1
            
            if changed:
                updated_items += 1

    if updated_items > 0:
        save_menu_items(items)

    return {
        'success': True,
        'loaded_files': loaded_files,
        'total_items_scanned': len(items),
        'matched_items': matched_items,
        'updated_items': updated_items,
        'updated_fields_count': updated_fields
    }
