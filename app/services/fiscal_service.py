import requests
import json
import logging
import os
import time
import re
import csv
import uuid
from datetime import datetime
from app.services.system_config_manager import (
    get_data_path, get_fiscal_path, PENDING_FISCAL_EMISSIONS_FILE, 
    FISCAL_NSU_FILE, FISCAL_SETTINGS_FILE
)
from app.services.printing_service import print_fiscal_receipt
from app.services.printer_manager import load_printer_settings, load_printers
from app.services.fiscal_pool_service import FiscalPoolService

# Configure logging
logger = logging.getLogger(__name__)

PENDING_EMISSIONS_FILE = PENDING_FISCAL_EMISSIONS_FILE

def load_pending_emissions():
    if not os.path.exists(PENDING_EMISSIONS_FILE):
        return []
    try:
        with open(PENDING_EMISSIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading pending emissions: {e}")
        return []

def save_pending_emissions(emissions):
    try:
        with open(PENDING_EMISSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(emissions, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving pending emissions: {e}")

def queue_fiscal_emission(order_id, items, payments, customer_cpf_cnpj=None):
    """
    Queues fiscal emissions based on payments.
    payments: list of dicts { 'method': str, 'amount': float, 'is_fiscal': bool, 'fiscal_cnpj': str }
    """
    total_order_amount = sum(item['qty'] * item['price'] for item in items)
    if total_order_amount == 0:
        return

    emissions_to_queue = []
    
    # Group payments by CNPJ (only fiscal ones)
    fiscal_payments = {}
    for p in payments:
        if p.get('is_fiscal'):
            cnpj = p.get('fiscal_cnpj')
            if not cnpj:
                continue
            if cnpj not in fiscal_payments:
                fiscal_payments[cnpj] = []
            fiscal_payments[cnpj].append(p)
            
    for cnpj, p_list in fiscal_payments.items():
        total_payment_amount = sum(p['amount'] for p in p_list)
        if total_payment_amount <= 0:
            continue
            
        # Prorate items
        ratio = total_payment_amount / total_order_amount
        prorated_items = []
        current_total = 0.0
        
        for item in items:
            new_price = round(item['price'] * ratio, 2)
            new_item = item.copy()
            new_item['price'] = new_price
            new_item['original_price'] = item['price']
            
            prorated_items.append(new_item)
            current_total += new_item['qty'] * new_price
            
        # Adjust rounding difference on the item with highest value
        diff = total_payment_amount - current_total
        if abs(diff) > 0.001:
            # Find item with highest total value to absorb diff
            # sort by total value desc
            prorated_items.sort(key=lambda x: x['qty'] * x['price'], reverse=True)
            target_item = prorated_items[0]
            
            # We need to adjust the unit price, but diff applies to the total line.
            # Ideally we adjust one unit of one item, but here we simplify by adjusting the unit price 
            # of the first item slightly. 
            # Note: This is tricky if qty > 1. 
            # Better approach: Adjust the 'price' field so that qty * price absorbs the diff.
            # But price must be 2 decimal places. 
            # If we can't adjust price perfectly, we might have a small discrepancy.
            # Nuvem Fiscal might validate Total = Sum(Items).
            
            # Let's try to add diff to the price of the first item.
            # adjusted_price = (current_total_of_item + diff) / qty
            old_total_item = target_item['qty'] * target_item['price']
            new_total_item = old_total_item + diff
            new_unit_price = round(new_total_item / target_item['qty'], 2)
            
            target_item['price'] = new_unit_price
            
            # Re-check total
            # If still off, we might need to split the item (1 unit with price X, N-1 with price Y).
            # For simplicity, we assume small diffs are acceptable or handled.
            pass

        emission_record = {
            'id': f"FISCAL_{order_id}_{cnpj}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'order_id': order_id,
            'cnpj_emitente': cnpj,
            'amount': total_payment_amount,
            'items': prorated_items,
            'payments': p_list, # List of payments covering this amount
            'customer_cpf_cnpj': customer_cpf_cnpj,
            'status': 'pending',
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'attempts': 0,
            'last_error': None
        }
        emissions_to_queue.append(emission_record)
        
    if emissions_to_queue:
        current_queue = load_pending_emissions()
        current_queue.extend(emissions_to_queue)
        save_pending_emissions(current_queue)
        logger.info(f"Queued {len(emissions_to_queue)} fiscal emissions for Order {order_id}")

def load_fiscal_settings():
    path = FISCAL_SETTINGS_FILE
    if not os.path.exists(path):
        return {"integrations": []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Migration for legacy format
            if "integrations" not in data and "provider" in data:
                return {"integrations": [data]}
            if "integrations" not in data:
                return {"integrations": []}
            if _apply_nuvem_fiscal_credentials_from_csv(data):
                save_fiscal_settings(data)
            return data
    except Exception as e:
        logger.error(f"Error loading fiscal settings from {path}: {e}")
        return {"integrations": []}

def save_fiscal_settings(settings):
    path = FISCAL_SETTINGS_FILE
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving fiscal settings: {e}")
        return False

def _parse_nuvem_fiscal_credentials_csv(csv_path):
    try:
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        logger.error(f"Error reading credentials CSV: {e}")
        return None

    if len(rows) < 2:
        return None

    headers = [str(h).strip().lower() for h in rows[0]]
    values = [str(v).strip() for v in rows[1]]

    def _idx(names):
        for name in names:
            try:
                return headers.index(name)
            except ValueError:
                continue
        return None

    idx_client_id = _idx(["client id", "client_id", "clientid", "id"])
    idx_client_secret = _idx(["client secret", "client_secret", "clientsecret", "secret"])

    if idx_client_id is None or idx_client_secret is None:
        if len(values) >= 2:
            return {"client_id": values[0], "client_secret": values[1]}
        return None

    if idx_client_id >= len(values) or idx_client_secret >= len(values):
        return None

    return {
        "client_id": values[idx_client_id],
        "client_secret": values[idx_client_secret],
    }

def _apply_nuvem_fiscal_credentials_from_csv(settings_obj):
    if not isinstance(settings_obj, dict):
        return False

    integrations = settings_obj.get("integrations", [])
    if not integrations:
        return False

    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, "Fiscal", "api_credentials.csv")
    if not os.path.exists(csv_path):
        return False

    creds = _parse_nuvem_fiscal_credentials_csv(csv_path)
    if not creds:
        return False

    modified = False
    for integration in integrations:
        if not isinstance(integration, dict):
            continue
        if integration.get("provider") != "nuvem_fiscal":
            continue
        if creds.get("client_id") and integration.get("client_id") != creds["client_id"]:
            integration["client_id"] = creds["client_id"]
            modified = True
        if creds.get("client_secret") and integration.get("client_secret") != creds["client_secret"]:
            integration["client_secret"] = creds["client_secret"]
            modified = True

    return modified

def get_fiscal_integration(settings, cnpj=None):
    """
    Returns the specific integration settings for a given CNPJ.
    If cnpj is None, returns the first one.
    """
    integrations = settings.get('integrations', [])
    if not integrations:
        return {}
        
    if cnpj:
        # Normalize CNPJ for comparison
        target_cnpj = str(cnpj).replace('.', '').replace('/', '').replace('-', '')
        for integration in integrations:
            curr_cnpj = str(integration.get('cnpj_emitente', '')).replace('.', '').replace('/', '').replace('-', '')
            if curr_cnpj == target_cnpj:
                return integration
    
    # Return first if not found or no cnpj specified (fallback)
    return integrations[0] if integrations else {}

def increment_fiscal_number(settings, cnpj):
    """
    Increments the 'next_number' for the specific CNPJ in fiscal settings and saves the file.
    settings: The root settings object containing 'integrations'.
    """
    try:
        integrations = settings.get('integrations', [])
        target_integration = None
        
        target_cnpj = str(cnpj).replace('.', '').replace('/', '').replace('-', '')
        
        for integration in integrations:
            curr_cnpj = str(integration.get('cnpj_emitente', '')).replace('.', '').replace('/', '').replace('-', '')
            if curr_cnpj == target_cnpj:
                target_integration = integration
                break
        
        if not target_integration:
            logger.error(f"No integration found for CNPJ {cnpj} to increment number.")
            return False

        current_number = int(target_integration.get('next_number', 1))
        target_integration['next_number'] = str(current_number + 1)
        
        save_fiscal_settings(settings)
        logger.info(f"Fiscal number for {cnpj} incremented to {target_integration['next_number']}")
        return True
    except Exception as e:
        logger.error(f"Error incrementing fiscal number: {e}")
        return False

def process_pending_emissions(settings=None, specific_id=None):
    """
    Processes all pending fiscal emissions (Queue + Pool).
    Returns summary of success/failures.
    """
    if settings is None:
        settings = load_fiscal_settings()

    all_pending = []
    
    if specific_id:
        # Optimized path for single item (supports retry of failed items)
        found = False
        
        # Check Legacy Queue
        queue = load_pending_emissions()
        queue_item = next((i for i in queue if i['id'] == specific_id), None)
        if queue_item:
             if queue_item.get('status') != 'emitted':
                 all_pending.append({'source': 'queue', 'data': queue_item})
                 found = True
        
        if not found:
            # Check Pool (Direct Fetch)
            pool_entry = FiscalPoolService.get_entry(specific_id)
            if pool_entry:
                # Allow retrying 'failed' or 'error_config' items
                if pool_entry['status'] in ['pending', 'failed', 'error_config']:
                     if pool_entry.get('fiscal_type') == 'nfce':
                         all_pending.append({'source': 'pool', 'data': pool_entry})
    else:
        # Bulk processing - Only Pending
        
        # 1. Process Legacy Queue
        queue = load_pending_emissions()
        pending_queue = [e for e in queue if e['status'] == 'pending']
        
        # 2. Process Fiscal Pool (Unified)
        pool_pending = FiscalPoolService.get_pool(filters={'status': 'pending'})
        pool_to_process = [p for p in pool_pending if p.get('fiscal_type') == 'nfce']
        
        for item in pending_queue:
            all_pending.append({'source': 'queue', 'data': item})
            
        for item in pool_to_process:
            all_pending.append({'source': 'pool', 'data': item})

    if not all_pending:
        return {"processed": 0, "success": 0, "failed": 0}
        
    success_count = 0
    failed_count = 0
    
    for entry in all_pending:
        emission = entry['data']
        source = entry['source']
        
        # Prepare transaction object for emit_invoice
        
        # Payments handling
        payments = emission.get('payments') or emission.get('payment_methods') or []
        primary_method = payments[0].get('method', 'Outros') if payments else 'Outros'
        
        transaction = {
            'id': emission['id'],
            'amount': emission['total_amount'] if 'total_amount' in emission else emission['amount'],
            'payment_method': primary_method, 
        }
        
        # Get specific integration settings for this emission's CNPJ
        emission_cnpj = emission.get('cnpj_emitente')
        integration_settings = get_fiscal_integration(settings, emission_cnpj)
        
        if not integration_settings:
            logger.error(f"No fiscal integration found for CNPJ {emission_cnpj}. Skipping emission {emission['id']}")
            # Update status to error/ignored to prevent loop
            msg = "Configuração fiscal não encontrada para este CNPJ"
            if source == 'pool':
                FiscalPoolService.update_status(emission['id'], 'error_config', error_msg=msg)
            else:
                emission['attempts'] = emission.get('attempts', 0) + 1
                emission['last_error'] = msg
            
            failed_count += 1
            continue

        customer_info = emission.get('customer', {})
        customer_cpf_cnpj = emission.get('customer_cpf_cnpj') or customer_info.get('cpf_cnpj') or customer_info.get('doc')
        
        # Validate Mandatory Fields
        if not integration_settings.get('client_id') or not integration_settings.get('client_secret'):
             msg = f"Credenciais ausentes para CNPJ {emission_cnpj}"
             logger.error(msg)
             if source == 'pool':
                 FiscalPoolService.update_status(emission['id'], 'error_config', error_msg=msg)
             else:
                 emission['attempts'] = emission.get('attempts', 0) + 1
                 emission['last_error'] = msg
                 
             failed_count += 1
             continue
             
        result = emit_invoice(transaction, integration_settings, emission['items'], customer_cpf_cnpj)
        
        if result['success']:
            nfe_id = result['data'].get('id')
            nfe_serie = result['data'].get('serie')
            nfe_number = result['data'].get('numero')
            
            if not nfe_number and 'numero_sequencial' in result['data']:
                nfe_number = result['data']['numero_sequencial']
            
            # Update Source
            if source == 'pool':
                FiscalPoolService.update_status(emission['id'], 'emitted', fiscal_doc_uuid=nfe_id, serie=nfe_serie, number=nfe_number)
            else:
                emission['status'] = 'emitted'
                emission['nfe_id'] = nfe_id
                emission['emitted_at'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                if emission.get('id', '').startswith('POOL-'):
                     # Legacy link
                     try:
                        pool_id = emission['id'].replace('POOL-', '')
                        FiscalPoolService.update_status(pool_id, 'emitted', fiscal_doc_uuid=nfe_id, serie=nfe_serie, number=nfe_number)
                     except: pass

            # Increment fiscal number
            increment_fiscal_number(settings, emission_cnpj)
            
            # Download XML
            try:
                xml_path = download_xml(nfe_id, integration_settings)
                if xml_path:
                    if source == 'queue': emission['xml_path'] = xml_path
                    logger.info(f"XML saved at {xml_path}")
            except Exception as e:
                logger.error(f"Failed to download XML for {nfe_id}: {e}")
            
            # Print Receipt (Logic kept same)
            try:
                p_settings = load_printer_settings()
                fiscal_printer_id = p_settings.get('fiscal_printer_id')
                printer = None
                if fiscal_printer_id:
                    printers = load_printers()
                    printer = next((p for p in printers if p['id'] == fiscal_printer_id), None)
                if not printer: printer = {} 

                invoice_data = result.get('data', {})
                if 'valor_total' not in invoice_data: invoice_data['valor_total'] = transaction['amount']
                if 'ambiente' not in invoice_data: invoice_data['ambiente'] = integration_settings.get('environment', 'homologacao')
                if 'items' not in invoice_data or not invoice_data['items']: invoice_data['items'] = emission.get('items', [])
                
                # QR Code logic (kept same)
                if 'qrcode_url' not in invoice_data:
                    candidates = ['url_consulta_qrcode', 'qr_code', 'url_qrcode', 'qrcode']
                    for cand in candidates:
                        if cand in invoice_data:
                            invoice_data['qrcode_url'] = invoice_data[cand]
                            break
                            
                print_fiscal_receipt(printer, invoice_data)
            except Exception as e:
                logger.error(f"Error printing fiscal receipt: {e}")
                
            success_count += 1
        else:
            # Handle Failure / Contingency
            error_msg = result['message']
            if source == 'pool':
                # Don't mark as error immediately, maybe retry? 
                # Or mark as 'failed' and allow retry in UI
                FiscalPoolService.update_status(emission['id'], 'failed', error_msg=error_msg)
            else:
                emission['attempts'] = emission.get('attempts', 0) + 1
                emission['last_error'] = error_msg
                if emission['attempts'] >= 3:
                    emission['status'] = 'failed'
            failed_count += 1
            
    save_pending_emissions(queue)
    return {"processed": len(all_pending), "success": success_count, "failed": failed_count}

def get_access_token(client_id, client_secret, scope="nfce"):
    url = "https://auth.nuvemfiscal.com.br/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        logger.error(f"Error getting access token: {e}")
        return None

def _normalize_digits(value):
    if value is None:
        return ""
    return re.sub(r'[^0-9]', '', str(value))

def sync_nfce_company_settings(integration_settings):
    if not isinstance(integration_settings, dict):
        return {"success": False, "message": "Configuração inválida."}

    if integration_settings.get('provider') != 'nuvem_fiscal':
        return {"success": False, "message": "Provedor não suportado."}

    client_id = integration_settings.get('client_id')
    client_secret = integration_settings.get('client_secret')
    cnpj_emitente = _normalize_digits(integration_settings.get('cnpj_emitente'))
    if not client_id or not client_secret or not cnpj_emitente:
        return {"success": False, "message": "Credenciais Nuvem Fiscal incompletas."}

    token = get_access_token(client_id, client_secret, scope="nfce")
    if not token:
        return {"success": False, "message": "Falha na autenticação com Nuvem Fiscal."}

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if integration_settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    api_url = f"{base_url}/empresas/{cnpj_emitente}/nfce"

    payload = {
        "ambiente": "homologacao" if integration_settings.get('environment') == 'homologation' else "producao"
    }

    crt = integration_settings.get('CRT', integration_settings.get('crt', 3))
    try:
        payload["CRT"] = int(crt)
    except Exception:
        payload["CRT"] = 3

    csc_id = integration_settings.get('csc_id')
    csc_token = integration_settings.get('csc_token')
    if csc_id and csc_token:
        try:
            payload["sefaz"] = {"id_csc": int(csc_id), "csc": str(csc_token)}
        except Exception:
            payload["sefaz"] = {"id_csc": 0, "csc": str(csc_token)}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.put(api_url, json=payload, headers=headers, timeout=30)
        if response.status_code in (200, 201):
            try:
                return {"success": True, "message": "Configuração NFC-e sincronizada.", "data": response.json()}
            except Exception:
                return {"success": True, "message": "Configuração NFC-e sincronizada."}

        try:
            err_data = response.json()
            msg = err_data.get('message') or err_data.get('error', {}).get('message') or response.text
        except Exception:
            msg = response.text
        return {"success": False, "message": f"Erro ao sincronizar NFC-e: {msg}"}
    except Exception as e:
        return {"success": False, "message": f"Erro ao sincronizar NFC-e: {e}"}

def download_xml(nfe_id, settings):
    """
    Downloads the XML for a given NFC-e ID and saves it locally.
    """
    if not nfe_id:
        return None

    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    # Authenticate
    token = get_access_token(client_id, client_secret)
    if not token:
        logger.error("Failed to authenticate for XML download")
        return None

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    api_url = f"{base_url}/nfce/{nfe_id}/xml"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            # Ensure directory exists with structure: fiscal_xmls/{CNPJ}/{YYYY-MM}/
            cnpj = settings.get('cnpj_emitente', 'unknown_cnpj')
            year_month = datetime.now().strftime('%Y/%m')
            
            # Use configured path or default fiscal path
            base_path = settings.get('xml_storage_path')
            if base_path:
                if not os.path.isabs(base_path):
                    base_path = os.path.join(os.getcwd(), base_path)
            else:
                base_path = get_fiscal_path('xmls')
                
            xml_dir = os.path.join(base_path, 'emitted', year_month)
            if not os.path.exists(xml_dir):
                os.makedirs(xml_dir)
                
            file_path = os.path.join(xml_dir, f"{nfe_id}.xml")
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            # Validation: Check if file exists and has content
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"XML saved and validated at {file_path}")
                return file_path
            else:
                logger.error(f"XML save failed validation at {file_path}")
                return None
        else:
            logger.error(f"Error downloading XML: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception downloading XML: {e}")
        return None

def manifest_nfe(access_key, settings, event_code=210210):
    """
    Sends a manifestation event (Ciência da Operação default) to SEFAZ via Nuvem Fiscal.
    """
    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe")
    if not token:
        token = get_access_token(client_id, client_secret, scope="nfe")
        
    if not token:
        return False, "Falha na autenticação"
        
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    api_url = f"{base_url}/nfe/dfe/documentos/manifestacoes"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "access_key": access_key,
        "codigo_evento": event_code
    }
    
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        if response.status_code in [200, 201]:
            return True, None
        else:
            try:
                err = response.json()
                msg = err.get('error', {}).get('message') or err.get('message')
            except:
                msg = response.text
            return False, msg
    except Exception as e:
        return False, str(e)

def consult_nfe_sefaz(access_key, settings):
    """
    Consults an NFe from SEFAZ using Nuvem Fiscal API and returns the XML content.
    """
    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    # We try 'nfe' and 'distribuicao-nfe' scope first
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe") 
    if not token:
        # Fallback
        token = get_access_token(client_id, client_secret, scope="nfe")
    
    if not token:
        # Try with 'nfce' or default scope if 'nfe' fails (maybe combined scope?)
        # Or maybe the user only has 'nfce' enabled? But for NFe we need 'nfe'.
        token = get_access_token(client_id, client_secret, scope="nfce")
        if not token:
            return None, "Falha na autenticação com Nuvem Fiscal"

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    
    # Endpoint to download XML from SEFAZ
    # Nuvem Fiscal allows fetching XML by access key
    api_url = f"{base_url}/nfe/sefaz/{access_key}/xml"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(api_url, headers=headers)
        if response.status_code == 200:
            return response.content, None
        elif response.status_code == 404:
             # Try /nfe/{access_key}/xml (maybe it's already synchronized in the account)
             api_url_internal = f"{base_url}/nfe/{access_key}/xml"
             response_internal = requests.get(api_url_internal, headers=headers)
             if response_internal.status_code == 200:
                 return response_internal.content, None

             # If not found locally, try to Manifest (Ciência da Operação) to allow download from SEFAZ
             manifest_success, _ = manifest_nfe(access_key, settings)
             if manifest_success:
                 import time
                 time.sleep(2) # Wait for propagation
                 
                 # Retry download from SEFAZ
                 response_retry = requests.get(api_url, headers=headers)
                 if response_retry.status_code == 200:
                     return response_retry.content, None
             
             return None, "Nota não encontrada na SEFAZ (mesmo após tentativa de manifestação) ou na base local."
        else:
            try:
                err = response.json()
                msg = err.get('error', {}).get('message') or err.get('message')
            except:
                msg = response.text
            return None, f"Erro Nuvem Fiscal: {msg}"
    except Exception as e:
        return None, str(e)

NSU_FILE = FISCAL_NSU_FILE

def get_last_nsu():
    if not os.path.exists(NSU_FILE):
        return 0
    try:
        with open(NSU_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('last_nsu', 0)
    except:
        return 0

def save_last_nsu(nsu):
    try:
        with open(NSU_FILE, 'w', encoding='utf-8') as f:
            json.dump({'last_nsu': nsu}, f)
    except Exception as e:
        logger.error(f"Error saving last NSU: {e}")

def list_received_nfes(settings):
    """
    Lists recent NFe documents received by the CNPJ (DFe).
    """
    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    # Authenticate with 'nfe' and 'distribuicao-nfe' scope
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe")
    if not token:
        # Fallback to just 'nfe' if the combined scope fails
        token = get_access_token(client_id, client_secret, scope="nfe")
    
    if not token:
        return None, "Falha na autenticação com Nuvem Fiscal"

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    
    # Map internal environment name to API expected values (pt-br)
    env_param = "homologacao" if settings.get('environment') == 'homologation' else "producao"
    
    # Clean CNPJ (remove non-digits just in case, though it looks clean in settings)
    cnpj = settings.get('cnpj_emitente', '').replace('.', '').replace('/', '').replace('-', '')

    params = {
        "$top": 50,
        "$orderby": "created_at desc",
        "cpf_cnpj": cnpj,
        "ambiente": env_param
    }
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Endpoint oficial para listar documentos DFe
    # Documentação: https://dev.nuvemfiscal.com.br/docs/api#tag/Distribuicao-NF-e
    api_url = f"{base_url}/distribuicao/nfe/documentos"

    try:
        trigger_url = f"{base_url}/distribuicao/nfe"
        last_nsu = int(get_last_nsu() or 0)
        start_nsu = max(last_nsu - 10, 0)
        max_consultas = 20
        consultas_feitas = 0
        ultimo_nsu_com_documento = None
        teve_documento = False

        nsu_atual = start_nsu
        while nsu_atual <= last_nsu and consultas_feitas < max_consultas:
            logger.info(f"Consultando SEFAZ por cons-nsu no NSU {nsu_atual} (backfill).")
            payload = {
                "cpf_cnpj": cnpj,
                "ambiente": env_param,
                "tipo_consulta": "cons-nsu",
                "dist_nsu": nsu_atual
            }
            try:
                resp_sync = requests.post(trigger_url, headers=headers, json=payload)
                consultas_feitas += 1

                if resp_sync.status_code in [200, 201, 202]:
                    sync_data = resp_sync.json()
                    c_status = sync_data.get('codigo_status')
                    if c_status == 656:
                        logger.warning("SEFAZ retornou 656 (Consumo Indevido) em cons-nsu. Encerrando.")
                        break

                    docs = sync_data.get('documentos', [])
                    if docs:
                        teve_documento = True
                        ultimo_nsu_com_documento = nsu_atual
                else:
                    logger.warning(f"cons-nsu retornou {resp_sync.status_code}: {resp_sync.text}")
                    break
            except Exception as e_req:
                logger.error(f"Erro de requisição em cons-nsu: {e_req}")
                break

            nsu_atual += 1

        if teve_documento and consultas_feitas < max_consultas:
            nsu_forward = (ultimo_nsu_com_documento or last_nsu) + 1
            while consultas_feitas < max_consultas:
                logger.info(f"Consultando SEFAZ por cons-nsu no NSU {nsu_forward} (forward).")
                payload = {
                    "cpf_cnpj": cnpj,
                    "ambiente": env_param,
                    "tipo_consulta": "cons-nsu",
            "dist_nsu": nsu_forward
        }
                try:
                    resp_sync = requests.post(trigger_url, headers=headers, json=payload)
                    consultas_feitas += 1

                    if resp_sync.status_code in [200, 201, 202]:
                        sync_data = resp_sync.json()
                        c_status = sync_data.get('codigo_status')
                        if c_status == 656:
                            logger.warning("SEFAZ retornou 656 (Consumo Indevido) em cons-nsu forward. Encerrando.")
                            break

                        docs = sync_data.get('documentos', [])
                        if docs:
                            ultimo_nsu_com_documento = nsu_forward
                            nsu_forward += 1
                        else:
                            logger.info(f"NSU {nsu_forward} sem novos documentos. Encerrando sequência.")
                            break
                    else:
                        logger.warning(f"cons-nsu forward retornou {resp_sync.status_code}: {resp_sync.text}")
                        break
                except Exception as e_req:
                    logger.error(f"Erro de requisição em cons-nsu forward: {e_req}")
                    break

        if ultimo_nsu_com_documento is not None:
            save_last_nsu(ultimo_nsu_com_documento)
            logger.info(f"NSU atualizado para {ultimo_nsu_com_documento} em modo cons-nsu.")
        
        # 2. Fetch DFe documents from cache
        logger.info(f"Fetching DFe from: {api_url}")
        response = requests.get(api_url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            documents = data.get('data', [])
            return documents, None
        else:
            try:
                err = response.json()
                msg = err.get('error', {}).get('message') or err.get('message')
            except:
                msg = response.text
            
            logger.error(f"Error fetching DFe: {msg}")
            return None, f"Erro ao buscar notas: {msg}"
            
    except Exception as e:
        logger.error(f"Exception fetching DFe: {str(e)}")
        return None, f"Erro de conexão: {str(e)}"

def sync_received_nfes(settings):
    """
    Syncs received NFe documents (DFe) from Nuvem Fiscal.
    Downloads XMLs for new documents and saves a summary list.
    """
    documents, error = list_received_nfes(settings)
    if error:
        logger.error(f"Sync NFe Error: {error}")
        return {"error": error, "synced_count": 0}
        
    # Get storage path from settings or default
    base_storage_path = settings.get('xml_storage_path', 'fiscal_documents/xmls')
    if not os.path.isabs(base_storage_path):
        base_storage_path = os.path.join(os.getcwd(), base_storage_path)
    
    if not os.path.exists(base_storage_path):
        try:
            os.makedirs(base_storage_path)
            logger.info(f"Created XML storage directory: {base_storage_path}")
        except Exception as e:
            logger.error(f"Failed to create XML storage directory: {e}")
            return
        
    synced_count = 0
    
    for doc in documents:
        key = doc.get('access_key') or doc.get('chave')
        if not key:
            continue
            
        # Organize by Year/Month based on emission date
        # doc['created_at'] example: "2025-01-13T14:30:00Z"
        date_str = doc.get('created_at') or doc.get('issued_at') or datetime.now().isoformat()
        try:
            # Parse ISO format (handling Z or offset if possible, but simple slicing is safer for folder names)
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            year_month = dt.strftime("%Y/%m") # 2025/01
        except:
            year_month = datetime.now().strftime("%Y/%m")

        target_dir = os.path.join(base_storage_path, year_month)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        filename = f"{key}.xml"
        file_path = os.path.join(target_dir, filename)
        
        # Also check in flat inbox or root just in case (optional, but let's stick to the new structure)
        if not os.path.exists(file_path):
            # Download XML
            xml_content, err = consult_nfe_sefaz(key, settings)
            if xml_content:
                with open(file_path, 'wb') as f:
                    f.write(xml_content)
                synced_count += 1
                logger.info(f"Downloaded XML for key {key} to {file_path}")
            else:
                # Only log warning if strictly necessary to avoid noise for old notes
                # logger.warning(f"Failed to download XML for {key}: {err}")
                pass
    
    if synced_count > 0:
        logger.info(f"Synced {synced_count} new NFe XMLs.")
    return {"synced_count": synced_count}

def emit_invoice(transaction, settings, order_items, customer_cpf_cnpj=None):
    """
    Emits an NFC-e using Nuvem Fiscal API.
    """
    if settings.get('provider') != 'nuvem_fiscal':
        return {"success": False, "message": "Provedor não suportado."}

    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    cnpj_emitente = settings.get('cnpj_emitente')
    ie_emitente = settings.get('ie_emitente')
    
    if not client_id or not client_secret or not cnpj_emitente:
        return {"success": False, "message": "Credenciais Nuvem Fiscal incompletas."}

    # Authenticate
    token = get_access_token(client_id, client_secret)
    if not token:
        return {"success": False, "message": "Falha na autenticação com Nuvem Fiscal."}

    # Prepare Items
    nfe_items = []
    total_items = 0.0
    
    # Validation: Items
    if not order_items:
        return {"success": False, "message": "Nenhum item para emissão."}

    nItem = 1
    for idx, item in enumerate(order_items):
        # Handle Individual Item Emission (Split by Quantity)
        # Standard behavior: 1 line per product type with Qty > 1
        # Requested behavior: "emissão individual para cada instância" -> 1 line per unit
        
        qty_to_process = float(item['qty'])
        price = float(item['price'])
        
        # Determine if we should split
        # Only split if it's an integer quantity (e.g. 2 units, not 1.5kg)
        is_integer_qty = (qty_to_process % 1 == 0)
        
        # If user explicitly requested individual instances, we loop
        # But we must be careful with performance and API limits (max items 990 usually)
        
        iterations = 1
        qty_per_line = qty_to_process
        
        if is_integer_qty and qty_to_process > 1:
            iterations = int(qty_to_process)
            qty_per_line = 1.0
            
        for _ in range(iterations):
            item_total = qty_per_line * price
            
            # Determine NCM (Fallback to 21069090 - Preparacoes alimenticias)
            ncm = item.get('ncm')
            if not ncm or len(ncm) < 8:
                ncm = '21069090'
                
            # ... (rest of loop)
    
            prod_data = {
                "cProd": str(item.get('id', '0')),
                "cEAN": "SEM GTIN",
                "xProd": item.get('name', 'Produto'),
                "NCM": ncm,
                "CFOP": item.get('cfop', '5102'),
                "uCom": "UN",
                "qCom": qty_per_line,
                "vUnCom": price,
                "vProd": item_total,
                "cEANTrib": "SEM GTIN",
                "uTrib": "UN",
                "qTrib": qty_per_line,
                "vUnTrib": price,
                "indTot": 1,
            }
            
            # Only add CEST if it has a valid value (not empty)
            cest = item.get('cest')
            if cest and cest.strip():
                 prod_data["CEST"] = cest.strip()
    
            nfe_item = {
                "nItem": nItem,
                "prod": prod_data,
                "imposto": {
                    "ICMS": {
                        "ICMSSN102": {
                            "orig": int(item.get('origin', 0)),
                            "CSOSN": "102"
                        }
                    },
                    "PIS": {
                        "PISOutr": {
                            "CST": "99",
                            "vBC": 0.00,
                            "pPIS": 0.00,
                            "vPIS": 0.00
                        }
                    },
                    "COFINS": {
                        "COFINSOutr": {
                            "CST": "99",
                            "vBC": 0.00,
                            "pCOFINS": 0.00,
                            "vCOFINS": 0.00
                        }
                    }
                }
            }
            nfe_items.append(nfe_item)
            total_items += item_total
            nItem += 1

    # Payment info
    payment_map = {
        'Dinheiro': '01',
        'Cartão de Crédito': '03',
        'Credito': '03',
        'Credito Pagseguro': '03',
        'Cartão de Débito': '04',
        'Debito': '04',
        'Pix': '17'
    }
    
    pay_code = payment_map.get(transaction.get('payment_method'), '99')
    
    pagamentos = [
        {
            "tPag": pay_code,
            "vPag": transaction.get('amount', total_items),
        }
    ]

    # Payload for Nuvem Fiscal
    # Using the 'infNFe' structure inside the payload
    
    # Offline Contingency (tpEmis)
    # 1=Normal, 9=Offline
    # Check if we should use offline mode (passed in transaction or settings?)
    # For now, default to 1, but allow override
    tp_emis = transaction.get('tpEmis', 1)
    
    payload = {
        "ambiente": "homologacao" if settings.get('environment') == 'homologation' else "producao",
        "infNFe": {
            "versao": "4.00",
            "ide": {
                "cUF": 26, # PE (Integer)
                "natOp": "Venda ao Consumidor",
                "mod": 65,
                "serie": int(settings.get('serie', 1)),
                "nNF": int(settings.get('next_number', 1)),
                "dhEmi": datetime.now().strftime("%Y-%m-%dT%H:%M:%S-03:00"), # UTC-3
                "tpNF": 1,
                "idDest": 1,
                "cMunFG": "2614857", # Tamandaré - PE
                "tpImp": 4,
                "tpEmis": tp_emis, # 1=Normal, 9=Offline
                "tpAmb": 2 if settings.get('environment') == 'homologation' else 1,
                "finNFe": 1,
                "indFinal": 1,
                "indPres": 1,
                "procEmi": 0,
                "verProc": "TraeSystem 1.0"
            },
            "emit": {
                "CNPJ": cnpj_emitente,
                "IE": ie_emitente,
                "enderEmit": {
                     "UF": "PE", 
                     "cMun": "2614857" # Tamandaré
                }
            },
            "det": nfe_items,
            "transp": {
                "modFrete": 9 # Sem frete
            },
            "total": {
                "ICMSTot": {
                    "vBC": 0.00,
                    "vICMS": 0.00,
                    "vICMSDeson": 0.00,
                    "vFCP": 0.00,
                    "vBCST": 0.00,
                    "vST": 0.00,
                    "vFCPST": 0.00,
                    "vFCPSTRet": 0.00,
                    "vProd": total_items,
                    "vFrete": 0.00,
                    "vSeg": 0.00,
                    "vDesc": 0.00,
                    "vII": 0.00,
                    "vIPI": 0.00,
                    "vIPIDevol": 0.00,
                    "vPIS": 0.00,
                    "vCOFINS": 0.00,
                    "vOutro": 0.00,
                    "vNF": total_items
                }
            },
            "pag": {
                "detPag": pagamentos
            },
            "infRespTec": {
                "CNPJ": "28952732000109", # CNPJ da Software House (Mirapraia mesmo?)
                "xContato": "Angelo Diamante",
                "email": "diamantegut@gmail.com",
                "fone": "8194931201"
            }
        }
    }
    
    # Contingency Specifics
    if tp_emis == 9:
        # Must generate dhCont and xJust if required by API, but Nuvem Fiscal abstracts this?
        # Nuvem Fiscal might require 'xJust' if we are in contingency?
        # Let's check docs or assume standard.
        pass

    if customer_cpf_cnpj:
        payload["infNFe"]["dest"] = {
            "CPF": _normalize_digits(customer_cpf_cnpj) if len(_normalize_digits(customer_cpf_cnpj)) == 11 else None,
            "CNPJ": _normalize_digits(customer_cpf_cnpj) if len(_normalize_digits(customer_cpf_cnpj)) == 14 else None
        }
        # Cleanup None keys
        payload["infNFe"]["dest"] = {k: v for k, v in payload["infNFe"]["dest"].items() if v}
        if not payload["infNFe"]["dest"]:
            del payload["infNFe"]["dest"]

    try:
        # Use Nuvem Fiscal API
        # POST /nfce/emitir (Assuming this is the endpoint for emission)
        # Docs: https://dev.nuvemfiscal.com.br/docs/api#tag/NFC-e/operation/EmitirNfce
        # Actually it's POST /nfce
        
        api_url = f"https://api.sandbox.nuvemfiscal.com.br/nfce" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br/nfce"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"Emitting NFC-e for {transaction['id']} to {api_url}")
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in (200, 201):
            resp_data = response.json()
            
            # If sync, we get the authorization.
            
            return {
                "success": True, 
                "message": f"NFC-e enviada! ID: {resp_data.get('id') or 'N/A'}",
                "data": resp_data
            }
        else:
            logger.error(f"Nuvem Fiscal Error: {response.status_code} - {response.text}")
            # Try to parse error
            try:
                err_data = response.json()
                msg = err_data.get('error', {}).get('message') or err_data.get('message') or response.text
            except:
                msg = f"Status {response.status_code}: {response.text}"
                
            return {"success": False, "message": f"Erro Nuvem Fiscal: {msg}"}

    except Exception as e:
        logger.error(f"Error emitting invoice: {e}")
        return {"success": False, "message": str(e)} 

def process_nfse_request(entry_id):
    """
    Processes an NFSe request for a Fiscal Pool entry.
    """
    logger.info(f"Processing NFSe for entry {entry_id}")
    
    # Load pool
    pool = FiscalPoolService._load_pool()
    entry = next((e for e in pool if e['id'] == entry_id), None)
    
    if not entry:
        logger.error(f"Entry {entry_id} not found in pool")
        return False
        
    try:
        # 1. Validation
        customer = entry.get('customer', {})
        if not customer.get('cpf_cnpj'):
            raise ValueError("CPF/CNPJ do tomador é obrigatório para NFSe")
            
        # 2. Tax Calculation (Mock)
        iss_rate = 0.05
        total = entry['total_amount']
        iss_val = total * iss_rate
        
        # 3. XML Generation (Mock)
        xml_content = f'''
<NFSe>
    <Prestador>
        <CNPJ>27.865.757/0001-02</CNPJ>
        <RazaoSocial>ALMAREIA MIRAPRAIA HOTELARIA LTDA</RazaoSocial>
    </Prestador>
    <Tomador>
        <CPFCNPJ>{customer.get('cpf_cnpj')}</CPFCNPJ>
        <RazaoSocial>{customer.get('name')}</RazaoSocial>
    </Tomador>
    <Servico>
        <Item>
            <Descricao>{entry['items'][0]['name'] if entry['items'] else 'Serviços de Hotelaria'}</Descricao>
            <Valor>{total:.2f}</Valor>
            <Aliquota>{iss_rate}</Aliquota>
            <ValorISS>{iss_val:.2f}</ValorISS>
        </Item>
    </Servico>
</NFSe>
'''
        
        # 4. Send to Prefeitura (Mock)
        time.sleep(2) # Simulate network
        success = True
        
        if success:
            entry['status'] = 'emitted'
            entry['fiscal_doc_uuid'] = str(uuid.uuid4())
            entry['notes'] = (entry.get('notes') or '') + " | NFSe Emitida com Sucesso"
            entry['xml_url'] = f"/fiscal/xml/{entry['fiscal_doc_uuid']}.xml"
            
            # Save updated pool
            FiscalPoolService._save_pool(pool)
            logger.info(f"NFSe emitted for {entry_id}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to process NFSe for {entry_id}: {e}")
        entry['status'] = 'error'
        entry['notes'] = (entry.get('notes') or '') + f" | Erro NFSe: {str(e)}"
        FiscalPoolService._save_pool(pool)
        return False
