import pandas as pd
import os
import sys
from datetime import datetime
import re
import hashlib
from app.services.system_config_manager import (
    MANUAL_ALLOCATIONS_FILE, GUEST_DETAILS_FILE, 
    MANUAL_RESERVATIONS_FILE, RESERVATIONS_DIR
)
from app.services.cashier_service import file_lock

class ReservationService:
    RESERVATIONS_DIR = RESERVATIONS_DIR
    RESERVATIONS_FILE = os.path.join(RESERVATIONS_DIR, "minhas_reservas.xlsx")
    MANUAL_RESERVATIONS_FILE = MANUAL_RESERVATIONS_FILE
    MANUAL_ALLOCATIONS_FILE = MANUAL_ALLOCATIONS_FILE
    RESERVATION_STATUS_OVERRIDES_FILE = os.path.join(RESERVATIONS_DIR, "reservation_status_overrides.json")
    
    RESERVATION_PAYMENTS_FILE = os.path.join(RESERVATIONS_DIR, "reservation_payments.json")
    RESERVATION_SYNC_LOG_FILE = os.path.join(RESERVATIONS_DIR, "reservation_sync_logs.json")

    ROOM_CAPACITIES = {
        "01": 2, "02": 2, "03": 2,
        "11": 4, # Family
        "12": 2, "14": 2, "15": 2, "16": 2, "17": 2,
        "21": 2, "22": 2, "23": 2, "24": 2, "25": 2, "26": 2,
        "31": 2, "32": 2, "33": 2, "34": 2, "35": 2
    }
    RESERVATION_STATUS_CATALOG = {
        'pre-reserva': 'Pré-reserva',
        'confirmada': 'Confirmada',
        'cancelada': 'Cancelada',
        'no-show': 'No-show',
        'hospedado': 'Hospedado',
        'finalizada': 'Finalizada',
    }
    OPERATIONAL_STATUS_CATALOG = {
        'aguardando_checkin': 'Aguardando check-in',
        'checkin_realizado': 'Check-in realizado',
        'ocupada': 'Ocupada',
        'saida_prevista_hoje': 'Saída prevista hoje',
        'checkout_realizado': 'Checkout realizado',
        'aguardando_limpeza': 'Aguardando limpeza',
        'em_limpeza': 'Em limpeza',
        'inspecionado': 'Inspecionado',
        'livre': 'Livre',
        'manutencao': 'Manutenção',
        'bloqueado': 'Bloqueado',
    }

    def _load_manual_allocations(self):
        import json
        manual_alloc_file = self.MANUAL_ALLOCATIONS_FILE
        if not os.path.exists(manual_alloc_file):
            return {}
        cached_data = getattr(self, '_manual_allocations_cache_data', None)
        cached_mtime = getattr(self, '_manual_allocations_cache_mtime', None)
        current_mtime = None
        try:
            current_mtime = os.path.getmtime(manual_alloc_file)
        except Exception:
            current_mtime = None
        if isinstance(cached_data, dict) and cached_mtime == current_mtime:
            return dict(cached_data)
        def _read_unlocked():
            with open(manual_alloc_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            return loaded if isinstance(loaded, dict) else {}
        try:
            with file_lock(manual_alloc_file):
                data = _read_unlocked()
        except Exception:
            try:
                data = _read_unlocked()
            except Exception:
                return dict(cached_data) if isinstance(cached_data, dict) else {}
        self._manual_allocations_cache_data = dict(data)
        self._manual_allocations_cache_mtime = current_mtime
        return data

    def _enrich_reservation_for_checkin(self, reservation):
        if not isinstance(reservation, dict):
            return reservation
        res = dict(reservation)
        rid = str(res.get('id') or '')
        if not rid:
            return res

        manual_allocs = self._load_manual_allocations()
        if rid in manual_allocs and isinstance(manual_allocs.get(rid), dict):
            room_value = manual_allocs[rid].get('room')
            if room_value:
                res['room'] = str(room_value)

        cat_lower = str(res.get('category', '')).lower()
        if 'família' in cat_lower or 'quadruplo' in cat_lower:
            res['num_adults'] = 4
        elif 'triplo' in cat_lower:
            res['num_adults'] = 3
        elif 'duplo' in cat_lower or 'casal' in cat_lower:
            res['num_adults'] = 2
        elif 'individual' in cat_lower or 'solteiro' in cat_lower:
            res['num_adults'] = 1
        elif 'suíte' in cat_lower:
            res['num_adults'] = 2
        elif res.get('room') and str(res['room']) in self.ROOM_CAPACITIES:
            res['num_adults'] = self.ROOM_CAPACITIES[str(res['room'])]
        else:
            res['num_adults'] = int(res.get('num_adults') or 1)

        try:
            details = self.get_guest_details(rid)
            p_info = details.get('personal_info') if isinstance(details, dict) else {}
            if isinstance(p_info, dict):
                if p_info.get('email'):
                    res['email'] = p_info['email']
                if p_info.get('phone'):
                    res['phone'] = p_info['phone']

                doc_value = p_info.get('doc_id') or p_info.get('cpf') or p_info.get('document')
                if doc_value:
                    res['doc_id'] = doc_value

                if p_info.get('address'):
                    res['address'] = p_info['address']
                if p_info.get('city'):
                    res['city'] = p_info['city']
                if p_info.get('state'):
                    res['state'] = p_info['state']

                zip_value = p_info.get('zipcode') or p_info.get('zip')
                if zip_value:
                    res['zipcode'] = zip_value

                if p_info.get('nationality'):
                    res['nationality'] = p_info['nationality']
                if p_info.get('profession'):
                    res['profession'] = p_info['profession']
                if p_info.get('gender'):
                    res['gender'] = p_info['gender']
                if p_info.get('birth_date'):
                    res['birth_date'] = p_info['birth_date']
        except Exception:
            pass

        return res

    def get_reservation_for_checkin(self, reservation_id):
        res = self.get_reservation_by_id(reservation_id)
        if not res:
            return None
        return self._enrich_reservation_for_checkin(res)

    def get_upcoming_checkins(self, days=2):
        """
        Returns a list of reservations checking in within the next 'days'.
        """
        import json
        from datetime import datetime, timedelta

        target_reservations = []
        today = datetime.now().date()
        limit_date = today + timedelta(days=days)
        
        # 1. Get all reservations
        all_res = self.get_february_reservations() 
        
        for res in all_res:
            # Filter Status
            status = str(res.get('status', '')).lower()
            if 'cancel' in status: continue
            
            # Filter Date
            cin_str = res.get('checkin')
            if not cin_str: continue
            
            try:
                if '-' in cin_str:
                    cin_date = datetime.strptime(cin_str, '%Y-%m-%d').date()
                else:
                    cin_date = datetime.strptime(cin_str, '%d/%m/%Y').date()
            except: continue
            
            if today <= cin_date < limit_date:
                target_reservations.append(self._enrich_reservation_for_checkin(res))
                
        return target_reservations

    def get_reservation_payments(self):
        import json
        if not os.path.exists(self.RESERVATION_PAYMENTS_FILE):
            return {}
        try:
            with file_lock(self.RESERVATION_PAYMENTS_FILE):
                with open(self.RESERVATION_PAYMENTS_FILE, 'r') as f:
                    return json.load(f)
        except:
            return {}

    def save_reservation_payment(self, reservation_id, payment_data):
        import json
        with file_lock(self.RESERVATION_PAYMENTS_FILE):
            if os.path.exists(self.RESERVATION_PAYMENTS_FILE):
                try:
                    with open(self.RESERVATION_PAYMENTS_FILE, 'r') as f:
                        payments = json.load(f)
                except:
                    payments = {}
            else:
                payments = {}
                
            if reservation_id not in payments:
                payments[reservation_id] = []
            
            payments[reservation_id].append(payment_data)
            
            with open(self.RESERVATION_PAYMENTS_FILE, 'w') as f:
                json.dump(payments, f, indent=4)

    def _find_reservation_by_id_raw(self, reservation_id):
        # Check Manual
        manual = self.get_manual_reservations_data()
        for i, res in enumerate(manual):
            rid = str(res.get('id'))
            target = str(reservation_id)
            if rid == target:
                res['source_type'] = 'manual'
                return res
        
        # Check Main Excel
        if os.path.exists(self.RESERVATIONS_FILE):
            items = self._parse_excel_file(self.RESERVATIONS_FILE)
            for item in items:
                if str(item.get('id')) == str(reservation_id):
                    item['source_type'] = 'excel'
                    return item
                    
        # Check other Excel files in directory
        if os.path.exists(self.RESERVATIONS_DIR):
            for f in os.listdir(self.RESERVATIONS_DIR):
                if (f.endswith('.xlsx') or f.endswith('.xls')) and f != os.path.basename(self.RESERVATIONS_FILE):
                    items = self._parse_excel_file(os.path.join(self.RESERVATIONS_DIR, f))
                    for item in items:
                        if str(item.get('id')) == str(reservation_id):
                            item['source_type'] = 'excel'
                            return item
        return None

    def get_reservation_by_id(self, reservation_id):
        res = self._find_reservation_by_id_raw(reservation_id)
        if not res:
            return None
        rid = str(res.get('id') or reservation_id or '')
        merged = self.merge_overrides_into_reservation(rid, res)
        overrides = self.get_reservation_status_overrides()
        if rid in overrides:
            merged['status'] = overrides[rid]
        return merged

    def _parse_date(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        raw = str(value).strip()
        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(raw, fmt).date()
            except Exception:
                continue
        return None

    def _normalize_imported_at_date(self, value):
        if isinstance(value, datetime):
            return value.strftime('%d/%m/%Y')
        raw = str(value or '').strip()
        if not raw:
            return datetime.now().strftime('%d/%m/%Y')
        candidates = [
            '%d/%m/%Y',
            '%d/%m/%Y %H:%M',
            '%Y-%m-%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(raw, fmt).strftime('%d/%m/%Y')
            except Exception:
                continue
        if 'T' in raw:
            base = raw.split('T', 1)[0]
            try:
                return datetime.strptime(base, '%Y-%m-%d').strftime('%d/%m/%Y')
            except Exception:
                pass
        if ' ' in raw:
            base = raw.split(' ', 1)[0]
            for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
                try:
                    return datetime.strptime(base, fmt).strftime('%d/%m/%Y')
                except Exception:
                    continue
        return datetime.now().strftime('%d/%m/%Y')

    def _parse_money(self, value):
        try:
            if value is None:
                return 0.0
            txt = str(value).replace('R$', '').strip()
            if ',' in txt:
                txt = txt.replace('.', '').replace(',', '.')
            return float(txt)
        except Exception:
            return 0.0

    def _normalize_doc(self, value):
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    def _normalize_phone(self, value):
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    def _normalize_email(self, value):
        return str(value or '').strip().lower()

    def _normalize_name(self, value):
        cleaned = re.sub(r'\s+', ' ', str(value or '').strip().lower())
        return cleaned

    def _append_sync_log(self, event, reservation_id, payload=None, source='system', direction='bidirectional'):
        import json
        log_row = {
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'event': str(event or '').strip(),
            'reservation_id': str(reservation_id or '').strip(),
            'source': str(source or 'system').strip(),
            'direction': str(direction or 'bidirectional').strip(),
            'payload': payload if isinstance(payload, dict) else {}
        }
        with file_lock(self.RESERVATION_SYNC_LOG_FILE):
            rows = []
            if os.path.exists(self.RESERVATION_SYNC_LOG_FILE):
                try:
                    with open(self.RESERVATION_SYNC_LOG_FILE, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                        rows = loaded if isinstance(loaded, list) else []
                except Exception:
                    rows = []
            rows.append(log_row)
            if len(rows) > 3000:
                rows = rows[-3000:]
            with open(self.RESERVATION_SYNC_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(rows, f, indent=2, ensure_ascii=False)

    def _normalize_text(self, value):
        raw = str(value or '').strip().lower()
        accents = str.maketrans('áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')
        return raw.translate(accents)

    def normalize_reservation_status(self, raw_status, checkin=None, checkout=None):
        status = self._normalize_text(raw_status)
        if any(k in status for k in ['cancel', 'cancelad']):
            code = 'cancelada'
        elif 'no-show' in status or 'noshow' in status:
            code = 'no-show'
        elif any(k in status for k in ['checked-out', 'checkout', 'finalizad']):
            code = 'finalizada'
        elif any(k in status for k in ['checked-in', 'hosped', 'ocupad']):
            code = 'hospedado'
        elif any(k in status for k in ['pre-reserva', 'pre reserva', 'pre']):
            code = 'pre-reserva'
        elif any(k in status for k in ['confirm', 'pendente', 'reservad']):
            code = 'confirmada'
        else:
            checkin_date = self._parse_date(checkin)
            checkout_date = self._parse_date(checkout)
            today = datetime.now().date()
            if checkout_date and checkout_date < today:
                code = 'finalizada'
            elif checkin_date and checkin_date > today:
                code = 'confirmada'
            else:
                code = 'confirmada'
        return {
            'code': code,
            'label': self.RESERVATION_STATUS_CATALOG.get(code, 'Confirmada')
        }

    def normalize_operational_status(self, raw_status):
        status = self._normalize_text(raw_status)
        if 'manutenc' in status:
            code = 'manutencao'
        elif 'block' in status or 'bloque' in status:
            code = 'bloqueado'
        elif 'inspect' in status or 'inspec' in status:
            code = 'inspecionado'
        elif 'cleaning' in status or 'limpeza' in status or 'in_progress' in status:
            code = 'em_limpeza'
        elif 'dirty' in status or 'aguardando limpeza' in status:
            code = 'aguardando_limpeza'
        elif 'livre' in status or 'free' in status:
            code = 'livre'
        else:
            code = 'livre'
        return {
            'code': code,
            'label': self.OPERATIONAL_STATUS_CATALOG.get(code, 'Livre')
        }

    def derive_stay_operational_status(self, reservation, occupancy_data=None, cleaning_status=None):
        res = reservation if isinstance(reservation, dict) else {}
        occupancy = occupancy_data if isinstance(occupancy_data, dict) else {}
        cleaning = cleaning_status if isinstance(cleaning_status, dict) else {}
        rid = str(res.get('id') or '')
        today = datetime.now().strftime('%d/%m/%Y')

        active_room = ''
        active_occ = None
        for room_key, occ in occupancy.items():
            if str((occ or {}).get('reservation_id') or '') == rid:
                active_room = str(room_key)
                active_occ = occ or {}
                break

        if active_occ:
            checkout = str(active_occ.get('checkout') or '')
            if checkout == today:
                return {'code': 'saida_prevista_hoje', 'label': self.OPERATIONAL_STATUS_CATALOG['saida_prevista_hoje'], 'room': active_room}
            checked_in_at = str(active_occ.get('checked_in_at') or '').strip()
            if checked_in_at:
                return {'code': 'ocupada', 'label': self.OPERATIONAL_STATUS_CATALOG['ocupada'], 'room': active_room}
            return {'code': 'checkin_realizado', 'label': self.OPERATIONAL_STATUS_CATALOG['checkin_realizado'], 'room': active_room}

        status_info = self.normalize_reservation_status(res.get('status'), res.get('checkin'), res.get('checkout'))
        if status_info.get('code') == 'finalizada':
            return {'code': 'checkout_realizado', 'label': self.OPERATIONAL_STATUS_CATALOG['checkout_realizado'], 'room': None}
        if status_info.get('code') in ['confirmada', 'pre-reserva']:
            return {'code': 'aguardando_checkin', 'label': self.OPERATIONAL_STATUS_CATALOG['aguardando_checkin'], 'room': res.get('room')}

        room = str(res.get('room') or '')
        room_clean = cleaning.get(room, {}) if room else {}
        clean_info = self.normalize_operational_status((room_clean or {}).get('status', 'livre'))
        return {'code': clean_info.get('code'), 'label': clean_info.get('label'), 'room': room or None}

    def build_guest_master_record(self, reservation_id, reservation=None, guest_details=None):
        rid = str(reservation_id)
        res = reservation if isinstance(reservation, dict) else (self.get_reservation_by_id(rid) or {})
        details = guest_details if isinstance(guest_details, dict) else (self.get_guest_details(rid) or {})
        pi = details.get('personal_info') if isinstance(details.get('personal_info'), dict) else {}
        recurrence = details.get('recurrence_summary') if isinstance(details.get('recurrence_summary'), dict) else {}
        return {
            'guest_uid': details.get('guest_uid'),
            'nome_completo': pi.get('name') or res.get('guest_name') or '',
            'documento': pi.get('doc_id') or pi.get('cpf') or '',
            'data_nascimento': pi.get('birth_date') or pi.get('dob') or '',
            'telefone': pi.get('phone') or '',
            'email': pi.get('email') or '',
            'endereco': pi.get('address') or '',
            'observacoes': details.get('notes') or '',
            'documento_anexado': bool(details.get('document_photo')),
            'assinatura': bool(details.get('signature')),
            'historico_estadias': recurrence
        }

    def build_reservation_record(self, reservation_id, reservation=None):
        rid = str(reservation_id)
        res = reservation if isinstance(reservation, dict) else (self.get_reservation_by_id(rid) or {})
        status_info = self.normalize_reservation_status(res.get('status'), res.get('checkin'), res.get('checkout'))
        return {
            'id': rid,
            'origem_canal': res.get('channel') or '',
            'datas': {'checkin': res.get('checkin') or '', 'checkout': res.get('checkout') or ''},
            'categoria_reservada': res.get('category') or '',
            'quarto_alocado': res.get('room') or '',
            'valor_total': res.get('amount') or '0.00',
            'status_reserva': status_info,
            'pagamentos': {'previsto': res.get('amount') or '0.00', 'recebido': res.get('paid_amount') or '0.00'},
            'observacoes_comerciais': res.get('commercial_notes') or res.get('notes') or '',
            'identificador_externo': {
                'source': res.get('external_source') or '',
                'id': res.get('external_reservation_id') or ''
            }
        }

    def build_stay_record(self, reservation_id, reservation=None, guest_details=None, occupancy_data=None, cleaning_status=None):
        rid = str(reservation_id)
        res = reservation if isinstance(reservation, dict) else (self.get_reservation_by_id(rid) or {})
        details = guest_details if isinstance(guest_details, dict) else (self.get_guest_details(rid) or {})
        occupancy = occupancy_data if isinstance(occupancy_data, dict) else {}
        if not occupancy:
            try:
                from app.services.data_service import load_room_occupancy
                occupancy = load_room_occupancy() or {}
            except Exception:
                occupancy = {}
        clean_status = cleaning_status if isinstance(cleaning_status, dict) else {}
        if not clean_status:
            try:
                from app.services.data_service import load_cleaning_status
                clean_status = load_cleaning_status() or {}
            except Exception:
                clean_status = {}

        op_status = self.derive_stay_operational_status(res, occupancy, clean_status)
        active_occ = {}
        for _, occ in occupancy.items():
            if str((occ or {}).get('reservation_id') or '') == rid:
                active_occ = occ or {}
                break
        return {
            'reserva_vinculada': rid,
            'hospede_principal': (details.get('personal_info') or {}).get('name') or res.get('guest_name') or '',
            'acompanhantes': details.get('companions') if isinstance(details.get('companions'), list) else [],
            'quarto_real_ocupado': op_status.get('room') or active_occ.get('room_number') or '',
            'status_operacional': {'code': op_status.get('code'), 'label': op_status.get('label')},
            'checkin_realizado_em': active_occ.get('checked_in_at') or '',
            'checkout_realizado_em': active_occ.get('checked_out_at') or '',
            'consumo_lancado': active_occ.get('consumption_total') or 0,
            'pendencias': active_occ.get('pending') or [],
            'ocorrencia_operacional': active_occ.get('occurrence') or ''
        }

    def build_operational_sheet(self, reservation_id, guest_details=None):
        rid = str(reservation_id)
        reservation = self.get_reservation_by_id(rid) or {}
        details = guest_details if isinstance(guest_details, dict) else (self.get_guest_details(rid) or {})
        op = details.get('operational_info') if isinstance(details.get('operational_info'), dict) else {}
        recurrence = details.get('recurrence_summary') if isinstance(details.get('recurrence_summary'), dict) else {}
        companions = details.get('companions') if isinstance(details.get('companions'), list) else []
        companions_clean = []
        for comp in companions:
            if not isinstance(comp, dict):
                continue
            companions_clean.append({
                'nome': str(comp.get('name') or '').strip(),
                'relacao': str(comp.get('relationship') or '').strip(),
                'documento': str(comp.get('doc_id') or comp.get('cpf') or '').strip(),
                'alergias': comp.get('allergies') if isinstance(comp.get('allergies'), list) else [],
                'restricoes': comp.get('dietary_restrictions') if isinstance(comp.get('dietary_restrictions'), list) else [],
                'frutas_preferidas': comp.get('breakfast_fruits') if isinstance(comp.get('breakfast_fruits'), list) else [],
                'aniversariante': bool(comp.get('is_birthday')),
                'comemoracao': str(comp.get('special_celebration') or '').strip(),
                'observacoes': str(comp.get('hospitality_notes') or comp.get('food_notes') or '').strip()
            })
        breakfast_standard = str(op.get('breakfast_time_standard') or '').strip()
        if not breakfast_standard:
            start = str(op.get('breakfast_time_start') or '').strip()
            end = str(op.get('breakfast_time_end') or '').strip()
            breakfast_standard = f"{start}-{end}".strip('-') if (start or end) else ''
        breakfast_fruits = op.get('breakfast_fruit_preferences') if isinstance(op.get('breakfast_fruit_preferences'), list) else []
        breakfast_fruits = [str(v).strip() for v in breakfast_fruits if str(v).strip()][:8]
        allergies_value = op.get('allergies')
        allergies_list = op.get('allergies_list') if isinstance(op.get('allergies_list'), list) else []
        if isinstance(allergies_value, list):
            allergies_list = allergies_value
        elif isinstance(allergies_value, str) and allergies_value.strip():
            allergies_list = [x.strip() for x in allergies_value.split(',') if x.strip()]
        special_events = op.get('special_events') if isinstance(op.get('special_events'), list) else []
        if not special_events:
            special_events = op.get('commemorative_dates') if isinstance(op.get('commemorative_dates'), list) else []
        dietary_restrictions = op.get('dietary_restrictions') if isinstance(op.get('dietary_restrictions'), list) else []
        dietary_restrictions = [str(v).strip() for v in dietary_restrictions if str(v).strip()][:12]
        return {
            'restricoes_alimentares': dietary_restrictions,
            'alergias': allergies_list,
            'preferencias_cafe_manha': {
                'inicio': op.get('breakfast_time_start') or '',
                'fim': op.get('breakfast_time_end') or '',
                'padrao': breakfast_standard,
                'frutas': breakfast_fruits,
                'observacoes': op.get('breakfast_notes') or ''
            },
            'datas_comemorativas': special_events,
            'observacoes_atendimento': op.get('service_notes') or op.get('vip_note') or '',
            'observacoes_governanca': op.get('housekeeping_notes') or '',
            'sinalizacao_vip': bool(op.get('vip_note') or op.get('vip') or recurrence.get('stays_count', 0) >= 3),
            'sinalizacao_recorrente': recurrence.get('stays_count', 0) >= 2,
            'base_cafe_manha': {
                'quarto': reservation.get('room') or '',
                'hospede_principal': (details.get('personal_info') or {}).get('name') or reservation.get('guest_name') or '',
                'demais_hospedes': companions_clean,
                'numero_hospedes': 1 + len(companions_clean),
                'horario_cafe': breakfast_standard,
                'frutas_preferidas': breakfast_fruits,
                'alergias_restricoes': list(dict.fromkeys(dietary_restrictions + allergies_list)),
                'aniversariante': bool(op.get('is_birthday') or op.get('birthday_flag')),
                'comemoracao': op.get('special_celebration') or '',
                'observacoes_especiais': op.get('hospitality_notes') or op.get('service_notes') or '',
                'ultima_atualizacao': {
                    'quando': op.get('last_updated_at') or '',
                    'quem': op.get('last_updated_by') or '',
                    'origem': op.get('last_updated_source') or ''
                }
            }
        }

    def build_unified_reservation_record(self, reservation_id, occupancy_data=None, cleaning_status=None):
        rid = str(reservation_id)
        reservation = self.get_reservation_by_id(rid) or {}
        guest = self.get_guest_details(rid) or {}
        return {
            'guest_master': self.build_guest_master_record(rid, reservation=reservation, guest_details=guest),
            'reservation': self.build_reservation_record(rid, reservation=reservation),
            'stay': self.build_stay_record(rid, reservation=reservation, guest_details=guest, occupancy_data=occupancy_data, cleaning_status=cleaning_status),
            'operational_sheet': self.build_operational_sheet(rid, guest_details=guest),
            'status_catalog': {
                'reserva': self.RESERVATION_STATUS_CATALOG,
                'operacional': self.OPERATIONAL_STATUS_CATALOG
            }
        }

    def sync_operational_state_for_reservation(self, reservation_id, reservation_status, occupancy_data=None, cleaning_status=None):
        rid = str(reservation_id or '').strip()
        occupancy = occupancy_data if isinstance(occupancy_data, dict) else {}
        cleaning = cleaning_status if isinstance(cleaning_status, dict) else {}
        status_info = self.normalize_reservation_status(reservation_status)
        status_code = status_info.get('code')
        found_room = None
        found_occ = None
        for room_key, occ in occupancy.items():
            if str((occ or {}).get('reservation_id') or '') == rid:
                found_room = str(room_key)
                found_occ = occ or {}
                break

        changed = {'occupancy_changed': False, 'cleaning_changed': False, 'room': found_room}
        if status_code in ['cancelada', 'no-show', 'finalizada'] and found_room:
            occupancy.pop(found_room, None)
            changed['occupancy_changed'] = True
            cleaning[found_room] = {
                'status': 'dirty_checkout',
                'marked_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'last_guest': (found_occ or {}).get('guest_name', ''),
                'note': f'Sincronizado por status de reserva: {status_info.get("label")}'
            }
            changed['cleaning_changed'] = True

        self._append_sync_log(
            event='reservation_status_sync',
            reservation_id=rid,
            payload={'status_code': status_code, 'status_label': status_info.get('label'), 'changed': changed},
            source='reservation_service',
            direction='reservation_to_rooms'
        )
        return changed

    def _build_guest_identity_signature(self, profile):
        if not isinstance(profile, dict):
            return ''
        doc = self._normalize_doc(profile.get('doc_id') or profile.get('cpf') or profile.get('document'))
        email = self._normalize_email(profile.get('email'))
        phone = self._normalize_phone(profile.get('phone'))
        name = self._normalize_name(profile.get('name') or profile.get('guest_name'))
        birth = str(profile.get('birth_date') or profile.get('dob') or '').strip()
        if doc:
            return f"doc:{doc}"
        if email:
            return f"email:{email}"
        if phone:
            return f"phone:{phone}"
        if name and birth:
            return f"name_birth:{name}|{birth}"
        if name:
            digest = hashlib.md5(name.encode('utf-8')).hexdigest()
            return f"name_hash:{digest}"
        return ''

    def get_guest_details_data(self):
        import json
        if not os.path.exists(GUEST_DETAILS_FILE):
            return {}
        try:
            with file_lock(GUEST_DETAILS_FILE):
                with open(GUEST_DETAILS_FILE, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                    return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _ensure_guest_identity(self, reservation_id, details, all_details=None):
        if not isinstance(details, dict):
            details = {}
        all_map = all_details if isinstance(all_details, dict) else self.get_guest_details_data()

        personal = details.get('personal_info') if isinstance(details.get('personal_info'), dict) else {}
        res = self.get_reservation_by_id(reservation_id) or {}
        profile = dict(personal)
        if not profile.get('name'):
            profile['name'] = res.get('guest_name', '')
        signature = self._build_guest_identity_signature(profile)
        guest_uid = ''
        confidence = 'baixa'
        duplicate_candidates = []
        if signature:
            for rid, info in (all_map or {}).items():
                if str(rid) == str(reservation_id):
                    continue
                if not isinstance(info, dict):
                    continue
                p = info.get('personal_info') if isinstance(info.get('personal_info'), dict) else {}
                p_profile = dict(p)
                if not p_profile.get('name'):
                    other_res = self.get_reservation_by_id(rid) or {}
                    p_profile['name'] = other_res.get('guest_name', '')
                if self._build_guest_identity_signature(p_profile) == signature:
                    same_uid = str(info.get('guest_uid') or '').strip()
                    if same_uid:
                        guest_uid = same_uid
                    duplicate_candidates.append(str(rid))
            if duplicate_candidates:
                confidence = 'alta'

        if not guest_uid:
            seed = signature or f"reservation:{reservation_id}"
            guest_uid = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]

        details['guest_uid'] = guest_uid
        details['identity_signature'] = signature
        details['possible_duplicate_reservations'] = duplicate_candidates[:10]
        details['match_confidence'] = confidence
        return details

    def _build_guest_recurrence_summary(self, reservation_id, details, all_details=None):
        all_map = all_details if isinstance(all_details, dict) else self.get_guest_details_data()
        current = details if isinstance(details, dict) else {}
        guest_uid = str(current.get('guest_uid') or '').strip()
        if not guest_uid:
            return {'stays_count': 0, 'last_stay': None, 'suggested_existing_reservation': None}

        reservations = self.get_february_reservations() or []
        by_id = {str(r.get('id')): r for r in reservations if isinstance(r, dict)}
        linked = []
        for rid, info in (all_map or {}).items():
            if not isinstance(info, dict):
                continue
            if str(info.get('guest_uid') or '') != guest_uid:
                continue
            res = by_id.get(str(rid)) or {}
            checkout = res.get('checkout') or (info.get('stay_info') or {}).get('checkout') or ''
            linked.append({'reservation_id': str(rid), 'checkout': checkout, 'guest_name': res.get('guest_name') or (info.get('personal_info') or {}).get('name')})

        linked_sorted = sorted(
            linked,
            key=lambda item: self._parse_date(item.get('checkout')) or datetime.min.date(),
            reverse=True
        )
        last_stay = linked_sorted[0].get('checkout') if linked_sorted else None
        suggested_existing = None
        for item in linked_sorted:
            if str(item.get('reservation_id')) != str(reservation_id):
                suggested_existing = item.get('reservation_id')
                break
        return {
            'stays_count': len(linked_sorted),
            'last_stay': last_stay,
            'suggested_existing_reservation': suggested_existing
        }

    def merge_overrides_into_reservation(self, reservation_id, reservation):
        base = dict(reservation) if isinstance(reservation, dict) else {}
        rid = str(reservation_id or base.get('id') or '')
        if rid and not base.get('id'):
            base['id'] = rid

        allocs = self._load_manual_allocations()
        override = allocs.get(rid, {}) if isinstance(allocs, dict) else {}
        if not isinstance(override, dict):
            override = {}

        for key in ('room', 'checkin', 'checkout'):
            if override.get(key):
                base[key] = override.get(key)

        financial = override.get('financial', {})
        if isinstance(financial, dict):
            for key in ('amount', 'paid_amount', 'to_receive', 'status', 'channel'):
                if financial.get(key) not in (None, ''):
                    base[key] = financial.get(key)

        amount_num = self._parse_money(base.get('amount') or base.get('amount_val'))
        paid_num = self._parse_money(base.get('paid_amount') or base.get('paid_amount_val'))
        to_receive_num = self._parse_money(base.get('to_receive') or base.get('to_receive_val'))
        if not base.get('to_receive'):
            to_receive_num = max(0.0, amount_num - paid_num)
            base['to_receive'] = f"{to_receive_num:.2f}"

        base['amount_val'] = round(amount_num, 2)
        base['paid_amount_val'] = round(paid_num, 2)
        base['to_receive_val'] = round(to_receive_num, 2)

        checkin_date = self._parse_date(base.get('checkin'))
        checkout_date = self._parse_date(base.get('checkout'))
        if checkin_date and checkout_date and checkout_date > checkin_date:
            days = max((checkout_date - checkin_date).days, 1)
            base['avg_daily_paid'] = round(paid_num / days, 2)
        else:
            base['avg_daily_paid'] = 0.0

        return base

    def get_manual_room(self, reservation_id):
        alloc = self._load_manual_allocations()
        entry = alloc.get(str(reservation_id), {}) if isinstance(alloc, dict) else {}
        if not isinstance(entry, dict):
            return None
        room = entry.get('room')
        return str(room) if room not in (None, '') else None

    def get_manual_dates(self, reservation_id):
        alloc = self._load_manual_allocations()
        entry = alloc.get(str(reservation_id), {}) if isinstance(alloc, dict) else {}
        if not isinstance(entry, dict):
            return (None, None)
        checkin = entry.get('checkin') or None
        checkout = entry.get('checkout') or None
        return (checkin, checkout)

    def calculate_reservation_update(self, reservation_id, new_room, new_checkin, new_checkout):
        from app.services.data_service import load_room_occupancy
        reservation = self.get_reservation_by_id(reservation_id)
        if not reservation:
            return {'valid': False, 'conflict_message': 'Reserva não encontrada'}

        old_checkin = self._parse_date(reservation.get('checkin'))
        old_checkout = self._parse_date(reservation.get('checkout'))
        new_checkin_date = self._parse_date(new_checkin)
        new_checkout_date = self._parse_date(new_checkout)

        if not new_checkin_date or not new_checkout_date or new_checkout_date <= new_checkin_date:
            return {'valid': False, 'conflict_message': 'Período inválido'}

        old_total = self._parse_money(reservation.get('amount_val') or reservation.get('amount') or reservation.get('total_value'))
        old_days = max((old_checkout - old_checkin).days, 1) if old_checkin and old_checkout else 1
        new_days = max((new_checkout_date - new_checkin_date).days, 1)
        daily_rate = old_total / old_days if old_days else old_total
        new_total = round(daily_rate * new_days, 2)

        occupancy = load_room_occupancy() or {}
        occ = occupancy.get(str(new_room))
        if occ:
            occ_in = self._parse_date(occ.get('checkin'))
            occ_out = self._parse_date(occ.get('checkout'))
            overlap = False
            if occ_in and occ_out:
                overlap = new_checkin_date < occ_out and new_checkout_date > occ_in
            else:
                overlap = True
            if overlap:
                guest = occ.get('guest_name', 'Hóspede')
                return {
                    'valid': False,
                    'conflict_message': f'Quarto {new_room} ocupado por {guest}'
                }

        reservations = self.get_february_reservations() or []
        for other in reservations:
            other_id = str(other.get('id'))
            if other_id == str(reservation_id):
                continue
            other_room = self.get_manual_room(other_id) if hasattr(self, 'get_manual_room') else None
            other_room = other_room or other.get('allocated_room') or other.get('room') or other.get('room_number')
            if str(other_room) != str(new_room):
                continue
            manual_dates = self.get_manual_dates(other_id) if hasattr(self, 'get_manual_dates') else (None, None)
            other_checkin = self._parse_date(manual_dates[0]) if manual_dates and manual_dates[0] else self._parse_date(other.get('checkin'))
            other_checkout = self._parse_date(manual_dates[1]) if manual_dates and manual_dates[1] else self._parse_date(other.get('checkout'))
            if not other_checkin or not other_checkout:
                continue
            if new_checkin_date < other_checkout and new_checkout_date > other_checkin:
                guest_name = other.get('guest_name', 'Outro hóspede')
                return {
                    'valid': False,
                    'conflict_message': f'Conflito com reserva de {guest_name}'
                }

        return {
            'valid': True,
            'old_total': round(old_total, 2),
            'new_total': new_total,
            'days': new_days,
            'diff': round(new_total - old_total, 2)
        }

    def search_reservations(self, query):
        import unicodedata
        q = str(query or '').strip()
        if not q:
            return []

        def norm(text):
            raw = str(text or '')
            raw = ''.join(c for c in unicodedata.normalize('NFD', raw) if unicodedata.category(c) != 'Mn')
            return raw.lower()

        def digits(text):
            return ''.join(ch for ch in str(text or '') if ch.isdigit())

        q_norm = norm(q)
        q_digits = digits(q)
        details = self.get_guest_details_data() if hasattr(self, 'get_guest_details_data') else {}
        reservations = self.get_february_reservations() or []
        found = []

        for res in reservations:
            rid = str(res.get('id'))
            d = details.get(rid, {}) if isinstance(details, dict) else {}
            p = d.get('personal_info', {}) if isinstance(d, dict) else {}
            f = d.get('fiscal_info', {}) if isinstance(d, dict) else {}

            names = [
                res.get('guest_name', ''),
                p.get('name', ''),
            ]
            docs = [
                p.get('doc_id', ''),
                f.get('cpf', ''),
                f.get('cnpj', ''),
            ]

            name_match = any(q_norm in norm(name) for name in names if name)
            doc_match = bool(q_digits) and any(q_digits in digits(doc) for doc in docs if doc)

            if name_match or doc_match:
                found.append(res)

        found.sort(key=lambda r: self._parse_date(r.get('checkin')) or datetime.min.date(), reverse=True)
        return found

    def check_collision(self, reservation_id, room_number, checkin, checkout, occupancy_data=None):
        room_number = str(room_number)
        checkin_date = self._parse_date(checkin)
        checkout_date = self._parse_date(checkout)
        if not checkin_date or not checkout_date or checkout_date <= checkin_date:
            raise ValueError('Período inválido para alocação.')

        occupancy = occupancy_data if isinstance(occupancy_data, dict) else {}
        room_occ = occupancy.get(room_number)
        if room_occ:
            if str((room_occ or {}).get('reservation_id') or '') == str(reservation_id):
                room_occ = None
        if room_occ:
            occ_in = self._parse_date(room_occ.get('checkin'))
            occ_out = self._parse_date(room_occ.get('checkout'))
            if occ_in and occ_out and checkin_date < occ_out and checkout_date > occ_in:
                guest = room_occ.get('guest_name', 'Hóspede')
                raise ValueError(f'Quarto {room_number} ocupado por {guest} no período selecionado.')

        for res in self.get_february_reservations() or []:
            rid = str(res.get('id'))
            if str(reservation_id) != 'new' and rid == str(reservation_id):
                continue
            room = self.get_manual_room(rid) if hasattr(self, 'get_manual_room') else None
            room = room or res.get('allocated_room') or res.get('room') or res.get('room_number')
            if str(room) != room_number:
                continue
            r_in = self._parse_date(res.get('checkin'))
            r_out = self._parse_date(res.get('checkout'))
            if r_in and r_out and checkin_date < r_out and checkout_date > r_in:
                guest = res.get('guest_name', 'Outro hóspede')
                raise ValueError(f'Conflito com reserva de {guest} no quarto {room_number}.')
        return True

    def validate_stay_restrictions(self, category, checkin, checkout, package_id=None):
        from app.services.stay_restriction_service import StayRestrictionService
        return StayRestrictionService.validate_stay(
            category=category,
            checkin=checkin,
            checkout=checkout,
            package_id=package_id,
        )

    def has_availability_for_category(self, category, checkin, checkout, channel='Recepção'):
        from app.services.inventory_restriction_service import InventoryRestrictionService
        from app.services.tariff_priority_engine_service import TariffPriorityEngineService
        engine = TariffPriorityEngineService.evaluate(
            category=category,
            channel=channel,
            checkin=checkin,
            checkout=checkout,
            apply_dynamic=False,
        )
        if not engine.get('sellable'):
            return False
        if not InventoryRestrictionService.is_open_for_period(category, checkin, checkout):
            return False
        rooms = self.get_room_mapping().get(category, [])
        for room in rooms:
            try:
                self.check_collision('new', room, checkin, checkout)
                return True
            except ValueError:
                continue
        return False

    def available_categories_for_period(self, checkin, checkout, exclude_category=None, channel='Recepção'):
        from app.services.inventory_restriction_service import InventoryRestrictionService
        from app.services.tariff_priority_engine_service import TariffPriorityEngineService
        available = []
        for category, rooms in self.get_room_mapping().items():
            if exclude_category and str(category) == str(exclude_category):
                continue
            engine = TariffPriorityEngineService.evaluate(
                category=category,
                channel=channel,
                checkin=checkin,
                checkout=checkout,
                apply_dynamic=False,
            )
            if not engine.get('sellable'):
                continue
            if not InventoryRestrictionService.is_open_for_period(category, checkin, checkout):
                continue
            for room in rooms:
                try:
                    self.check_collision('new', room, checkin, checkout)
                    available.append(category)
                    break
                except ValueError:
                    continue
        return available

    def add_payment(self, reservation_id, amount, payment_details):
        # print(f"DEBUG: add_payment id={reservation_id} amount={amount}")
        res = self.get_reservation_by_id(reservation_id)
        if not res:
            raise ValueError("Reserva não encontrada")
            
        # Record payment in sidecar
        self.save_reservation_payment(reservation_id, {
            'amount': amount,
            'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'details': payment_details
        })
        
        # print(f"DEBUG: add_payment source_type={res.get('source_type')}")
        
        # If manual, update the file directly too for consistency
        if res.get('source_type') == 'manual':
            self.update_manual_reservation_payment(reservation_id, amount)

        try:
            from app.services.reservation_rateio_service import ReservationRateioService
            total_package = res.get('amount') or res.get('total_value') or res.get('total')
            ReservationRateioService.generate(
                reservation_id=str(reservation_id),
                total_package=total_package,
                checkin=res.get('checkin'),
                checkout=res.get('checkout'),
                user=payment_details.get('user') if isinstance(payment_details, dict) else 'Sistema',
                trigger='package_payment',
                force=False
            )
        except Exception:
            pass

    def update_manual_reservation_payment(self, reservation_id, amount):
        import json
        # print(f"DEBUG: update_manual_reservation_payment id={reservation_id} amount={amount}")
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            # print("DEBUG: MANUAL_RESERVATIONS_FILE not found")
            return
            
        with file_lock(self.MANUAL_RESERVATIONS_FILE):
            with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                data = json.load(f)
                
            changed = False
            found = False
            for item in data:
                if str(item.get('id')) == str(reservation_id):
                    found = True
                    try:
                        val_str = str(item.get('paid_amount', '0')).strip()
                        if ',' in val_str:
                            # Assume BR format: 1.000,00
                            current_paid = float(val_str.replace('R$', '').replace('.', '').replace(',', '.'))
                        else:
                            # Assume standard format: 1000.00
                            current_paid = float(val_str.replace('R$', ''))
                    except:
                        current_paid = 0.0
                        
                    new_paid = current_paid + float(amount)
                    item['paid_amount'] = f"{new_paid:.2f}"
                    # print(f"DEBUG: Updating paid_amount from {current_paid} to {new_paid}")
                    
                    # Update remaining if needed
                    try:
                        total_str = str(item.get('amount', '0')).strip()
                        if ',' in total_str:
                            total = float(total_str.replace('R$', '').replace('.', '').replace(',', '.'))
                        else:
                            total = float(total_str.replace('R$', ''))
                    except:
                        total = 0.0
                        
                    item['to_receive'] = f"{max(0, total - new_paid):.2f}"
                    changed = True
                    break
            
            if not found:
                pass
                # print(f"DEBUG: Reservation ID {reservation_id} not found in file")
            
            if changed:
                with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                # print("DEBUG: File updated")

    def get_guest_details(self, reservation_id):
        import json
        
        # 1. Try to load from Guest Details File
        details = {}
        if os.path.exists(GUEST_DETAILS_FILE):
            try:
                with file_lock(GUEST_DETAILS_FILE):
                    with open(GUEST_DETAILS_FILE, 'r', encoding='utf-8') as f:
                        all_details = json.load(f)
                        details = all_details.get(str(reservation_id), {})
            except Exception as e:
                print(f"Error loading guest details: {e}")
        
        # 2. If empty, try to populate from Reservation
        if not details:
            res = self.get_reservation_by_id(reservation_id)
            if res:
                details = {
                    'personal_info': {
                        'name': res.get('guest_name', ''),
                        'email': '',
                        'phone': '',
                        'cpf': '',
                        'address': '',
                        'city': '',
                        'state': '',
                        'zip': '',
                        'country': ''
                    },
                    'history': [],
                    'companions': []
                }
        
        # Ensure structure
        if 'personal_info' not in details:
            details['personal_info'] = {}

        personal_info = details.get('personal_info')
        if isinstance(personal_info, dict):
            if not personal_info.get('doc_id') and personal_info.get('cpf'):
                personal_info['doc_id'] = personal_info.get('cpf')
            if not personal_info.get('cpf') and personal_info.get('doc_id'):
                personal_info['cpf'] = personal_info.get('doc_id')
            if not personal_info.get('zipcode') and personal_info.get('zip'):
                personal_info['zipcode'] = personal_info.get('zip')
            if not personal_info.get('zip') and personal_info.get('zipcode'):
                personal_info['zip'] = personal_info.get('zipcode')
        
        details = self._ensure_guest_identity(reservation_id, details)

        # If we have reservation but name is missing in details, sync it
        if 'name' not in details['personal_info'] or not details['personal_info']['name']:
             res = self.get_reservation_by_id(reservation_id)
             if res:
                 details['personal_info']['name'] = res.get('guest_name', '')
        details['recurrence_summary'] = self._build_guest_recurrence_summary(reservation_id, details)
        return details

    def update_guest_details(self, reservation_id, updates):
        """
        Updates guest details for a reservation.
        Updates 'guest_name' in MANUAL_RESERVATIONS_FILE.
        Updates other fields in GUEST_DETAILS_FILE.
        """
        import json
        
        success = False
        
        # 1. Update Manual Reservation (if name changed)
        if 'guest_name' in updates:
            if os.path.exists(self.MANUAL_RESERVATIONS_FILE):
                with file_lock(self.MANUAL_RESERVATIONS_FILE):
                    try:
                        with open(self.MANUAL_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        changed = False
                        for item in data:
                            if str(item.get('id')) == str(reservation_id):
                                item['guest_name'] = updates['guest_name']
                                changed = True
                        
                        if changed:
                            with open(self.MANUAL_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=4, ensure_ascii=False)
                            success = True
                    except Exception as e:
                        print(f"Error updating manual reservation: {e}")
        
        # 2. Update Extended Details in GUEST_DETAILS_FILE
        try:
            with file_lock(GUEST_DETAILS_FILE):
                all_details = {}
                if os.path.exists(GUEST_DETAILS_FILE):
                    try:
                        with open(GUEST_DETAILS_FILE, 'r', encoding='utf-8') as f:
                            all_details = json.load(f)
                    except:
                        all_details = {}
                
                # Get existing or create new
                current_details = all_details.get(str(reservation_id), {})
                
                # Ensure structure
                if 'personal_info' not in current_details:
                    current_details['personal_info'] = {}
                if 'companions' not in current_details:
                    current_details['companions'] = []
                
                # Map specific fields if present at top level
                if 'guest_name' in updates:
                    current_details['personal_info']['name'] = updates['guest_name']
                if 'email' in updates:
                    current_details['personal_info']['email'] = updates['email']
                if 'phone' in updates:
                    current_details['personal_info']['phone'] = updates['phone']
                if 'cpf' in updates:
                    current_details['personal_info']['cpf'] = updates['cpf']
                if 'notes' in updates:
                    current_details['notes'] = updates['notes']
                    
                # Also support direct structured updates
                if 'personal_info' in updates:
                    current_details['personal_info'].update(updates['personal_info'])
                    pi = current_details['personal_info']
                    if isinstance(pi, dict):
                        if not pi.get('cpf') and pi.get('doc_id'):
                            pi['cpf'] = pi.get('doc_id')
                        if not pi.get('doc_id') and pi.get('cpf'):
                            pi['doc_id'] = pi.get('cpf')
                        if not pi.get('zip') and pi.get('zipcode'):
                            pi['zip'] = pi.get('zipcode')
                        if not pi.get('zipcode') and pi.get('zip'):
                            pi['zipcode'] = pi.get('zip')
                
                if 'companions' in updates:
                    current_details['companions'] = updates['companions']
                if 'payment_followup' in updates and isinstance(updates.get('payment_followup'), dict):
                    current_details['payment_followup'] = updates.get('payment_followup')
                if 'fiscal_info' in updates and isinstance(updates.get('fiscal_info'), dict):
                    existing_fiscal = current_details.get('fiscal_info')
                    if not isinstance(existing_fiscal, dict):
                        existing_fiscal = {}
                    existing_fiscal.update(updates.get('fiscal_info') or {})
                    current_details['fiscal_info'] = existing_fiscal
                if 'operational_info' in updates and isinstance(updates.get('operational_info'), dict):
                    existing_operational = current_details.get('operational_info')
                    if not isinstance(existing_operational, dict):
                        existing_operational = {}
                    existing_operational.update(updates.get('operational_info') or {})
                    current_details['operational_info'] = existing_operational

                current_details = self._ensure_guest_identity(reservation_id, current_details, all_details=all_details)
                current_details['recurrence_summary'] = self._build_guest_recurrence_summary(reservation_id, current_details, all_details=all_details)
                all_details[str(reservation_id)] = current_details
                
                with open(GUEST_DETAILS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(all_details, f, indent=4, ensure_ascii=False)
                
                success = True
        except Exception as e:
            print(f"Error updating guest details file: {e}")
            
        return success

    def auto_pre_allocate(self, window_hours=48):
        """
        Placeholder for auto pre-allocation logic.
        Returns a list of actions taken.
        """
        # print(f"DEBUG: auto_pre_allocate window_hours={window_hours}")
        return []

    def save_manual_allocation(self, reservation_id, room_number, checkin, checkout, price_adjustment=None, occupancy_data=None):
        import json

        rid = str(reservation_id)
        room = str(room_number) if room_number not in (None, '') else ''
        checkin_val = str(checkin).strip() if checkin not in (None, '') else ''
        checkout_val = str(checkout).strip() if checkout not in (None, '') else ''

        base_res = self.get_reservation_by_id(rid) or self._find_reservation_by_id_raw(rid) or {}
        base_merged = self.merge_overrides_into_reservation(rid, base_res)

        if not checkin_val:
            checkin_val = str(base_merged.get('checkin') or '').strip()
        if not checkout_val:
            checkout_val = str(base_merged.get('checkout') or '').strip()

        if room and checkin_val and checkout_val:
            self.check_collision(rid, room, checkin_val, checkout_val, occupancy_data=occupancy_data or {})

        amount_num = self._parse_money(base_merged.get('amount') or base_merged.get('amount_val'))
        paid_num = self._parse_money(base_merged.get('paid_amount') or base_merged.get('paid_amount_val'))
        status_val = base_merged.get('status')
        channel_val = base_merged.get('channel')

        p_adj = price_adjustment if isinstance(price_adjustment, dict) else {}
        adj_type = str(p_adj.get('type') or '').strip().lower()
        if adj_type == 'manual_total':
            amount_num = self._parse_money(p_adj.get('amount'))
        elif adj_type in ['auto', 'recalculate']:
            old_checkin = self._parse_date(base_merged.get('checkin'))
            old_checkout = self._parse_date(base_merged.get('checkout'))
            new_checkin = self._parse_date(checkin_val)
            new_checkout = self._parse_date(checkout_val)
            if old_checkin and old_checkout and new_checkin and new_checkout and old_checkout > old_checkin and new_checkout > new_checkin:
                old_days = max((old_checkout - old_checkin).days, 1)
                new_days = max((new_checkout - new_checkin).days, 1)
                daily = amount_num / old_days if old_days else amount_num
                amount_num = round(daily * new_days, 2)

        to_receive_num = max(0.0, amount_num - paid_num)
        manual_alloc_file = self.MANUAL_ALLOCATIONS_FILE

        with file_lock(manual_alloc_file):
            allocations = {}
            if os.path.exists(manual_alloc_file):
                try:
                    with open(manual_alloc_file, 'r') as f:
                        allocations = json.load(f)
                except Exception:
                    allocations = {}

            current = allocations.get(rid, {})
            if not isinstance(current, dict):
                current = {}

            if room:
                current['room'] = room
            if checkin_val:
                current['checkin'] = checkin_val
            if checkout_val:
                current['checkout'] = checkout_val

            current['financial'] = {
                'amount': f"{amount_num:.2f}",
                'paid_amount': f"{paid_num:.2f}",
                'to_receive': f"{to_receive_num:.2f}",
                'status': status_val,
                'channel': channel_val
            }
            if p_adj:
                current['price_adjustment'] = p_adj

            allocations[rid] = current

            with open(manual_alloc_file, 'w') as f:
                json.dump(allocations, f, indent=2)
        self._append_sync_log(
            event='manual_allocation_saved',
            reservation_id=rid,
            payload={
                'room': room,
                'checkin': checkin_val,
                'checkout': checkout_val,
                'price_adjustment': p_adj if isinstance(p_adj, dict) else {}
            },
            source='reservation_service',
            direction='bidirectional'
        )
        return allocations.get(rid, {})

    def update_financial_overrides(self, reservation_id, data):
        import json

        rid = str(reservation_id)
        payload = data if isinstance(data, dict) else {}

        with file_lock(self.MANUAL_ALLOCATIONS_FILE):
            allocations = {}
            if os.path.exists(self.MANUAL_ALLOCATIONS_FILE):
                try:
                    with open(self.MANUAL_ALLOCATIONS_FILE, 'r', encoding='utf-8') as f:
                        allocations = json.load(f)
                except Exception:
                    allocations = {}

            current = allocations.get(rid, {})
            if not isinstance(current, dict):
                current = {}

            current_fin = current.get('financial', {})
            if not isinstance(current_fin, dict):
                current_fin = {}

            amount = payload.get('amount', current_fin.get('amount'))
            paid_amount = payload.get('paid_amount', current_fin.get('paid_amount'))
            to_receive = payload.get('to_receive', current_fin.get('to_receive'))
            status = payload.get('status', current_fin.get('status'))
            channel = payload.get('channel', current_fin.get('channel'))

            amount_num = self._parse_money(amount)
            paid_num = self._parse_money(paid_amount)
            if to_receive in (None, ''):
                to_receive_num = max(0.0, amount_num - paid_num)
                to_receive = f"{to_receive_num:.2f}"
            else:
                to_receive_num = self._parse_money(to_receive)

            financial = {
                'amount': f"{amount_num:.2f}",
                'paid_amount': f"{paid_num:.2f}",
                'to_receive': f"{to_receive_num:.2f}",
            }
            if status not in (None, ''):
                financial['status'] = self.normalize_reservation_status(status).get('label')
            if channel not in (None, ''):
                financial['channel'] = channel

            current['financial'] = financial
            allocations[rid] = current

            with open(self.MANUAL_ALLOCATIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(allocations, f, indent=2, ensure_ascii=False)

        self._append_sync_log(
            event='reservation_financial_updated',
            reservation_id=rid,
            payload={'financial': financial},
            source='reservation_service',
            direction='bidirectional'
        )
        return financial

    # Room Capacities (Estimated)
    ROOM_CAPACITIES = {
        "01": 2, "02": 2, "03": 2, # Areia
        "11": 4, # Mar Familia
        "12": 3, "14": 3, "15": 3, "16": 3, "17": 3, "21": 3, "22": 3, "23": 3, "24": 3, "25": 3, "26": 3, # Mar
        "31": 2, "35": 2, # Alma Banheira
        "32": 2, "34": 2, # Alma
        "33": 2 # Master Diamante
    }

    def get_reservation_status_overrides(self):
        import json
        if not os.path.exists(self.RESERVATION_STATUS_OVERRIDES_FILE):
            return {}
        try:
            with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}

    def update_reservation_status(self, reservation_id, new_status):
        import json
        normalized = self.normalize_reservation_status(new_status)
        with file_lock(self.RESERVATION_STATUS_OVERRIDES_FILE):
            overrides = {}
            if os.path.exists(self.RESERVATION_STATUS_OVERRIDES_FILE):
                try:
                    with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'r') as f:
                        overrides = json.load(f)
                except:
                    overrides = {}

            overrides[str(reservation_id)] = str(new_status)
            
            with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'w') as f:
                json.dump(overrides, f, indent=4)
        self._append_sync_log(
            event='reservation_status_updated',
            reservation_id=reservation_id,
            payload={'raw_status': str(new_status), 'normalized_code': normalized.get('code'), 'normalized_label': normalized.get('label')},
            source='reservation_service',
            direction='bidirectional'
        )
            
    def get_manual_reservations_data(self):
        import json
        # print(f"DEBUG: Reading manual reservations from {self.MANUAL_RESERVATIONS_FILE}")
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            return []
        try:
            with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                data = json.load(f)
                if not isinstance(data, list): return []
                
                # Apply Status Overrides
                overrides = self.get_reservation_status_overrides()
                for item in data:
                    rid = str(item.get('id'))
                    if rid in overrides:
                        item['status'] = overrides[rid]
                        
                return data
        except:
            return []

    def create_manual_reservation(self, data):
        import json
        import uuid
        
        print(f"DEBUG: create_manual_reservation data={data}")
        
        amount_val = data.get('amount')
        if not amount_val:
            amount_val = data.get('total_value')
        if not amount_val:
            amount_val = '0.00'

        normalized_status = self.normalize_reservation_status(data.get('status', 'Pendente'))
        new_res = {
            'id': str(uuid.uuid4()),
            'guest_name': data.get('guest_name'),
            'checkin': data.get('checkin'), # DD/MM/YYYY
            'checkout': data.get('checkout'), # DD/MM/YYYY
            'category': data.get('category', 'Manual'),
            'status': normalized_status.get('label'),
            'channel': data.get('channel', 'Direto'),
            'external_source': str(data.get('external_source') or data.get('source') or '').strip(),
            'external_reservation_id': str(data.get('external_reservation_id') or data.get('external_id') or '').strip(),
            'amount': str(amount_val),
            'paid_amount': str(data.get('paid_amount', '0.00')),
            'to_receive': str(data.get('to_receive', '0.00')),
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        
        print(f"DEBUG: create_manual_reservation new_res={new_res}")
        
        dir_name = os.path.dirname(self.MANUAL_RESERVATIONS_FILE)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
        with file_lock(self.MANUAL_RESERVATIONS_FILE):
            reservations = []
            if os.path.exists(self.MANUAL_RESERVATIONS_FILE):
                try:
                    with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                        reservations = json.load(f)
                        if not isinstance(reservations, list): reservations = []
                except:
                    reservations = []
            
            reservations.append(new_res)
            
            with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
                json.dump(reservations, f, indent=2)
            
        try:
            from app.services.reservation_rateio_service import ReservationRateioService
            ReservationRateioService.generate(
                reservation_id=str(new_res.get('id')),
                total_package=new_res.get('amount'),
                checkin=new_res.get('checkin'),
                checkout=new_res.get('checkout'),
                user=str(data.get('user') or 'Sistema'),
                trigger='reservation_confirmed',
                force=False
            )
        except Exception:
            pass

        self._append_sync_log(
            event='reservation_created',
            reservation_id=new_res.get('id'),
            payload={'checkin': new_res.get('checkin'), 'checkout': new_res.get('checkout'), 'status': new_res.get('status')},
            source='reservation_service',
            direction='reservations_to_rooms'
        )

        return new_res

    def upsert_external_reservation(self, payload):
        import json

        data = payload if isinstance(payload, dict) else {}
        source = str(data.get('external_source') or data.get('source') or '').strip()
        external_id = str(data.get('external_reservation_id') or data.get('external_id') or '').strip()
        if not source or not external_id:
            raise ValueError('Identificador externo obrigatório.')

        now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
        external_key = f"{source}:{external_id}"

        with file_lock(self.MANUAL_RESERVATIONS_FILE):
            reservations = []
            if os.path.exists(self.MANUAL_RESERVATIONS_FILE):
                try:
                    with open(self.MANUAL_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                        reservations = loaded if isinstance(loaded, list) else []
                except Exception:
                    reservations = []

            found = None
            for item in reservations:
                item_source = str(item.get('external_source') or item.get('source') or '').strip()
                item_external = str(item.get('external_reservation_id') or item.get('external_id') or '').strip()
                if f"{item_source}:{item_external}" == external_key:
                    found = item
                    break

            if found:
                for key in ['guest_name', 'checkin', 'checkout', 'category', 'status', 'channel', 'amount', 'paid_amount', 'to_receive']:
                    if data.get(key) not in (None, ''):
                        found[key] = str(data.get(key))
                found['external_source'] = source
                found['external_reservation_id'] = external_id
                found['updated_at'] = now_str
                if data.get('status') not in (None, ''):
                    status_norm = self.normalize_reservation_status(data.get('status'))
                    found['status'] = status_norm.get('label')
                reservation_id = str(found.get('id'))
                action = 'updated'
            else:
                import uuid
                reservation_id = str(uuid.uuid4())
                amount_raw = data.get('amount') if data.get('amount') not in (None, '') else data.get('total_value', '0.00')
                new_res = {
                    'id': reservation_id,
                    'guest_name': data.get('guest_name'),
                    'checkin': data.get('checkin'),
                    'checkout': data.get('checkout'),
                    'category': data.get('category', 'Manual'),
                    'status': self.normalize_reservation_status(data.get('status', 'Confirmada')).get('label'),
                    'channel': data.get('channel', 'Motor de Reservas'),
                    'external_source': source,
                    'external_reservation_id': external_id,
                    'amount': str(amount_raw if amount_raw not in (None, '') else '0.00'),
                    'paid_amount': str(data.get('paid_amount', '0.00')),
                    'to_receive': str(data.get('to_receive', '0.00')),
                    'created_at': now_str
                }
                reservations.append(new_res)
                action = 'created'

            with open(self.MANUAL_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(reservations, f, indent=2, ensure_ascii=False)

        if data.get('room_number'):
            self.save_manual_allocation(
                reservation_id=reservation_id,
                room_number=str(data.get('room_number')),
                checkin=data.get('checkin'),
                checkout=data.get('checkout')
            )
        self._append_sync_log(
            event='external_reservation_upsert',
            reservation_id=reservation_id,
            payload={'action': action, 'source': source, 'external_id': external_id},
            source='engine_sync',
            direction='reservations_to_rooms'
        )
        return {'action': action, 'reservation_id': reservation_id}

    def get_february_reservations(self):
        """
        Retrieves all active reservations from Manual and Excel sources.
        Originally named for a specific month, now returns all relevant reservations.
        """
        # Load Manual
        manual = self.get_manual_reservations_data()
        
        # Load Excel
        excel_items = []
        if os.path.exists(self.RESERVATIONS_FILE):
             excel_items.extend(self._parse_excel_file(self.RESERVATIONS_FILE))
        
        if os.path.exists(self.RESERVATIONS_DIR):
             for f in os.listdir(self.RESERVATIONS_DIR):
                 if (f.endswith('.xlsx') or f.endswith('.xls')) and f != os.path.basename(self.RESERVATIONS_FILE):
                     try:
                        excel_items.extend(self._parse_excel_file(os.path.join(self.RESERVATIONS_DIR, f)))
                     except: pass
        
        overrides = self.get_reservation_status_overrides()
        sidecar = self.get_reservation_payments()
        merged_manual = []
        for item in manual:
            rid = str(item.get('id') or '')
            base_item = dict(item)
            base_item['source_type'] = 'manual'
            if rid in overrides:
                base_item['status'] = overrides[rid]
            merged_item = self.merge_overrides_into_reservation(rid, base_item)
            status_info = self.normalize_reservation_status(
                merged_item.get('status'),
                merged_item.get('checkin'),
                merged_item.get('checkout')
            )
            merged_item['reservation_status_code'] = status_info.get('code')
            merged_item['reservation_status_label'] = status_info.get('label')
            merged_manual.append(merged_item)

        merged_excel = []
        for item in excel_items:
            rid = str(item.get('id') or '')
            base_item = dict(item)
            base_item['source_type'] = 'excel'
            if rid in overrides:
                base_item['status'] = overrides[rid]
            merged_item = self.merge_overrides_into_reservation(rid, base_item)
            payments = sidecar.get(rid, []) if isinstance(sidecar, dict) else []
            sidecar_total = 0.0
            if isinstance(payments, list):
                for p in payments:
                    sidecar_total += self._parse_money((p or {}).get('amount'))
            if sidecar_total > 0:
                amount_num = self._parse_money(merged_item.get('amount') or merged_item.get('amount_val'))
                paid_num = self._parse_money(merged_item.get('paid_amount') or merged_item.get('paid_amount_val')) + sidecar_total
                to_receive_num = max(0.0, amount_num - paid_num)
                merged_item['paid_amount'] = f"{paid_num:.2f}"
                merged_item['to_receive'] = f"{to_receive_num:.2f}"
                merged_item['paid_amount_val'] = round(paid_num, 2)
                merged_item['to_receive_val'] = round(to_receive_num, 2)
            status_info = self.normalize_reservation_status(
                merged_item.get('status'),
                merged_item.get('checkin'),
                merged_item.get('checkout')
            )
            merged_item['reservation_status_code'] = status_info.get('code')
            merged_item['reservation_status_label'] = status_info.get('label')
            merged_excel.append(merged_item)

        return merged_manual + merged_excel

    def get_room_mapping(self):
        """
        Returns a dictionary mapping categories to lists of room numbers.
        """
        # Hardcoded based on ROOM_CAPACITIES knowledge or derived
        return {
            "Suíte Areia": ["01", "02", "03"],
            "Suíte Mar Família": ["11"],
            "Suíte Mar": ["12", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26"],
            "Suíte Alma c/ Banheira": ["31", "35"],
            "Suíte Alma": ["32", "34"],
            "Suíte Master Diamante": ["33"]
        }

    def get_occupancy_grid(self, occupancy_data, start_date, num_days):
        """
        Initializes an empty grid for the given date range.
        grid[room] = [slot0, slot1, ...]
        Each day has 2 slots (AM/PM).
        """
        grid = {}
        total_slots = num_days * 2
        
        # All known rooms
        all_rooms = []
        mapping = self.get_room_mapping()
        for rooms in mapping.values():
            all_rooms.extend(rooms)
            
        for room in all_rooms:
            grid[room] = [None] * total_slots
            
        return grid

    def allocate_reservations(self, grid, reservations, start_date, num_days):
        """
        Places reservations into the grid.
        Resolves room allocation based on manual allocations or category matching.
        """
        import json
        from datetime import timedelta
        
        # Load Manual Allocations
        manual_allocs = {}
        manual_alloc_file = self.MANUAL_ALLOCATIONS_FILE
        if os.path.exists(manual_alloc_file):
            try:
                with open(manual_alloc_file, 'r') as f:
                    manual_allocs = json.load(f)
            except: pass

        # Sort reservations to prioritize fixed allocations?
        # Or just process all.
        
        mapping = self.get_room_mapping()
        # Invert mapping for easy lookup
        room_to_cat = {}
        for cat, rooms in mapping.items():
            for r in rooms:
                room_to_cat[r] = cat

        for res in reservations:
            try:
                # Parse dates
                # Checkin format: DD/MM/YYYY or YYYY-MM-DD
                cin_str = res.get('checkin')
                cout_str = res.get('checkout')
                
                if not cin_str or not cout_str: continue
                
                try:
                    if '-' in cin_str:
                        cin = datetime.strptime(cin_str, '%Y-%m-%d')
                    else:
                        cin = datetime.strptime(cin_str, '%d/%m/%Y')
                        
                    if '-' in cout_str:
                        cout = datetime.strptime(cout_str, '%Y-%m-%d')
                    else:
                        cout = datetime.strptime(cout_str, '%d/%m/%Y')
                except: continue
                
                # Calculate slots relative to start_date
                # Start Date 00:00 is Slot 0 (Day 1 AM)
                # Checkin usually 14:00 -> Slot 1 (Day 1 PM)
                # Checkout usually 12:00 -> Slot 0 (Day 2 AM) - wait, next day AM.
                
                # Logic:
                # Day Delta = (Date - StartDate).days
                # Checkin Slot = DayDelta * 2 + 1 (PM)
                # Checkout Slot = DayDelta * 2 (AM) (Exclusive? No, inclusive of that morning?)
                # A stay from Day 1 to Day 2:
                # Day 1 PM (Slot 1)
                # Day 2 AM (Slot 2)
                # Checkout is at Day 2 AM. So it occupies Slot 2.
                # Next guest checks in Day 2 PM (Slot 3).
                
                start_delta = (cin - start_date).days
                end_delta = (cout - start_date).days
                
                # Range of slots
                # Start: start_delta * 2 + 1
                # End: end_delta * 2
                # Example: 1st to 2nd.
                # Start 1st (delta 0) -> Slot 1.
                # End 2nd (delta 1) -> Slot 2.
                # Range: [1, 2] (inclusive)
                
                start_slot = start_delta * 2 + 1
                end_slot = end_delta * 2
                
                # Clip to grid range
                total_slots = num_days * 2
                if end_slot < 0 or start_slot >= total_slots:
                    continue
                    
                # Effective range
                eff_start = max(0, start_slot)
                eff_end = min(total_slots - 1, end_slot)
                
                if eff_start > eff_end: continue
                
                # Determine Room
                res_id = str(res.get('id'))
                allocated_room = None
                
                # 1. Check Manual Allocation
                if res_id in manual_allocs:
                    allocated_room = manual_allocs[res_id].get('room')
                
                # 2. Check if reservation has room field (some manual ones might)
                if not allocated_room and res.get('room'):
                    allocated_room = res.get('room')
                    
                # 3. If not allocated, try to find empty room in category
                if not allocated_room:
                    cat = res.get('category', 'Unknown')
                    # Normalize category string?
                    # Try exact match first
                    candidates = mapping.get(cat, [])
                    if not candidates:
                         # Try partial match
                         for k, v in mapping.items():
                             if cat.lower() in k.lower() or k.lower() in cat.lower():
                                 candidates = v
                                 break
                    
                    # Find first free room
                    for room in candidates:
                        is_free = True
                        if room not in grid: continue
                        for s in range(eff_start, eff_end + 1):
                            if grid[room][s] is not None:
                                is_free = False
                                break
                        if is_free:
                            allocated_room = room
                            break
                            
                # Place in grid if room found/assigned
                if allocated_room and allocated_room in grid:
                    # Check conflicts if forced
                    # We just overwrite for now or mark conflict?
                    # The grid stores the reservation object
                    
                    # Store simple dict or full res?
                    # Store dict with needed info
                    amount_val = self._parse_money(res.get('amount') or res.get('amount_val'))
                    paid_val = self._parse_money(res.get('paid_amount') or res.get('paid_amount_val'))
                    to_receive_raw = res.get('to_receive')
                    if to_receive_raw in (None, ''):
                        to_receive_val = max(0.0, amount_val - paid_val)
                    else:
                        to_receive_val = self._parse_money(to_receive_raw)
                    payment_state = 'none'
                    payment_status_label = 'Em aberto'
                    if amount_val <= 0.01:
                        payment_state = 'none'
                        payment_status_label = 'Em aberto'
                    elif to_receive_val <= 0.01:
                        payment_state = 'complete'
                        payment_status_label = 'Pago'
                    elif paid_val > 0.01:
                        payment_state = 'partial'
                        payment_status_label = 'Parcial'
                    reservation_status_label = res.get('reservation_status_label') or res.get('status') or ''
                    cell_data = {
                        'id': res_id,
                        'guest': res.get('guest_name'),
                        'checkin': cin.strftime('%d/%m/%Y'),
                        'checkout': cout.strftime('%d/%m/%Y'),
                        'category': res.get('category'),
                        'reservation_status': reservation_status_label,
                        'payment_status': payment_status_label,
                        'payment_state': payment_state,
                        'channel': res.get('channel'),
                        'num_adults': res.get('num_adults'),
                        'amount': f"{amount_val:.2f}",
                        'paid_amount': f"{paid_val:.2f}",
                        'to_receive': f"{to_receive_val:.2f}"
                    }
                    
                    for s in range(eff_start, eff_end + 1):
                        if grid[allocated_room][s] is None:
                            grid[allocated_room][s] = cell_data
                        else:
                            # Conflict!
                            # Could store list of collisions?
                            # For visualization, maybe just overwrite or mark conflict
                            # Let's keep the existing one or overwrite?
                            # If we overwrite, we lose the previous one.
                            # Maybe we shouldn't have placed it if occupied.
                            # But if it was manually allocated, we force it.
                            pass
                            
            except Exception as e:
                print(f"Error allocating reservation {res.get('id')}: {e}")
                continue
                
        return grid

    def get_gantt_segments(self, grid, start_date, num_days):
        """
        Converts the grid into segments for the UI.
        Returns: { 'room': [ {type, length, data}, ... ] }
        """
        segments = {}
        total_slots = num_days * 2
        
        for room, slots in grid.items():
            room_segments = []
            current_res_id = None
            current_start = 0
            current_data = None
            
            for i in range(total_slots):
                cell = slots[i]
                cell_id = cell['id'] if cell else None
                
                if cell_id != current_res_id:
                    # End previous segment
                    if current_start < i:
                        length = i - current_start
                        
                        seg_type = 'empty'
                        if current_res_id:
                            status = str(current_data.get('payment_status', '')).lower()
                            if 'checked-in' in status or 'hospedado' in status or 'ocupado' in status:
                                seg_type = 'occupied'
                            else:
                                seg_type = 'reserved'
                        
                        seg_data = current_data if current_res_id else {'start_day': current_start}
                        if current_res_id:
                            # Add start_day to data for UI
                            seg_data['start_day'] = current_start
                        
                        room_segments.append({
                            'type': seg_type,
                            'length': length,
                            'data': seg_data
                        })
                    
                    # Start new segment
                    current_res_id = cell_id
                    current_start = i
                    current_data = cell
            
            # End last segment
            if current_start < total_slots:
                length = total_slots - current_start
                
                seg_type = 'empty'
                if current_res_id:
                    status = str(current_data.get('payment_status', '')).lower()
                    if 'checked-in' in status or 'hospedado' in status or 'ocupado' in status:
                        seg_type = 'occupied'
                    else:
                        seg_type = 'reserved'
                        
                seg_data = current_data if current_res_id else {'start_day': current_start}
                if current_res_id:
                    seg_data['start_day'] = current_start
                    
                room_segments.append({
                    'type': seg_type,
                    'length': length,
                    'data': seg_data
                })
                
            segments[room] = room_segments
            
        return segments

    def _parse_excel_file(self, file_path):
        parsed_items = []
        try:
            df = pd.read_excel(file_path)
            
            # Determine format based on columns
            is_standard = 'Checkin/out' in df.columns and 'Responsável' in df.columns
            
            if is_standard:
                for index, row in df.iterrows():
                    # Parse Checkin/out "04/02/2026 - 06/02/2026"
                    checkin_out = str(row.get('Checkin/out', ''))
                    checkin = None
                    checkout = None
                    
                    if ' - ' in checkin_out:
                        parts = checkin_out.split(' - ')
                        if len(parts) == 2:
                            checkin = parts[0].strip()
                            checkout = parts[1].strip()
                    
                    # Basic cleaning
                    guest_name = str(row.get('Responsável', 'Unknown'))
                    category = str(row.get('Categoria', 'Unknown'))
                    status = str(row.get('Status do pagamento', 'Unknown'))
                    channel = str(row.get('Canais', 'Unknown'))
                    res_id = str(row.get('Id', ''))
                    
                    amount_str = str(row.get('Valor', ''))
                    paid_amount_str = str(row.get('Valor pago', ''))
                    to_receive_str = str(row.get('Valor a receber', ''))

                    def parse_br_money(val_str):
                        try:
                            clean = str(val_str).replace('R$', '').replace('.', '').replace(',', '.').strip()
                            if not clean: return 0.0
                            return float(clean)
                        except:
                            return 0.0

                    parsed_items.append({
                        'id': res_id,
                        'guest_name': guest_name,
                        'checkin': checkin,
                        'checkout': checkout,
                        'category': category,
                        'status': status,
                        'channel': channel,
                        'amount': amount_str,
                        'paid_amount': paid_amount_str,
                        'to_receive': to_receive_str,
                        'amount_val': parse_br_money(amount_str),
                        'paid_amount_val': parse_br_money(paid_amount_str),
                        'to_receive_val': parse_br_money(to_receive_str),
                        'source_file': os.path.basename(file_path)
                    })
            else:
                # Import format (no headers or specific column indices)
                df_no_header = pd.read_excel(file_path, header=None)
                if df_no_header.shape[1] >= 10:
                    start_row = 0
                    if str(df_no_header.iloc[0, 2]).lower() in ['hóspede', 'nome', 'guest']:
                        start_row = 1
                        
                    for index, row in df_no_header.iloc[start_row:].iterrows():
                        try:
                            # Col C (2): Name
                            guest_name = str(row[2]).strip()
                            if not guest_name or guest_name.lower() == 'nan': continue
                            
                            # Col D (3): Dates
                            dates_raw = str(row[3]).strip()
                            checkin, checkout = None, None
                            if ' - ' in dates_raw:
                                parts = dates_raw.split(' - ')
                                if len(parts) == 2:
                                    checkin = parts[0].strip()
                                    checkout = parts[1].strip()
                            
                            # Col E (4): Category
                            category = str(row[4]).strip()
                            
                            # Col G (6): Channel
                            channel = str(row[6]).strip()
                            
                            # Col H (7): Total
                            amount_val = row[7]
                            
                            # Col I (8): Paid
                            paid_val = row[8]
                            
                            # Col J (9): To Receive
                            to_receive_val = row[9]
                            
                            # Generate ID
                            import hashlib
                            res_id_raw = f"{guest_name}_{dates_raw}_{category}"
                            res_id = hashlib.md5(res_id_raw.encode()).hexdigest()[:8]
                            
                            def format_money(val):
                                try:
                                    if isinstance(val, (int, float)): return f"{val:.2f}"
                                    return str(val)
                                except: return "0.00"
                                
                            def parse_money(val):
                                try:
                                    if isinstance(val, (int, float)): return float(val)
                                    s = str(val).replace('R$', '').replace('.', '').replace(',', '.').strip()
                                    return float(s) if s else 0.0
                                except: return 0.0

                            parsed_items.append({
                                'id': res_id,
                                'guest_name': guest_name,
                                'checkin': checkin,
                                'checkout': checkout,
                                'category': category,
                                'status': 'Importada',
                                'channel': channel,
                                'amount': format_money(amount_val),
                                'paid_amount': format_money(paid_val),
                                'to_receive': format_money(to_receive_val),
                                'amount_val': parse_money(amount_val),
                                'paid_amount_val': parse_money(paid_val),
                                'to_receive_val': parse_money(to_receive_val),
                                'source_file': os.path.basename(file_path)
                            })
                        except Exception:
                            continue
        except Exception as e:
            print(f"Error reading reservations Excel {file_path}: {e}")
        return parsed_items

    def _import_signature(self, item):
        if not isinstance(item, dict):
            return ''
        guest = self._normalize_name(item.get('guest_name'))
        checkin = str(item.get('checkin') or '').strip()
        checkout = str(item.get('checkout') or '').strip()
        category = str(item.get('category') or '').strip().lower()
        return f"{guest}|{checkin}|{checkout}|{category}"

    def _find_import_target_by_name(self, item, existing_by_name):
        name_key = self._normalize_name(item.get('guest_name'))
        if not name_key:
            return None
        candidates = existing_by_name.get(name_key, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        checkin_item = self._parse_date(item.get('checkin'))
        checkout_item = self._parse_date(item.get('checkout'))

        exact_period = []
        overlap_period = []
        for candidate in candidates:
            c_in = self._parse_date(candidate.get('checkin'))
            c_out = self._parse_date(candidate.get('checkout'))
            if checkin_item and checkout_item and c_in and c_out:
                if c_in == checkin_item and c_out == checkout_item:
                    exact_period.append(candidate)
                if checkin_item < c_out and checkout_item > c_in:
                    overlap_period.append(candidate)

        if len(exact_period) == 1:
            return exact_period[0]
        if len(overlap_period) == 1:
            return overlap_period[0]
        return None

    def preview_import(self, file_path):
        try:
            imported = self._parse_excel_file(file_path)
            if not imported:
                return {'success': False, 'error': 'Nenhuma reserva válida encontrada no arquivo.'}

            existing = self.get_february_reservations() or []
            existing_by_id = {}
            existing_by_sig = {}
            existing_by_name = {}
            for res in existing:
                if not isinstance(res, dict):
                    continue
                rid = str(res.get('id') or '').strip()
                if rid:
                    existing_by_id[rid] = res
                sig = self._import_signature(res)
                if sig and sig not in existing_by_sig:
                    existing_by_sig[sig] = res
                name_key = self._normalize_name(res.get('guest_name'))
                if name_key:
                    existing_by_name.setdefault(name_key, []).append(res)

            new_entries = []
            updates = []
            conflicts = []
            unchanged_entries = []
            seen_signatures = set()

            for raw in imported:
                item = dict(raw) if isinstance(raw, dict) else {}
                item['guest_name'] = str(item.get('guest_name') or '').strip()
                item['checkin'] = str(item.get('checkin') or '').strip()
                item['checkout'] = str(item.get('checkout') or '').strip()
                item['category'] = str(item.get('category') or '').strip()
                item['status'] = str(item.get('status') or 'Importada').strip()
                item['channel'] = str(item.get('channel') or 'Importação').strip()

                if not item['guest_name'] or not item['checkin'] or not item['checkout']:
                    conflicts.append({
                        'item': item,
                        'reason': 'Dados incompletos',
                        'details': {'details': ['Nome, check-in e check-out são obrigatórios.']}
                    })
                    continue

                sig = self._import_signature(item)
                if sig in seen_signatures:
                    continue
                seen_signatures.add(sig)

                target = None
                item_id = str(item.get('id') or '').strip()
                if item_id and item_id in existing_by_id:
                    target = existing_by_id[item_id]
                if not target and sig:
                    target = existing_by_sig.get(sig)
                if not target:
                    target = self._find_import_target_by_name(item, existing_by_name)

                if not target:
                    new_entries.append(item)
                    continue

                target_id = str(target.get('id') or '').strip()
                item['target_id'] = target_id
                changes = self._get_diff(target, item)
                if changes:
                    item['changes'] = changes
                    updates.append(item)
                else:
                    unchanged_entries.append(item)

            return {
                'success': True,
                'report': {
                    'new_entries': new_entries,
                    'updates': updates,
                    'conflicts': conflicts,
                    'unchanged_entries': unchanged_entries,
                    'summary': {
                        'new': len(new_entries),
                        'updates': len(updates),
                        'conflicts': len(conflicts),
                        'unchanged': len(unchanged_entries)
                    }
                }
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def process_import_confirm(self, file_path, token=None):
        try:
            preview = self.preview_import(file_path)
            if not preview.get('success'):
                return preview

            report = preview.get('report') or {}
            new_entries = report.get('new_entries') or []
            updates = report.get('updates') or []
            conflicts = report.get('conflicts') or []

            imported_count = 0
            updated_count = 0

            for item in new_entries:
                payload = {
                    'guest_name': item.get('guest_name'),
                    'checkin': item.get('checkin'),
                    'checkout': item.get('checkout'),
                    'category': item.get('category'),
                    'status': item.get('status') or 'Importada',
                    'channel': item.get('channel') or 'Importação',
                    'amount': item.get('amount') or item.get('amount_val') or '0.00',
                    'paid_amount': item.get('paid_amount') or item.get('paid_amount_val') or '0.00',
                    'to_receive': item.get('to_receive') or item.get('to_receive_val') or '0.00',
                    'external_source': 'import_excel',
                    'external_id': str(item.get('id') or self._import_signature(item) or datetime.now().strftime('%Y%m%d%H%M%S'))
                }
                self.create_manual_reservation(payload)
                imported_count += 1

            for item in updates:
                target_id = str(item.get('target_id') or item.get('id') or '').strip()
                if not target_id:
                    payload = {
                        'guest_name': item.get('guest_name'),
                        'checkin': item.get('checkin'),
                        'checkout': item.get('checkout'),
                        'category': item.get('category'),
                        'status': item.get('status') or 'Importada',
                        'channel': item.get('channel') or 'Importação',
                        'amount': item.get('amount') or item.get('amount_val') or '0.00',
                        'paid_amount': item.get('paid_amount') or item.get('paid_amount_val') or '0.00',
                        'to_receive': item.get('to_receive') or item.get('to_receive_val') or '0.00',
                        'external_source': 'import_excel',
                        'external_id': str(self._import_signature(item) or datetime.now().strftime('%Y%m%d%H%M%S'))
                    }
                    self.create_manual_reservation(payload)
                    imported_count += 1
                    continue

                self.save_manual_allocation(
                    reservation_id=target_id,
                    room_number=self.get_manual_room(target_id) or '',
                    checkin=item.get('checkin'),
                    checkout=item.get('checkout')
                )
                self.update_financial_overrides(target_id, {
                    'amount': item.get('amount') or item.get('amount_val') or '0.00',
                    'paid_amount': item.get('paid_amount') or item.get('paid_amount_val') or '0.00',
                    'to_receive': item.get('to_receive') or item.get('to_receive_val') or '0.00',
                    'status': item.get('status'),
                    'channel': item.get('channel')
                })
                if item.get('status'):
                    self.update_reservation_status(target_id, item.get('status'))
                updated_count += 1

            if conflicts:
                conflict_rows = []
                now_str = datetime.now().strftime('%d/%m/%Y')
                for c in conflicts:
                    row = dict(c.get('item') or {})
                    row['conflict_reason'] = c.get('reason') or 'Conflito'
                    row['conflict_details'] = c.get('details') or {}
                    row['imported_at'] = self._normalize_imported_at_date(now_str)
                    if token:
                        row['import_token'] = str(token)
                    conflict_rows.append(row)
                self.save_unallocated_reservations(conflict_rows)

            return {
                'success': True,
                'summary': {
                    'imported': imported_count,
                    'updated': updated_count,
                    'conflicts': len(conflicts)
                }
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    UNALLOCATED_RESERVATIONS_FILE = os.path.join(RESERVATIONS_DIR, "unallocated_reservations.json")

    def _get_diff(self, old, new):
        """
        Compares two reservation dictionaries and returns a list of changed fields.
        """
        changes = []
        fields = [
            ('guest_name', 'Nome do Hóspede'),
            ('checkin', 'Check-in'),
            ('checkout', 'Check-out'),
            ('category', 'Categoria'),
            ('status', 'Status'),
            ('amount', 'Valor Total'),
            ('paid_amount', 'Valor Pago'),
            ('to_receive', 'A Receber')
        ]
        
        for field, label in fields:
            old_val = str(old.get(field, '')).strip()
            new_val = str(new.get(field, '')).strip()
            
            # Special handling for floats/money to avoid "100.0" vs "100.00" false positives
            if field in ['amount', 'paid_amount', 'to_receive']:
                try:
                    v1 = float(old_val.replace('R$', '').replace('.', '').replace(',', '.')) if old_val else 0.0
                    v2 = float(new_val.replace('R$', '').replace('.', '').replace(',', '.')) if new_val else 0.0
                    if abs(v1 - v2) > 0.01:
                        changes.append(f"{label}: '{old_val}' -> '{new_val}'")
                except:
                    if old_val != new_val:
                        changes.append(f"{label}: '{old_val}' -> '{new_val}'")
            else:
                if old_val != new_val:
                    changes.append(f"{label}: '{old_val}' -> '{new_val}'")
                    
        return changes

    def save_unallocated_reservations(self, unallocated_items):
        """
        Saves unallocated reservations to a JSON file.
        """
        import json
        if not unallocated_items:
            return
            
        current_data = self.get_unallocated_reservations()
        normalized_new = []
        for item in unallocated_items:
            row = dict(item) if isinstance(item, dict) else {}
            row['imported_at'] = self._normalize_imported_at_date(row.get('imported_at'))
            normalized_new.append(row)
        
        # Append new items
        current_data.extend(normalized_new)
        
        with open(self.UNALLOCATED_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, indent=4, ensure_ascii=False)

    def get_unallocated_reservations(self, filters=None):
        """
        Retrieves unallocated reservations, optionally filtered.
        filters: dict with keys 'date', 'start_date', 'end_date', 'category', 'guest_name'
        """
        import json
        if not os.path.exists(self.UNALLOCATED_RESERVATIONS_FILE):
            return []
            
        try:
            with open(self.UNALLOCATED_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data = data if isinstance(data, list) else []
            changed = False
            for item in data:
                if not isinstance(item, dict):
                    continue
                normalized_imported_at = self._normalize_imported_at_date(item.get('imported_at'))
                if item.get('imported_at') != normalized_imported_at:
                    item['imported_at'] = normalized_imported_at
                    changed = True
            if changed:
                with open(self.UNALLOCATED_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
            # Add index to item for deletion reference
            for idx, item in enumerate(data):
                item['original_index'] = idx

            if not filters:
                return data
                
            filtered = []
            for item in data:
                match = True
                
                # Date Range Overlap Filter
                if filters.get('start_date') or filters.get('end_date'):
                    try:
                        r_cin = datetime.strptime(item.get('checkin'), '%d/%m/%Y')
                        r_cout = datetime.strptime(item.get('checkout'), '%d/%m/%Y')
                        
                        f_start = datetime.min
                        f_end = datetime.max
                        
                        if filters.get('start_date'):
                            f_start = datetime.strptime(filters['start_date'], '%Y-%m-%d')
                        if filters.get('end_date'):
                            f_end = datetime.strptime(filters['end_date'], '%Y-%m-%d')
                            
                        # Overlap: (StartA <= EndB) and (EndA >= StartB)
                        if not (r_cin <= f_end and r_cout >= f_start):
                            match = False
                    except: pass
                
                # Single Date Point Filter (Legacy)
                elif filters.get('date'):
                    # Check if date falls within reservation range
                    try:
                        f_date = datetime.strptime(filters['date'], '%Y-%m-%d')
                        r_cin = datetime.strptime(item.get('checkin'), '%d/%m/%Y')
                        r_cout = datetime.strptime(item.get('checkout'), '%d/%m/%Y')
                        if not (r_cin <= f_date <= r_cout):
                            match = False
                    except: pass
                    
                if filters.get('category') and filters['category'].lower() not in str(item.get('category')).lower():
                    match = False
            return filtered
        except:
            return []
