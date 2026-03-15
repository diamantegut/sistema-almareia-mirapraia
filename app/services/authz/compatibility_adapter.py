from __future__ import annotations

from datetime import datetime, timezone
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.permission_service import (
    derive_legacy_profile,
    effective_profile_for_user,
    legacy_tokens_from_profile,
    normalize_role,
)
from app.services.authz.schemas import GrantPermissions, GrantSchema, GrantUser, role_level_for


LEGACY_TOKEN_ACTION_PREFIXES: Dict[str, List[str]] = {
    "recepcao": ["action.reception.*"],
    "principal": ["action.reception.*", "action.restaurant.*"],
    "restaurante": ["action.restaurant.*", "action.menu.*"],
    "restaurante_full_access": ["action.restaurant.*", "action.menu.*"],
    "rh": ["action.hr.*"],
    "financeiro": ["action.finance.*"],
    "governanca": ["action.governance.*"],
    "conferencia": ["action.quality.*", "action.assets.*"],
    "estoque": ["action.stock.*", "action.suppliers.*"],
    "cozinha": ["action.kitchen.*"],
}

DEPARTMENT_SCOPE_HINTS: Dict[str, List[str]] = {
    "recepcao": ["scope.department", "scope.hotel", "scope.shift.current"],
    "reservas": ["scope.department", "scope.hotel", "scope.shift.current"],
    "restaurante": ["scope.department", "scope.shift.current"],
    "cozinha": ["scope.department", "scope.shift.current"],
    "estoque": ["scope.department", "scope.warehouse"],
    "fornecedores": ["scope.department", "scope.warehouse"],
    "financeiro": ["scope.department", "scope.finance.period"],
    "auditoria": ["scope.audit.readonly", "scope.department"],
    "governanca": ["scope.department", "scope.shift.current"],
    "rh": ["scope.department"],
    "manutencao": ["scope.department", "scope.shift.current"],
    "admin": ["scope.global"],
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def _normalize_profile_v2(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"version": 2, "areas": {}, "level_pages": []}
    areas_raw = raw.get("areas") if isinstance(raw.get("areas"), dict) else {}
    level_pages_raw = raw.get("level_pages") if isinstance(raw.get("level_pages"), list) else []
    normalized_areas: Dict[str, Any] = {}
    for area_key, area_value in areas_raw.items():
        area_name = str(area_key or "").strip()
        if not area_name or not isinstance(area_value, dict):
            continue
        pages_raw = area_value.get("pages") if isinstance(area_value.get("pages"), dict) else {}
        normalized_areas[area_name] = {
            "all": bool(area_value.get("all")),
            "pages": {str(k): bool(v) for k, v in pages_raw.items()},
        }
    level_pages = [str(item).strip() for item in level_pages_raw if str(item).strip()]
    return {"version": 2, "areas": normalized_areas, "level_pages": level_pages}


def _profile_to_pages(profile: Dict[str, Any], policy_registry: Any = None) -> Set[str]:
    pages: Set[str] = set()
    normalized = _normalize_profile_v2(profile)
    for area_key, area_data in (normalized.get("areas") or {}).items():
        area_name = str(area_key or "").strip()
        if not area_name:
            continue
        if bool((area_data or {}).get("all")):
            pages.add(f"page.{area_name}.*")
            if policy_registry is not None and hasattr(policy_registry, "policies_by_endpoint"):
                for policy in policy_registry.policies_by_endpoint.values():
                    if getattr(policy, "area", None) == area_name:
                        pages.add(policy.page)
        area_pages = (area_data or {}).get("pages") if isinstance((area_data or {}).get("pages"), dict) else {}
        for endpoint, granted in area_pages.items():
            if granted:
                endpoint_name = str(endpoint).strip()
                if endpoint_name:
                    pages.add(f"page.{endpoint_name}")
    for endpoint in normalized.get("level_pages") or []:
        endpoint_name = str(endpoint).strip()
        if endpoint_name:
            pages.add(f"page.{endpoint_name}")
    return pages


def _collect_legacy_tokens(
    explicit_permissions: Any,
    effective_profile: Dict[str, Any],
) -> Set[str]:
    tokens: Set[str] = set()
    if isinstance(explicit_permissions, (list, tuple, set)):
        tokens.update({str(item).strip() for item in explicit_permissions if str(item).strip()})
    tokens.update(legacy_tokens_from_profile(effective_profile))
    return {token for token in tokens if token}


def _tokens_to_actions(tokens: Iterable[str]) -> Set[str]:
    actions: Set[str] = set()
    for token_raw in tokens:
        token = str(token_raw or "").strip()
        if not token:
            continue
        actions.add(f"action.legacy_token.{token}")
        for prefix in LEGACY_TOKEN_ACTION_PREFIXES.get(token, []):
            actions.add(prefix)
    return actions


def _derive_scopes(
    department: str,
    role: str,
    context: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    scopes: Set[str] = set()
    dept_norm = _normalize_text(department)
    role_norm = _normalize_text(role)
    for key, hinted in DEPARTMENT_SCOPE_HINTS.items():
        if key in dept_norm or key in role_norm:
            scopes.update(hinted)
    context_data = context if isinstance(context, dict) else {}
    if context_data.get("shift_id"):
        scopes.add("scope.shift.current")
    if context_data.get("cashier_session_id"):
        scopes.add("scope.cashier.session")
    if context_data.get("warehouse_id"):
        scopes.add("scope.warehouse")
    if context_data.get("finance_period"):
        scopes.add("scope.finance.period")
    if context_data.get("hotel_id"):
        scopes.add("scope.hotel")
    if role_norm == "admin":
        scopes.add("scope.global")
    return scopes


def build_grant_from_user(
    username: str,
    users: Dict[str, Any],
    department_permissions: Dict[str, Any],
    *,
    session_payload: Optional[Dict[str, Any]] = None,
    policy_registry: Any = None,
    resolved_at: Optional[str] = None,
) -> GrantSchema:
    user_data = users.get(username) if isinstance(users, dict) else None
    if not isinstance(user_data, dict):
        raise ValueError("usuário não encontrado para adaptação")

    role_raw = (session_payload or {}).get("role", user_data.get("role"))
    role_normalized = normalize_role(role_raw)
    role_level = role_level_for(role_normalized)
    department = str((session_payload or {}).get("department", user_data.get("department") or "sem_departamento")).strip()
    effective_profile = effective_profile_for_user(username, users, department_permissions)
    profile_v2_raw = user_data.get("permissions_v2")
    source_permissions_v2 = bool(_normalize_profile_v2(profile_v2_raw).get("areas") or _normalize_profile_v2(profile_v2_raw).get("level_pages"))
    pages = _profile_to_pages(effective_profile, policy_registry=policy_registry)

    explicit_permissions = (session_payload or {}).get("permissions", user_data.get("permissions"))
    tokens = _collect_legacy_tokens(explicit_permissions, effective_profile)
    actions = _tokens_to_actions(tokens)
    scopes = _derive_scopes(department, role_normalized, context=session_payload)

    grants = GrantPermissions(
        pages=sorted(pages),
        actions=sorted(actions),
        scopes=sorted(scopes),
        can_request_override=True,
        can_approve_override=role_level >= role_level_for("gerente"),
        approve_min_role="gerente" if role_level >= role_level_for("gerente") else None,
    )
    grant_user = GrantUser(
        username=str(username).strip(),
        department=department,
        role=role_normalized,
        role_level=role_level,
    )
    return GrantSchema(
        user=grant_user,
        grants=grants,
        source_permissions_v2=source_permissions_v2,
        source_legacy_tokens_used=bool(tokens),
        resolved_at=resolved_at or _now_iso(),
    )


def build_grant_from_session(
    session_payload: Dict[str, Any],
    *,
    users: Optional[Dict[str, Any]] = None,
    department_permissions: Optional[Dict[str, Any]] = None,
    policy_registry: Any = None,
    resolved_at: Optional[str] = None,
) -> GrantSchema:
    username = str((session_payload or {}).get("user") or "").strip()
    role_raw = (session_payload or {}).get("role")
    department = str((session_payload or {}).get("department") or "sem_departamento").strip()
    role_normalized = normalize_role(role_raw)
    role_level = role_level_for(role_normalized)

    users_map = users if isinstance(users, dict) else {}
    departments_map = department_permissions if isinstance(department_permissions, dict) else {}
    source_permissions_v2 = False
    effective_profile: Dict[str, Any]
    explicit_permissions = (session_payload or {}).get("permissions")

    if username and username in users_map:
        user_data = users_map.get(username) if isinstance(users_map.get(username), dict) else {}
        profile_v2_raw = user_data.get("permissions_v2")
        source_permissions_v2 = bool(_normalize_profile_v2(profile_v2_raw).get("areas") or _normalize_profile_v2(profile_v2_raw).get("level_pages"))
        effective_profile = effective_profile_for_user(username, users_map, departments_map)
        if explicit_permissions is None:
            explicit_permissions = user_data.get("permissions")
        if not role_raw:
            role_normalized = normalize_role(user_data.get("role"))
            role_level = role_level_for(role_normalized)
        if department == "sem_departamento":
            department = str(user_data.get("department") or department)
    else:
        raw_permissions_v2 = (session_payload or {}).get("permissions_v2")
        profile_v2 = _normalize_profile_v2(raw_permissions_v2)
        source_permissions_v2 = bool(profile_v2.get("areas") or profile_v2.get("level_pages"))
        if source_permissions_v2:
            effective_profile = profile_v2
        else:
            effective_profile = derive_legacy_profile(role_normalized, department, explicit_permissions)

    pages = _profile_to_pages(effective_profile, policy_registry=policy_registry)
    tokens = _collect_legacy_tokens(explicit_permissions, effective_profile)
    actions = _tokens_to_actions(tokens)
    scopes = _derive_scopes(department, role_normalized, context=session_payload)

    grants = GrantPermissions(
        pages=sorted(pages),
        actions=sorted(actions),
        scopes=sorted(scopes),
        can_request_override=True,
        can_approve_override=role_level >= role_level_for("gerente"),
        approve_min_role="gerente" if role_level >= role_level_for("gerente") else None,
    )
    grant_user = GrantUser(
        username=username or "anonymous_session",
        department=department,
        role=role_normalized,
        role_level=role_level,
    )
    return GrantSchema(
        user=grant_user,
        grants=grants,
        source_permissions_v2=source_permissions_v2,
        source_legacy_tokens_used=bool(tokens),
        resolved_at=resolved_at or _now_iso(),
    )
