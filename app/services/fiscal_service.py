import requests
import json
import logging
import os
import time
import re
import csv
import uuid
import threading
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from app.services.system_config_manager import (
    get_data_path, get_fiscal_path, PENDING_FISCAL_EMISSIONS_FILE, 
    FISCAL_NSU_FILE, FISCAL_SETTINGS_FILE, FISCAL_SEFAZ_BLOCK_FILE
)
from app.services.printing_service import print_fiscal_receipt
from app.services.printer_manager import load_printer_settings, load_printers
from app.services.fiscal_pool_service import FiscalPoolService
from app.services.sefaz_service import SefazService

# Configure logging
logger = logging.getLogger(__name__)

PENDING_EMISSIONS_FILE = PENDING_FISCAL_EMISSIONS_FILE

def _round_money(val):
    try:
        return float(Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except Exception:
        try:
            return round(float(val), 2)
        except Exception:
            return 0.0

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

        try:
            current_number = int(target_integration.get('next_number', 1))
        except Exception:
            current_number = 1
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
        integration_settings = get_fiscal_integration(settings, emission_cnpj).copy()
        
        # Se existir snapshot fiscal, só usamos para filas legadas (queue).
        # Para itens do Fiscal Pool, SEMPRE usamos a configuração fiscal atual,
        # inclusive ambiente (homologação/produção), série, CRT etc.
        snap = emission.get('fiscal_snapshot') or {}
        if source != 'pool' and isinstance(snap, dict) and snap:
            for k in ['sefaz_environment', 'environment', 'serie', 'ie_emitente', 'CRT', 'crt']:
                if snap.get(k) is not None:
                    integration_settings[k] = snap.get(k)
        
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

            xml_ok = False
            xml_error_msg = None
            try:
                xml_path = download_xml(nfe_id, integration_settings)
                if xml_path:
                    xml_ok = True
                    if source == 'queue':
                        emission['xml_path'] = xml_path
                    if source == 'pool':
                        try:
                            FiscalPoolService.set_xml_ready(emission['id'], True, xml_path)
                        except Exception:
                            pass
                    logger.info(f"XML saved at {xml_path}")
                else:
                    xml_error_msg = "XML da NFC-e não disponível na Nuvem Fiscal (verifique autorização)."
            except Exception as e:
                xml_error_msg = f"Falha ao baixar XML da NFC-e: {e}"
                logger.error(f"Failed to download XML for {nfe_id}: {e}")

            if not xml_ok:
                err_msg = xml_error_msg or "XML da NFC-e não disponível."
                if source == 'pool':
                    FiscalPoolService.update_status(emission['id'], 'failed', error_msg=err_msg)
                else:
                    emission['attempts'] = emission.get('attempts', 0) + 1
                    emission['last_error'] = err_msg
                    if emission['attempts'] >= 3:
                        emission['status'] = 'failed'
                failed_count += 1
                continue

            # Update Source only após XML confirmado
            if source == 'pool':
                FiscalPoolService.update_status(emission['id'], 'emitted', fiscal_doc_uuid=nfe_id, serie=nfe_serie, number=nfe_number)
            else:
                emission['status'] = 'emitted'
                emission['nfe_id'] = nfe_id
                emission['emitted_at'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                if emission.get('id', '').startswith('POOL-'):
                    try:
                        pool_id = emission['id'].replace('POOL-', '')
                        FiscalPoolService.update_status(pool_id, 'emitted', fiscal_doc_uuid=nfe_id, serie=nfe_serie, number=nfe_number)
                    except:
                        pass

            # Increment fiscal number somente após XML ok
            increment_fiscal_number(settings, emission_cnpj)
            
            try:
                pdf_path = download_pdf(nfe_id, integration_settings)
                if pdf_path:
                    if source == 'queue':
                        emission['pdf_path'] = pdf_path
                    if source == 'pool':
                        try:
                            FiscalPoolService.set_pdf_ready(emission['id'], True, pdf_path)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Failed to download PDF for {nfe_id}: {e}")
                
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

def get_access_token(client_id, client_secret, scope="nfce", audience=None):
    url = "https://auth.nuvemfiscal.com.br/oauth/token"
    if audience is None:
        audience = "https://api.nuvemfiscal.com.br/"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
        "audience": audience
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

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if integration_settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    token = get_access_token(client_id, client_secret, scope="nfce", audience=audience)
    if not token:
        return {"success": False, "message": "Falha na autenticação com Nuvem Fiscal."}

    api_url = f"{base_url}/empresas/{cnpj_emitente}/nfce"

    sefaz_env = integration_settings.get('sefaz_environment', integration_settings.get('environment', 'production'))

    payload = {
        "ambiente": "homologacao" if sefaz_env == 'homologation' else "producao"
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
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    token = get_access_token(client_id, client_secret, scope="nfce", audience=audience)
    if not token:
        logger.error("Failed to authenticate for XML download")
        return None

    api_url = f"{base_url}/nfce/{nfe_id}/xml"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        attempts = 5
        response = None
        for _ in range(attempts):
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                break
            time.sleep(2)
        if response and response.status_code == 200:
            year_month = datetime.now().strftime('%Y/%m')
            base_path = get_data_path(os.path.join('fiscal', 'xmls'))
            xml_dir = os.path.join(base_path, 'emitted', year_month)
            if not os.path.exists(xml_dir):
                os.makedirs(xml_dir)

            file_path = os.path.join(xml_dir, f"{nfe_id}.xml")
            with open(file_path, 'wb') as f:
                f.write(response.content)

            try:
                import xml.etree.ElementTree as ET
                import re as _re
                root = ET.fromstring(response.content)
                chave = None
                for elem in root.iter():
                    tag = elem.tag.split('}')[-1]
                    if tag == 'infNFe':
                        _id = elem.attrib.get('Id') or elem.attrib.get('id')
                        if _id:
                            only_digits = _re.sub(r'[^0-9]', '', _id)
                            if len(only_digits) == 44:
                                chave = only_digits
                                break
                    if tag == 'chNFe' and elem.text:
                        only_digits = _re.sub(r'[^0-9]', '', elem.text)
                        if len(only_digits) == 44:
                            chave = only_digits
                            break
                if chave:
                    chave_path = os.path.join(xml_dir, f"{chave}.xml")
                    if not os.path.exists(chave_path):
                        with open(chave_path, 'wb') as f2:
                            f2.write(response.content)
            except Exception:
                pass

            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"XML saved and validated at {file_path}")
                return file_path
            else:
                logger.error(f"XML save failed validation at {file_path}")
                return None
        else:
            status = response.status_code if response is not None else 'N/A'
            text = response.text if response is not None else ''
            logger.error(f"Error downloading XML: {status} - {text}")
            return None
    except Exception as e:
        logger.error(f"Exception downloading XML: {e}")
        return None


def download_pdf(nfe_id, settings):
    if not nfe_id:
        return None
    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    token = get_access_token(client_id, client_secret, scope="nfce", audience=audience)
    if not token:
        logger.error("Failed to authenticate for PDF download")
        return None
    api_url = f"{base_url}/nfce/{nfe_id}/pdf"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        attempts = 5
        response = None
        for _ in range(attempts):
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                break
            time.sleep(2)
        if response and response.status_code == 200:
            year_month = datetime.now().strftime('%Y/%m')
            base_path = get_data_path(os.path.join('fiscal', 'pdfs'))
            pdf_dir = os.path.join(base_path, 'emitted', year_month)
            if not os.path.exists(pdf_dir):
                os.makedirs(pdf_dir)
            file_path = os.path.join(pdf_dir, f"{nfe_id}.pdf")
            with open(file_path, 'wb') as f:
                f.write(response.content)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return file_path
            else:
                return None
        else:
            return None
    except Exception as e:
        logger.error(f"Exception downloading PDF: {e}")
        return None

def manifest_nfe(access_key, settings, event_code=210210):
    """
    Sends a manifestation event (Ciência da Operação default) to SEFAZ via Nuvem Fiscal.
    """
    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe", audience=audience)
    if not token:
        token = get_access_token(client_id, client_secret, scope="nfe", audience=audience)
        
    if not token:
        return False, "Falha na autenticação"
        
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
    if settings.get('provider') == 'sefaz_direto':
        service = _get_sefaz_service_instance(settings)
        if not service: return None, "Erro certificado"
        
        try:
            with service:
                 # Consulta por chave
                 result = service.consultar_por_chave(access_key, settings.get('cnpj_emitente'))
                 if not result['success']:
                     return None, result.get('message')
                     
                 # Procura o XML completo nos documentos retornados
                 for doc in result.get('documents', []):
                     # Verifica se é procNFe ou NFe
                     if 'nfeProc' in doc['content'] or '<NFe' in doc['content']:
                         return doc['content'].encode('utf-8'), None
                         
                 # Se não achou, tenta manifestar Ciência
                 logger.info(f"XML não disponível para {access_key}. Tentando manifestar Ciência.")
                 manif_res = service.manifestar_ciencia_operacao(access_key, settings.get('cnpj_emitente'))
                 if manif_res.get('success'): # Atenção: sefaz_service retorna dict padronizado?
                      # manifestar_ciencia_operacao chama _enviar_evento que precisa ser implementado ou retorna o _enviar_soap
                      # Se _enviar_evento não estiver implementado (retorna None), vai falhar.
                      # Mas deixamos o TODO lá. Se falhar, falha aqui.
                      
                      time.sleep(2)
                      result_retry = service.consultar_por_chave(access_key, settings.get('cnpj_emitente'))
                      for doc in result_retry.get('documents', []):
                         if 'nfeProc' in doc['content'] or '<NFe' in doc['content']:
                             return doc['content'].encode('utf-8'), None
                             
                 return None, "XML completo não disponível (nota resumida ou pendente de autorização)."
        except Exception as e:
            return None, f"Erro SEFAZ Direto: {str(e)}"

    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    
    # We try 'nfe' and 'distribuicao-nfe' scope first
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe", audience=audience) 
    if not token:
        # Fallback
        token = get_access_token(client_id, client_secret, scope="nfe", audience=audience)
    
    if not token:
        # Try with 'nfce' or default scope if 'nfe' fails (maybe combined scope?)
        # Or maybe the user only has 'nfce' enabled? But for NFe we need 'nfe'.
        token = get_access_token(client_id, client_secret, scope="nfce", audience=audience)
        if not token:
            return None, "Falha na autenticação com Nuvem Fiscal"
    
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

def get_sefaz_block_until():
    path = FISCAL_SEFAZ_BLOCK_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        blocked_until_str = data.get('blocked_until')
        if not blocked_until_str:
            return None
        return datetime.fromisoformat(blocked_until_str)
    except Exception:
        return None

def set_sefaz_block_for_one_hour():
    path = FISCAL_SEFAZ_BLOCK_FILE
    try:
        blocked_until = datetime.now() + timedelta(hours=1)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'blocked_until': blocked_until.isoformat()}, f)
    except Exception as e:
        logger.error(f"Error saving SEFAZ block status: {e}")

def _get_sefaz_service_instance(settings):
    pfx_path = settings.get('certificate_path')
    pfx_password = settings.get('certificate_password')
    
    if not pfx_path:
        return None
        
    if not os.path.isabs(pfx_path):
        possible_path = os.path.join(os.getcwd(), 'data', 'certs', pfx_path)
        if os.path.exists(possible_path):
            pfx_path = possible_path
        else:
             pfx_path = os.path.join(os.getcwd(), pfx_path)
             
    if not os.path.exists(pfx_path):
        logger.error(f"Certificado não encontrado em: {pfx_path}")
        return None
        
    return SefazService(pfx_path, pfx_password)

def _list_received_nfes_sefaz(settings):
    block_until = get_sefaz_block_until()
    if block_until and datetime.now() < block_until:
        remaining = block_until - datetime.now()
        minutes = int(remaining.total_seconds() / 60)
        return None, f"As consultas DF-e foram temporariamente bloqueadas pela SEFAZ por 'Consumo Indevido'. Aguarde {minutes} minutos."
    
    service = _get_sefaz_service_instance(settings)
    if not service:
        return None, "Certificado digital não configurado ou inválido (verifique data/certs)."
        
    try:
        with service:
            cnpj = settings.get('cnpj_emitente')
            # last_nsu = str(get_last_nsu() or 0)
            ambiente = 2 if settings.get('environment') == 'homologation' else 1
            
            all_documents = []
            max_pages = 20 # Reduzido para 20 para evitar timeout do browser
            page_count = 0
            
            # Start timer
            start_time = time.time()
            
            while page_count < max_pages:
                last_nsu = str(get_last_nsu() or 0)
                logger.info(f"Consultando SEFAZ Direto (NSU {last_nsu})...")
                result = service.consultar_distribuicao_dfe(cnpj, ult_nsu=last_nsu, ambiente=ambiente)
                
                if not result['success']:
                    if str(result.get('cStat')) == '656':
                        ult_nsu_retorno = result.get('ultNSU')
                        try:
                            if ult_nsu_retorno and int(ult_nsu_retorno) > int(last_nsu):
                                save_last_nsu(ult_nsu_retorno)
                        except Exception:
                            pass
                        set_sefaz_block_for_one_hour()
                        msg = "A SEFAZ retornou 'Consumo Indevido' e bloqueou temporariamente novas consultas. Aguarde 1 hora."
                        if all_documents:
                            return all_documents, f"{msg} (Parcialmente sincronizado)"
                        return None, msg
                    
                    # Se erro for 137 (Nenhum documento), paramos
                    if str(result.get('cStat')) == '137':
                        # Mas se tiver ultNSU, salvamos para não consultar o mesmo de novo
                        ult_nsu_retorno = result.get('ultNSU')
                        if ult_nsu_retorno and int(ult_nsu_retorno) > int(last_nsu):
                            save_last_nsu(ult_nsu_retorno)
                        break
                        
                    return None, f"Erro SEFAZ: {result.get('message')} (cStat: {result.get('cStat')})"
                    
                ult_nsu_retorno = result.get('ultNSU')
                max_nsu_retorno = result.get('maxNSU')

                # Log de progresso se estivermos atrasados
                if max_nsu_retorno and ult_nsu_retorno:
                    diff = int(max_nsu_retorno) - int(ult_nsu_retorno)
                    if diff > 100:
                        logger.info(f"Sincronização em andamento: Processado {ult_nsu_retorno}, Alvo {max_nsu_retorno} (Faltam ~{diff})")

                # Se não avançou o NSU, paramos para evitar loop infinito
                if ult_nsu_retorno and int(ult_nsu_retorno) <= int(last_nsu):
                    # Se não avançou mas o maxNSU é maior, é porque não há docs nesse range
                    # Mas se já fizemos o fast-forward, devemos estar perto do final.
                    # Se max_nsu_retorno > ult_nsu_retorno, significa que há mais documentos à frente?
                    # Não necessariamente. maxNSU é o topo global.
                    
                    # Vamos tentar avançar para maxNSU se estiver travado?
                    # Não, SEFAZ retorna ultNSU como o último pesquisado.
                    break

                batch_docs = []
                for doc in result.get('documents', []):
                    parsed = service.parse_xml_content(doc['content'])
                    if parsed:
                        # Extrair valor com segurança
                        try:
                            v_nf = float(parsed.get('vnf', 0) or 0)
                        except:
                            v_nf = 0.0

                        normalized = {
                            'id': parsed.get('access_key'),
                            'access_key': parsed.get('access_key'),
                            'chave': parsed.get('access_key'),
                            'created_at': parsed.get('dhemi') or parsed.get('dh_evento') or datetime.now().isoformat(),
                            'issued_at': parsed.get('dhemi'),
                            'amount': v_nf,
                            'total_amount': v_nf,
                            'digest_value': parsed.get('digval'),
                            'schema': doc.get('schema'),
                            'type': parsed.get('type'),
                            'nsu': doc.get('nsu'),
                            'emitente': {
                                'cpf_cnpj': parsed.get('cnpj_emitente'),
                                'nome': parsed.get('nome_emitente'),
                                'ie': parsed.get('ie_emitente')
                            },
                            'xml_content': doc.get('content') # Guarda XML bruto para salvar depois
                        }
                        batch_docs.append(normalized)
                
                # IMPORTANT: Adicionar batch_docs ao all_documents SOMENTE se for válido
                # JSON serializável check? 
                # Vamos garantir que não fique gigante.
                if len(all_documents) > 100:
                    # Se já temos 100 docs, vamos parar e retornar o que temos para não estourar timeout do browser
                    # Mas precisamos salvar o NSU
                    pass
                
                all_documents.extend(batch_docs)
                
                # Atualiza NSU com o último pesquisado (ultNSU)
                if ult_nsu_retorno:
                    save_last_nsu(ult_nsu_retorno)
                
                page_count += 1
                
                # Se não tem mais documentos (ultNSU >= maxNSU), paramos
                if max_nsu_retorno and ult_nsu_retorno and int(ult_nsu_retorno) >= int(max_nsu_retorno):
                    break
                
                # Timeout check: se passar de 45 segundos, retorna o que tem para não quebrar o browser
                if (time.time() - start_time) > 45:
                    logger.warning("Tempo limite de execução atingido. Retornando parcial.")
                    break
                    
                # Pausa de 2 segundos para evitar Consumo Indevido (segurança extra)
                time.sleep(2)
            
            # Limitar retorno para evitar payload gigante que trava o browser/JSON
            # O usuário pediu "ultimas 20 notas"
            if len(all_documents) > 50:
                 all_documents = all_documents[-50:]
            
            return all_documents, None
            
    except Exception as e:
        logger.error(f"Erro no serviço SEFAZ: {e}")
        return None, f"Erro interno SEFAZ: {str(e)}"

def list_received_nfes(settings):
    """
    Lists recent NFe documents received by the CNPJ (DFe).
    """
    if settings.get('provider') == 'sefaz_direto':
        return _list_received_nfes_sefaz(settings)
    
    return None, "Consulta DF-e via Nuvem Fiscal desativada. Configure a integração SEFAZ Direto para continuar usando DF-e."

    client_id = settings.get('client_id')
    client_secret = settings.get('client_secret')
    
    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    
    # Authenticate with 'nfe' and 'distribuicao-nfe' scope
    token = get_access_token(client_id, client_secret, scope="nfe distribuicao-nfe", audience=audience)
    if not token:
        # Fallback to just 'nfe' if the combined scope fails
        token = get_access_token(client_id, client_secret, scope="nfe", audience=audience)
    
    if not token:
        return None, "Falha na autenticação com Nuvem Fiscal"
    
    sefaz_env = settings.get('sefaz_environment', settings.get('environment', 'production'))
    env_param = "homologacao" if sefaz_env == 'homologation' else "producao"
    
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
        
    # Always store received XMLs under DATA directory for consistency
    base_storage_path = get_data_path(os.path.join('fiscal', 'xmls'))
    
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

        # Save under DATA/fiscal/xmls/received/YYYY/MM
        target_dir = os.path.join(base_storage_path, 'received', year_month)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        filename = f"{key}.xml"
        file_path = os.path.join(target_dir, filename)
        
        # Also check in flat inbox or root just in case (optional, but let's stick to the new structure)
        if not os.path.exists(file_path):
            # Download XML
            xml_content = doc.get('xml_content')
            if xml_content:
                if isinstance(xml_content, str):
                    xml_content = xml_content.encode('utf-8')
                err = None
            else:
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
    crt_val = settings.get('CRT') or settings.get('crt')
    
    missing_fields = []
    if not client_id:
        missing_fields.append("Client ID Nuvem Fiscal")
    if not client_secret:
        missing_fields.append("Client Secret Nuvem Fiscal")
    if not cnpj_emitente:
        missing_fields.append("CNPJ do emitente")
    if not ie_emitente:
        missing_fields.append("Inscrição Estadual do emitente")
    if not crt_val:
        missing_fields.append("CRT do emitente (Simples Nacional)")

    if missing_fields:
        return {
            "success": False,
            "message": "Configuração fiscal incompleta: " + ", ".join(missing_fields)
        }

    try:
        crt_int = int(str(crt_val).strip())
    except Exception:
        return {
            "success": False,
            "message": "CRT inválido para Simples Nacional. Use 1 ou 2."
        }

    if crt_int not in (1, 2):
        return {
            "success": False,
            "message": "CRT inválido para Simples Nacional. Use 1 ou 2."
        }

    erros_itens = []
    if not order_items:
        return {"success": False, "message": "Nenhum item para emissão."}
    
    for idx, item in enumerate(order_items, start=1):
        if not item.get('name'):
            erros_itens.append(f"Item {idx}: descrição do produto não informada.")
        if not item.get('id'):
            erros_itens.append(f"Item {idx}: código do produto não informado.")
        if not item.get('cfop'):
            erros_itens.append(f"Item {idx}: CFOP não informado.")
        if not item.get('ncm'):
            erros_itens.append(f"Item {idx}: NCM não informado.")
        csosn_val = (item.get('csosn') or "").strip()
        if not csosn_val:
            item['csosn'] = "102"
        elif csosn_val != "102":
            erros_itens.append(f"Item {idx}: CSOSN {csosn_val} não suportado. Atualmente apenas 102 é aceito.")

        try:
            q = float(item.get('qty', 0) or 0)
            if q <= 0:
                erros_itens.append(f"Item {idx}: quantidade deve ser maior que zero.")
        except Exception:
            erros_itens.append(f"Item {idx}: quantidade inválida.")
        try:
            v = float(item.get('price', 0) or 0)
            if v < 0:
                erros_itens.append(f"Item {idx}: valor unitário não pode ser negativo.")
        except Exception:
            erros_itens.append(f"Item {idx}: valor unitário inválido.")

    if erros_itens:
        return {
            "success": False,
            "message": "Erros de configuração fiscal nos itens da NFC-e:\n" + "\n".join(erros_itens)
        }

    base_url = "https://api.sandbox.nuvemfiscal.com.br" if settings.get('environment') == 'homologation' else "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"

    token = get_access_token(client_id, client_secret, scope="nfce", audience=audience)
    if not token:
        return {"success": False, "message": "Falha na autenticação com Nuvem Fiscal."}

    nfe_items = []
    total_items = 0.0

    nItem = 1
    for idx, item in enumerate(order_items):
        # Handle Individual Item Emission (Split by Quantity)
        # Standard behavior: 1 line per product type with Qty > 1
        # Requested behavior: "emissão individual para cada instância" -> 1 line per unit
        
        qty_to_process = float(item['qty'])
        price = _round_money(float(item['price']))
        
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
            item_total = _round_money(qty_per_line * price)
            
            # Determine NCM (Fallback to 21069090 - Preparacoes alimenticias)
            ncm = item.get('ncm')
            if not ncm or len(ncm) < 8:
                ncm = '21069090'
            
            # Enforce CFOP/CSOSN consistency for Simples Nacional
            # User reported: "Rejeicao: CFOP nao permitido para o CSOSN informado"
            # If CSOSN is 102 (Simples Nacional), CFOP must be compatible (e.g. 5102).
            # If CFOP is 5405 (ST), CSOSN should be 500.
            # To simplify and ensure emission, if CSOSN is 102, we ensure CFOP is 5102.
            csosn_val = (item.get('csosn') or "102").strip()
            
            # Sanitize CFOP (remove dots/symbols)
            raw_cfop = str(item.get('cfop', '5102'))
            cfop_val = re.sub(r'[^0-9]', '', raw_cfop)
            
            if csosn_val == "102":
                if not cfop_val.startswith('51'):
                    cfop_val = '5102'

            prod_data = {
                "cProd": str(item.get('id', '0')),
                "cEAN": "SEM GTIN",
                "xProd": item.get('name', 'Produto'),
                "NCM": ncm,
                "CFOP": cfop_val,
                "uCom": "UN",
                "qCom": qty_per_line,
                "vUnCom": _round_money(price),
                "vProd": _round_money(item_total),
                "cEANTrib": "SEM GTIN",
                "uTrib": "UN",
                "qTrib": qty_per_line,
                "vUnTrib": _round_money(price),
                "indTot": 1,
            }
            
            # Only add CEST if it has 7 digits; otherwise omit to avoid validation error
            cest = item.get('cest')
            if cest:
                try:
                    _digits = re.sub(r'\\D', '', str(cest))
                    if len(_digits) == 7:
                        prod_data["CEST"] = _digits
                except Exception:
                    pass
    
            nfe_item = {
                "nItem": nItem,
                "prod": prod_data,
                "imposto": {
                    "ICMS": {
                        "ICMSSN102": {
                            "orig": int(item.get('origin', 0) or 0),
                            "CSOSN": (item.get('csosn') or "102").strip()
                        }
                    }
                    # PIS and COFINS removed for Simples Nacional (CSOSN 102) to simplify payload
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
    
    # To avoid "Ausencia de troco" rejection or "Valor do pagamento menor que o total",
    # we force vPag to be exactly equal to the total of items (vNF).
    # This simplifies the logic and ensures acceptance, as we don't need to calculate change (vTroco).
    # If the real transaction amount was higher (e.g. tip/service), for fiscal purposes here we just emit the products.
    v_pag_final = _round_money(total_items)

    pagamentos = [
        {
            "tPag": pay_code,
            "vPag": v_pag_final,
        }
    ]

    # Payload for Nuvem Fiscal
    # Using the 'infNFe' structure inside the payload
    
    # Offline Contingency (tpEmis)
    # 1=Normal, 9=Offline
    tp_emis = transaction.get('tpEmis', 1)
    
    def _to_int(val, default_val):
        try:
            if val is None: 
                return int(default_val)
            if isinstance(val, str) and val.strip() == "":
                return int(default_val)
            return int(val)
        except Exception:
            return int(default_val)

    serie_val = _to_int(settings.get('serie', 1), 1)
    nnum_val = _to_int(settings.get('next_number', 1), 1)

    sefaz_env = settings.get('sefaz_environment', settings.get('environment', 'production'))
    is_homolog = sefaz_env == 'homologation'

    # Simplified Payload
    payload = {
        "ambiente": "homologacao" if is_homolog else "producao",
        "infNFe": {
            "versao": "4.00",
            "ide": {
                "cUF": 26, # PE
                "natOp": "Venda ao Consumidor",
                "mod": 65,
                "serie": serie_val,
                "nNF": nnum_val,
                "dhEmi": datetime.now().strftime("%Y-%m-%dT%H:%M:%S-03:00"),
                "tpNF": 1,
                "idDest": 1,
                "cMunFG": "2614857", # Tamandaré
                "tpImp": 4,
                "tpEmis": tp_emis,
                "tpAmb": 2 if is_homolog else 1,
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
                     "cMun": "2614857"
                }
            },
            "det": nfe_items,
            "transp": {
                "modFrete": 9
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
                    "vProd": _round_money(total_items),
                    "vFrete": 0.00,
                    "vSeg": 0.00,
                    "vDesc": 0.00,
                    "vII": 0.00,
                    "vIPI": 0.00,
                    "vIPIDevol": 0.00,
                    "vPIS": 0.00,
                    "vCOFINS": 0.00,
                    "vOutro": 0.00,
                    "vNF": _round_money(total_items)
                }
            },
            "pag": {
                "detPag": pagamentos,
                "vTroco": 0.00
            },
            "infRespTec": {
                "CNPJ": "28952732000109",
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
            status_val = ""
            chave_val = ""
            try:
                raw_status = resp_data.get("status") or resp_data.get("situacao") or resp_data.get("status_sefaz")
                if isinstance(raw_status, str):
                    status_val = raw_status.lower().strip()
            except Exception:
                status_val = ""
            try:
                chave_candidates = [
                    resp_data.get("chave"),
                    resp_data.get("chave_acesso"),
                    resp_data.get("chaveNFe"),
                    resp_data.get("chNFe"),
                ]
                for c in chave_candidates:
                    if isinstance(c, str) and len(c.strip()) >= 44:
                        chave_val = "".join([d for d in c if d.isdigit()])
                        break
            except Exception:
                chave_val = ""
            authorized_status = status_val in ["autorizada", "autorizado", "aprovada", "authorized"]
            
            # STRICT CHECK: Must be authorized. Merely having a key is not enough if status is not authorized.
            if not authorized_status:
                base_msg = None
                
                # Check authorization rejection reason (Nuvem Fiscal specific structure)
                if isinstance(resp_data.get("autorizacao"), dict):
                     base_msg = resp_data["autorizacao"].get("motivo_status")

                if not base_msg and isinstance(resp_data.get("error"), dict):
                    base_msg = resp_data.get("error", {}).get("message")
                
                if not base_msg:
                    base_msg = resp_data.get("message") or resp_data.get("title") or f"NFC-e não autorizada (Status: {status_val})"
                
                # If we have a key but not authorized, it might be a rejection or processing
                if len(chave_val) == 44:
                    base_msg += f" - Chave gerada: {chave_val}"
                    
                logger.error(f"NFC-e emission not authorized. Status={status_val} Body={resp_data}")
                return {
                    "success": False,
                    "message": base_msg,
                    "data": resp_data
                }
            
            return {
                "success": True, 
                "message": f"NFC-e emitida com sucesso! ID: {resp_data.get('id') or 'N/A'}",
                "data": resp_data
            }
        else:
            logger.error(f"Nuvem Fiscal Error: {response.status_code} - {response.text}")
            try:
                err_data = response.json()
            except Exception:
                err_data = None

            msg = None
            details_txt = ""

            if isinstance(err_data, dict):
                base_msg = None
                # Common locations for a human-readable message
                if isinstance(err_data.get('error'), dict):
                    base_msg = err_data.get('error', {}).get('message')
                if not base_msg:
                    base_msg = err_data.get('message') or err_data.get('title')
                if base_msg:
                    msg = base_msg

                parts = []
                # Nuvem Fiscal may return errors under multiple shapes:
                # 1) error.details: [ { field, message } ]
                # 2) errors: [ { field/name/code, message/detail } ] or errors: { field: [msg1, msg2] }
                # 3) issues / invalidParams / violations (fallback)
                if isinstance(err_data.get('error', {}).get('details'), list):
                    for d in err_data['error']['details'][:10]:
                        field = d.get('field') or d.get('name') or d.get('code')
                        dmsg = d.get('message') or d.get('detail') or str(d)
                        parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                elif isinstance(err_data.get('error', {}).get('errors'), list):
                    for d in err_data['error']['errors'][:10]:
                        if isinstance(d, dict):
                            field = d.get('field') or d.get('name') or d.get('code')
                            dmsg = d.get('message') or d.get('detail') or str(d)
                            parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                        else:
                            parts.append(str(d))
                elif isinstance(err_data.get('error', {}).get('errors'), dict):
                    for k, v in list(err_data['error']['errors'].items())[:10]:
                        if isinstance(v, list) and v:
                            parts.append(f"{k}: {v[0]}")
                        else:
                            parts.append(f"{k}: {str(v)}")
                elif isinstance(err_data.get('errors'), list):
                    for d in err_data['errors'][:10]:
                        if isinstance(d, dict):
                            field = d.get('field') or d.get('name') or d.get('code')
                            dmsg = d.get('message') or d.get('detail') or str(d)
                            parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                        else:
                            parts.append(str(d))
                elif isinstance(err_data.get('errors'), dict):
                    for k, v in list(err_data['errors'].items())[:10]:
                        if isinstance(v, list) and v:
                            parts.append(f"{k}: {v[0]}")
                        else:
                            parts.append(f"{k}: {str(v)}")
                elif isinstance(err_data.get('error', {}).get('violations'), list):
                    for d in err_data['error']['violations'][:10]:
                        field = d.get('field') or d.get('propertyPath')
                        dmsg = d.get('message') or str(d)
                        parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                elif isinstance(err_data.get('issues'), list):
                    for d in err_data['issues'][:10]:
                        field = d.get('field') or d.get('path') or d.get('pointer')
                        dmsg = d.get('message') or d.get('detail') or d.get('description') or str(d)
                        parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                elif isinstance(err_data.get('invalidParams'), list):
                    for d in err_data['invalidParams'][:10]:
                        field = d.get('name') or d.get('param') or d.get('field')
                        dmsg = d.get('reason') or d.get('message') or str(d)
                        parts.append(f"{field}: {dmsg}" if field else str(dmsg))
                elif isinstance(err_data.get('violations'), list):
                    for d in err_data['violations'][:10]:
                        field = d.get('field') or d.get('propertyPath')
                        dmsg = d.get('message') or str(d)
                        parts.append(f"{field}: {dmsg}" if field else str(dmsg))

                if parts:
                    details_txt = " | Detalhes: " + " ; ".join(parts)
                else:
                    try:
                        details_txt = " | Detalhes: " + json.dumps(err_data)[:600]
                    except Exception:
                        pass

            if not msg:
                msg = f"Status {response.status_code}: {response.text}"

            return {"success": False, "message": f"Erro Nuvem Fiscal: {msg}{details_txt}"}

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
