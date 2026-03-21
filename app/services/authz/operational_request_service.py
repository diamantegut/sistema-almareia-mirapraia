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
SUGGESTION_WINDOW_DAYS = 60
SUGGESTION_MIN_REPEATS = 5
SUGGESTION_CACHE_TTL_SECONDS = 120
_SUGGESTION_CACHE: Dict[str, Any] = {'expires_at': 0.0, 'signature': '', 'index': {}}
PROMOTION_MIN_APPROVALS = 10
PROMOTION_MIN_SUGGESTION_USED_RATE = 0.6
PROMOTION_MIN_CONSISTENCY_SCORE = 0.7
_PROMOTION_CACHE: Dict[str, Any] = {'expires_at': 0.0, 'signature': '', 'rows': []}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_role(role: Any) -> str:
    return str(role or '').strip().lower()


def _approver_allowed(role: Any) -> bool:
    return _normalize_role(role) in {'admin', 'gerente', 'supervisor'}


def _load_data() -> Dict[str, Any]:
    if not os.path.exists(REQUESTS_FILE):
        return {'requests': [], 'grants': [], 'promoted_rules': [], 'promotion_candidates': []}
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
            'promoted_rules': data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else [],
            'promotion_candidates': data.get('promotion_candidates') if isinstance(data.get('promotion_candidates'), list) else [],
        }
    except Exception:
        return {'requests': [], 'grants': [], 'promoted_rules': [], 'promotion_candidates': []}


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


def _parse_iso(value: Any) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _minutes_between(start_iso: Any, end_iso: Any) -> Optional[int]:
    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso)
    if start_dt is None or end_dt is None:
        return None
    delta = int((end_dt - start_dt).total_seconds() // 60)
    if delta <= 0:
        return None
    return delta


def _permission_key(route_key: Any, method: Any, module_key: Any) -> str:
    route_value = str(route_key or '').strip()
    method_value = str(method or 'GET').strip().upper()
    module_value = str(module_key or '').strip()
    return f"{route_value}|{method_value}|{module_value}"


def _build_suggestion_index(data: Dict[str, Any]) -> Dict[str, Any]:
    rows = data.get('requests') if isinstance(data, dict) else []
    grants = data.get('grants') if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    if not isinstance(grants, list):
        grants = []
    grants_by_id: Dict[str, Dict[str, Any]] = {}
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        grant_id = str(grant.get('id') or '').strip()
        if grant_id:
            grants_by_id[grant_id] = grant
    cutoff = datetime.now() - timedelta(days=SUGGESTION_WINDOW_DAYS)
    index: Dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('status') or '').strip().lower() != REQUEST_APPROVED:
            continue
        decided_at = _parse_iso(row.get('decided_at') or row.get('created_at'))
        if decided_at is None or decided_at < cutoff:
            continue
        route_key = str(row.get('route_key') or '').strip()
        if not route_key:
            continue
        key = _permission_key(route_key, row.get('http_method'), row.get('module_key'))
        bucket = index.setdefault(
            key,
            {
                'total': 0,
                'department_counts': {},
                'role_counts': {},
                'duration_counts': {},
            },
        )
        bucket['total'] += 1
        department = str(row.get('requester_department') or '').strip()
        role_name = str(row.get('requester_class') or row.get('requester_role') or '').strip().lower()
        if department:
            bucket['department_counts'][department] = int(bucket['department_counts'].get(department, 0)) + 1
        if role_name:
            bucket['role_counts'][role_name] = int(bucket['role_counts'].get(role_name, 0)) + 1
        decision_type = str(row.get('decision_type') or '').strip().lower()
        if decision_type == GRANT_PERMANENT:
            duration_key = 'permanent:0'
        else:
            duration_minutes = None
            grant_id = str(row.get('grant_id') or '').strip()
            grant = grants_by_id.get(grant_id) if grant_id else None
            if isinstance(grant, dict):
                duration_minutes = _minutes_between(grant.get('created_at'), grant.get('expires_at'))
            if duration_minutes is None:
                duration_minutes = 120
            duration_key = f"temporary:{int(duration_minutes)}"
        bucket['duration_counts'][duration_key] = int(bucket['duration_counts'].get(duration_key, 0)) + 1
    return index


def _get_suggestion_index(data: Dict[str, Any]) -> Dict[str, Any]:
    requests = data.get('requests') if isinstance(data, dict) else []
    grants = data.get('grants') if isinstance(data, dict) else []
    if not isinstance(requests, list):
        requests = []
    if not isinstance(grants, list):
        grants = []
    signature = f"{len(requests)}:{len(grants)}:{str(requests[-1].get('decided_at') if requests else '')}:{str(grants[-1].get('created_at') if grants else '')}"
    now_ts = datetime.now().timestamp()
    if (
        str(_SUGGESTION_CACHE.get('signature') or '') == signature
        and float(_SUGGESTION_CACHE.get('expires_at') or 0) > now_ts
        and isinstance(_SUGGESTION_CACHE.get('index'), dict)
    ):
        return _SUGGESTION_CACHE.get('index')
    index = _build_suggestion_index({'requests': requests, 'grants': grants})
    _SUGGESTION_CACHE['signature'] = signature
    _SUGGESTION_CACHE['expires_at'] = now_ts + SUGGESTION_CACHE_TTL_SECONDS
    _SUGGESTION_CACHE['index'] = index
    return index


def _build_promotion_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get('requests') if isinstance(data, dict) else []
    grants = data.get('grants') if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    if not isinstance(grants, list):
        grants = []
    grants_by_id: Dict[str, Dict[str, Any]] = {}
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        grant_id = str(grant.get('id') or '').strip()
        if grant_id:
            grants_by_id[grant_id] = grant
    cutoff = datetime.now() - timedelta(days=SUGGESTION_WINDOW_DAYS)
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('status') or '').strip().lower() != REQUEST_APPROVED:
            continue
        decided_at = _parse_iso(row.get('decided_at') or row.get('created_at'))
        if decided_at is None or decided_at < cutoff:
            continue
        route_key = str(row.get('route_key') or '').strip()
        if not route_key:
            continue
        method = str(row.get('http_method') or 'GET').strip().upper()
        module = str(row.get('module_key') or '').strip() or route_key.split('.', 1)[0]
        permission_key = _permission_key(route_key, method, module)
        bucket = grouped.setdefault(
            permission_key,
            {
                'permission_key': permission_key,
                'module': module,
                'scope_counts': {'user': 0, 'role': 0, 'department': 0},
                'duration_counts': {'temporary': 0, 'permanent': 0},
                'total_approvals': 0,
                'suggestion_used': 0,
                'created_at': decided_at.isoformat(),
                'last_seen_at': decided_at.isoformat(),
            },
        )
        bucket['total_approvals'] += 1
        if bool(row.get('suggestion_used')):
            bucket['suggestion_used'] += 1
        grant_scope = 'user'
        grant_id = str(row.get('grant_id') or '').strip()
        grant = grants_by_id.get(grant_id) if grant_id else None
        if isinstance(grant, dict):
            grant_scope = str(grant.get('grant_scope') or 'user').strip().lower()
            if grant_scope not in {'user', 'role', 'department'}:
                grant_scope = 'user'
        bucket['scope_counts'][grant_scope] = int(bucket['scope_counts'].get(grant_scope, 0)) + 1
        decision_type = str(row.get('decision_type') or '').strip().lower()
        duration_label = 'permanent' if decision_type == GRANT_PERMANENT else 'temporary'
        bucket['duration_counts'][duration_label] = int(bucket['duration_counts'].get(duration_label, 0)) + 1
        if decided_at.isoformat() < str(bucket.get('created_at') or ''):
            bucket['created_at'] = decided_at.isoformat()
        if decided_at.isoformat() > str(bucket.get('last_seen_at') or ''):
            bucket['last_seen_at'] = decided_at.isoformat()
    candidates: List[Dict[str, Any]] = []
    for bucket in grouped.values():
        total_approvals = int(bucket.get('total_approvals') or 0)
        if total_approvals <= 0:
            continue
        suggestion_used_rate = float(bucket.get('suggestion_used') or 0) / float(total_approvals)
        scope_counts = bucket.get('scope_counts') if isinstance(bucket.get('scope_counts'), dict) else {}
        recommended_scope = max(scope_counts, key=lambda key: int(scope_counts.get(key, 0)))
        consistency_score = float(int(scope_counts.get(recommended_scope, 0)) / float(total_approvals))
        duration_counts = bucket.get('duration_counts') if isinstance(bucket.get('duration_counts'), dict) else {}
        recommended_duration = 'permanent' if int(duration_counts.get('permanent', 0)) >= int(duration_counts.get('temporary', 0)) else 'temporary'
        if not (
            total_approvals >= PROMOTION_MIN_APPROVALS
            and suggestion_used_rate >= PROMOTION_MIN_SUGGESTION_USED_RATE
            and consistency_score >= PROMOTION_MIN_CONSISTENCY_SCORE
        ):
            continue
        confidence_score = min(1.0, round((consistency_score * 0.5) + (suggestion_used_rate * 0.4) + (min(total_approvals / 20.0, 1.0) * 0.1), 4))
        candidates.append(
            {
                'permission_key': bucket.get('permission_key'),
                'module': bucket.get('module'),
                'recommended_scope': recommended_scope,
                'recommended_duration': recommended_duration,
                'confidence_score': confidence_score,
                'total_approvals': total_approvals,
                'suggestion_used_rate': round(suggestion_used_rate, 4),
                'consistency_score': round(consistency_score, 4),
                'created_at': bucket.get('created_at'),
                'last_seen_at': bucket.get('last_seen_at'),
            }
        )
    candidates.sort(key=lambda item: (float(item.get('confidence_score') or 0), int(item.get('total_approvals') or 0)), reverse=True)
    return candidates


def _get_promotion_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    requests = data.get('requests') if isinstance(data, dict) else []
    grants = data.get('grants') if isinstance(data, dict) else []
    if not isinstance(requests, list):
        requests = []
    if not isinstance(grants, list):
        grants = []
    signature = f"{len(requests)}:{len(grants)}:{str(requests[-1].get('decided_at') if requests else '')}:{str(grants[-1].get('created_at') if grants else '')}"
    now_ts = datetime.now().timestamp()
    if (
        str(_PROMOTION_CACHE.get('signature') or '') == signature
        and float(_PROMOTION_CACHE.get('expires_at') or 0) > now_ts
        and isinstance(_PROMOTION_CACHE.get('rows'), list)
    ):
        return list(_PROMOTION_CACHE.get('rows'))
    rows = _build_promotion_candidates({'requests': requests, 'grants': grants})
    _PROMOTION_CACHE['signature'] = signature
    _PROMOTION_CACHE['expires_at'] = now_ts + SUGGESTION_CACHE_TTL_SECONDS
    _PROMOTION_CACHE['rows'] = list(rows)
    return rows


def list_promotion_candidates(*, limit: int = 200) -> List[Dict[str, Any]]:
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        rows = _get_promotion_candidates(data)
        data['promotion_candidates'] = rows
        _save_data(data)
    return rows[: max(1, int(limit))]


def count_promotion_candidates() -> int:
    return len(list_promotion_candidates(limit=5000))


def _suggest_for_request(
    *,
    data: Dict[str, Any],
    route_key: str,
    method: str,
    module_key: str,
    requester_department: str,
    requester_role: str,
) -> Dict[str, Any]:
    permission_key = _permission_key(route_key, method, module_key)
    index = _get_suggestion_index(data)
    bucket = index.get(permission_key) if isinstance(index, dict) else None
    if not isinstance(bucket, dict):
        return {
            'suggested_scope': '',
            'suggested_duration': '',
            'suggested_duration_value': 0,
            'suggestion_confidence': 0.0,
            'suggestion_reason': 'Sem dados suficientes para sugestão.',
        }
    total = int(bucket.get('total') or 0)
    department_counts = bucket.get('department_counts') if isinstance(bucket.get('department_counts'), dict) else {}
    role_counts = bucket.get('role_counts') if isinstance(bucket.get('role_counts'), dict) else {}
    duration_counts = bucket.get('duration_counts') if isinstance(bucket.get('duration_counts'), dict) else {}
    department_value = str(requester_department or '').strip()
    role_value = str(requester_role or '').strip().lower()
    dept_count = int(department_counts.get(department_value, 0)) if department_value else 0
    role_count = int(role_counts.get(role_value, 0)) if role_value else 0
    if dept_count >= SUGGESTION_MIN_REPEATS:
        suggested_scope = 'department'
        top_scope_count = dept_count
        scope_reason = f"Esta permissão foi aprovada {dept_count} vezes para o departamento {department_value}."
    elif role_count >= SUGGESTION_MIN_REPEATS:
        suggested_scope = 'role'
        top_scope_count = role_count
        scope_reason = f"{role_value.title()} já recebeu este acesso em {role_count} ocasiões."
    else:
        suggested_scope = 'user'
        top_scope_count = 1 if total > 0 else 0
        scope_reason = 'Sem padrão dominante por departamento ou classe funcional; recomendação individual.'
    duration_key = ''
    duration_count = 0
    for key, value in duration_counts.items():
        count_value = int(value or 0)
        if count_value > duration_count:
            duration_count = count_value
            duration_key = str(key or '')
    if duration_key.startswith('permanent:'):
        suggested_duration = 'permanent'
        suggested_duration_value = 0
        duration_reason = 'A maioria das aprovações anteriores foi permanente.'
    else:
        suggested_duration = 'temporary'
        duration_minutes = 120
        if duration_key.startswith('temporary:'):
            try:
                duration_minutes = max(1, int(duration_key.split(':', 1)[1]))
            except Exception:
                duration_minutes = 120
        suggested_duration_value = duration_minutes
        duration_reason = f"A maioria das aprovações foi temporária ({duration_minutes} minutos)."
    if total < 3:
        confidence = 0.35
    else:
        consistency = float(top_scope_count / total) if total > 0 else 0.0
        if total >= 8 and consistency >= 0.75:
            confidence = 0.9
        elif total >= 5 and consistency >= 0.5:
            confidence = 0.7
        else:
            confidence = 0.45
    return {
        'suggested_scope': suggested_scope,
        'suggested_duration': suggested_duration,
        'suggested_duration_value': int(suggested_duration_value),
        'suggestion_confidence': float(max(0.0, min(confidence, 1.0))),
        'suggestion_reason': f"{scope_reason} {duration_reason}".strip(),
    }


def create_request(
    *,
    requester_user: str,
    requester_role: str,
    route_key: str,
    endpoint: str,
    http_method: str,
    requester_department: str = '',
    requester_class: str = '',
    module_key: str = '',
    sensitivity: str = 'operacional',
    context: Optional[Dict[str, Any]] = None,
    reason: str = '',
) -> Dict[str, Any]:
    route_key_value = str(route_key or '').strip()
    if not route_key_value:
        raise ValueError('route_key obrigatório')
    payload_context = context if isinstance(context, dict) else {}
    requester_user_value = str(requester_user or 'unknown')
    requester_role_value = str(requester_role or '')
    requester_department_value = str(requester_department or '')
    requester_class_value = str(requester_class or requester_role_value or '').strip().lower()
    method_value = str(http_method or 'GET').upper()
    module_value = str(module_key or '').strip() or route_key_value.split('.', 1)[0]
    sensitivity_value = str(sensitivity or 'operacional').strip().lower() or 'operacional'
    suggested_scope_value = str(payload_context.get('suggested_scope') or '').strip()
    suggested_duration_value = str(payload_context.get('suggested_duration') or '').strip()
    suggested_duration_minutes = int(payload_context.get('suggested_duration_value') or 0) if str(payload_context.get('suggested_duration_value') or '').strip().isdigit() else 0
    suggestion_confidence = float(payload_context.get('suggestion_confidence') or 0.0)
    suggestion_reason = str(payload_context.get('suggestion_reason') or '').strip()
    record = {
        'id': uuid.uuid4().hex,
        'status': REQUEST_PENDING,
        'requester_user': requester_user_value,
        'requester_role': requester_role_value,
        'requester_department': requester_department_value,
        'requester_class': requester_class_value,
        'route_key': route_key_value,
        'endpoint': str(endpoint or ''),
        'http_method': method_value,
        'module_key': module_value,
        'sensitivity': sensitivity_value,
        'context': payload_context,
        'suggested_scope': suggested_scope_value,
        'suggested_duration': suggested_duration_value,
        'suggested_duration_value': suggested_duration_minutes,
        'suggestion_confidence': suggestion_confidence,
        'suggestion_reason': suggestion_reason,
        'suggestion_used': False,
        'suggestion_modified': False,
        'reason': str(reason or '').strip(),
        'created_at': _now_iso(),
        'decided_at': '',
        'decided_by': '',
        'decision_type': '',
        'decision_reason': '',
        'grant_id': '',
    }
    duplicate_window_minutes = 5
    now_dt = datetime.now()
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        if not record['suggested_scope'] or not record['suggested_duration']:
            suggestion = _suggest_for_request(
                data=data,
                route_key=route_key_value,
                method=method_value,
                module_key=module_value,
                requester_department=requester_department_value,
                requester_role=requester_class_value,
            )
            record['suggested_scope'] = str(suggestion.get('suggested_scope') or '')
            record['suggested_duration'] = str(suggestion.get('suggested_duration') or '')
            record['suggested_duration_value'] = int(suggestion.get('suggested_duration_value') or 0)
            record['suggestion_confidence'] = float(suggestion.get('suggestion_confidence') or 0.0)
            record['suggestion_reason'] = str(suggestion.get('suggestion_reason') or '')
        rows = data.get('requests') or []
        for row in rows:
            if str(row.get('status') or '').strip().lower() != REQUEST_PENDING:
                continue
            if str(row.get('requester_user') or '') != requester_user_value:
                continue
            if str(row.get('route_key') or '') != route_key_value:
                continue
            if str(row.get('http_method') or '').upper() != method_value:
                continue
            created_at = str(row.get('created_at') or '').strip()
            if not created_at:
                continue
            try:
                created_dt = datetime.fromisoformat(created_at)
            except Exception:
                continue
            if (now_dt - created_dt).total_seconds() <= duplicate_window_minutes * 60:
                return row
        data['requests'].append(record)
        data['promotion_candidates'] = _get_promotion_candidates(data)
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
    target_department: str = '',
    target_role: str = '',
    suggestion_used: bool = False,
    suggested_scope: str = '',
    suggested_duration: str = '',
    suggested_duration_value: int = 0,
) -> Dict[str, Any]:
    if not _approver_allowed(approver_role):
        raise ValueError('approver sem permissão')
    decision_norm = str(decision or '').strip().lower()
    if decision_norm not in {
        'deny',
        'approve_once',
        'approve_temporary',
        'approve_permanent',
        'approve_department_temporary',
        'approve_department_permanent',
        'approve_role_temporary',
        'approve_role_permanent',
    }:
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
            elif decision_norm in {'approve_temporary', 'approve_department_temporary'}:
                grant_type = GRANT_TEMPORARY
                remaining_uses = None
                ttl = max(1, min(int(ttl_minutes), 24 * 60))
                expires_at = (datetime.now() + timedelta(minutes=ttl)).isoformat()
            else:
                grant_type = GRANT_PERMANENT
                remaining_uses = None
                expires_at = ''
            is_department_scope = decision_norm in {'approve_department_temporary', 'approve_department_permanent'}
            is_role_scope = decision_norm in {'approve_role_temporary', 'approve_role_permanent'}
            grant_scope = 'department' if is_department_scope else ('role' if is_role_scope else 'user')
            target_department_value = str(target_department or target.get('requester_department') or '').strip()
            target_role_value = str(target_role or target.get('requester_class') or target.get('requester_role') or '').strip().lower()
            if is_department_scope and not target_department_value:
                raise ValueError('departamento obrigatório para aprovação por departamento')
            if is_role_scope and not target_role_value:
                raise ValueError('classe funcional obrigatória para aprovação por classe')
            grant = {
                'id': uuid.uuid4().hex,
                'request_id': target['id'],
                'requester_user': target.get('requester_user'),
                'requester_department': target.get('requester_department'),
                'grant_scope': grant_scope,
                'target_department': target_department_value,
                'target_role': target_role_value,
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
        applied_scope = str(grant.get('grant_scope') or 'user') if isinstance(grant, dict) else 'user'
        applied_duration = str(target.get('decision_type') or '')
        if applied_duration == GRANT_ONE_SHOT:
            applied_duration_label = 'temporary'
            applied_duration_value = 120
        elif applied_duration == GRANT_PERMANENT:
            applied_duration_label = 'permanent'
            applied_duration_value = 0
        else:
            applied_duration_label = 'temporary'
            applied_duration_value = max(1, min(int(ttl_minutes), 24 * 60))
        suggested_scope_value = str(suggested_scope or '').strip().lower()
        suggested_duration_value_norm = str(suggested_duration or '').strip().lower()
        suggested_duration_minutes = int(suggested_duration_value or 0)
        used_flag = bool(suggestion_used) and bool(suggested_scope_value or suggested_duration_value_norm)
        modified_flag = False
        if used_flag:
            if suggested_scope_value and suggested_scope_value != applied_scope:
                modified_flag = True
            if suggested_duration_value_norm and suggested_duration_value_norm != applied_duration_label:
                modified_flag = True
            if suggested_duration_value_norm == 'temporary' and suggested_duration_minutes > 0 and int(suggested_duration_minutes) != int(applied_duration_value):
                modified_flag = True
        target['suggestion_used'] = used_flag
        target['suggestion_modified'] = modified_flag
        data['promotion_candidates'] = _get_promotion_candidates(data)
        _save_data(data)
    _log(
        'AUTHZ_OPERATIONAL_REQUEST_DECIDED',
        {
            'request_id': target.get('id'),
            'decision': decision_norm,
            'decision_type': target.get('decision_type'),
            'route_key': target.get('route_key'),
            'grant_id': target.get('grant_id'),
            'suggestion_used': target.get('suggestion_used'),
            'suggestion_modified': target.get('suggestion_modified'),
        },
        user=str(approver_user or 'unknown'),
    )
    return target


def apply_promotion_candidate(
    *,
    permission_key: str,
    module: str,
    promoted_by: str,
    promotion_scope: str,
    promotion_duration: str,
    duration_minutes: int = 120,
    target_department: str = '',
    target_role: str = '',
) -> Dict[str, Any]:
    permission_key_value = str(permission_key or '').strip()
    module_value = str(module or '').strip()
    promotion_scope_value = str(promotion_scope or '').strip().lower()
    promotion_duration_value = str(promotion_duration or '').strip().lower()
    if promotion_scope_value not in {'department', 'role'}:
        raise ValueError('escopo de promoção inválido')
    if promotion_duration_value not in {'temporary', 'permanent'}:
        raise ValueError('duração de promoção inválida')
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        candidates = _get_promotion_candidates(data)
        candidate = next(
            (
                row
                for row in candidates
                if str(row.get('permission_key') or '') == permission_key_value and str(row.get('module') or '') == module_value
            ),
            None,
        )
        if not isinstance(candidate, dict):
            raise ValueError('candidato não encontrado')
        promoted_rules = data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else []
        route_key = permission_key_value.split('|', 1)[0]
        method = permission_key_value.split('|')[1].split('|')[0] if '|' in permission_key_value else 'GET'
        ttl_value = max(1, min(int(duration_minutes), 24 * 60))
        expires_at = ''
        if promotion_duration_value == 'temporary':
            expires_at = (datetime.now() + timedelta(minutes=ttl_value)).isoformat()
        rule = {
            'id': uuid.uuid4().hex,
            'permission_key': permission_key_value,
            'module': module_value,
            'route_key': route_key,
            'http_method': method,
            'promotion_scope': promotion_scope_value,
            'promotion_duration': promotion_duration_value,
            'expires_at': expires_at,
            'target_department': str(target_department or '').strip(),
            'target_role': str(target_role or '').strip().lower(),
            'active': True,
            'created_at': _now_iso(),
            'promoted_by': str(promoted_by or 'unknown'),
            'promotion_confidence': float(candidate.get('confidence_score') or 0.0),
            'source_metrics': {
                'total_approvals': int(candidate.get('total_approvals') or 0),
                'suggestion_used_rate': float(candidate.get('suggestion_used_rate') or 0.0),
                'consistency_score': float(candidate.get('consistency_score') or 0.0),
            },
            'promotion_applied': True,
        }
        if promotion_scope_value == 'department' and not str(rule.get('target_department') or '').strip():
            raise ValueError('departamento obrigatório para promoção por departamento')
        if promotion_scope_value == 'role' and not str(rule.get('target_role') or '').strip():
            raise ValueError('classe funcional obrigatória para promoção por classe')
        promoted_rules.append(rule)
        data['promoted_rules'] = promoted_rules
        data['promotion_candidates'] = _get_promotion_candidates(data)
        _save_data(data)
    _log(
        'AUTHZ_PROMOTION_APPLIED',
        {
            'permission_key': permission_key_value,
            'module': module_value,
            'promotion_scope': promotion_scope_value,
            'promotion_duration': promotion_duration_value,
            'promotion_confidence': rule.get('promotion_confidence'),
            'promotion_applied': True,
            'source_metrics': rule.get('source_metrics'),
        },
        user=str(promoted_by or 'unknown'),
    )
    return rule


def rollback_promoted_rule(*, rule_id: str, revoked_by: str) -> Dict[str, Any]:
    rule_id_value = str(rule_id or '').strip()
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        promoted_rules = data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else []
        target = next((row for row in promoted_rules if str(row.get('id') or '') == rule_id_value), None)
        if not isinstance(target, dict):
            raise ValueError('regra promovida não encontrada')
        target['active'] = False
        target['revoked_at'] = _now_iso()
        target['revoked_by'] = str(revoked_by or 'unknown')
        _save_data(data)
    _log(
        'AUTHZ_PROMOTION_ROLLBACK',
        {'rule_id': rule_id_value, 'permission_key': target.get('permission_key'), 'promotion_applied': False},
        user=str(revoked_by or 'unknown'),
    )
    return target


def reactivate_promoted_rule(*, rule_id: str, reactivated_by: str, duration_minutes: int = 120) -> Dict[str, Any]:
    rule_id_value = str(rule_id or '').strip()
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        promoted_rules = data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else []
        target = next((row for row in promoted_rules if str(row.get('id') or '') == rule_id_value), None)
        if not isinstance(target, dict):
            raise ValueError('regra promovida não encontrada')
        target['active'] = True
        target['reactivated_at'] = _now_iso()
        target['reactivated_by'] = str(reactivated_by or 'unknown')
        if str(target.get('promotion_duration') or '').strip().lower() == 'temporary':
            ttl_value = max(1, min(int(duration_minutes), 24 * 60))
            target['expires_at'] = (datetime.now() + timedelta(minutes=ttl_value)).isoformat()
        _save_data(data)
    _log(
        'AUTHZ_PROMOTION_REACTIVATED',
        {'rule_id': rule_id_value, 'permission_key': target.get('permission_key'), 'promotion_applied': True},
        user=str(reactivated_by or 'unknown'),
    )
    return target


def list_promoted_rules(*, include_inactive: bool = True, limit: int = 5000) -> List[Dict[str, Any]]:
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        rows = data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else []
    output: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not include_inactive and not bool(row.get('active', True)):
            continue
        item = dict(row)
        if bool(item.get('active', True)):
            expires_at = str(item.get('expires_at') or '').strip()
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) < datetime.now():
                        item['status'] = 'expired'
                    else:
                        item['status'] = 'active'
                except Exception:
                    item['status'] = 'expired'
            else:
                item['status'] = 'active'
        else:
            item['status'] = 'revoked'
        output.append(item)
    output.sort(key=lambda row: str(row.get('created_at') or ''), reverse=True)
    return output[: max(1, int(limit))]


def authorize_by_grant(*, user: str, route_key: str) -> bool:
    return authorize_by_grant_with_scope(user=user, route_key=route_key, department='', role='')


def authorize_by_grant_with_scope(*, user: str, route_key: str, department: str = '', role: str = '') -> bool:
    user_value = str(user or '').strip()
    department_value = str(department or '').strip()
    role_value = str(role or '').strip().lower()
    route_key_value = str(route_key or '').strip()
    if not user_value or not route_key_value:
        return False
    now = datetime.now()
    allowed = False
    changed = False
    with file_lock(REQUESTS_FILE):
        data = _load_data()
        promoted_rules = data.get('promoted_rules') if isinstance(data.get('promoted_rules'), list) else []
        for rule in promoted_rules:
            if not isinstance(rule, dict):
                continue
            if not bool(rule.get('active', True)):
                continue
            if str(rule.get('route_key') or '') != route_key_value:
                continue
            if str(rule.get('promotion_scope') or '') == 'department':
                if str(rule.get('target_department') or '').strip() != department_value:
                    continue
            elif str(rule.get('promotion_scope') or '') == 'role':
                if str(rule.get('target_role') or '').strip().lower() != role_value:
                    continue
            else:
                continue
            expires_at = str(rule.get('expires_at') or '').strip()
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) < now:
                        rule['active'] = False
                        changed = True
                        continue
                except Exception:
                    rule['active'] = False
                    changed = True
                    continue
            allowed = True
            break
        if allowed:
            if changed:
                _save_data(data)
            _log('AUTHZ_PROMOTED_RULE_USED', {'user': user_value, 'route_key': route_key_value}, user=user_value)
            return True
        grants = data.get('grants') or []
        for grant in grants:
            if bool(grant.get('revoked')):
                continue
            grant_scope = str(grant.get('grant_scope') or 'user').strip().lower()
            if grant_scope == 'department':
                if not department_value:
                    continue
                if str(grant.get('target_department') or '').strip() != department_value:
                    continue
            elif grant_scope == 'role':
                if not role_value:
                    continue
                if str(grant.get('target_role') or '').strip().lower() != role_value:
                    continue
            else:
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
