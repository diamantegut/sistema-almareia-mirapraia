import json
import os
import uuid
from datetime import datetime, timedelta
import unicodedata
from flask import current_app
from app.models.database import db
from app.models.models import WaitingListEntry

WAITING_LIST_FILE = os.path.join('data', 'waiting_list.json')
_WAITING_LIST_DB_SYNC_DONE = False

def _dt_from_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

def _can_use_db():
    try:
        _ = current_app.name
        return True
    except Exception:
        return False

def _upsert_waiting_list_entry(entry):
    if not _can_use_db():
        return None
    if not isinstance(entry, dict):
        return None
    entry_id = entry.get('id')
    if not entry_id:
        return None

    phone_wa = entry.get('phone_wa')
    try:
        existing = WaitingListEntry.query.get(entry_id)
        if existing:
            existing.entry_time = _dt_from_iso(entry.get('entry_time')) or existing.entry_time
            existing.name = (entry.get('name') or existing.name)[:60]
            existing.phone = entry.get('phone')
            existing.phone_wa = phone_wa
            try:
                existing.party_size = int(entry.get('party_size')) if entry.get('party_size') is not None else existing.party_size
            except Exception:
                pass
            existing.status = entry.get('status') or existing.status
            existing.status_reason = entry.get('status_reason')
            existing.last_updated = _dt_from_iso(entry.get('last_updated'))
            existing.raw_data = json.dumps(entry, ensure_ascii=False)
            db.session.commit()
            return existing

        existing_count = 0
        if phone_wa:
            existing_count = WaitingListEntry.query.filter(WaitingListEntry.phone_wa == phone_wa).count()
        is_recurring = existing_count >= 1
        visit_number = existing_count + 1 if phone_wa else None

        try:
            party_size_int = int(entry.get('party_size'))
        except Exception:
            party_size_int = 1

        obj = WaitingListEntry(
            id=entry_id,
            entry_time=_dt_from_iso(entry.get('entry_time')) or datetime.now(),
            name=str(entry.get('name') or "")[:60],
            phone=entry.get('phone'),
            phone_wa=phone_wa,
            party_size=party_size_int,
            status=str(entry.get('status') or "waiting")[:20],
            status_reason=entry.get('status_reason'),
            last_updated=_dt_from_iso(entry.get('last_updated')),
            source=str(entry.get('source') or "waiting_list")[:30] if entry.get('source') is not None else "waiting_list",
            created_by=entry.get('created_by'),
            is_recurring=bool(is_recurring),
            visit_number=visit_number,
            raw_data=json.dumps(entry, ensure_ascii=False)
        )
        db.session.add(obj)
        db.session.commit()

        entry['is_recurring'] = bool(is_recurring)
        entry['visit_number'] = visit_number
        return obj
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None

def _sync_waiting_list_to_db(data):
    global _WAITING_LIST_DB_SYNC_DONE
    if _WAITING_LIST_DB_SYNC_DONE:
        return
    if not _can_use_db():
        return

    entries_by_id = {}
    for section in ("queue", "history"):
        for item in (data.get(section) or []):
            if isinstance(item, dict) and item.get("id"):
                entries_by_id[item["id"]] = item

    if not entries_by_id:
        _WAITING_LIST_DB_SYNC_DONE = True
        return

    ids = list(entries_by_id.keys())
    try:
        existing_ids = set()
        chunk_size = 400
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            rows = db.session.query(WaitingListEntry.id).filter(WaitingListEntry.id.in_(chunk)).all()
            existing_ids.update(r[0] for r in rows)

        for entry_id, entry in entries_by_id.items():
            if entry_id in existing_ids:
                continue
            _upsert_waiting_list_entry(entry)

        _WAITING_LIST_DB_SYNC_DONE = True
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

def _today_key(now=None):
    now = now or datetime.now()
    return now.strftime('%Y-%m-%d')

def _is_after_cutoff(now=None, cutoff_hour=20):
    now = now or datetime.now()
    try:
        cutoff_hour_int = int(cutoff_hour)
    except (TypeError, ValueError):
        cutoff_hour_int = 20
    return now.hour >= cutoff_hour_int

def _apply_daily_policy(data, now=None):
    now = now or datetime.now()
    settings = data.get('settings') or {}
    cutoff_hour = settings.get('cutoff_hour', 20)

    if 'history' not in data or not isinstance(data.get('history'), list):
        data['history'] = []
    if 'queue' not in data or not isinstance(data.get('queue'), list):
        data['queue'] = []

    last_reset = data.get('last_reset_date')
    today = _today_key(now)
    if last_reset != today:
        if data.get('queue'):
            archived_at = now.isoformat()
            for item in data['queue']:
                if isinstance(item, dict):
                    item.setdefault('archived_at', archived_at)
                    item.setdefault('archive_reason', 'daily_reset')
                    data['history'].append(item)
        data['queue'] = []
        data['last_reset_date'] = today

    if _is_after_cutoff(now=now, cutoff_hour=cutoff_hour):
        data.setdefault('settings', {})
        data['settings']['is_open'] = False

    return data

def load_waiting_data():
    default_settings = {
        "is_open": True,
        "max_queue_size": 50,
        "average_wait_per_party": 15, # minutes
        "critical_wait_threshold": 45, # minutes
        "whatsapp_api_token": "",
        "whatsapp_phone_id": "",
        "cutoff_hour": 20
    }
    
    if not os.path.exists(WAITING_LIST_FILE):
        return {
            "queue": [],
            "history": [],
            "settings": default_settings,
            "last_reset_date": _today_key()
        }
    try:
        with open(WAITING_LIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure settings exist and have defaults
            if "settings" not in data:
                data["settings"] = default_settings
            else:
                for key, value in default_settings.items():
                    if key not in data["settings"]:
                        data["settings"][key] = value
            if "last_reset_date" not in data:
                data["last_reset_date"] = _today_key()
            data = _apply_daily_policy(data)
            _sync_waiting_list_to_db(data)
            return data
    except json.JSONDecodeError:
        return {
            "queue": [],
            "history": [],
            "settings": default_settings,
            "last_reset_date": _today_key()
        }

def save_waiting_data(data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(WAITING_LIST_FILE), exist_ok=True)
    with open(WAITING_LIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_waiting_list():
    data = load_waiting_data()
    # Filter only waiting status for the active queue view
    active_queue = [item for item in data.get('queue', []) if item['status'] == 'waiting']
    # Sort by entry time
    active_queue.sort(key=lambda x: x['entry_time'])
    return active_queue

def get_settings():
    data = load_waiting_data()
    settings = data.get('settings', {}) or {}
    env_token = (os.environ.get('WHATSAPP_API_TOKEN') or '').strip()
    env_phone_id = (os.environ.get('WHATSAPP_PHONE_ID') or '').strip()

    cutoff_hour = settings.get('cutoff_hour', 20)
    if _is_after_cutoff(cutoff_hour=cutoff_hour):
        computed = dict(settings)
        computed['is_open'] = False
        if env_token and not (computed.get('whatsapp_api_token') or '').strip():
            computed['whatsapp_api_token'] = env_token
        if env_phone_id and not (computed.get('whatsapp_phone_id') or '').strip():
            computed['whatsapp_phone_id'] = env_phone_id
        return computed

    if env_token and not (settings.get('whatsapp_api_token') or '').strip():
        settings = dict(settings)
        settings['whatsapp_api_token'] = env_token
    if env_phone_id and not (settings.get('whatsapp_phone_id') or '').strip():
        settings = dict(settings)
        settings['whatsapp_phone_id'] = env_phone_id
    return settings

def update_settings(new_settings):
    data = load_waiting_data()
    data['settings'].update(new_settings)
    save_waiting_data(data)
    return data['settings']

def _sanitize_customer_name(name):
    if name is None:
        return None, "Informe um nome válido."
    name_str = str(name).strip()
    name_str = " ".join(name_str.split())
    if len(name_str) < 2:
        return None, "Informe um nome válido."
    if len(name_str) > 60:
        name_str = name_str[:60].rstrip()

    allowed_extra = set(" .'-")
    has_letter = False
    for ch in name_str:
        if ch in allowed_extra:
            continue
        if ch.isdigit():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith('L') or cat.startswith('M'):
            has_letter = True
            continue
        return None, "Nome contém caracteres inválidos."

    if not has_letter:
        return None, "Informe um nome válido."
    return name_str, None

def _normalize_phone_for_whatsapp(phone):
    if phone is None:
        return None, None, "Informe um WhatsApp válido."
    phone_str = str(phone).strip()
    phone_str = " ".join(phone_str.split())
    if len(phone_str) > 30:
        phone_str = phone_str[:30].rstrip()
    if any(ord(ch) < 32 for ch in phone_str):
        return None, None, "Informe um WhatsApp válido."
    if any(ch.isalpha() for ch in phone_str):
        return None, None, "Informe um WhatsApp válido."

    digits = "".join(ch for ch in phone_str if ch.isdigit())
    if len(digits) < 10:
        return None, None, "Informe um WhatsApp com DDD."

    wa_digits = digits if digits.startswith('55') else f"55{digits}"
    if len(wa_digits) not in (12, 13):
        return None, None, "Informe um WhatsApp com DDD."

    return phone_str, wa_digits, None

def _ensure_waiting_list_tag(phone_number, contact_name=None):
    return True

def add_customer(name, phone, party_size):
    data = load_waiting_data()

    cutoff_hour = data.get('settings', {}).get('cutoff_hour', 20)
    if _is_after_cutoff(cutoff_hour=cutoff_hour):
        return None, "A fila de espera encerrou novas entradas após 20:00."
    
    if not data['settings']['is_open']:
        return None, "A fila de espera está fechada no momento."
        
    active_count = sum(1 for item in data['queue'] if item['status'] == 'waiting')
    if active_count >= data['settings']['max_queue_size']:
        return None, "A fila de espera atingiu a capacidade máxima."

    # Calculate estimated wait time
    # Simple heuristic: (number of parties * avg wait) / (concurrent tables turning approx 1/3)
    # Or just sum of avg wait per party? Let's keep it simple: avg * count
    estimated_wait = active_count * data['settings']['average_wait_per_party'] // 2 # Rough estimate assuming concurrency
    if estimated_wait < 10: estimated_wait = 10

    clean_name, name_error = _sanitize_customer_name(name)
    if name_error:
        return None, name_error

    phone_display, phone_wa, phone_error = _normalize_phone_for_whatsapp(phone)
    if phone_error:
        return None, phone_error
    
    new_entry = {
        "id": str(uuid.uuid4()),
        "name": clean_name,
        "phone": phone_display,
        "phone_wa": phone_wa,
        "party_size": int(party_size),
        "entry_time": datetime.now().isoformat(),
        "status": "waiting",
        "estimated_wait_minutes": estimated_wait,
        "notifications": []
    }

    _upsert_waiting_list_entry(new_entry)
    
    data['queue'].append(new_entry)
    save_waiting_data(data)
    
    # Return position (1-based index)
    position = active_count + 1
    return {
        "entry": new_entry,
        "position": position,
        "estimated_wait": estimated_wait
    }, None

def update_customer_status(customer_id, new_status, reason=None, user=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    
    for item in queue:
        if item['id'] == customer_id:
            old_status = item['status']
            item['status'] = new_status
            item['last_updated'] = datetime.now().isoformat()
            if reason:
                item['status_reason'] = reason
            if user:
                item['updated_by'] = user
                
            # If moving to final state, maybe move to history? 
            # For now, keep in queue list but filtered out in get_waiting_list
            # Periodically we can archive to history
            
            save_waiting_data(data)
            _upsert_waiting_list_entry(item)
            return item
            
    return None

def log_notification(customer_id, type, method="whatsapp", user="system"):
    data = load_waiting_data()
    queue = data.get('queue', [])
    
    for item in queue:
        if item['id'] == customer_id:
            notification = {
                "type": type,
                "method": method,
                "timestamp": datetime.now().isoformat(),
                "sent_by": user
            }
            if "notifications" not in item:
                item["notifications"] = []
            item["notifications"].append(notification)
            save_waiting_data(data)
            _upsert_waiting_list_entry(item)
            return True
    return False

def send_notification(customer_id, message_type, user=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    customer = next((item for item in queue if item['id'] == customer_id), None)
    
    if not customer:
        return False, "Customer not found"
    
    message = ""
    if message_type == "table_ready":
        party_size = customer.get('party_size')
        try:
            party_size_int = int(party_size)
        except (TypeError, ValueError):
            party_size_int = None

        if party_size_int == 1:
            party_label = "1 pessoa"
        elif party_size_int and party_size_int > 1:
            party_label = f"{party_size_int} pessoas"
        else:
            party_label = "seu grupo"

        message = (
            f"Olá {customer.get('name', '')}! Aqui é do Mirapraia. "
            f"Sua mesa já está pronta para {party_label}. "
            "Vamos te esperar por até 15 minutos. "
            "Por favor, venham até a recepção. Até já!"
        )
    elif message_type == "welcome":
        message = (
            f"Olá {customer.get('name', '')}! Aqui é do Mirapraia. "
            "Confirmamos sua entrada na nossa fila de espera. "
            "Fique atento: assim que sua mesa estiver disponível, "
            "vamos avisar pelo WhatsApp."
        )
    else:
        message = f"Olá {customer['name']}, notificação do Restaurante Mirapraia."
    
    log_notification(customer_id, message_type, method="whatsapp_deeplink", user=user or "system")
    return True, message

def get_queue_metrics():
    data = load_waiting_data()
    queue = data.get('queue', [])
    active_count = sum(1 for x in queue if x['status'] == 'waiting')
    
    # Calculate average wait time today
    today_str = datetime.now().strftime('%Y-%m-%d')
    completed_today = [
        x for x in queue 
        if x['status'] == 'seated' and x['entry_time'].startswith(today_str)
    ]
    
    avg_wait = 0
    if completed_today:
        total_wait = 0
        for item in completed_today:
            entry = datetime.fromisoformat(item['entry_time'])
            seated = datetime.fromisoformat(item['last_updated'])
            total_wait += (seated - entry).total_seconds() / 60
        avg_wait = int(total_wait / len(completed_today))
        
    return {
        "active_count": active_count,
        "avg_wait_today": avg_wait
    }
