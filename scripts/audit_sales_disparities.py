import json
import sqlite3
import os
from datetime import datetime, timedelta
import re

# Configuration
DATA_DIR = os.path.join(os.getcwd(), 'data')
SALES_HISTORY_FILE = os.path.join(DATA_DIR, 'sales_history.json')
LOGS_DB = os.path.join(DATA_DIR, 'department_logs.db')
START_DATE = datetime(2026, 2, 15)

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return []

def get_db_connection():
    try:
        conn = sqlite3.connect(LOGS_DB)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def parse_timestamp(ts_str):
    if not ts_str: return None
    try:
        # Try ISO format first
        return datetime.fromisoformat(ts_str)
    except:
        # Try various formats
        formats = [
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%d/%m/%Y %H:%M:%S'
        ]
        for fmt in formats:
            try:
                return datetime.strptime(ts_str, fmt)
            except:
                continue
    return None

def normalize_money(val):
    try:
        if isinstance(val, str):
            val = val.replace('R$', '').replace('.', '').replace(',', '.')
        return float(val)
    except:
        return 0.0

def extract_table_from_log(details):
    # Try to extract table ID from log details string
    # Patterns like "Mesa 40", "table': '40'"
    match = re.search(r"Mesa\s+(\w+)", details)
    if match:
        return match.group(1)
    
    match = re.search(r"'table':\s*'(\w+)'", details)
    if match:
        return match.group(1)
        
    return None

def extract_total_from_log(details):
    # Try to extract total from log
    # Patterns like "Total: R$ 100.00"
    match = re.search(r"Total:\s*R\$\s*([\d\.,]+)", details)
    if match:
        return normalize_money(match.group(1))
    return None

def main():
    print(f"Iniciando auditoria de vendas a partir de {START_DATE.strftime('%d/%m/%Y')}...")

    # 1. Load Sales History
    history = load_json(SALES_HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    # Filter history since start date
    relevant_sales = []
    for sale in history:
        # Check closed_at or opened_at
        ts = parse_timestamp(sale.get('closed_at')) or parse_timestamp(sale.get('opened_at'))
        if ts and ts >= START_DATE:
            relevant_sales.append(sale)
            
    print(f"Total de registros de vendas encontrados no período: {len(relevant_sales)}")

    # 2. Load Logs
    conn = get_db_connection()
    logs = []
    if conn:
        cursor = conn.cursor()
        # Get logs for closure or cancellation
        cursor.execute("SELECT * FROM logs_acoes_departamento WHERE acao IN ('Mesa Fechada', 'Cancelamento Mesa', 'Venda Balcao')")
        for row in cursor.fetchall():
            log_entry = dict(row)
            ts = parse_timestamp(log_entry['timestamp'])
            if ts and ts >= START_DATE:
                logs.append(log_entry)
        conn.close()
    
    print(f"Total de logs de fechamento/cancelamento encontrados: {len(logs)}")

    # 3. Analyze Disparities
    
    # Map Sales by ID/Keys for quick lookup
    sales_map = {}
    for s in relevant_sales:
        # Key 1: close_id
        if s.get('close_id'):
            sales_map[s.get('close_id')] = s
        
        # Key 2: Heuristic (Table + Time)
        # We store in a list because multiple sales for same table possible
        tid = s.get('table_id') or s.get('room_number') or s.get('customer_name')
        if tid:
            k = f"TABLE_{tid}"
            if k not in sales_map: sales_map[k] = []
            sales_map[k].append(s)

    disparities = []

    # Check 1: Log exists but no Sale?
    for log in logs:
        log_ts = parse_timestamp(log['timestamp'])
        details = log.get('detalhes', '') or ''
        action = log['acao']
        
        table_id = extract_table_from_log(details)
        log_total = extract_total_from_log(details)
        
        if action == 'Cancelamento Mesa':
            # Check if this cancellation is reflected? 
            # Usually cancellations remove from history, so we expect NOT to find it in "open" or "closed" sales,
            # BUT maybe we should track if it was a "silent" cancellation vs one that logged.
            # Here we are looking for MISSING sales mainly.
            continue
            
        if action == 'Mesa Fechada':
            found = False
            
            # Search in sales_map
            # 1. By table/time
            if table_id:
                candidates = sales_map.get(f"TABLE_{table_id}", [])
                for sale in candidates:
                    sale_ts = parse_timestamp(sale.get('closed_at'))
                    if sale_ts and abs((sale_ts - log_ts).total_seconds()) < 300: # 5 min tolerance
                        found = True
                        break
                        
                    # Also check total match if time is off but same day
                    sale_total = float(sale.get('total', 0))
                    if log_total is not None and abs(sale_total - log_total) < 0.1:
                        # Check if same day
                        if sale_ts and sale_ts.date() == log_ts.date():
                            found = True
                            break
            
            if not found:
                # Deep search in all relevant sales (slow but thorough)
                for sale in relevant_sales:
                    sale_ts = parse_timestamp(sale.get('closed_at'))
                    if not sale_ts: continue
                    
                    # Match Time + Total
                    time_match = abs((sale_ts - log_ts).total_seconds()) < 120
                    
                    sale_total = float(sale.get('final_total', sale.get('total', 0)))
                    total_match = False
                    if log_total is not None:
                         total_match = abs(sale_total - log_total) < 0.5
                    
                    if time_match and (total_match or not log_total):
                        found = True
                        break
            
            if not found:
                disparities.append({
                    'type': 'MISSING_IN_HISTORY',
                    'log_id': log['id'],
                    'timestamp': log['timestamp'],
                    'action': action,
                    'details': details,
                    'table_id': table_id,
                    'log_total': log_total
                })

    # Check 2: Sale exists but no Log? (Less critical, but good for audit)
    for sale in relevant_sales:
        if sale.get('status') != 'closed':
            continue
            
        sale_ts = parse_timestamp(sale.get('closed_at'))
        if not sale_ts: continue
        
        sale_total = float(sale.get('final_total', sale.get('total', 0)))
        table_id = sale.get('table_id') or sale.get('room_number')
        
        found_log = False
        for log in logs:
            log_ts = parse_timestamp(log['timestamp'])
            if abs((log_ts - sale_ts).total_seconds()) < 300: # 5 min
                # Check table
                log_details = log.get('detalhes', '')
                log_table = extract_table_from_log(log_details)
                
                if str(log_table) == str(table_id):
                    found_log = True
                    break
        
        if not found_log:
            # Maybe it was recovered by script?
            if sale.get('recovered_via'):
                continue # Known recovery
                
            disparities.append({
                'type': 'MISSING_IN_LOGS',
                'sale_id': sale.get('id') or sale.get('close_id'),
                'timestamp': sale.get('closed_at'),
                'table_id': table_id,
                'total': sale_total
            })

    # Report
    print("\n=== RELATÓRIO DE DISPARIDADES ===")
    if not disparities:
        print("Nenhuma disparidade encontrada. Logs e Histórico estão consistentes.")
    else:
        print(f"Encontradas {len(disparities)} disparidades.")
        for d in disparities:
            print("-" * 40)
            if d['type'] == 'MISSING_IN_HISTORY':
                print(f"[CRÍTICO] Log de Fechamento sem Venda no Histórico")
                print(f"  Data: {d['timestamp']}")
                print(f"  Mesa: {d['table_id']}")
                print(f"  Total Log: {d['log_total']}")
                print(f"  Detalhes: {d['details']}")
            elif d['type'] == 'MISSING_IN_LOGS':
                print(f"[AVISO] Venda no Histórico sem Log de Fechamento")
                print(f"  Data: {d['timestamp']}")
                print(f"  Mesa: {d['table_id']}")
                print(f"  Total: {d['total']}")

if __name__ == "__main__":
    main()
