import json
import os
import uuid
import shutil
import logging
from datetime import datetime, timedelta
import unicodedata
from copy import deepcopy
from flask import current_app
from app.models.database import db
from app.models.models import WaitingListEntry, WaitingListEvent, WaitingListTableAllocation
from app.services.system_config_manager import WAITING_LIST_FILE as SYSTEM_WAITING_LIST_FILE
from app.utils.lock import file_lock

logger = logging.getLogger(__name__)
WAITING_LIST_FILE = SYSTEM_WAITING_LIST_FILE
_WAITING_LIST_DB_SYNC_DONE = False
STATUS_ALIASES = {
    'waiting': 'aguardando',
    'called': 'chamado',
    'seated': 'sentado',
    'cancelled': 'desistiu',
    'removed': 'cancelado_pela_equipe',
    'no_show': 'nao_compareceu',
    'expired': 'expirado',
}
QUEUE_STATUSES = {
    'aguardando',
    'chamado',
    'sentado',
    'desistiu',
    'cancelado_pela_equipe',
    'nao_compareceu',
    'expirado'
}
ACTIVE_STATUSES = {'aguardando', 'chamado'}
FINAL_STATUSES = {'desistiu', 'cancelado_pela_equipe', 'nao_compareceu', 'expirado'}

COUNTRY_PHONE_RULES = {
    'BR': {'dial_code': '55', 'name': 'Brasil', 'min_digits': 10, 'max_digits': 11},
    'US': {'dial_code': '1', 'name': 'Estados Unidos', 'min_digits': 10, 'max_digits': 10},
    'AR': {'dial_code': '54', 'name': 'Argentina', 'min_digits': 10, 'max_digits': 11},
    'PT': {'dial_code': '351', 'name': 'Portugal', 'min_digits': 9, 'max_digits': 9},
    'GB': {'dial_code': '44', 'name': 'Reino Unido', 'min_digits': 10, 'max_digits': 10},
    'ES': {'dial_code': '34', 'name': 'Espanha', 'min_digits': 9, 'max_digits': 9},
    'FR': {'dial_code': '33', 'name': 'França', 'min_digits': 9, 'max_digits': 9},
    'DE': {'dial_code': '49', 'name': 'Alemanha', 'min_digits': 10, 'max_digits': 11},
    'IT': {'dial_code': '39', 'name': 'Itália', 'min_digits': 9, 'max_digits': 11},
    'CL': {'dial_code': '56', 'name': 'Chile', 'min_digits': 9, 'max_digits': 9},
    'UY': {'dial_code': '598', 'name': 'Uruguai', 'min_digits': 8, 'max_digits': 9},
    'PY': {'dial_code': '595', 'name': 'Paraguai', 'min_digits': 9, 'max_digits': 9},
}

def _normalize_status(status):
    raw = str(status or '').strip().lower()
    if not raw:
        return 'aguardando'
    return STATUS_ALIASES.get(raw, raw)

def _safe_int(value, default=0, min_value=None, max_value=None):
    try:
        num = int(value)
    except Exception:
        num = default
    if min_value is not None and num < min_value:
        num = min_value
    if max_value is not None and num > max_value:
        num = max_value
    return num

def _find_entry(queue, customer_id):
    if not isinstance(queue, list):
        return None
    for item in queue:
        if isinstance(item, dict) and item.get('id') == customer_id:
            return item
    return None

def update_customer_notes(customer_id, notes, user=None, action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    history = data.get('history', [])
    item = _find_entry(queue, customer_id)
    section = 'queue'
    if not item:
        item = _find_entry(history, customer_id)
        section = 'history'
    if not item:
        return None
    now_iso = datetime.now().isoformat()
    previous_notes = str(item.get('internal_notes') or '')
    item['internal_notes'] = str(notes or '').strip()[:500]
    if previous_notes != item['internal_notes']:
        item.setdefault('internal_notes_history', []).append({
            'edited_at': now_iso,
            'edited_by': user or 'system',
            'previous_notes': previous_notes,
            'new_notes': item['internal_notes']
        })
    item['last_updated'] = now_iso
    item['updated_by'] = user or 'system'
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='notes_updated',
        user=user or 'system',
        details={'section': section, 'previous_notes': previous_notes[:200], 'new_notes': item['internal_notes'][:200], 'action_origin': action_origin or {}},
        status_from=item.get('status'),
        status_to=item.get('status')
    )
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item

def get_public_status_view(status):
    normalized = _normalize_status(status)
    labels = {
        'aguardando': 'Aguardando',
        'chamado': 'Chamado',
        'sentado': 'Sentado',
        'desistiu': 'Desistiu',
        'cancelado_pela_equipe': 'Cancelado pela equipe',
        'nao_compareceu': 'Não compareceu',
        'expirado': 'Expirado'
    }
    return {
        'code': normalized,
        'label': labels.get(normalized, normalized.replace('_', ' ').title()),
        'is_active': normalized in {'aguardando', 'chamado'},
        'is_final': normalized in FINAL_STATUSES
    }

def _append_event(data, entry_id, event_type, user='system', details=None, status_from=None, status_to=None):
    if not isinstance(data, dict):
        return None
    data.setdefault('events', [])
    timestamp = datetime.now().isoformat()
    event = {
        'id': str(uuid.uuid4()),
        'timestamp': timestamp,
        'entry_id': entry_id,
        'event_type': event_type,
        'user': user or 'system',
        'status_from': status_from,
        'status_to': status_to,
        'details': details or {}
    }
    data['events'].append(event)
    _persist_waiting_event_to_db(event)
    return event

def _persist_waiting_event_to_db(event):
    if not _can_use_db():
        return None
    if not isinstance(event, dict):
        return None
    waiting_list_id = event.get('entry_id')
    if not waiting_list_id:
        return None
    details = event.get('details') or {}
    colaborador_nome = str(event.get('user') or details.get('colaborador_nome') or 'system')[:120]
    colaborador_id = str(details.get('colaborador_id') or colaborador_nome)[:60]
    mesa_id = str(details.get('table_id') or details.get('new_table_id') or '')[:20] or None
    mesa_nome = str(details.get('mesa_nome_ou_numero') or mesa_id or '')[:60] or None
    descricao = str(details.get('reason') or details.get('descricao') or event.get('event_type') or '')[:1000]
    event_dt = _dt_from_iso(event.get('timestamp')) or datetime.now()
    raw_event_type = str(event.get('event_type') or '').strip().lower()
    tipo_evento_map = {
        'entry_created': 'entrou_na_fila',
        'customer_called': 'chamado',
        'notification_logged': 'chamado',
        'customer_seated': 'sentado',
        'table_changed': 'mudou_de_mesa',
        'status_changed': str(_normalize_status(event.get('status_to') or ''))[:40],
        'archived_daily_reset': 'expirado',
        'notes_updated': 'observacao_adicionada',
        'survey_invite_created': 'survey_enviada',
        'survey_responded': 'survey_respondida',
        'survey_delivery_failed': 'survey_falhou',
        'call_timeout_no_show': 'nao_compareceu',
        'marked_for_marketing': 'marcado_para_marketing'
    }
    tipo_evento = tipo_evento_map.get(raw_event_type, raw_event_type or 'status_changed')
    if tipo_evento == 'chamado' and bool(details.get('resend')):
        tipo_evento = 'rechamado'
    payload = {
        'tipo_evento': str(tipo_evento)[:40],
        'status_anterior': str(_normalize_status(event.get('status_from')))[:30] if event.get('status_from') else None,
        'status_novo': str(_normalize_status(event.get('status_to')))[:30] if event.get('status_to') else None,
        'descricao': descricao,
        'colaborador_id': colaborador_id,
        'colaborador_nome': colaborador_nome,
        'mesa_id': mesa_id,
        'mesa_nome_ou_numero': mesa_nome,
        'metadata_json': json.dumps(details, ensure_ascii=False),
        'created_at': event_dt
    }
    try:
        existing = WaitingListEvent.query.get(str(event.get('id') or ''))
        if existing:
            existing.tipo_evento = payload['tipo_evento']
            existing.status_anterior = payload['status_anterior']
            existing.status_novo = payload['status_novo']
            existing.descricao = payload['descricao']
            existing.colaborador_id = payload['colaborador_id']
            existing.colaborador_nome = payload['colaborador_nome']
            existing.mesa_id = payload['mesa_id']
            existing.mesa_nome_ou_numero = payload['mesa_nome_ou_numero']
            existing.metadata_json = payload['metadata_json']
            existing.created_at = payload['created_at']
            db.session.commit()
            return existing
        obj = WaitingListEvent(
            id=str(event.get('id') or str(uuid.uuid4())),
            waiting_list_id=str(waiting_list_id),
            **payload
        )
        db.session.add(obj)
        db.session.commit()
        return obj
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None

def _marketing_key(phone_wa):
    if not phone_wa:
        return None
    digits = "".join(ch for ch in str(phone_wa) if ch.isdigit())
    return digits or None

def _update_marketing_contact(data, entry, event_type):
    if not isinstance(data, dict) or not isinstance(entry, dict):
        return
    data.setdefault('marketing_contacts', {})
    now_iso = datetime.now().isoformat()
    phone_key = _marketing_key(entry.get('phone_wa'))
    if not phone_key:
        return
    contact = data['marketing_contacts'].get(phone_key) or {}
    contact['phone_wa'] = phone_key
    contact['phone_display'] = entry.get('phone') or entry.get('phone_raw')
    contact['phone_e164'] = entry.get('phone_e164') or entry.get('phone_normalized')
    contact['name'] = entry.get('name')
    contact['country_code'] = entry.get('country_code')
    contact['country_dial_code'] = entry.get('country_dial_code')
    contact['last_seen_at'] = now_iso
    contact['last_status'] = entry.get('status')
    contact['last_source'] = entry.get('source', 'waiting_list')
    contact['survey_audience'] = 'restaurant'
    contact['consent_marketing'] = bool(entry.get('consent_marketing'))
    contact['consent_survey'] = bool(entry.get('consent_survey'))
    contact['events_count'] = _safe_int(contact.get('events_count', 0), default=0, min_value=0) + 1
    if event_type == 'entry_created':
        contact['visits_count'] = _safe_int(contact.get('visits_count', 0), default=0, min_value=0) + 1
        contact['first_seen_at'] = contact.get('first_seen_at') or now_iso
    data['marketing_contacts'][phone_key] = contact

def _normalize_house_rules(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, list):
        values = [str(v).strip() for v in raw_value]
    else:
        values = [line.strip() for line in str(raw_value).splitlines()]
    normalized = [v for v in values if v]
    return normalized

def get_supported_countries():
    items = []
    for code, cfg in COUNTRY_PHONE_RULES.items():
        items.append({
            'code': code,
            'name': cfg.get('name'),
            'dial_code': cfg.get('dial_code')
        })
    items.sort(key=lambda x: (0 if x.get('code') == 'BR' else 1, x.get('name') or ''))
    return items

def _dt_from_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

def _minutes_between(start_dt, end_dt):
    if not start_dt or not end_dt:
        return None
    diff = int((end_dt - start_dt).total_seconds() / 60)
    return diff if diff >= 0 else None

def _entry_timeline(entry):
    entry_dt = _dt_from_iso(entry.get('entry_time'))
    first_called = _dt_from_iso(entry.get('first_called_at') or entry.get('last_called_at'))
    last_called = _dt_from_iso(entry.get('last_called_at'))
    seated_dt = _dt_from_iso(entry.get('seated_at'))
    finished_dt = _dt_from_iso(entry.get('finished_at') or entry.get('last_updated'))
    for row in entry.get('status_history') or []:
        if not isinstance(row, dict):
            continue
        st = _normalize_status(row.get('status'))
        ts = _dt_from_iso(row.get('timestamp'))
        if st == 'chamado' and ts:
            if not first_called:
                first_called = ts
            last_called = ts
        if st == 'sentado' and ts and not seated_dt:
            seated_dt = ts
    return entry_dt, first_called, last_called, seated_dt, finished_dt

def _compute_flow_metrics(entry):
    entry_dt, first_called, _, seated_dt, finished_dt = _entry_timeline(entry)
    return {
        'tempo_espera_ate_chamada': _minutes_between(entry_dt, first_called),
        'tempo_espera_ate_sentar': _minutes_between(entry_dt, seated_dt),
        'tempo_entre_chamada_e_sentar': _minutes_between(first_called, seated_dt),
        'tempo_total_do_fluxo': _minutes_between(entry_dt, finished_dt)
    }

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
    status_norm = _normalize_status(entry.get('status') or 'aguardando')
    metrics = _compute_flow_metrics(entry)
    consent_marketing = bool(entry.get('consent_marketing'))
    consent_survey = bool(entry.get('consent_survey'))
    survey_sent_at = _dt_from_iso(entry.get('last_survey_invited_at') or entry.get('survey_sent_at'))
    survey_status = str(entry.get('survey_status') or ('enviada' if survey_sent_at else 'nao_enviada'))[:30]
    if entry.get('survey_responded_at'):
        survey_status = 'respondida'
    motivo_cancelamento = entry.get('status_reason') if status_norm in {'cancelado_pela_equipe', 'desistiu', 'nao_compareceu', 'expirado'} else None
    first_called_at = _dt_from_iso(entry.get('first_called_at'))
    if not first_called_at:
        _, first_called_at, _, _, _ = _entry_timeline(entry)
    last_called_at = _dt_from_iso(entry.get('last_called_at'))
    data_hora_sentou = _dt_from_iso(entry.get('seated_at'))
    data_hora_encerramento = _dt_from_iso(entry.get('finished_at'))
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
            existing.status = status_norm
            existing.status_reason = entry.get('status_reason')
            existing.last_updated = _dt_from_iso(entry.get('last_updated'))
            existing.nome_completo = str(entry.get('name') or '')[:120] or existing.nome_completo
            existing.telefone_raw = str(entry.get('phone_raw') or entry.get('phone') or '')[:40] or existing.telefone_raw
            existing.telefone_normalizado = str(entry.get('phone_normalized') or entry.get('phone_e164') or '')[:30] or existing.telefone_normalizado
            existing.ddi = str(entry.get('country_dial_code') or '')[:6] or existing.ddi
            existing.pais = str(entry.get('country_code') or '')[:8] or existing.pais
            existing.numero_pessoas = _safe_int(entry.get('party_size'), default=existing.party_size or 1, min_value=1, max_value=60)
            existing.origem_cadastro = str(entry.get('source') or existing.source or 'fila_virtual')[:40]
            existing.status_atual = status_norm
            existing.data_hora_entrada = _dt_from_iso(entry.get('entry_time')) or existing.data_hora_entrada
            existing.data_hora_primeira_chamada = first_called_at or existing.data_hora_primeira_chamada
            existing.data_hora_ultima_chamada = last_called_at or existing.data_hora_ultima_chamada
            existing.data_hora_sentou = data_hora_sentou or existing.data_hora_sentou
            existing.data_hora_encerramento = data_hora_encerramento or existing.data_hora_encerramento
            existing.motivo_cancelamento = str(motivo_cancelamento or '')[:1000] if motivo_cancelamento else existing.motivo_cancelamento
            existing.observacoes_internas = str(entry.get('internal_notes') or existing.observacoes_internas or '')[:2000] if (entry.get('internal_notes') or existing.observacoes_internas) else None
            existing.consentimento_marketing = consent_marketing
            existing.consentimento_pesquisa = consent_survey
            existing.survey_status = survey_status
            existing.survey_sent_at = survey_sent_at or existing.survey_sent_at
            existing.tempo_espera_ate_chamada = metrics.get('tempo_espera_ate_chamada')
            existing.tempo_espera_ate_sentar = metrics.get('tempo_espera_ate_sentar')
            existing.tempo_entre_chamada_e_sentar = metrics.get('tempo_entre_chamada_e_sentar')
            existing.tempo_total_do_fluxo = metrics.get('tempo_total_do_fluxo')
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
            status=str(status_norm)[:20],
            status_reason=entry.get('status_reason'),
            last_updated=_dt_from_iso(entry.get('last_updated')),
            source=str(entry.get('source') or "waiting_list")[:30] if entry.get('source') is not None else "waiting_list",
            created_by=entry.get('created_by'),
            is_recurring=bool(is_recurring),
            visit_number=visit_number,
            nome_completo=str(entry.get('name') or "")[:120],
            telefone_raw=str(entry.get('phone_raw') or entry.get('phone') or "")[:40] or None,
            telefone_normalizado=str(entry.get('phone_normalized') or entry.get('phone_e164') or "")[:30] or None,
            ddi=str(entry.get('country_dial_code') or "")[:6] or None,
            pais=str(entry.get('country_code') or "")[:8] or None,
            numero_pessoas=party_size_int,
            origem_cadastro=str(entry.get('source') or "fila_virtual")[:40],
            status_atual=str(status_norm)[:30],
            data_hora_entrada=_dt_from_iso(entry.get('entry_time')) or datetime.now(),
            data_hora_primeira_chamada=first_called_at,
            data_hora_ultima_chamada=last_called_at,
            data_hora_sentou=data_hora_sentou,
            data_hora_encerramento=data_hora_encerramento,
            motivo_cancelamento=str(motivo_cancelamento or "")[:1000] if motivo_cancelamento else None,
            observacoes_internas=str(entry.get('internal_notes') or "")[:2000] if entry.get('internal_notes') else None,
            consentimento_marketing=consent_marketing,
            consentimento_pesquisa=consent_survey,
            survey_status=survey_status,
            survey_sent_at=survey_sent_at,
            tempo_espera_ate_chamada=metrics.get('tempo_espera_ate_chamada'),
            tempo_espera_ate_sentar=metrics.get('tempo_espera_ate_sentar'),
            tempo_entre_chamada_e_sentar=metrics.get('tempo_entre_chamada_e_sentar'),
            tempo_total_do_fluxo=metrics.get('tempo_total_do_fluxo'),
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
            _upsert_waiting_list_entry(entry)

        for ev in (data.get('events') or []):
            if isinstance(ev, dict):
                _persist_waiting_event_to_db(ev)

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
    if 'events' not in data or not isinstance(data.get('events'), list):
        data['events'] = []
    if 'marketing_contacts' not in data or not isinstance(data.get('marketing_contacts'), dict):
        data['marketing_contacts'] = {}

    last_reset = data.get('last_reset_date')
    today = _today_key(now)
    if last_reset != today:
        if data.get('queue'):
            archived_at = now.isoformat()
            for item in data['queue']:
                if isinstance(item, dict):
                    if _normalize_status(item.get('status')) in {'aguardando', 'chamado'}:
                        item['status'] = 'expirado'
                    item.setdefault('archived_at', archived_at)
                    item.setdefault('archive_reason', 'daily_reset')
                    data['history'].append(item)
                    _append_event(
                        data,
                        item.get('id'),
                        'archived_daily_reset',
                        user='system',
                        details={'archive_reason': 'daily_reset'},
                        status_from=item.get('status'),
                        status_to=item.get('status')
                    )
        data['queue'] = []
        data['last_reset_date'] = today

    if _is_after_cutoff(now=now, cutoff_hour=cutoff_hour):
        data.setdefault('settings', {})
        data['settings']['is_open'] = False

    return data

def _waiting_default_payload(default_settings):
    return {
        "queue": [],
        "history": [],
        "events": [],
        "marketing_contacts": {},
        "settings": default_settings,
        "last_reset_date": _today_key()
    }

def _store_corrupted_waiting_list_snapshot():
    if not os.path.exists(WAITING_LIST_FILE):
        return
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        target = f"{WAITING_LIST_FILE}.corrupt_{timestamp}.json"
        shutil.copy2(WAITING_LIST_FILE, target)
        logger.error(f"waiting_list corrupt snapshot created at {target}")
    except Exception as exc:
        logger.error(f"waiting_list corrupt snapshot failed: {exc}")

def _write_waiting_data_atomic(payload):
    temp_file = WAITING_LIST_FILE + ".tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, WAITING_LIST_FILE)

def load_waiting_data():
    default_settings = {
        "is_open": True,
        "max_queue_size": 50,
        "average_wait_per_party": 15, # minutes
        "critical_wait_threshold": 45, # minutes
        "cutoff_hour": 20,
        "max_party_size": 20,
        "duplicate_block_minutes": 5,
        "call_response_timeout_minutes": 15,
        "call_presence_sla_minutes": 15,
        "call_timeout_action": "manual",
        "smart_call_enabled": False,
        "smart_call_target_capacity": 4,
        "public_queue_url": "",
        "house_rules": [
            "Todos devem estar presentes para ocupar a mesa.",
            "Tolerância de 5 minutos após chamarmos."
        ]
    }
    
    if not os.path.exists(WAITING_LIST_FILE):
        return _waiting_default_payload(default_settings)
    try:
        with file_lock(WAITING_LIST_FILE):
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
            _apply_call_timeout_policy(data)
            _sync_waiting_list_to_db(data)
            return data
    except json.JSONDecodeError as exc:
        logger.error(f"waiting_list json inválido: {exc}")
        _store_corrupted_waiting_list_snapshot()
        payload = _waiting_default_payload(default_settings)
        payload["_integrity_error"] = "json_invalid"
        return payload
    except TimeoutError as exc:
        logger.error(f"waiting_list lock timeout em leitura: {exc}")
        payload = _waiting_default_payload(default_settings)
        payload["_integrity_error"] = "read_lock_timeout"
        return payload
    except Exception as exc:
        logger.error(f"waiting_list erro de leitura: {exc}")
        payload = _waiting_default_payload(default_settings)
        payload["_integrity_error"] = "read_error"
        return payload

def save_waiting_data(data):
    os.makedirs(os.path.dirname(WAITING_LIST_FILE), exist_ok=True)
    with file_lock(WAITING_LIST_FILE):
        _write_waiting_data_atomic(data)

def get_waiting_list():
    data = load_waiting_data()
    active_queue = []
    for item in data.get('queue', []):
        if _normalize_status(item.get('status')) not in ACTIVE_STATUSES:
            continue
        row = dict(item)
        row['status'] = _normalize_status(row.get('status'))
        active_queue.append(row)
    active_queue.sort(key=lambda x: x['entry_time'])
    return active_queue

def get_recurring_summary(phone_wa, current_entry_id=None, limit=5):
    phone_key = _marketing_key(phone_wa)
    if not phone_key:
        return {'is_recurring': False, 'visit_number': 1, 'total_previous': 0, 'recent_visits': []}
    data = load_waiting_data()
    entries = list(data.get('history', [])) + list(data.get('queue', []))
    matches = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        if str(row.get('id') or '') == str(current_entry_id or ''):
            continue
        if _marketing_key(row.get('phone_wa')) != phone_key:
            continue
        matches.append(row)
    matches.sort(key=lambda x: x.get('entry_time') or '', reverse=True)
    compact = []
    for row in matches[:_safe_int(limit, default=5, min_value=1, max_value=20)]:
        compact.append({
            'entry_id': row.get('id'),
            'entry_time': row.get('entry_time'),
            'status': _normalize_status(row.get('status')),
            'party_size': _safe_int(row.get('party_size'), default=0, min_value=0),
            'table': row.get('current_table_id') or '',
            'wait_to_called_minutes': row.get('wait_to_called_minutes'),
        })
    return {
        'is_recurring': len(matches) > 0,
        'visit_number': len(matches) + 1,
        'total_previous': len(matches),
        'recent_visits': compact
    }

def get_capacity_aware_queue_reference(target_capacity=None, limit=200):
    queue = get_waiting_list()
    target = _safe_int(target_capacity, default=0, min_value=0, max_value=60)
    ranked = []
    for idx, item in enumerate(queue, start=1):
        party = _safe_int(item.get('party_size'), default=0, min_value=0, max_value=60)
        fit_gap = abs(party - target) if target > 0 else 0
        ranked.append({
            'entry_id': item.get('id'),
            'reference_position': idx,
            'party_size': party,
            'fit_gap': fit_gap,
            'smart_score': (fit_gap * 1000) + idx
        })
    ranked.sort(key=lambda x: (x.get('fit_gap', 0), x.get('reference_position', 0)))
    if limit:
        ranked = ranked[:_safe_int(limit, default=200, min_value=1, max_value=1000)]
    return ranked

def _apply_call_timeout_policy(data):
    if not isinstance(data, dict):
        return 0
    settings = data.get('settings') or {}
    timeout_action = str(settings.get('call_timeout_action') or 'manual').strip().lower()
    if timeout_action != 'automatico':
        return 0
    return _process_call_sla_expired_entries(data, user='system', trigger='automatico')

def get_customer_entry(customer_id):
    if not customer_id:
        return None
    data = load_waiting_data()
    queue_item = _find_entry(data.get('queue', []), customer_id)
    if queue_item:
        row = dict(queue_item)
        row['status'] = _normalize_status(row.get('status'))
        return row
    history_item = _find_entry(data.get('history', []), customer_id)
    if not history_item:
        return None
    row = dict(history_item)
    row['status'] = _normalize_status(row.get('status'))
    return row

def get_entry_position(customer_id):
    if not customer_id:
        return 0
    queue = get_waiting_list()
    for idx, row in enumerate(queue, start=1):
        if row.get('id') == customer_id:
            return idx
    return 0

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
    payload = dict(new_settings or {})
    house_rules = _normalize_house_rules(payload.get('house_rules'))
    if house_rules is not None:
        payload['house_rules'] = house_rules
    if 'average_wait_per_party' in payload:
        payload['average_wait_per_party'] = _safe_int(payload.get('average_wait_per_party'), default=15, min_value=1, max_value=180)
    if 'max_queue_size' in payload:
        payload['max_queue_size'] = _safe_int(payload.get('max_queue_size'), default=50, min_value=1, max_value=500)
    if 'cutoff_hour' in payload:
        payload['cutoff_hour'] = _safe_int(payload.get('cutoff_hour'), default=20, min_value=0, max_value=23)
    if 'max_party_size' in payload:
        payload['max_party_size'] = _safe_int(payload.get('max_party_size'), default=20, min_value=1, max_value=60)
    if 'duplicate_block_minutes' in payload:
        payload['duplicate_block_minutes'] = _safe_int(payload.get('duplicate_block_minutes'), default=5, min_value=0, max_value=120)
    if 'call_response_timeout_minutes' in payload:
        payload['call_response_timeout_minutes'] = _safe_int(payload.get('call_response_timeout_minutes'), default=15, min_value=1, max_value=180)
    if 'call_presence_sla_minutes' in payload:
        payload['call_presence_sla_minutes'] = _safe_int(payload.get('call_presence_sla_minutes'), default=15, min_value=1, max_value=180)
    if 'call_timeout_action' in payload:
        action = str(payload.get('call_timeout_action') or 'manual').strip().lower()
        payload['call_timeout_action'] = action if action in {'manual', 'automatico'} else 'manual'
    if 'smart_call_enabled' in payload:
        payload['smart_call_enabled'] = bool(payload.get('smart_call_enabled'))
    if 'smart_call_target_capacity' in payload:
        payload['smart_call_target_capacity'] = _safe_int(payload.get('smart_call_target_capacity'), default=4, min_value=1, max_value=20)
    if 'public_queue_url' in payload:
        payload['public_queue_url'] = str(payload.get('public_queue_url') or '').strip()[:250]
    settings_before = deepcopy(data.get('settings', {}))
    data['settings'].update(payload)
    _append_event(
        data,
        entry_id=None,
        event_type='settings_updated',
        user=(payload.get('updated_by') or 'system'),
        details={'changed_fields': sorted(list(payload.keys())), 'before': settings_before, 'after': data.get('settings', {})}
    )
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

def _normalize_country(country_code, dial_code=None):
    code = str(country_code or 'BR').strip().upper()
    cfg = COUNTRY_PHONE_RULES.get(code)
    if not cfg:
        code = 'BR'
        cfg = COUNTRY_PHONE_RULES.get(code)
    dial = "".join(ch for ch in str(dial_code or cfg.get('dial_code') or '') if ch.isdigit())
    if not dial:
        dial = str(cfg.get('dial_code') or '55')
    return code, dial, cfg

def _normalize_phone_for_whatsapp(phone_raw, country_code='BR', dial_code=None):
    if phone_raw is None:
        return None, "Informe um WhatsApp válido.", None
    phone_str = str(phone_raw).strip()
    phone_str = " ".join(phone_str.split())
    if len(phone_str) > 40:
        phone_str = phone_str[:40].rstrip()
    if any(ord(ch) < 32 for ch in phone_str):
        return None, "Informe um WhatsApp válido.", None
    if any(ch.isalpha() for ch in phone_str):
        return None, "Informe um WhatsApp válido.", None

    selected_country, selected_dial, cfg = _normalize_country(country_code, dial_code)
    digits = "".join(ch for ch in phone_str if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]

    if phone_str.startswith('+'):
        e164_digits = digits
    else:
        local = digits
        if selected_country == 'BR' and len(local) in (12, 13) and local.startswith('55'):
            local = local[2:]
        e164_digits = f"{selected_dial}{local}"

    if len(e164_digits) < 8 or len(e164_digits) > 15:
        return None, "Informe um WhatsApp válido com código do país.", None

    local_digits = e164_digits
    if selected_dial and e164_digits.startswith(selected_dial):
        local_digits = e164_digits[len(selected_dial):]
    min_digits = _safe_int(cfg.get('min_digits'), default=8, min_value=4, max_value=15)
    max_digits = _safe_int(cfg.get('max_digits'), default=15, min_value=min_digits, max_value=15)
    if len(local_digits) < min_digits or len(local_digits) > max_digits:
        return None, f"Número inválido para {cfg.get('name')}.", None

    normalized = {
        'phone_raw': phone_str,
        'phone_normalized': f"+{e164_digits}",
        'phone_wa': e164_digits,
        'country_code': selected_country,
        'country_dial_code': selected_dial
    }
    return normalized, None, cfg

def _is_duplicate_recent(data, phone_normalized, now_dt, minutes, party_size=None, clean_name=None):
    if not phone_normalized:
        return False
    window_minutes = _safe_int(minutes, default=0, min_value=0, max_value=240)
    if window_minutes <= 0:
        return False
    threshold = now_dt - timedelta(minutes=window_minutes)
    all_entries = list(data.get('queue', [])) + list(data.get('history', []))
    for row in all_entries:
        if not isinstance(row, dict):
            continue
        if str(row.get('phone_normalized') or row.get('phone_e164') or '').strip() != phone_normalized:
            continue
        row_dt = _dt_from_iso(row.get('entry_time'))
        if not row_dt or row_dt < threshold:
            continue
        if party_size is not None and _safe_int(row.get('party_size'), default=0) != _safe_int(party_size, default=0):
            continue
        if clean_name and str(row.get('name') or '').strip().lower() != clean_name.strip().lower():
            continue
        return True
    return False

def _has_active_duplicate_phone(data, phone_wa):
    target = _marketing_key(phone_wa)
    if not target:
        return False
    for row in data.get('queue', []):
        if not isinstance(row, dict):
            continue
        if _normalize_status(row.get('status')) not in ACTIVE_STATUSES:
            continue
        if _marketing_key(row.get('phone_wa')) == target:
            return True
    return False

def _ensure_waiting_list_tag(phone_number, contact_name=None):
    return True

def _set_entry_finalized(data, entry, reason=None, user=None):
    if not isinstance(data, dict) or not isinstance(entry, dict):
        return
    if not entry.get('finished_at'):
        entry['finished_at'] = datetime.now().isoformat()
    if reason:
        entry['status_reason'] = reason
    if user:
        entry['updated_by'] = user
    if entry not in data.get('history', []):
        data.setdefault('history', []).append(entry)
    _close_current_db_allocations(entry.get('id'), ended_at=_dt_from_iso(entry.get('finished_at')))

def _history_call_and_seat_times(entry):
    called_at = _dt_from_iso(entry.get('last_called_at'))
    seated_at = _dt_from_iso(entry.get('seated_at'))
    status_history = entry.get('status_history') or []
    for row in status_history:
        if not isinstance(row, dict):
            continue
        st = _normalize_status(row.get('status'))
        ts = _dt_from_iso(row.get('timestamp'))
        if st == 'chamado' and ts and not called_at:
            called_at = ts
        if st == 'sentado' and ts and not seated_at:
            seated_at = ts
    return called_at, seated_at

def _history_durations(entry):
    entry_dt = _dt_from_iso(entry.get('entry_time'))
    called_at, seated_at = _history_call_and_seat_times(entry)
    finished_at = _dt_from_iso(entry.get('finished_at')) or _dt_from_iso(entry.get('last_updated'))
    wait_to_called = None
    called_to_seated = None
    total_to_finish = None
    if entry_dt and called_at:
        wait_to_called = int((called_at - entry_dt).total_seconds() / 60)
    if called_at and seated_at:
        called_to_seated = int((seated_at - called_at).total_seconds() / 60)
    if entry_dt and finished_at:
        total_to_finish = int((finished_at - entry_dt).total_seconds() / 60)
    return wait_to_called, called_to_seated, total_to_finish

def add_customer(
    name,
    phone,
    party_size,
    country_code='BR',
    country_dial_code=None,
    consent_marketing=False,
    consent_survey=False,
    action_origin=None,
    created_by='public',
    source='fila_virtual',
    force_queue_end=False
):
    data = load_waiting_data()
    now_dt = datetime.now()
    cutoff_hour = data.get('settings', {}).get('cutoff_hour', 20)
    if _is_after_cutoff(cutoff_hour=cutoff_hour):
        return None, "A fila de espera encerrou novas entradas após 20:00."
    
    if not data['settings']['is_open']:
        return None, "A fila de espera está fechada no momento."

    active_count = sum(1 for item in data['queue'] if _normalize_status(item.get('status')) in ACTIVE_STATUSES)
    if active_count >= data['settings']['max_queue_size']:
        return None, "A fila de espera atingiu a capacidade máxima."
    max_party_size = _safe_int(data.get('settings', {}).get('max_party_size', 20), default=20, min_value=1, max_value=60)
    duplicate_block_minutes = _safe_int(data.get('settings', {}).get('duplicate_block_minutes', 5), default=5, min_value=0, max_value=120)

    estimated_wait = max(10, (active_count * _safe_int(data['settings']['average_wait_per_party'], default=15, min_value=1)) // 2)

    clean_name, name_error = _sanitize_customer_name(name)
    if name_error:
        return None, name_error

    phone_data, phone_error, _ = _normalize_phone_for_whatsapp(phone, country_code=country_code, dial_code=country_dial_code)
    if phone_error:
        return None, phone_error
    party_size_int = _safe_int(party_size, default=0, min_value=1, max_value=max_party_size)
    if party_size_int <= 0:
        return None, "Informe uma quantidade de pessoas válida."

    if _has_active_duplicate_phone(data, phone_data.get('phone_wa')):
        return None, "Já existe uma entrada ativa para este telefone na fila."

    if _is_duplicate_recent(
        data,
        phone_normalized=phone_data.get('phone_normalized'),
        now_dt=now_dt,
        minutes=duplicate_block_minutes,
        party_size=party_size_int,
        clean_name=clean_name
    ):
        return None, f"Já existe uma solicitação recente para este telefone. Aguarde {duplicate_block_minutes} minuto(s) antes de tentar novamente."

    if force_queue_end:
        max_entry_dt = None
        for existing in data.get('queue', []):
            if _normalize_status(existing.get('status')) not in ACTIVE_STATUSES:
                continue
            existing_dt = _dt_from_iso(existing.get('entry_time'))
            if existing_dt and (max_entry_dt is None or existing_dt > max_entry_dt):
                max_entry_dt = existing_dt
        if max_entry_dt and now_dt <= max_entry_dt:
            now_dt = max_entry_dt + timedelta(seconds=1)

    now_iso = now_dt.isoformat()
    estimated_entry_at = now_dt + timedelta(minutes=estimated_wait)
    created_by_norm = str(created_by or 'public').strip() or 'public'
    source_norm = str(source or 'fila_virtual').strip() or 'fila_virtual'
    
    new_entry = {
        "id": str(uuid.uuid4()),
        "name": clean_name,
        "phone": phone_data.get('phone_raw'),
        "phone_raw": phone_data.get('phone_raw'),
        "phone_normalized": phone_data.get('phone_normalized'),
        "phone_e164": phone_data.get('phone_normalized'),
        "phone_wa": phone_data.get('phone_wa'),
        "country_code": phone_data.get('country_code'),
        "country_dial_code": phone_data.get('country_dial_code'),
        "party_size": party_size_int,
        "entry_time": now_iso,
        "status": "aguardando",
        "status_history": [{"status": "aguardando", "timestamp": now_iso, "reason": "entry_created", "user": created_by_norm}],
        "estimated_wait_minutes": estimated_wait,
        "estimated_entry_at": estimated_entry_at.isoformat(),
        "notifications": [],
        "table_history": [],
        "current_table_id": None,
        "internal_notes": "",
        "created_by": created_by_norm,
        "source": source_norm,
        "consent_marketing": bool(consent_marketing),
        "consent_survey": bool(consent_survey),
        "survey_status": "nao_enviada"
    }

    _upsert_waiting_list_entry(new_entry)
    
    data['queue'].append(new_entry)
    _append_event(
        data,
        entry_id=new_entry.get('id'),
        event_type='entry_created',
        user=created_by_norm,
        details={
            'phone_wa': new_entry.get('phone_wa'),
            'phone_e164': new_entry.get('phone_e164'),
            'country_code': new_entry.get('country_code'),
            'party_size': party_size_int,
            'consent_marketing': bool(consent_marketing),
            'consent_survey': bool(consent_survey),
            'source': source_norm,
            'action_origin': action_origin or {}
        },
        status_from=None,
        status_to='aguardando'
    )
    if bool(consent_marketing):
        _append_event(
            data,
            entry_id=new_entry.get('id'),
            event_type='marked_for_marketing',
            user=created_by_norm,
            details={'consent_marketing': True, 'action_origin': action_origin or {}},
            status_from='aguardando',
            status_to='aguardando'
        )
    _update_marketing_contact(data, new_entry, 'entry_created')
    save_waiting_data(data)
    
    position = active_count + 1
    return {
        "entry": new_entry,
        "position": position,
        "estimated_wait": estimated_wait
    }, None

def update_customer_status(customer_id, new_status, reason=None, user=None, action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])

    item = _find_entry(queue, customer_id)
    if item:
        status_norm = _normalize_status(new_status)
        if status_norm not in QUEUE_STATUSES:
            return None
        old_status = _normalize_status(item.get('status'))
        now_iso = datetime.now().isoformat()
        item['status'] = status_norm
        item['last_updated'] = now_iso
        if reason:
            item['status_reason'] = reason
        if user:
            item['updated_by'] = user
        item.setdefault('status_history', []).append({
            'status': status_norm,
            'timestamp': now_iso,
            'reason': reason or '',
            'user': user or 'system'
        })
        if status_norm == 'chamado':
            if not item.get('first_called_at'):
                item['first_called_at'] = now_iso
            item['last_called_at'] = now_iso
            item['call_count'] = _safe_int(item.get('call_count', 0), default=0, min_value=0) + 1
        if status_norm in FINAL_STATUSES:
            for table_event in reversed(item.get('table_history', [])):
                if not table_event.get('ended_at'):
                    table_event['ended_at'] = now_iso
                    break
            _set_entry_finalized(data, item, reason=reason, user=user)
            data['queue'] = [row for row in queue if row.get('id') != item.get('id')]
        _append_event(
            data,
            entry_id=item.get('id'),
            event_type='status_changed',
            user=user or 'system',
            details={'reason': reason or '', 'status': status_norm, 'action_origin': action_origin or {}},
            status_from=old_status,
            status_to=status_norm
        )
        _update_marketing_contact(data, item, 'status_changed')
        save_waiting_data(data)
        _upsert_waiting_list_entry(item)
        return item

    return None

def log_notification(customer_id, type, method="whatsapp", user="system", action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    item = _find_entry(queue, customer_id)
    if item:
        notification = {
            "type": type,
            "method": method,
            "timestamp": datetime.now().isoformat(),
            "sent_by": user
        }
        if "notifications" not in item:
            item["notifications"] = []
        item["notifications"].append(notification)
        _append_event(
            data,
            entry_id=item.get('id'),
            event_type='notification_logged',
            user=user or 'system',
            details={'notification_type': type, 'method': method, 'action_origin': action_origin or {}},
            status_from=item.get('status'),
            status_to=item.get('status')
        )
        _update_marketing_contact(data, item, 'notification_logged')
        save_waiting_data(data)
        _upsert_waiting_list_entry(item)
        return True
    return False

def send_notification(customer_id, message_type, user=None, action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    customer = _find_entry(queue, customer_id)
    
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
    
    log_notification(customer_id, message_type, method="whatsapp_deeplink", user=user or "system", action_origin=action_origin)
    return True, message

def _process_call_sla_expired_entries(data, user='system', trigger='manual'):
    if not isinstance(data, dict):
        return 0
    queue = data.get('queue', [])
    now_dt = datetime.now()
    changed = 0
    for item in list(queue):
        if not isinstance(item, dict):
            continue
        if _normalize_status(item.get('status')) != 'chamado':
            continue
        expires_at = _dt_from_iso(item.get('call_expires_at'))
        if not expires_at or now_dt < expires_at:
            continue
        now_iso = now_dt.isoformat()
        old_status = _normalize_status(item.get('status'))
        item['status'] = 'nao_compareceu'
        item['last_updated'] = now_iso
        item['updated_by'] = user or 'system'
        item['status_reason'] = 'Tempo limite de comparecimento expirado'
        item.setdefault('status_history', []).append({
            'status': 'nao_compareceu',
            'timestamp': now_iso,
            'reason': 'Tempo limite de comparecimento expirado',
            'user': user or 'system'
        })
        _set_entry_finalized(data, item, reason=item.get('status_reason'), user=user)
        data['queue'] = [row for row in data.get('queue', []) if row.get('id') != item.get('id')]
        _append_event(
            data,
            entry_id=item.get('id'),
            event_type='call_timeout_no_show',
            user=user or 'system',
            details={
                'expires_at': item.get('call_expires_at'),
                'timeout_minutes': item.get('call_timeout_minutes'),
                'trigger': trigger
            },
            status_from=old_status,
            status_to='nao_compareceu'
        )
        _update_marketing_contact(data, item, 'call_timeout_no_show')
        _upsert_waiting_list_entry(item)
        changed += 1
    if changed > 0:
        save_waiting_data(data)
    return changed

def process_call_sla_expired_entries(user='system', trigger='manual'):
    data = load_waiting_data()
    return _process_call_sla_expired_entries(data, user=user, trigger=trigger)

def call_customer(customer_id, user=None, channel='whatsapp', timeout_minutes=None, reason=None, resend=False, action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    item = _find_entry(queue, customer_id)
    if not item:
        return None, "Cliente não encontrado."
    now_dt = datetime.now()
    now_iso = now_dt.isoformat()
    old_status = _normalize_status(item.get('status'))
    timeout_default = _safe_int(
        data.get('settings', {}).get('call_presence_sla_minutes', data.get('settings', {}).get('call_response_timeout_minutes', 15)),
        default=15,
        min_value=1,
        max_value=180
    )
    timeout_final = _safe_int(timeout_minutes, default=timeout_default, min_value=1, max_value=180)
    expires_at = (now_dt + timedelta(minutes=timeout_final)).isoformat()
    item['status'] = 'chamado'
    item['last_updated'] = now_iso
    if not item.get('first_called_at'):
        item['first_called_at'] = now_iso
    item['last_called_at'] = now_iso
    item['call_channel'] = str(channel or 'whatsapp').strip()[:40]
    item['call_timeout_minutes'] = timeout_final
    item['call_expires_at'] = expires_at
    item['call_count'] = _safe_int(item.get('call_count', 0), default=0, min_value=0) + 1
    item['updated_by'] = user or 'system'
    if reason:
        item['status_reason'] = str(reason).strip()[:140]
    item.setdefault('status_history', []).append({
        'status': 'chamado',
        'timestamp': now_iso,
        'reason': reason or ('Reenvio de chamada' if resend else 'Cliente chamado'),
        'user': user or 'system'
    })
    item.setdefault('call_history', []).append({
        'called_at': now_iso,
        'channel': item.get('call_channel'),
        'timeout_minutes': timeout_final,
        'expires_at': expires_at,
        'resend': bool(resend),
        'called_by': user or 'system'
    })
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='customer_called',
        user=user or 'system',
        details={
            'channel': item.get('call_channel'),
            'timeout_minutes': timeout_final,
            'expires_at': expires_at,
            'resend': bool(resend),
            'action_origin': action_origin or {}
        },
        status_from=old_status,
        status_to='chamado'
    )
    _update_marketing_contact(data, item, 'customer_called')
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item, None

def list_available_tables():
    try:
        return [row.get('table_id') for row in get_table_status_catalog() if row.get('is_available_for_allocation')]
    except Exception:
        return []

def get_table_status_catalog():
    catalog = []
    try:
        from app.services.data_service import load_table_orders, load_restaurant_table_settings
        orders = load_table_orders() or {}
        if not isinstance(orders, dict):
            orders = {}
        settings = load_restaurant_table_settings() or {}
        if not isinstance(settings, dict):
            settings = {}
        disabled_tables = set(str(t) for t in (settings.get('disabled_tables') or []))
        reserved_raw = settings.get('reserved_tables') or settings.get('reservations_by_table') or []
        reserved_tables = set()
        if isinstance(reserved_raw, dict):
            reserved_tables = set(str(k) for k, v in reserved_raw.items() if v)
        elif isinstance(reserved_raw, list):
            for row in reserved_raw:
                if isinstance(row, dict):
                    t = row.get('table_id') or row.get('mesa_id') or row.get('table')
                    if t:
                        reserved_tables.add(str(t))
                elif row is not None:
                    reserved_tables.add(str(row))
        for i in range(36, 102):
            table_id = str(i)
            status = 'available'
            if table_id in disabled_tables:
                status = 'disabled'
            elif table_id in reserved_tables:
                status = 'reserved'
            elif table_id in orders:
                status = 'occupied'
            catalog.append({
                'table_id': table_id,
                'table_name': f"Mesa {table_id}",
                'status': status,
                'is_available_for_allocation': status in {'available'},
                'order_snapshot': orders.get(table_id) if table_id in orders else None
            })
        return catalog
    except Exception:
        for i in range(36, 102):
            table_id = str(i)
            catalog.append({
                'table_id': table_id,
                'table_name': f"Mesa {table_id}",
                'status': 'available',
                'is_available_for_allocation': True,
                'order_snapshot': None
            })
        return catalog

def _bind_restaurant_table_for_passant(entry, table_id, user=None):
    try:
        from app.services.data_service import load_table_orders, save_table_orders
        orders = load_table_orders()
        table_key = str(table_id).strip()
        if table_key in orders:
            return False
        opened_at = datetime.now().strftime('%d/%m/%Y %H:%M')
        orders[table_key] = {
            'items': [],
            'total': 0,
            'status': 'open',
            'opened_at': opened_at,
            'num_adults': _safe_int(entry.get('party_size'), default=1, min_value=1, max_value=60),
            'customer_type': 'passante',
            'customer_name': str(entry.get('name') or '')[:80],
            'room_number': None,
            'waiter': user or 'Recepção',
            'opened_by': user or 'Recepção',
            'created_via': 'waiting_list_seat',
            'waiting_list_entry_id': entry.get('id'),
            'waiting_list_phone': str(entry.get('phone') or ''),
            'waiting_list_phone_wa': str(entry.get('phone_wa') or ''),
            'waiting_list_country': str(entry.get('country_code') or ''),
            'waiting_list_source': str(entry.get('source') or ''),
            'waiting_list_seated_at': datetime.now().isoformat(),
            'waiting_list_internal_notes': str(entry.get('internal_notes') or '')[:400],
        }
        return bool(save_table_orders(orders))
    except Exception:
        return False

def _close_current_db_allocations(waiting_list_id, ended_at=None):
    if not _can_use_db() or not waiting_list_id:
        return
    end_dt = ended_at or datetime.now()
    try:
        rows = WaitingListTableAllocation.query.filter_by(waiting_list_id=str(waiting_list_id), is_current=True).all()
        changed = False
        for row in rows:
            row.is_current = False
            row.ended_at = row.ended_at or end_dt
            row.updated_at = datetime.now()
            changed = True
        if changed:
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

def _create_db_table_allocation(waiting_list_id, mesa_id, mesa_nome_ou_numero=None, moved_by_user_id=None, moved_by_user_name=None, started_at=None):
    if not _can_use_db() or not waiting_list_id or not mesa_id:
        return None
    start_dt = started_at or datetime.now()
    try:
        _close_current_db_allocations(waiting_list_id, ended_at=start_dt)
        obj = WaitingListTableAllocation(
            waiting_list_id=str(waiting_list_id),
            mesa_id=str(mesa_id),
            mesa_nome_ou_numero=str(mesa_nome_ou_numero or mesa_id)[:60],
            started_at=start_dt,
            ended_at=None,
            is_current=True,
            moved_by_user_id=(str(moved_by_user_id or '')[:60] or None),
            moved_by_user_name=(str(moved_by_user_name or moved_by_user_id or '')[:120] or None),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        db.session.add(obj)
        db.session.commit()
        return obj
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None

def seat_customer(customer_id, table_id, user=None, reason=None, action_origin=None):
    if not table_id:
        return None, "Selecione uma mesa."
    data = load_waiting_data()
    queue = data.get('queue', [])
    item = _find_entry(queue, customer_id)
    if not item:
        return None, "Cliente não encontrado."
    table_id_str = str(table_id).strip()
    table_name = f"Mesa {table_id_str}"
    if table_id_str not in list_available_tables() and table_id_str != str(item.get('current_table_id') or ''):
        return None, "Mesa indisponível no momento."
    now_iso = datetime.now().isoformat()
    old_status = item.get('status')
    item['status'] = 'sentado'
    item['last_updated'] = now_iso
    item['status_reason'] = reason or item.get('status_reason') or 'Cliente sentado'
    item['updated_by'] = user or 'system'
    item['seated_at'] = item.get('seated_at') or now_iso
    item['current_table_id'] = table_id_str
    linked_to_restaurant = _bind_restaurant_table_for_passant(item, table_id_str, user=user)
    item['restaurant_table_linked'] = bool(linked_to_restaurant)
    item.setdefault('status_history', []).append({
        'status': 'sentado',
        'timestamp': now_iso,
        'reason': reason or 'Cliente sentado',
        'user': user or 'system'
    })
    item.setdefault('table_history', []).append({
        'table_id': table_id_str,
        'table_name': table_name,
        'started_at': now_iso,
        'ended_at': None,
        'changed_by': user or 'system',
        'reason': reason or 'Primeira alocação de mesa'
    })
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='customer_seated',
        user=user or 'system',
        details={'table_id': table_id_str, 'mesa_nome_ou_numero': table_name, 'reason': reason or '', 'restaurant_table_linked': bool(linked_to_restaurant), 'action_origin': action_origin or {}},
        status_from=old_status,
        status_to='sentado'
    )
    _create_db_table_allocation(
        waiting_list_id=item.get('id'),
        mesa_id=table_id_str,
        mesa_nome_ou_numero=table_name,
        moved_by_user_id=user,
        moved_by_user_name=user,
        started_at=_dt_from_iso(now_iso)
    )
    _update_marketing_contact(data, item, 'customer_seated')
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item, None

def get_seated_customers(limit=100):
    data = load_waiting_data()
    seated = [item for item in data.get('queue', []) if isinstance(item, dict) and _normalize_status(item.get('status')) == 'sentado']
    seated.sort(key=lambda x: x.get('seated_at') or x.get('last_updated') or x.get('entry_time') or '', reverse=True)
    return seated[:_safe_int(limit, default=100, min_value=1, max_value=500)]

def change_customer_table(customer_id, new_table_id, user=None, reason=None, action_origin=None):
    if not new_table_id:
        return None, "Selecione uma nova mesa."
    data = load_waiting_data()
    queue = data.get('queue', [])
    item = _find_entry(queue, customer_id)
    if not item:
        return None, "Cliente não encontrado."
    if _normalize_status(item.get('status')) != 'sentado':
        return None, "A troca de mesa só é permitida para cliente sentado."
    new_table = str(new_table_id).strip()
    new_table_name = f"Mesa {new_table}"
    old_table = str(item.get('current_table_id') or '').strip()
    old_table_name = f"Mesa {old_table}" if old_table else ''
    if not old_table:
        return None, "Cliente sem mesa associada."
    if old_table == new_table:
        return None, "Cliente já está nesta mesa."
    if new_table not in list_available_tables():
        return None, "Nova mesa indisponível no momento."
    now_iso = datetime.now().isoformat()
    for table_event in reversed(item.get('table_history', [])):
        if table_event.get('table_id') == old_table and not table_event.get('ended_at'):
            table_event['ended_at'] = now_iso
            break
    item.setdefault('table_history', []).append({
        'table_id': new_table,
        'table_name': new_table_name,
        'started_at': now_iso,
        'ended_at': None,
        'changed_by': user or 'system',
        'reason': reason or 'Troca de mesa'
    })
    item['current_table_id'] = new_table
    item['last_updated'] = now_iso
    item['updated_by'] = user or 'system'
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='table_changed',
        user=user or 'system',
        details={'old_table_id': old_table, 'old_mesa_nome_ou_numero': old_table_name, 'new_table_id': new_table, 'mesa_nome_ou_numero': new_table_name, 'reason': reason or '', 'action_origin': action_origin or {}},
        status_from='sentado',
        status_to='sentado'
    )
    _create_db_table_allocation(
        waiting_list_id=item.get('id'),
        mesa_id=new_table,
        mesa_nome_ou_numero=new_table_name,
        moved_by_user_id=user,
        moved_by_user_name=user,
        started_at=_dt_from_iso(now_iso)
    )
    _update_marketing_contact(data, item, 'table_changed')
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item, None

def get_queue_history(limit=200):
    data = load_waiting_data()
    history = [item for item in data.get('history', []) if isinstance(item, dict)]
    history.sort(key=lambda x: x.get('last_updated') or x.get('entry_time') or '', reverse=True)
    return history[:_safe_int(limit, default=200, min_value=1, max_value=1000)]

def register_survey_invite(entry_id, survey_id, ref, invited_by='system', invite_url='', action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    history = data.get('history', [])
    item = _find_entry(queue, entry_id) or _find_entry(history, entry_id)
    if not item:
        return None
    now_iso = datetime.now().isoformat()
    survey_rec = {
        'survey_id': str(survey_id or ''),
        'ref': str(ref or ''),
        'invited_at': now_iso,
        'invited_by': invited_by or 'system',
        'invite_url': str(invite_url or '')
    }
    item.setdefault('survey_invites', []).append(survey_rec)
    item['last_survey_invited_at'] = now_iso
    item['survey_invites_count'] = _safe_int(item.get('survey_invites_count', 0), default=0, min_value=0) + 1
    item['survey_status'] = 'enviada'
    item['survey_sent_at'] = now_iso
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='survey_invite_created',
        user=invited_by or 'system',
        details={'survey_id': survey_rec['survey_id'], 'ref': survey_rec['ref'], 'action_origin': action_origin or {}},
        status_from=item.get('status'),
        status_to=item.get('status')
    )
    _update_marketing_contact(data, item, 'survey_invite_created')
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item

def mark_survey_responded(ref, response_id=None, action_origin=None):
    ref_str = str(ref or '').strip()
    if not ref_str:
        return None
    data = load_waiting_data()
    now_iso = datetime.now().isoformat()
    targets = list(data.get('queue', [])) + list(data.get('history', []))
    updated_item = None
    for item in targets:
        if not isinstance(item, dict):
            continue
        invites = item.get('survey_invites') or []
        hit = False
        for inv in invites:
            if not isinstance(inv, dict):
                continue
            if str(inv.get('ref') or '').strip() == ref_str:
                inv['responded_at'] = now_iso
                if response_id:
                    inv['response_id'] = str(response_id)
                hit = True
        if hit:
            item['survey_status'] = 'respondida'
            item['survey_responded_at'] = now_iso
            _append_event(
                data,
                entry_id=item.get('id'),
                event_type='survey_responded',
                user='guest',
                details={'ref': ref_str, 'response_id': response_id or '', 'action_origin': action_origin or {}},
                status_from=item.get('status'),
                status_to=item.get('status')
            )
            _update_marketing_contact(data, item, 'survey_responded')
            updated_item = item
            break
    if updated_item:
        save_waiting_data(data)
        _upsert_waiting_list_entry(updated_item)
    return updated_item

def mark_survey_failed(entry_id, error_message='', user='system', action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    history = data.get('history', [])
    item = _find_entry(queue, entry_id) or _find_entry(history, entry_id)
    if not item:
        return None
    now_iso = datetime.now().isoformat()
    item['survey_status'] = 'falhou'
    item['survey_failed_at'] = now_iso
    item['survey_fail_reason'] = str(error_message or '')[:300]
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='survey_delivery_failed',
        user=user or 'system',
        details={'error': item.get('survey_fail_reason'), 'action_origin': action_origin or {}},
        status_from=item.get('status'),
        status_to=item.get('status')
    )
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item

def register_marketing_campaign_target(entry_id, campaign_key, user='system', channel='whatsapp', action_origin=None):
    data = load_waiting_data()
    queue = data.get('queue', [])
    history = data.get('history', [])
    item = _find_entry(queue, entry_id) or _find_entry(history, entry_id)
    if not item:
        return None
    if not bool(item.get('consent_marketing')):
        return None
    now_iso = datetime.now().isoformat()
    rec = {
        'campaign_key': str(campaign_key or 'campanha_marketing')[:80],
        'channel': str(channel or 'whatsapp')[:30],
        'registered_at': now_iso,
        'registered_by': user or 'system'
    }
    item.setdefault('marketing_campaigns', []).append(rec)
    item['last_marketing_campaign_at'] = now_iso
    _append_event(
        data,
        entry_id=item.get('id'),
        event_type='marked_for_marketing',
        user=user or 'system',
        details={'campaign_key': rec['campaign_key'], 'channel': rec['channel'], 'action_origin': action_origin or {}},
        status_from=item.get('status'),
        status_to=item.get('status')
    )
    _update_marketing_contact(data, item, 'marked_for_marketing')
    save_waiting_data(data)
    _upsert_waiting_list_entry(item)
    return item

def _history_filter_match(row, filters):
    if not isinstance(filters, dict):
        return True
    name_q = str(filters.get('name') or '').strip().lower()
    phone_q = str(filters.get('phone') or '').strip()
    status_q = _normalize_status(filters.get('status'))
    country_q = str(filters.get('country_code') or '').strip().upper()
    table_q = str(filters.get('table_id') or '').strip()
    collaborator_q = str(filters.get('collaborator') or '').strip().lower()
    start_q = str(filters.get('start_date') or '').strip()
    end_q = str(filters.get('end_date') or '').strip()
    party_size_q = str(filters.get('party_size') or '').strip()
    source_q = str(filters.get('source') or '').strip().lower()
    wait_min_q = str(filters.get('wait_min') or '').strip()
    wait_max_q = str(filters.get('wait_max') or '').strip()
    consent_mode_q = str(filters.get('consent_mode') or '').strip().lower()
    served_only_q = str(filters.get('served_only') or '').strip().lower()
    survey_status_q = str(filters.get('survey_status') or '').strip().lower()
    if name_q and name_q not in str(row.get('name') or '').lower():
        return False
    if phone_q:
        base_phone = str(row.get('phone_raw') or row.get('phone') or '')
        if phone_q not in base_phone and phone_q not in str(row.get('phone_e164') or '') and phone_q not in str(row.get('phone_wa') or ''):
            return False
    if status_q and status_q != 'aguardando' and status_q not in QUEUE_STATUSES:
        return False
    if status_q and status_q in QUEUE_STATUSES and _normalize_status(row.get('status')) != status_q:
        return False
    if country_q and str(row.get('country_code') or '').upper() != country_q:
        return False
    if table_q:
        current_table = str(row.get('current_table_id') or '')
        table_history = row.get('table_history') or []
        all_tables = {current_table} if current_table else set()
        for t in table_history:
            if isinstance(t, dict) and t.get('table_id'):
                all_tables.add(str(t.get('table_id')))
        if table_q not in all_tables:
            return False
    if collaborator_q:
        users = [str(row.get('updated_by') or '').lower(), str(row.get('created_by') or '').lower()]
        for hs in row.get('status_history') or []:
            if isinstance(hs, dict):
                users.append(str(hs.get('user') or '').lower())
        if not any(collaborator_q in u for u in users if u):
            return False
    if party_size_q:
        target_size = _safe_int(party_size_q, default=0, min_value=0)
        if target_size > 0 and _safe_int(row.get('party_size'), default=0) != target_size:
            return False
    if source_q and source_q not in str(row.get('source') or '').lower():
        return False
    wait_to_called = row.get('wait_to_called_minutes')
    if wait_min_q:
        wait_min = _safe_int(wait_min_q, default=0, min_value=0)
        if wait_min > 0 and (not isinstance(wait_to_called, int) or wait_to_called < wait_min):
            return False
    if wait_max_q:
        wait_max = _safe_int(wait_max_q, default=0, min_value=0)
        if wait_max > 0 and isinstance(wait_to_called, int) and wait_to_called > wait_max:
            return False
    if consent_mode_q == 'survey_only' and (not bool(row.get('consent_survey')) or bool(row.get('consent_marketing'))):
        return False
    if consent_mode_q == 'marketing_only' and (not bool(row.get('consent_marketing')) or bool(row.get('consent_survey'))):
        return False
    if consent_mode_q == 'none' and (bool(row.get('consent_marketing')) or bool(row.get('consent_survey'))):
        return False
    if consent_mode_q == 'both' and (not bool(row.get('consent_marketing')) or not bool(row.get('consent_survey'))):
        return False
    if served_only_q in {'1', 'true', 'yes'} and _normalize_status(row.get('status')) != 'sentado':
        return False
    if survey_status_q:
        effective_status = str(row.get('survey_status') or ('enviada' if row.get('received_survey') else 'nao_enviada')).strip().lower()
        if effective_status != survey_status_q:
            return False
    entry_dt = _dt_from_iso(row.get('entry_time'))
    if start_q and entry_dt:
        try:
            start_dt = datetime.fromisoformat(f"{start_q}T00:00:00")
            if entry_dt < start_dt:
                return False
        except Exception:
            pass
    if end_q and entry_dt:
        try:
            end_dt = datetime.fromisoformat(f"{end_q}T23:59:59")
            if entry_dt > end_dt:
                return False
        except Exception:
            pass
    return True

def get_queue_history_filtered(filters=None, limit=500):
    data = load_waiting_data()
    merged = {}
    for item in data.get('history', []):
        if isinstance(item, dict) and item.get('id'):
            merged[item.get('id')] = deepcopy(item)
    for item in data.get('queue', []):
        if isinstance(item, dict) and item.get('id'):
            merged[item.get('id')] = deepcopy(item)
    rows = []
    for item in merged.values():
        item['status'] = _normalize_status(item.get('status'))
        wait_to_called, called_to_seated, total_to_finish = _history_durations(item)
        item['wait_to_called_minutes'] = wait_to_called
        item['called_to_seated_minutes'] = called_to_seated
        item['total_to_finish_minutes'] = total_to_finish
        item['received_survey'] = bool(item.get('survey_invites_count') or item.get('survey_invites'))
        item['accepted_marketing'] = bool(item.get('consent_marketing'))
        item['source'] = item.get('source') or 'fila_virtual'
        item['survey_status'] = str(item.get('survey_status') or ('enviada' if item.get('received_survey') else 'nao_enviada')).strip().lower()
        item['was_served'] = item.get('status') == 'sentado'
        item['table_used_list'] = [str(x.get('table_id')) for x in (item.get('table_history') or []) if isinstance(x, dict) and x.get('table_id')]
        if _history_filter_match(item, filters or {}):
            rows.append(item)
    rows.sort(key=lambda x: x.get('last_updated') or x.get('entry_time') or '', reverse=True)
    return rows[:_safe_int(limit, default=500, min_value=1, max_value=3000)]

def get_queue_events(limit=300):
    data = load_waiting_data()
    events = [item for item in data.get('events', []) if isinstance(item, dict)]
    events.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
    return events[:_safe_int(limit, default=300, min_value=1, max_value=2000)]

def get_queue_metrics():
    data = load_waiting_data()
    queue = data.get('queue', [])
    active_count = sum(1 for x in queue if _normalize_status(x.get('status')) in ACTIVE_STATUSES)
    called_count = sum(1 for x in queue if _normalize_status(x.get('status')) == 'chamado')
    seated_count = sum(1 for x in queue if _normalize_status(x.get('status')) == 'sentado')
    cancelled_count = sum(1 for x in queue if _normalize_status(x.get('status')) in FINAL_STATUSES)

    all_rows = get_queue_history_filtered(filters={}, limit=3000)
    today = datetime.now().strftime('%Y-%m-%d')
    today_rows = [r for r in all_rows if str(r.get('entry_time') or '').startswith(today)]

    avg_wait = 0
    wait_samples = [r.get('wait_to_called_minutes') for r in today_rows if isinstance(r.get('wait_to_called_minutes'), int) and r.get('wait_to_called_minutes') >= 0]
    if wait_samples:
        avg_wait = int(sum(wait_samples) / len(wait_samples))

    called_today = 0
    seated_today = 0
    desist_today = 0
    cancelled_today = 0
    called_to_seated_samples = []
    for row in today_rows:
        called_at, seated_at = _history_call_and_seat_times(row)
        if called_at and called_at.strftime('%Y-%m-%d') == today:
            called_today += 1
        if seated_at and seated_at.strftime('%Y-%m-%d') == today:
            seated_today += 1
        status_norm = _normalize_status(row.get('status'))
        if status_norm == 'desistiu' and str(row.get('last_updated') or row.get('finished_at') or '').startswith(today):
            desist_today += 1
        if status_norm == 'cancelado_pela_equipe' and str(row.get('last_updated') or row.get('finished_at') or '').startswith(today):
            cancelled_today += 1
        c2s = row.get('called_to_seated_minutes')
        if isinstance(c2s, int) and c2s >= 0:
            called_to_seated_samples.append(c2s)

    avg_called_to_seated = int(sum(called_to_seated_samples) / len(called_to_seated_samples)) if called_to_seated_samples else 0
    conversion_rate = round((seated_today / len(today_rows)) * 100, 2) if today_rows else 0.0

    guests_serving = 0
    passants_serving = 0
    try:
        from app.services.data_service import load_table_orders
        orders = load_table_orders()
        for order in (orders.values() if isinstance(orders, dict) else []):
            if not isinstance(order, dict):
                continue
            qty = _safe_int(order.get('num_adults', 0), default=0, min_value=0)
            if qty <= 0:
                continue
            ctype = str(order.get('customer_type') or '').strip().lower()
            if ctype == 'hospede':
                guests_serving += qty
            elif ctype == 'passante':
                passants_serving += qty
    except Exception:
        guests_serving = 0
        passants_serving = 0

    return {
        "active_count": active_count,
        "called_count": called_count,
        "seated_count": seated_count,
        "cancelled_count": cancelled_count,
        "avg_wait_today": avg_wait,
        "called_today": called_today,
        "seated_today": seated_today,
        "desist_today": desist_today,
        "cancelled_today": cancelled_today,
        "avg_called_to_seated_today": avg_called_to_seated,
        "conversion_to_seated_pct": conversion_rate,
        "guests_serving": guests_serving,
        "passants_serving": passants_serving
    }
