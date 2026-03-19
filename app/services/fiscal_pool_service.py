import json
import os
import re
import uuid
import threading
import requests
import shutil
from datetime import datetime
from json import JSONDecodeError
from app.services.system_config_manager import get_config_value, FISCAL_POOL_FILE
from app.services.data_service import load_menu_items, load_room_occupancy

# FISCAL_POOL_FILE = get_data_path('fiscal_pool.json')

class FiscalPoolService:
    MIRAPRAIA_CNPJ = '28952732000109'
    CANONICAL_STATUSES = {'pending', 'issuing', 'emitted', 'rejected', 'manual_retry_required', 'ignored'}

    @staticmethod
    def _normalize_digits(value):
        return re.sub(r'[^0-9]', '', str(value or ''))

    @staticmethod
    def _normalize_status(status):
        raw = str(status or '').strip().lower()
        migration = {
            'error': 'manual_retry_required',
            'failed': 'manual_retry_required',
            'error_config': 'manual_retry_required',
        }
        normalized = migration.get(raw, raw or 'pending')
        if normalized not in FiscalPoolService.CANONICAL_STATUSES:
            return 'pending'
        return normalized

    @staticmethod
    def _is_valid_document(value):
        digits = FiscalPoolService._normalize_digits(value)
        return len(digits) in (11, 14)

    @staticmethod
    def _resolve_customer_document(customer_info):
        if not isinstance(customer_info, dict):
            return ''
        candidates = [
            customer_info.get('cpf_cnpj'),
            customer_info.get('doc_id'),
            customer_info.get('doc'),
            customer_info.get('cpf'),
            customer_info.get('cnpj'),
            customer_info.get('document'),
        ]
        for cand in candidates:
            digits = FiscalPoolService._normalize_digits(cand)
            if len(digits) in (11, 14):
                return digits
        return ''

    @staticmethod
    def _is_non_fiscal_consumption(origin, customer_info, notes, original_id, items):
        lower_origin = str(origin or '').lower()
        lower_notes = str(notes or '').lower()
        lower_original_id = str(original_id or '').lower()
        customer_type = str((customer_info or {}).get('type') or (customer_info or {}).get('customer_type') or '').lower()
        if 'funcion' in customer_type:
            return 'consumo_funcionario'
        if 'propriet' in customer_type:
            return 'consumo_proprietario'
        combined_text = f"{lower_origin} {lower_notes} {lower_original_id}"
        if 'func_' in combined_text or 'funcionario' in combined_text:
            return 'consumo_funcionario'
        if 'propriet' in combined_text or 'mesa 68' in combined_text or 'mesa 69' in combined_text:
            return 'consumo_proprietario'
        item_text = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            item_text.append(str(item.get('name') or '').lower())
            item_text.append(str(item.get('category') or '').lower())
            item_text.append(str(item.get('source') or '').lower())
        merged = " ".join(item_text + [lower_notes, lower_original_id, lower_origin])
        if 'café da manhã' in merged or 'cafe da manha' in merged:
            return 'cafe_da_manha'
        if 'cortesia' in merged:
            return 'cortesia'
        return ''

    @staticmethod
    def _autofill_customer_document_for_reception(origin, total_amount, customer_info):
        lower_origin = str(origin or '').lower()
        if lower_origin not in {'reception_charge', 'restaurant'}:
            return customer_info
        info = dict(customer_info or {})
        if lower_origin == 'restaurant':
            customer_type = str(info.get('type') or info.get('customer_type') or '').lower()
            if 'hospede' not in customer_type and 'hóspede' not in customer_type:
                return info
        current_doc = FiscalPoolService._resolve_customer_document(info)
        if current_doc:
            info['cpf_cnpj'] = current_doc
            return info
        if float(total_amount or 0) <= 999.0:
            return info
        room_number = str(info.get('room_number') or '').strip()
        if not room_number:
            return info
        reservation_id = ''
        try:
            occupancy = load_room_occupancy() or {}
            occ = occupancy.get(room_number)
            if not occ and room_number.isdigit():
                occ = occupancy.get(str(int(room_number)))
            reservation_id = str((occ or {}).get('reservation_id') or '').strip()
        except Exception:
            reservation_id = ''
        if not reservation_id:
            return info
        try:
            from app.services.reservation_service import ReservationService
            service = ReservationService()
            reservation = service.get_reservation_by_id(reservation_id) or {}
            details = service.get_guest_details(reservation_id) or {}
            personal_info = details.get('personal_info') if isinstance(details, dict) else {}
            candidates = [
                reservation.get('doc_id'),
                reservation.get('cpf_cnpj'),
                reservation.get('cpf'),
                reservation.get('cnpj'),
                reservation.get('document'),
                personal_info.get('cpf'),
                personal_info.get('cnpj'),
                personal_info.get('document'),
            ] if isinstance(personal_info, dict) else [
                reservation.get('doc_id'),
                reservation.get('cpf_cnpj'),
                reservation.get('cpf'),
                reservation.get('cnpj'),
                reservation.get('document'),
            ]
            for cand in candidates:
                digits = FiscalPoolService._normalize_digits(cand)
                if len(digits) in (11, 14):
                    info['cpf_cnpj'] = digits
                    info['reservation_id'] = reservation_id
                    break
        except Exception:
            pass
        return info

    @staticmethod
    def evaluate_fiscal_policy(origin, total_amount, items, customer_info=None, notes=None, original_id=None, fiscal_type='nfce'):
        info = FiscalPoolService._autofill_customer_document_for_reception(origin, total_amount, customer_info)
        customer_doc = FiscalPoolService._resolve_customer_document(info)
        non_fiscal_reason = FiscalPoolService._is_non_fiscal_consumption(
            origin=origin,
            customer_info=info,
            notes=notes,
            original_id=original_id,
            items=items,
        )
        document_required = float(total_amount or 0) > 999.0 and str(fiscal_type or '').lower() == 'nfce'
        return {
            'customer_info': info,
            'customer_document': customer_doc,
            'non_fiscal_reason': non_fiscal_reason or None,
            'eligible_for_fiscal': not bool(non_fiscal_reason),
            'document_required': bool(document_required),
        }

    @staticmethod
    def _backup_pool_file():
        if not os.path.exists(FISCAL_POOL_FILE):
            return
        backup_dir = os.path.join(os.path.dirname(FISCAL_POOL_FILE), 'backups', 'fiscal_pool')
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = f"fiscal_pool_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        shutil.copy2(FISCAL_POOL_FILE, os.path.join(backup_dir, backup_name))

    @staticmethod
    def _write_pool_atomic(pool):
        os.makedirs(os.path.dirname(FISCAL_POOL_FILE), exist_ok=True)
        temp_path = f"{FISCAL_POOL_FILE}.tmp.{uuid.uuid4().hex}"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(pool, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, FISCAL_POOL_FILE)
        return True

    @staticmethod
    def _log_pool_recovery(action, details):
        try:
            from app.services.logger_service import LoggerService
            LoggerService.log_acao(
                acao=action,
                entidade='Fiscal Pool',
                detalhes=details,
                nivel_severidade='WARNING',
                departamento_id='Financeiro'
            )
        except Exception:
            pass

    @staticmethod
    def _normalize_pool_payload(payload):
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
        if isinstance(payload, dict):
            nested = payload.get('pool')
            if isinstance(nested, list):
                return [entry for entry in nested if isinstance(entry, dict)]
            return [payload]
        return []

    @staticmethod
    def _recover_pool_from_text(raw_text):
        if not isinstance(raw_text, str):
            return None
        text = raw_text.strip()
        if not text:
            return []
        decoder = json.JSONDecoder()
        idx = 0
        recovered = []
        decoded_any = False
        text_len = len(text)
        while idx < text_len:
            while idx < text_len and text[idx].isspace():
                idx += 1
            if idx >= text_len:
                break
            try:
                obj, end_idx = decoder.raw_decode(text, idx)
            except JSONDecodeError:
                break
            decoded_any = True
            recovered.extend(FiscalPoolService._normalize_pool_payload(obj))
            idx = end_idx
        if not decoded_any:
            return None
        return recovered

    @staticmethod
    def _load_pool():
        import time
        if not os.path.exists(FISCAL_POOL_FILE):
            return []
        
        pool = []
        loaded = False
        max_retries = 30
        
        for i in range(max_retries):
            try:
                with open(FISCAL_POOL_FILE, 'r', encoding='utf-8') as f:
                    pool = json.load(f)
                loaded = True
                break
            except (PermissionError, OSError):
                if i == max_retries - 1:
                    # CRITICAL: Do NOT return empty list on lock failure.
                    # Raising exception prevents overwriting data with empty list.
                    raise OSError(f"Could not acquire lock for {FISCAL_POOL_FILE} after {max_retries} attempts.")
                time.sleep(0.1)
            except JSONDecodeError:
                try:
                    with open(FISCAL_POOL_FILE, 'r', encoding='utf-8') as f:
                        raw_text = f.read()
                except Exception as read_exc:
                    raise read_exc

                recovered_pool = FiscalPoolService._recover_pool_from_text(raw_text)
                if recovered_pool is None:
                    raise

                pool = recovered_pool
                try:
                    FiscalPoolService._backup_pool_file()
                    FiscalPoolService._write_pool_atomic(pool)
                except Exception:
                    pass

                FiscalPoolService._log_pool_recovery(
                    action='Fiscal Pool Recuperado',
                    details={
                        'file': FISCAL_POOL_FILE,
                        'entries_recovered': len(pool)
                    }
                )
                loaded = True
                break
            except Exception as e:
                raise e
        
        if not loaded:
             raise OSError(f"Failed to load {FISCAL_POOL_FILE}")
            
        try:
            # Migration / Backfill
            modified = False
            normalized_pool = FiscalPoolService._normalize_pool_payload(pool)
            if len(normalized_pool) != len(pool) if isinstance(pool, list) else True:
                pool = normalized_pool
                modified = True
            else:
                pool = normalized_pool

            for entry in pool:
                # Backfill 'closed_at' if missing
                if 'closed_at' not in entry:
                    entry['closed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    modified = True
                normalized_status = FiscalPoolService._normalize_status(entry.get('status'))
                if entry.get('status') != normalized_status:
                    entry['status'] = normalized_status
                    modified = True
                if entry.get('fiscal_type') == 'nfce':
                    normalized_cnpj = FiscalPoolService._normalize_digits(entry.get('cnpj_emitente'))
                    if not normalized_cnpj or normalized_cnpj != FiscalPoolService.MIRAPRAIA_CNPJ:
                        entry['cnpj_emitente'] = FiscalPoolService.MIRAPRAIA_CNPJ
                        modified = True
                
                # Check if we need to recalculate fiscal_amount
                # Scenarios:
                # 1. Missing 'fiscal_amount'
                # 2. 'fiscal_amount' is 0 but total > 0, and payments don't have explicit 'is_fiscal' flags (Legacy migration issue)
                
                recalc_needed = False
                if 'fiscal_amount' not in entry:
                    recalc_needed = True
                elif entry.get('fiscal_amount', 0) == 0 and entry.get('total_amount', 0) > 0:
                    # Check if any payment has is_fiscal flag
                    pms = entry.get('payment_methods') or []
                    has_explicit_flag = any('is_fiscal' in pm for pm in pms)
                    if not has_explicit_flag:
                        recalc_needed = True
                
                if recalc_needed:
                    pms = entry.get('payment_methods') or []
                    fiscal_val = 0.0
                    has_fiscal_flag = False
                    
                    for pm in pms:
                        # If flag exists, use it
                        if pm.get('is_fiscal'):
                            has_fiscal_flag = True
                            fiscal_val += float(pm.get('amount', 0.0))
                    
                    if has_fiscal_flag:
                        entry['fiscal_amount'] = round(fiscal_val, 2)
                    else:
                        # Fallback for legacy data without flags: assume total is fiscal
                        # This fixes the migration of old closed accounts
                        entry['fiscal_amount'] = float(entry.get('total_amount', 0.0))
                    
                    # Cap at total
                    if entry['fiscal_amount'] > float(entry.get('total_amount', 0.0)):
                        entry['fiscal_amount'] = float(entry.get('total_amount', 0.0))
                        
                    modified = True
            
            if modified:
                try:
                    FiscalPoolService._backup_pool_file()
                    FiscalPoolService._write_pool_atomic(pool)
                except: pass
                
            return pool
        except Exception:
            return []

    @staticmethod
    def _save_pool(pool):
        try:
            FiscalPoolService._backup_pool_file()
            return FiscalPoolService._write_pool_atomic(pool)
        except Exception:
            return False

    @staticmethod
    def save_pool(pool):
        return FiscalPoolService._save_pool(pool)

    @staticmethod
    def add_to_pool(origin, original_id, total_amount, items, payment_methods, user, customer_info=None, notes=None):
        """
        Adds a closed account snapshot to the fiscal pool.
        origin: 'restaurant', 'reception', 'daily_rates'
        """
        pool = FiscalPoolService._load_pool()
        
        # Determine fiscal type and issuer CNPJ
        fiscal_type = 'nfce'
        cnpj_emitente = FiscalPoolService.MIRAPRAIA_CNPJ
        
        # Load Menu Items for enrichment
        try:
            menu_items = load_menu_items()
            menu_map = {str(m['id']): m for m in menu_items}
            # Fallback map by name
            menu_map_name = {m['name'].lower().strip(): m for m in menu_items}
        except:
            menu_map = {}
            menu_map_name = {}
        
        enriched_items = []
        for item in items:
            # Clone item to avoid modifying original reference if any
            new_item = item.copy()
            
            # Ensure basic fields are correct type
            try:
                new_item['qty'] = float(new_item.get('qty', 1))
                new_item['price'] = float(new_item.get('price', 0))
                if 'total' in new_item:
                    new_item['total'] = float(new_item['total'])
                else:
                    new_item['total'] = new_item['qty'] * new_item['price']
            except: pass
            
            # Find in menu
            product = None
            if 'id' in new_item and str(new_item['id']) in menu_map:
                product = menu_map[str(new_item['id'])]
            elif 'name' in new_item and new_item['name'].lower().strip() in menu_map_name:
                product = menu_map_name[new_item['name'].lower().strip()]
            
            if product:
                # Enrich with fiscal data if missing in item
                # Priorities: item > product > default
                if not new_item.get('ncm'): new_item['ncm'] = product.get('ncm')
                if not new_item.get('cest'): new_item['cest'] = product.get('cest')
                if not new_item.get('cfop'): new_item['cfop'] = product.get('cfop')
                if not new_item.get('origin'): new_item['origin'] = product.get('origin')
                
                # Tax info
                if not new_item.get('tax_situation'): new_item['tax_situation'] = product.get('tax_situation')
                if not new_item.get('icms_rate'): new_item['icms_rate'] = product.get('icms_rate')
                if not new_item.get('pis_cst'): new_item['pis_cst'] = product.get('pis_cst')
                if not new_item.get('cofins_cst'): new_item['cofins_cst'] = product.get('cofins_cst')
            
            # Default fallback for required fields if still missing
            if not new_item.get('ncm'): new_item['ncm'] = '00000000' # Invalid but prevents crash? Or better let it fail?
            # Actually empty NCM causes rejection. But '00000000' also causes rejection.
            # We leave it empty if not found, validator will catch it.
            
            enriched_items.append(new_item)

        if origin == 'daily_rates':
            fiscal_type = 'nfse' # Service
            cnpj_emitente = '46500590000112' # Almareia
        elif origin in ['reservations', 'reservation_checkin']:
            fiscal_type = 'nfse'
            cnpj_emitente = str((customer_info or {}).get('nfse_emit_cnpj') or '46500590000112').replace('.', '').replace('/', '').replace('-', '').strip()
        elif origin == 'reception':
            # Check items for services
            if any(item.get('is_service') for item in enriched_items):
                fiscal_type = 'nfse'
                # Ideally mixed carts should be split, but if service is present, 
                # we might treat as service or daily rate if it's accommodation.
                # If it's pure consumption at reception (minibar), it stays NFC-e Mirapraia.
                # If it's accommodation payment at reception, it goes to Almareia.
                # We need a flag in items or check categories.
                # Simple heuristic: If "Diária" or "Hospedagem" in item name -> Almareia
                is_accommodation = any(
                    'diaria' in str(item.get('name', '')).lower() or 
                    'hospedagem' in str(item.get('name', '')).lower() 
                    for item in enriched_items
                )
                if is_accommodation:
                    cnpj_emitente = '46500590000112' # Almareia
        
        # Override if specific fiscal_cnpj in payment methods (Legacy support)
        # Only if all payments point to the same CNPJ distinct from default
        # (This logic can be refined, but for now we stick to Origin-based rules as requested)
        
        # Calculate Fiscal Amount
        fiscal_amount = 0.0
        if origin in ['reservations', 'reservation_checkin']:
            fiscal_amount = float(total_amount)
        else:
            for pm in payment_methods:
                if pm.get('is_fiscal'):
                    fiscal_amount += float(pm.get('amount', 0.0))
        
        # Ensure we don't exceed total_amount due to rounding
        if fiscal_amount > float(total_amount):
            fiscal_amount = float(total_amount)
            
        policy = FiscalPoolService.evaluate_fiscal_policy(
            origin=origin,
            total_amount=total_amount,
            items=enriched_items,
            customer_info=customer_info,
            notes=notes,
            original_id=original_id,
            fiscal_type=fiscal_type,
        )
        customer_info = policy.get('customer_info') or {}
        customer_doc = policy.get('customer_document') or ''
        doc_required = bool(policy.get('document_required'))
        non_fiscal_reason = policy.get('non_fiscal_reason') or ''
        status = 'pending'
        notes_str = notes
        
        # Auto-ignore zero-value invoices
        if float(total_amount) <= 0.001 or fiscal_amount <= 0.001:
            status = 'ignored'
            notes_str = (notes_str or "") + " | Auto-ignored: Valor Zero"
        if non_fiscal_reason:
            status = 'ignored'
            fiscal_amount = 0.0
            notes_str = (notes_str or "") + f" | Auto-ignored: {non_fiscal_reason}"
            
        entry = {
            'id': str(uuid.uuid4()),
            'origin': origin,
            'fiscal_type': fiscal_type,
            'cnpj_emitente': cnpj_emitente,
            'original_id': str(original_id),
            'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'closed_by': user,
            'total_amount': float(total_amount),
            'fiscal_amount': round(fiscal_amount, 2),
            'items': enriched_items,
            'payment_methods': payment_methods,
            'customer': customer_info or {},
            'status': FiscalPoolService._normalize_status(status),
            'eligible_for_fiscal': not bool(non_fiscal_reason) and round(fiscal_amount, 2) > 0,
            'non_fiscal_reason': non_fiscal_reason or None,
            'document_required': bool(doc_required),
            'customer_document': customer_doc or None,
            'notes': notes_str,
            'fiscal_doc_uuid': None,
            'history': []
        }
        
        # Snapshot minimal fiscal config at the time of export for stability on later emission
        try:
            # Lazy import to avoid circular import at module import time
            from app.services.fiscal_service import load_fiscal_settings, get_fiscal_integration
            settings = load_fiscal_settings()
            integ = get_fiscal_integration(settings, cnpj_emitente)
            if integ:
                entry['fiscal_snapshot'] = {
                    'sefaz_environment': integ.get('sefaz_environment', integ.get('environment', 'production')),
                    'environment': integ.get('environment', 'production'),
                    'serie': integ.get('serie'),
                    'ie_emitente': integ.get('ie_emitente'),
                    'CRT': integ.get('CRT', integ.get('crt'))
                }
        except Exception:
            pass
        
        pool.append(entry)
        FiscalPoolService._save_pool(pool)
        
        # Async Sync to Remote
        try:
            threading.Thread(target=FiscalPoolService.sync_entry_to_remote, args=(entry,)).start()
        except Exception as e:
            print(f"Error starting fiscal sync thread: {e}")
            
        return entry['id']

    @staticmethod
    def sync_entry_to_remote(entry):
        """
        Sends the fiscal entry to the remote fiscal management server.
        """
        try:
            # We post to the remote URL. 
            # Note: The user gave http://192.168.69.99:5000/config/fiscal which seems to be a UI URL.
            # We will assume there is an API endpoint or we post to a specific 'receive' endpoint.
            # If the user meant the UI, we can't really "transfer" to a UI.
            # We'll try posting to /api/fiscal/receive or similar, but for now let's use the base + /api/receive
            # OR we simply post to the exact URL provided if it accepts POST.
            # Given instructions "transfer to...", let's assume an endpoint exists.
            # I will use a dedicated API endpoint assumption: /api/fiscal/receive
            
            # However, looking at the URL http://192.168.69.99:5000/config/fiscal, it looks like another instance of THIS app.
            # If so, it might have the SAME routes.
            # But 'config/fiscal' is the UI route I just added to THIS app.
            # So I should probably add a receiver route to THIS app's code (which will run on the other server too)
            # to handle the incoming POST.
            
            target_url = str(
                get_config_value(
                    'fiscal_pool_remote_receive_url',
                    "http://192.168.69.99:5001/api/fiscal/receive"
                ) or ''
            ).strip()
            if not target_url:
                return False
            
            response = requests.post(target_url, json=entry, timeout=5)
            if response.status_code == 200:
                print(f"Fiscal Entry {entry['id']} synced to remote successfully.")
                return True
            else:
                print(f"Failed to sync fiscal entry {entry['id']}: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Exception syncing fiscal entry {entry['id']}: {e}")
            return False

    @staticmethod
    def set_xml_ready(entry_id, ready=True, xml_path=None):
        """
        Marks an entry as having its XML available and optionally stores the path.
        """
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                entry['xml_ready'] = bool(ready)
                if xml_path:
                    entry['xml_path'] = xml_path
                return FiscalPoolService._save_pool(pool)
        return False

    @staticmethod
    def set_pdf_ready(entry_id, ready=True, pdf_path=None):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                entry['pdf_ready'] = bool(ready)
                if pdf_path:
                    entry['pdf_path'] = pdf_path
                return FiscalPoolService._save_pool(pool)
        return False

    @staticmethod
    def get_pool(filters=None):
        pool = FiscalPoolService._load_pool()
        if not filters:
            # Return sorted by date desc
            return sorted(pool, key=lambda x: x['closed_at'], reverse=True)
            
        filtered = []
        for entry in pool:
            match = True
            if filters.get('status') and filters['status'] != 'all' and entry['status'] != filters['status']:
                match = False
            if filters.get('origin') and filters['origin'] != 'all' and entry['origin'] != filters['origin']:
                match = False
            if filters.get('date_start'):
                # Simple string compare works if format is YYYY-MM-DD
                if entry['closed_at'] < filters['date_start']:
                    match = False
            if filters.get('date_end'):
                if entry['closed_at'] > filters['date_end']:
                    match = False
                    
            if match:
                filtered.append(entry)
                
        return sorted(filtered, key=lambda x: x['closed_at'], reverse=True)

    @staticmethod
    def get_entry(entry_id):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                return entry
        return None

    @staticmethod
    def update_status(entry_id, new_status, fiscal_doc_uuid=None, user='Sistema', serie=None, number=None, error_msg=None, access_key=None):
        pool = FiscalPoolService._load_pool()
        for entry in pool:
            if entry['id'] == entry_id:
                old_status = entry['status']
                entry['status'] = FiscalPoolService._normalize_status(new_status)
                if fiscal_doc_uuid:
                    entry['fiscal_doc_uuid'] = fiscal_doc_uuid
                
                if serie:
                    entry['fiscal_serie'] = serie
                if number:
                    entry['fiscal_number'] = number
                if access_key:
                    entry['access_key'] = str(access_key)
                
                if error_msg:
                    entry['last_error'] = error_msg
                
                entry['history'].append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'status_change',
                    'from': old_status,
                    'to': new_status,
                    'user': user,
                    'details': error_msg
                })
                
                FiscalPoolService._save_pool(pool)
                return True
        return False
