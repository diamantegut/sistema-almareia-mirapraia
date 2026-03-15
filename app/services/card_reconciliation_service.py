import pandas as pd
import json
import os
from datetime import datetime, timedelta
import re
import itertools
import requests
import xml.etree.ElementTree as ET
import base64

from app.services.system_config_manager import get_data_path

# Configuration
SETTINGS_FILE = get_data_path('card_settings.json')
RECONCILIATION_AUDIT_FILE = get_data_path('card_reconciliation_audit.json')

def load_card_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_card_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_reconciliation_audits():
    if not os.path.exists(RECONCILIATION_AUDIT_FILE):
        return []
    try:
        with open(RECONCILIATION_AUDIT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_reconciliation_audits(audits):
    with open(RECONCILIATION_AUDIT_FILE, 'w', encoding='utf-8') as f:
        json.dump(audits, f, indent=2, ensure_ascii=False)


def append_reconciliation_audit(audit_entry):
    audits = load_reconciliation_audits()
    audits.append(audit_entry)
    if len(audits) > 2000:
        audits = audits[-2000:]
    save_reconciliation_audits(audits)

def fetch_pagseguro_transactions(start_date, end_date):
    """
    Fetches transactions from PagSeguro API V3 (XML).
    Iterates over all configured accounts.
    Args:
        start_date (datetime): Start of range.
        end_date (datetime): End of range.
    """
    settings = load_card_settings()
    ps_config_list = settings.get('pagseguro', [])
    
    # Backward compatibility: handle if it's a dict (old format)
    if isinstance(ps_config_list, dict):
        ps_config_list = [ps_config_list]
        
    all_transactions = []

    for idx, ps_config in enumerate(ps_config_list):
        email = ps_config.get('email')
        token = ps_config.get('token')
        sandbox = ps_config.get('sandbox', False)
        alias = ps_config.get('alias', f'Conta {idx+1}')
        
        print(f"Processing PagSeguro account: {alias}")
        
        if not email or not token:
            print(f"PagSeguro credentials missing for {alias}.")
            continue

        # API Endpoint
        base_url = "https://ws.pagseguro.uol.com.br/v3/transactions"
        if sandbox:
            base_url = "https://ws.sandbox.pagseguro.uol.com.br/v3/transactions"
            
        # Format dates: YYYY-MM-DDThh:mm (max range 30 days)
        initial_date = start_date.strftime('%Y-%m-%dT%H:%M')
        final_date = end_date.strftime('%Y-%m-%dT%H:%M')
        
        params = {
            'email': email,
            'token': token,
            'initialDate': initial_date,
            'finalDate': final_date,
            'maxPageResults': 100
        }
        
        page = 1
        
        while True:
            params['page'] = page
            try:
                response = requests.get(base_url, params=params)
                
                if response.status_code != 200:
                    print(f"PagSeguro API Error ({alias}): {response.status_code} - {response.text}")
                    break
                    
                # Parse XML
                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError:
                    print(f"PagSeguro XML Parse Error ({alias})")
                    break
                
                # Extract Transactions
                tx_nodes = root.findall('.//transaction')
                if not tx_nodes:
                    break
                    
                for tx in tx_nodes:
                    try:
                        status = tx.find('status').text # 1=Aguardando, 3=Paga, 4=Disponível, 7=Cancelada
                        if status == '7': continue # Skip cancelled
                        
                        date_str = tx.find('date').text 
                        date_str = date_str.split('.')[0]
                        dt = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S')
                        
                        amount = float(tx.find('grossAmount').text)
                        type_code = tx.find('paymentMethod/type').text 
                        
                        all_transactions.append({
                            'provider': f'PagSeguro ({alias})',
                            'date': dt,
                            'amount': float(amount),
                            'type': type_code,
                            'status': status,
                            'original_row': {'code': tx.find('code').text, 'status': status, 'account': alias}
                        })
                    except Exception as e:
                        print(f"Error parsing XML transaction ({alias}): {e}")
                        continue
                
                # Check pagination
                current_page_node = root.find('currentPage')
                total_pages_node = root.find('totalPages')
                
                if current_page_node is not None and total_pages_node is not None:
                    current_page = int(current_page_node.text)
                    total_pages = int(total_pages_node.text)
                    
                    if current_page >= total_pages:
                        break
                else:
                    break
                    
                page += 1
                
            except Exception as e:
                print(f"PagSeguro Request Failed ({alias}): {e}")
                break
            
    return all_transactions

def fetch_rede_transactions(start_date, end_date):
    """
    Fetches transactions from Rede API (Gestão de Vendas).
    Iterates over all configured accounts.
    Requires OAuth2 authentication.
    """
    settings = load_card_settings()
    rede_config_list = settings.get('rede', [])
    
    # Backward compatibility
    if isinstance(rede_config_list, dict):
        rede_config_list = [rede_config_list]
        
    all_transactions = []
    
    for idx, rede_config in enumerate(rede_config_list):
        client_id = rede_config.get('client_id')
        client_secret = rede_config.get('client_secret')
        username = rede_config.get('username')
        password = rede_config.get('password')
        alias = rede_config.get('alias', f'Conta {idx+1}')
        
        print(f"Processing Rede account: {alias}")
        
        if not client_id or not client_secret or not username or not password:
            print(f"Rede credentials missing for {alias}.")
            continue

        # 1. Get Access Token
        token_url = "https://api.userede.com.br/redelabs/oauth/token"
        
        auth_str = f"{client_id}:{client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {b64_auth}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'password',
            'username': username,
            'password': password
        }
        
        try:
            resp = requests.post(token_url, headers=headers, data=data)
            if resp.status_code != 200:
                print(f"Rede Auth Failed ({alias}): {resp.text}")
                continue
                
            token_data = resp.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                print(f"Rede: No access token returned for {alias}.")
                continue
                
            # 2. Fetch Sales
            sales_url = "https://api.userede.com.br/redelabs/merchant-sales/v1/sales"
            
            params = {
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d')
            }
            
            headers_api = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            resp_sales = requests.get(sales_url, headers=headers_api, params=params)
            
            if resp_sales.status_code != 200:
                 print(f"Rede Sales Fetch Failed ({alias}): {resp_sales.text}")
                 continue
                 
            sales_data = resp_sales.json()
            
            items = sales_data.get('sales', []) if isinstance(sales_data, dict) else sales_data
            if not isinstance(items, list):
                 items = []

            for item in items:
                try:
                    date_str = item.get('saleDate') or item.get('date')
                    amount = float(item.get('amount', 0))
                    
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    
                    all_transactions.append({
                        'provider': f'Rede ({alias})',
                        'date': dt,
                        'amount': amount,
                        'type': 'Card',
                        'original_row': item
                    })
                except Exception as e:
                    print(f"Error parsing Rede item ({alias}): {e}")
                    continue
                
        except Exception as e:
            print(f"Rede API Exception ({alias}): {e}")
            continue
            
    return all_transactions

def parse_pagseguro_csv(file_path):
    """
    Parses PagSeguro CSV export.
    Expected columns (example): 'Data', 'Hora', 'Tipo', 'Valor Bruto', 'Bandeira'
    Returns list of dicts: {'date': datetime, 'amount': float, 'type': str, 'brand': str}
    """
    try:
        # PagSeguro often uses specific encoding like iso-8859-1 for PT-BR
        df = pd.read_csv(file_path, encoding='iso-8859-1', sep=';') # Semicolon is common in BR CSVs
        if 'Data' not in df.columns:
             df = pd.read_csv(file_path, encoding='iso-8859-1', sep=',') # Try comma
        
        transactions = []
        for _, row in df.iterrows():
            try:
                # Adjust column names based on actual file format
                # This is a heuristic based on common PagSeguro formats
                date_str = row.get('Data', '') or row.get('Data da Transação', '')
                time_str = row.get('Hora', '') or row.get('Hora da Transação', '')
                amount_str = str(row.get('Valor Bruto', '') or row.get('Valor', '0'))
                type_str = row.get('Tipo', '') or row.get('Meio de Pagamento', '')
                
                # Clean amount (R$ 1.234,56 -> 1234.56)
                amount_str = amount_str.replace('R$', '').replace('.', '').replace(',', '.').strip()
                amount = float(amount_str)
                
                # Combine Date/Time
                dt_str = f"{date_str} {time_str}".strip()
                try:
                    dt = datetime.strptime(dt_str, '%d/%m/%Y %H:%M:%S')
                except:
                    dt = datetime.strptime(date_str, '%d/%m/%Y') # Fallback if no time
                
                transactions.append({
                    'provider': 'PagSeguro',
                    'date': dt,
                    'amount': abs(amount), # Ensure positive
                    'type': type_str,
                    'original_row': row.to_dict()
                })
            except Exception as e:
                print(f"Error parsing row: {e}")
                continue
                
        return transactions
    except Exception as e:
        print(f"Failed to parse PagSeguro file: {e}")
        return []

def parse_rede_csv(file_path):
    """
    Parses Rede (RedeCard) CSV export.
    """
    try:
        df = pd.read_csv(file_path, encoding='iso-8859-1', sep=';')
        if 'Data' not in df.columns:
             df = pd.read_csv(file_path, encoding='iso-8859-1', sep=',')

        transactions = []
        for _, row in df.iterrows():
            try:
                # Heuristic for Rede columns
                date_str = row.get('Data Venda', '') or row.get('Data', '')
                amount_str = str(row.get('Valor Bruto', '') or row.get('Valor', '0'))
                
                amount_str = amount_str.replace('R$', '').replace('.', '').replace(',', '.').strip()
                amount = float(amount_str)
                
                try:
                    dt = datetime.strptime(date_str, '%d/%m/%Y')
                except:
                    continue
                    
                transactions.append({
                    'provider': 'Rede',
                    'date': dt, # Rede often doesn't have time in basic exports, just date
                    'amount': abs(amount),
                    'type': 'Card',
                    'original_row': row.to_dict()
                })
            except Exception as e:
                continue
        return transactions
    except Exception as e:
        print(f"Failed to parse Rede file: {e}")
        return []

def _is_card_time_match(sys_time, card_time, tolerance_mins):
    if card_time.hour == 0 and card_time.minute == 0:
        return sys_time.date() == card_time.date()
    time_diff = abs((sys_time - card_time).total_seconds()) / 60
    return time_diff <= tolerance_mins


def _build_grouped_system_transaction(grouped_items):
    grouped_sorted = sorted(grouped_items, key=lambda x: x.get('timestamp', datetime.min))
    amount = round(sum(float(i.get('amount', 0.0) or 0.0) for i in grouped_sorted), 2)
    first_item = grouped_sorted[0] if grouped_sorted else {}
    return {
        'id': f"GROUP_{first_item.get('id', 'NA')}",
        'timestamp': first_item.get('timestamp', datetime.now()),
        'amount': amount,
        'description': f"Pagamento Agrupado ({len(grouped_sorted)} lançamentos)",
        'payment_method': 'Múltiplo',
        'grouped_ids': [i.get('id') for i in grouped_sorted]
    }


def _find_combination_match(system_items, target_amount, card_time, tolerance_mins, tolerance_val, max_group_size=4):
    if not system_items:
        return None

    ordered = sorted(system_items, key=lambda x: x.get('timestamp', datetime.min))
    limited = ordered[:12]

    for size in range(2, min(max_group_size, len(limited)) + 1):
        for combo in itertools.combinations(limited, size):
            combo_sum = round(sum(float(t.get('amount', 0.0) or 0.0) for t in combo), 2)
            if abs(combo_sum - target_amount) > tolerance_val:
                continue
            if not all(_is_card_time_match(t.get('timestamp'), card_time, tolerance_mins) for t in combo):
                continue
            return list(combo)
    return None


def reconcile_transactions(system_transactions, card_transactions, tolerance_mins=60, tolerance_val=0.05):
    """
    Matches system transactions with card transactions.
    
    Args:
        system_transactions: list of dict {'amount', 'timestamp' (datetime), 'id'}
        card_transactions: list of dict {'amount', 'date' (datetime), 'provider'}
        tolerance_mins: time difference tolerance (Rede often has no time, so check date only?)
        tolerance_val: monetary difference tolerance
        
    Returns:
        matched: list of matches
        unmatched_system: list
        unmatched_card: list
    """
    
    matched = []
    unmatched_system = system_transactions[:] # Copy
    unmatched_card = card_transactions[:] # Copy
    
    for sys_tx in list(unmatched_system):
        best_match = None
        best_match_idx = -1
        
        sys_time = sys_tx['timestamp']
        sys_amount = sys_tx['amount']
        
        for i, card_tx in enumerate(unmatched_card):
            card_time = card_tx['date']
            card_amount = card_tx['amount']
            
            if abs(sys_amount - card_amount) <= tolerance_val:
                if _is_card_time_match(sys_time, card_time, tolerance_mins):
                    best_match = card_tx
                    best_match_idx = i
                    break
        
        if best_match:
            matched.append({
                'system': sys_tx,
                'card': best_match,
                'status': 'matched'
            })
            unmatched_system.remove(sys_tx)
            del unmatched_card[best_match_idx]

    grouped_by_payment = {}
    for sys_tx in unmatched_system:
        details = sys_tx.get('details') or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {}
        group_id = details.get('payment_group_id')
        if group_id:
            grouped_by_payment.setdefault(group_id, []).append(sys_tx)

    for group_id, group_items in list(grouped_by_payment.items()):
        if len(group_items) < 2:
            continue
        system_group_tx = _build_grouped_system_transaction(group_items)
        group_amount = system_group_tx['amount']
        group_time = system_group_tx['timestamp']
        matched_idx = -1
        matched_card = None

        for i, card_tx in enumerate(unmatched_card):
            if abs(group_amount - float(card_tx.get('amount', 0.0) or 0.0)) <= tolerance_val and _is_card_time_match(group_time, card_tx['date'], tolerance_mins):
                matched_idx = i
                matched_card = card_tx
                break

        if matched_card is None:
            continue

        matched.append({
            'system': system_group_tx,
            'system_items': group_items,
            'card': matched_card,
            'status': 'matched_group'
        })

        for item in group_items:
            if item in unmatched_system:
                unmatched_system.remove(item)
        del unmatched_card[matched_idx]

    for card_tx in list(unmatched_card):
        combo = _find_combination_match(
            system_items=unmatched_system,
            target_amount=float(card_tx.get('amount', 0.0) or 0.0),
            card_time=card_tx['date'],
            tolerance_mins=tolerance_mins,
            tolerance_val=tolerance_val
        )
        if not combo:
            continue

        system_group_tx = _build_grouped_system_transaction(combo)
        matched.append({
            'system': system_group_tx,
            'system_items': combo,
            'card': card_tx,
            'status': 'matched_group'
        })

        for item in combo:
            if item in unmatched_system:
                unmatched_system.remove(item)
        if card_tx in unmatched_card:
            unmatched_card.remove(card_tx)
            
    return {
        'matched': matched,
        'unmatched_system': unmatched_system,
        'unmatched_card': unmatched_card
    }
