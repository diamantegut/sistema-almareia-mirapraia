import json
import os
import re
import unicodedata
from datetime import datetime

from app.services.data_service import load_room_occupancy, format_room_number
from app.services.reservation_service import ReservationService
from app.services.system_config_manager import get_data_path
from app.utils.lock import file_lock


BREAKFAST_KDS_FILE = get_data_path('kitchen_breakfast_kds.json')
BREAKFAST_KDS_STATUSES = ['pending', 'in_preparo', 'pronto']
BREAKFAST_KDS_STATUS_ALIASES = {
    'pending': 'pending',
    'pendente': 'pending',
    'preparing': 'in_preparo',
    'em_preparo': 'in_preparo',
    'em preparo': 'in_preparo',
    'in_preparo': 'in_preparo',
    'ready': 'pronto',
    'done': 'pronto',
    'delivered': 'pronto',
    'pronto': 'pronto',
}


def _today_key(now=None):
    ref_now = now if isinstance(now, datetime) else datetime.now()
    return ref_now.strftime('%Y-%m-%d')


def normalize_breakfast_status(value):
    status = str(value or '').strip().lower()
    return BREAKFAST_KDS_STATUS_ALIASES.get(status, 'pending')


def normalize_name_key(value):
    text = str(value or '').strip().lower()
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def load_breakfast_kds_store():
    default_store = {'status_by_date': {}, 'history_by_date': {}}
    if not os.path.exists(BREAKFAST_KDS_FILE):
        return default_store
    try:
        with open(BREAKFAST_KDS_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return default_store
        if not isinstance(payload.get('status_by_date'), dict):
            payload['status_by_date'] = {}
        if not isinstance(payload.get('history_by_date'), dict):
            payload['history_by_date'] = {}
        return payload
    except Exception:
        return default_store


def save_breakfast_kds_store(store):
    payload = store if isinstance(store, dict) else {'status_by_date': {}, 'history_by_date': {}}
    if not isinstance(payload.get('status_by_date'), dict):
        payload['status_by_date'] = {}
    if not isinstance(payload.get('history_by_date'), dict):
        payload['history_by_date'] = {}
    os.makedirs(os.path.dirname(BREAKFAST_KDS_FILE), exist_ok=True)
    lock_ctx = file_lock(BREAKFAST_KDS_FILE) if callable(file_lock) else None
    if lock_ctx is None:
        with open(BREAKFAST_KDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return
    with lock_ctx:
        with open(BREAKFAST_KDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


def get_statuses_for_day(store, date_key):
    if not isinstance(store, dict):
        return {}
    by_date = store.get('status_by_date')
    if not isinstance(by_date, dict):
        return {}
    day_map = by_date.get(date_key)
    return day_map if isinstance(day_map, dict) else {}


def get_room_history_for_day(store, date_key, room):
    if not isinstance(store, dict):
        return []
    room_key = str(room or '').strip()
    if not room_key:
        return []
    history_by_date = store.get('history_by_date')
    if not isinstance(history_by_date, dict):
        return []
    day_map = history_by_date.get(date_key)
    if not isinstance(day_map, dict):
        return []
    entries = day_map.get(room_key)
    return entries if isinstance(entries, list) else []


def update_breakfast_status(room, status, user, source='manual', context=None, now=None):
    room_key = str(room or '').strip()
    if not room_key:
        return {'success': False, 'error': 'room_invalid'}
    next_status = normalize_breakfast_status(status)
    ref_now = now if isinstance(now, datetime) else datetime.now()
    date_key = _today_key(ref_now)
    store = load_breakfast_kds_store()
    status_by_date = store.get('status_by_date') if isinstance(store.get('status_by_date'), dict) else {}
    history_by_date = store.get('history_by_date') if isinstance(store.get('history_by_date'), dict) else {}
    day_map = status_by_date.get(date_key) if isinstance(status_by_date.get(date_key), dict) else {}
    prev_meta = day_map.get(room_key) if isinstance(day_map.get(room_key), dict) else {}
    prev_status = normalize_breakfast_status(prev_meta.get('status'))
    changed = prev_status != next_status
    day_map[room_key] = {
        'status': next_status,
        'updated_at': ref_now.strftime('%d/%m/%Y %H:%M'),
        'updated_by': str(user or 'Sistema').strip() or 'Sistema',
        'updated_source': str(source or 'manual').strip() or 'manual',
    }
    status_by_date[date_key] = day_map

    day_history = history_by_date.get(date_key) if isinstance(history_by_date.get(date_key), dict) else {}
    room_history = day_history.get(room_key) if isinstance(day_history.get(room_key), list) else []
    if changed:
        room_history.append({
            'status': next_status,
            'at': ref_now.strftime('%d/%m/%Y %H:%M'),
            'by': str(user or 'Sistema').strip() or 'Sistema',
            'source': str(source or 'manual').strip() or 'manual',
            'context': context if isinstance(context, dict) else {},
        })
        room_history = room_history[-20:]
    day_history[room_key] = room_history
    history_by_date[date_key] = day_history

    store['status_by_date'] = status_by_date
    store['history_by_date'] = history_by_date
    save_breakfast_kds_store(store)
    return {
        'success': True,
        'room': room_key,
        'status': next_status,
        'previous_status': prev_status,
        'changed': changed,
        'date_key': date_key,
    }


def _normalize_breakfast_room_sort_key(room_label):
    room = str(room_label or '').strip()
    digits = ''.join(ch for ch in room if ch.isdigit())
    if digits:
        return (0, int(digits), room)
    return (1, room)


def _extract_candidate_display_name(base, occ, reservation):
    return (
        str((base or {}).get('hospede_principal') or '').strip()
        or str((occ or {}).get('guest_name') or '').strip()
        or str((reservation or {}).get('guest_name') or '').strip()
        or 'Hóspede'
    )


def build_today_breakfast_candidates(now=None):
    occupancy = load_room_occupancy()
    if not isinstance(occupancy, dict):
        occupancy = {}
    service = ReservationService()
    rows = []
    for room_key in sorted(occupancy.keys(), key=_normalize_breakfast_room_sort_key):
        occ = occupancy.get(room_key)
        if not isinstance(occ, dict):
            continue
        reservation_id = str(occ.get('reservation_id') or '').strip()
        reservation = service.get_reservation_by_id(reservation_id) if reservation_id else {}
        sheet = service.build_operational_sheet(reservation_id) if reservation_id else {}
        base = sheet.get('base_cafe_manha') if isinstance(sheet.get('base_cafe_manha'), dict) else {}
        room_label = str(base.get('quarto') or room_key).strip() or str(room_key)
        guest_main = _extract_candidate_display_name(base, occ, reservation)
        rows.append({
            'room': room_label,
            'guest_main': guest_main,
            'guest_key': normalize_name_key(guest_main),
            'reservation_id': reservation_id,
        })
    return rows


def auto_set_in_preparo_from_table_open(customer_type, customer_name, room_number, user, now=None):
    ref_now = now if isinstance(now, datetime) else datetime.now()
    date_key = _today_key(ref_now)
    store = load_breakfast_kds_store()
    statuses = get_statuses_for_day(store, date_key)
    candidates = build_today_breakfast_candidates(now=ref_now)
    candidate_by_room = {str(row.get('room') or '').strip(): row for row in candidates}
    type_norm = str(customer_type or '').strip().lower()
    room_norm = format_room_number(room_number) if str(room_number or '').strip() else ''
    guest_key = normalize_name_key(customer_name)

    if type_norm == 'hospede' and room_norm:
        candidate = candidate_by_room.get(room_norm)
        if not candidate:
            return {'success': True, 'result': 'no_match', 'reason': 'room_without_breakfast_candidate'}
        current_status = normalize_breakfast_status(((statuses.get(room_norm) or {}) if isinstance(statuses.get(room_norm), dict) else {}).get('status'))
        if current_status == 'pronto':
            return {'success': True, 'result': 'already_pronto', 'room': room_norm}
        updated = update_breakfast_status(
            room=room_norm,
            status='in_preparo',
            user=user,
            source='restaurant_tables_auto',
            context={'trigger': 'table_open', 'customer_type': type_norm, 'room': room_norm, 'customer_name': customer_name},
            now=ref_now,
        )
        return {'success': True, 'result': 'updated', 'room': room_norm, 'update': updated}

    if not guest_key:
        return {'success': True, 'result': 'no_match', 'reason': 'missing_guest_name'}
    name_matches = [row for row in candidates if row.get('guest_key') == guest_key]
    if len(name_matches) > 1:
        return {'success': True, 'result': 'ambiguous', 'reason': 'duplicate_name', 'rooms': [row.get('room') for row in name_matches]}
    if not name_matches:
        return {'success': True, 'result': 'no_match', 'reason': 'name_not_found'}
    match_room = str(name_matches[0].get('room') or '').strip()
    if not match_room:
        return {'success': True, 'result': 'no_match', 'reason': 'invalid_room_match'}
    current_status = normalize_breakfast_status(((statuses.get(match_room) or {}) if isinstance(statuses.get(match_room), dict) else {}).get('status'))
    if current_status == 'pronto':
        return {'success': True, 'result': 'already_pronto', 'room': match_room}
    updated = update_breakfast_status(
        room=match_room,
        status='in_preparo',
        user=user,
        source='restaurant_tables_auto_name',
        context={'trigger': 'table_open', 'customer_type': type_norm, 'room': room_norm, 'customer_name': customer_name},
        now=ref_now,
    )
    return {'success': True, 'result': 'updated', 'room': match_room, 'update': updated}
