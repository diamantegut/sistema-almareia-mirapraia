from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.logger_service import LoggerService
from app.services.system_config_manager import get_data_path
from app.utils.lock import file_lock


REQUESTS_FILE = get_data_path('authz_operational_requests.json')

REQUEST_PENDING = 'pending'
REQUEST_APPROVED = 'approved'
REQUEST_DENIED = 'denied'
REQUEST_STATES = {REQUEST_PENDING, REQUEST_APPROVED, REQUEST_DENIED}

GRANT_ONE_SHOT = 'one_shot'
GRANT_TEMPORARY = 'temporary'
GRANT_PERMANENT = 'permanent'
GRANT_TYPES = {GRANT_ONE_SHOT, GRANT_TEMPORARY, GRANT_PERMANENT}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_role(role: Any) -> str:
    return str(role or '').strip().lower()


def _approver_allowed(role: Any) -> bool:
    return _normalize_role(role) in {'admin', 'gerente', 'supervisor'}


def _load_data() -> Dict[str, Any]:
    if not os.path.exists(REQUESTS_FILE):
        return {'requests': [], 'grants': []}
    try:
        with open(REQUESTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {'requests': [], 'grants': []}
        requests = data.get('requests')
        grants = data.get('grants')
        return {
            'requests': requests if isinstance(requests, list) else [],
            'grants': grants if isinstance(grants, list) else [],
        }
    except Exception:
        return {'requests': [], 'grants': []}


def _save_data(payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(REQUESTS_FILE), exist_ok=True)
    tmp_path = REQUESTS_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, REQUESTS_FILE)


def _log(action: str, details: Dict[str, Any], user: str = 'Sistema') -> None:
    try:
        LoggerService.log_acao(
            acao=action,
            entidade='AuthZ Operacional',
            detalhes=details,
            nivel_severidade='INFO',
            departamento_id='Administração',
            colaborador_id=user,
        )
    except Exception:
        pass


def create_request(
    *,
    requester_user: str,
    requester_role: str,
    route_key: str,
    endpoint: str,
    http_method: str,
    context: Optional[Dict[str, Any]] = None,
    reason: str = '',
) -> Dict[str, Any]:
    route_key_value = str(route_key or '').strip()
    if not route_key_value:
        raise ValueError('route_key obrigatório')
    payload_context = context if isinstance(context, dict) else {}
    record = {
        'id': uuid.uuid4().hex,
        'status': REQUEST_PENDING,
        'requester_user': str(requester_user or 'unknown'),
        'requester_role': str(requester_role or ''),
        'route_key': route_key_value,
        'endpoint': str(endpoint or ''),
        'http_method': str(http_method or 'GET').upper(),
        'context': payload_context,
        'reason': str(reason or '').strip(),
        'created_at': _now_iso(),
        'decided_at': '',
        'decided_by': '',
        'decision_type': '',
        'decision_reason': '',
        'grant_id': '',
    }
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        data['requests'].append(record)
        _save_data(data)
    _log('AUTHZ_OPERATIONAL_REQUEST_CREATED', {'request_id': record['id'], 'route_key': route_key_value, 'context': payload_context}, user=record['requester_user'])
    return record


def list_requests(*, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with file_lock(REQUESTS_FILE):
        data = _load_data()
    rows = data.get('requests') or []
    status_filter = str(status or '').strip().lower()
    if status_filter:
        rows = [row for row in rows if str(row.get('status') or '').strip().lower() == status_filter]
    rows.sort(key=lambda row: str(row.get('created_at') or ''), reverse=True)
    return rows[: max(1, int(limit))]


def count_pending() -> int:
    return len(list_requests(status=REQUEST_PENDING, limit=5000))


def decide_request(
    *,
    request_id: str,
    approver_user: str,
    approver_role: str,
    decision: str,
    decision_reason: str = '',
    ttl_minutes: int = 60,
) -> Dict[str, Any]:
    if not _approver_allowed(approver_role):
        raise ValueError('approver sem permissão')
    decision_norm = str(decision or '').strip().lower()
    if decision_norm not in {'deny', 'approve_once', 'approve_temporary', 'approve_permanent'}:
        raise ValueError('decision inválida')
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        rows = data.get('requests') or []
        target = next((row for row in rows if str(row.get('id')) == str(request_id)), None)
        if not target:
            raise ValueError('request não encontrado')
        if str(target.get('status')) != REQUEST_PENDING:
            raise ValueError('request não está pendente')
        target['decided_at'] = _now_iso()
        target['decided_by'] = str(approver_user or 'unknown')
        target['decision_reason'] = str(decision_reason or '').strip()
        grant = None
        if decision_norm == 'deny':
            target['status'] = REQUEST_DENIED
            target['decision_type'] = 'deny'
        else:
            target['status'] = REQUEST_APPROVED
            if decision_norm == 'approve_once':
                grant_type = GRANT_ONE_SHOT
                remaining_uses = 1
                expires_at = ''
            elif decision_norm == 'approve_temporary':
                grant_type = GRANT_TEMPORARY
                remaining_uses = None
                ttl = max(1, min(int(ttl_minutes), 24 * 60))
                expires_at = (datetime.now() + timedelta(minutes=ttl)).isoformat()
            else:
                grant_type = GRANT_PERMANENT
                remaining_uses = None
                expires_at = ''
            grant = {
                'id': uuid.uuid4().hex,
                'request_id': target['id'],
                'requester_user': target.get('requester_user'),
                'route_key': target.get('route_key'),
                'grant_type': grant_type,
                'remaining_uses': remaining_uses,
                'expires_at': expires_at,
                'approved_by': target['decided_by'],
                'created_at': _now_iso(),
                'revoked': False,
            }
            data['grants'].append(grant)
            target['decision_type'] = grant_type
            target['grant_id'] = grant['id']
        _save_data(data)
    _log(
        'AUTHZ_OPERATIONAL_REQUEST_DECIDED',
        {
            'request_id': target.get('id'),
            'decision': decision_norm,
            'decision_type': target.get('decision_type'),
            'route_key': target.get('route_key'),
            'grant_id': target.get('grant_id'),
        },
        user=str(approver_user or 'unknown'),
    )
    return target


def authorize_by_grant(*, user: str, route_key: str) -> bool:
    user_value = str(user or '').strip()
    route_key_value = str(route_key or '').strip()
    if not user_value or not route_key_value:
        return False
    now = datetime.now()
    allowed = False
    changed = False
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        grants = data.get('grants') or []
        for grant in grants:
            if bool(grant.get('revoked')):
                continue
            if str(grant.get('requester_user')) != user_value:
                continue
            if str(grant.get('route_key')) != route_key_value:
                continue
            expires_at = str(grant.get('expires_at') or '').strip()
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) < now:
                        grant['revoked'] = True
                        changed = True
                        continue
                except Exception:
                    grant['revoked'] = True
                    changed = True
                    continue
            grant_type = str(grant.get('grant_type') or '')
            if grant_type == GRANT_ONE_SHOT:
                remaining = int(grant.get('remaining_uses') or 0)
                if remaining <= 0:
                    grant['revoked'] = True
                    changed = True
                    continue
                grant['remaining_uses'] = remaining - 1
                if grant['remaining_uses'] <= 0:
                    grant['revoked'] = True
                changed = True
                allowed = True
                break
            if grant_type in {GRANT_TEMPORARY, GRANT_PERMANENT}:
                allowed = True
                break
        if changed:
            _save_data(data)
    if allowed:
        _log('AUTHZ_OPERATIONAL_GRANT_USED', {'user': user_value, 'route_key': route_key_value}, user=user_value)
    return allowed
