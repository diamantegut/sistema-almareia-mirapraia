import pandas as pd
import json
import os
import re
from datetime import datetime
import locale

from app.services.system_config_manager import (
    SALES_HISTORY_FILE, SALES_PRODUCTS_FILE,
    CASHIER_SESSIONS_FILE, STOCK_FILE, STOCK_ENTRIES_FILE, SALES_DIR
)
from app.services.data_service import save_stock_entries, save_sales_history

# Constants
SALES_FOLDER = SALES_DIR
STOCK_REQUESTS_FILE = STOCK_FILE # Alias for compatibility

try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    pass

MONTH_MAP = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9,
    'outubro': 10, 'novembro': 11, 'dezembro': 12
}

def load_json(path):
    if not os.path.exists(path): return {} if path.endswith('dict.json') else []
    try:
        with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {} if path.endswith('dict.json') else []

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def parse_filename_date(filename):
    """
    Tries to extract start and end dates from filename.
    Returns (start_date_obj, end_date_obj) or (None, None).
    """
    name = filename.lower().replace('.xlsx', '').strip()
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # 1. Full Month Name (e.g. "novembro")
    if name in MONTH_MAP:
        month = MONTH_MAP[name]
        year = current_year
        if month > current_month: year -= 1
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - pd.Timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - pd.Timedelta(days=1)
        return start_date, end_date

    # 2. Range with Month Name (e.g. "01-26 de dezembro")
    match_range_month = re.match(r'(\d{1,2})-(\d{1,2})\s+de\s+([a-zç]+)', name)
    if match_range_month:
        d1, d2, month_name = match_range_month.groups()
        if month_name in MONTH_MAP:
            month = MONTH_MAP[month_name]
            year = current_year
            try:
                start_date = datetime(year, month, int(d1))
                end_date = datetime(year, month, int(d2))
                return start_date, end_date
            except ValueError: pass

    # 4. Specific Date (YYYY-MM-DD) e.g. "2025-12-28"
    match_date = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', name)
    if match_date:
        y, m, d = map(int, match_date.groups())
        try:
            date_obj = datetime(y, m, d)
            return date_obj, date_obj
        except ValueError: pass

    # 3. Simple Range (e.g. "26-28") - Assume current month
    match_range_simple = re.match(r'(\d{1,2})-(\d{1,2})$', name)
    if match_range_simple:
        d1, d2 = match_range_simple.groups()
        year = current_year
        month = current_month 
        try:
            start_date = datetime(year, month, int(d1))
            end_date = datetime(year, month, int(d2))
            return start_date, end_date
        except ValueError: pass

    return None, None

def calculate_monthly_sales(target_month_str):
    if not os.path.exists(SALES_FOLDER):
        return 0.0

    try:
        target_date = datetime.strptime(target_month_str, '%Y-%m')
        target_year = target_date.year
        target_month = target_date.month
    except ValueError:
        return 0.0

    total_sales = 0.0
    
    files = [f for f in os.listdir(SALES_FOLDER) if f.endswith('.xlsx') and not f.startswith('~$')]
    
    for filename in files:
        start_date, end_date = parse_filename_date(filename)
        if not start_date:
            continue
            
        if start_date.year == target_year and start_date.month == target_month:
             pass 
        else:
             continue
             
        file_path = os.path.join(SALES_FOLDER, filename)
        try:
            df = pd.read_excel(file_path, header=1)
            if 'ValorVendido' in df.columns:
                 for val in df['ValorVendido']:
                     if isinstance(val, str):
                         clean_val = val.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
                         try:
                             total_sales += float(clean_val)
                         except: pass
                     elif isinstance(val, (int, float)):
                         total_sales += float(val)
        except:
            continue
            
    if os.path.exists(CASHIER_SESSIONS_FILE):
        try:
            with open(CASHIER_SESSIONS_FILE, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
                
            for session in sessions:
                for t in session.get('transactions', []):
                    if t.get('type') == 'sale':
                        ts_str = t.get('timestamp', '')
                        try:
                            t_date = datetime.strptime(ts_str, '%d/%m/%Y %H:%M')
                            if t_date.year == target_year and t_date.month == target_month:
                                total_sales += float(t.get('amount', 0))
                        except:
                            pass
        except:
            pass

    return total_sales

def process_sales_files():
    messages = []
    messages.append("Iniciando processamento de arquivos de vendas...")
    
    history_data = load_json(SALES_HISTORY_FILE)
    if isinstance(history_data, list):
        history_data = {"last_processed_date": "", "history": history_data}
    
    processed_files = {h['filename'] for h in history_data.get('history', [])}
    
    sales_products = load_json(SALES_PRODUCTS_FILE)
    stock_entries = load_json(STOCK_ENTRIES_FILE)
    
    if not os.path.exists(SALES_FOLDER):
        return ["Pasta de vendas não encontrada."]
        
    files = [f for f in os.listdir(SALES_FOLDER) if f.endswith('.xlsx') and not f.startswith('~$')]
    new_files_count = 0
    
    for filename in files:
        if filename in processed_files:
            continue
            
        messages.append(f"Processando: {filename}")
        file_path = os.path.join(SALES_FOLDER, filename)
        
        start_date, end_date = parse_filename_date(filename)
        if not start_date:
            messages.append(f"  -> Data não identificada no nome do arquivo: {filename}")
            continue
            
        try:
            df = pd.read_excel(file_path, header=1)
            if 'Nome' not in df.columns or 'Qtd.' not in df.columns:
                 messages.append(f"  -> Colunas 'Nome' ou 'Qtd.' não encontradas.")
                 continue
                 
            items_processed = 0
            stock_deductions = []
            
            for _, row in df.iterrows():
                p_name = row['Nome']
                try:
                    qty = float(row['Qtd.'])
                except:
                    qty = 0
                
                if not p_name or pd.isna(p_name) or qty <= 0:
                    continue
                
                items_processed += qty
                
                if p_name in sales_products:
                    mapping = sales_products[p_name]
                    if mapping.get('ignored'):
                        continue
                        
                    for linked in mapping.get('linked_stock', []):
                        stock_name = linked['product_name']
                        multiplier = float(linked['qty'])
                        total_deduct = qty * multiplier
                        
                        stock_deductions.append({
                            "id": f"SALE_{filename}_{p_name}_{stock_name}",
                            "user": "Sistema (Vendas)",
                            "product": stock_name,
                            "supplier": f"Venda: {p_name}",
                            "qty": -total_deduct,
                            "price": 0.0,
                            "invoice": filename,
                            "date": end_date.strftime('%d/%m/%Y')
                        })
                else:
                    sales_products[p_name] = {
                        "category": row.get('Categoria', 'Geral'),
                        "linked_stock": [],
                        "ignored": False
                    }
            
            history_entry = {
                "date_uploaded": datetime.now().strftime('%d/%m/%Y %H:%M'),
                "start_date": start_date.strftime('%d/%m/%Y'),
                "end_date": end_date.strftime('%d/%m/%Y'),
                "items_processed": items_processed,
                "filename": filename,
                "note": "Importado via Script"
            }
            history_data['history'].append(history_entry)
            
            try:
                current_last_str = history_data.get('last_processed_date')
                current_last = datetime.min
                if current_last_str:
                    try:
                        current_last = datetime.strptime(current_last_str, '%d/%m/%Y')
                    except ValueError:
                        try:
                            current_last = datetime.strptime(current_last_str, '%Y-%m-%d')
                        except ValueError:
                            pass

                if end_date > current_last:
                    history_data['last_processed_date'] = end_date.strftime('%d/%m/%Y')
            except Exception as e:
                 history_data['last_processed_date'] = end_date.strftime('%d/%m/%Y')
            
            base_id = int(datetime.now().timestamp())
            for i, entry in enumerate(stock_deductions):
                entry['id'] = f"SALE_{base_id}_{i}"
                stock_entries.append(entry)
                
            new_files_count += 1
            messages.append(f"  -> Processado com sucesso. {items_processed} itens. {len(stock_deductions)} baixas de estoque geradas.")
            
        except Exception as e:
            messages.append(f"  -> Erro ao processar arquivo: {e}")
            
    save_sales_history(history_data)
    save_json(SALES_PRODUCTS_FILE, sales_products)
    save_stock_entries(stock_entries)
    
    messages.append(f"Concluído. {new_files_count} novos arquivos processados.")
    return "\n".join(messages)

if __name__ == '__main__':
    print(process_sales_files())
