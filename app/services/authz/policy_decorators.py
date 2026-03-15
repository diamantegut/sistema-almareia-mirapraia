from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from app.services.authz.schemas import role_level_for


POLICY_METADATA_ATTR = "__authz_policy_metadata__"
POLICY_CONFLICTS_ATTR = "__authz_policy_conflicts__"


def _copy_list(values: Any) -> List[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    items = [str(item).strip() for item in values if str(item).strip()]
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _current_metadata(func: Callable[..., Any]) -> Dict[str, Any]:
    existing = getattr(func, POLICY_METADATA_ATTR, None)
    if isinstance(existing, dict):
        action_raw = existing.get("action") if isinstance(existing.get("action"), dict) else {}
        scope_raw = existing.get("scope") if isinstance(existing.get("scope"), dict) else {}
        override_raw = existing.get("override") if isinstance(existing.get("override"), dict) else {}
        return {
            "public": bool(existing.get("public", False)),
            "page": str(existing.get("page") or "").strip() or None,
            "action": {
                "required": bool(action_raw.get("required", False)),
                "name_by_method": dict(action_raw.get("name_by_method") or {}),
            },
            "scope": {
                "scopes_any": _copy_list(scope_raw.get("scopes_any")),
                "scopes_all": _copy_list(scope_raw.get("scopes_all")),
            },
            "override": {
                "required": bool(override_raw.get("required", False)),
                "approver_minimum_role": override_raw.get("approver_minimum_role"),
                "reason_required": bool(override_raw.get("reason_required", True)),
                "ttl_seconds": int(override_raw.get("ttl_seconds", 300)),
            },
            "minimum_role": str(existing.get("minimum_role") or "").strip() or None,
            "minimum_role_level": int(existing.get("minimum_role_level", 0) or 0) or None,
        }
    return {
        "public": False,
        "page": None,
        "action": {"required": False, "name_by_method": {}},
        "scope": {"scopes_any": [], "scopes_all": []},
        "override": {"required": False, "approver_minimum_role": None, "reason_required": True, "ttl_seconds": 300},
        "minimum_role": None,
        "minimum_role_level": None,
    }


def _append_conflict(func: Callable[..., Any], message: str) -> None:
    conflicts = getattr(func, POLICY_CONFLICTS_ATTR, None)
    if not isinstance(conflicts, list):
        conflicts = []
    if message not in conflicts:
        conflicts.append(message)
    setattr(func, POLICY_CONFLICTS_ATTR, conflicts)


def _attach_metadata(func: Callable[..., Any], updater: Callable[[Dict[str, Any]], None]) -> Callable[..., Any]:
    metadata = _current_metadata(func)
    updater(metadata)
    setattr(func, POLICY_METADATA_ATTR, metadata)
    if getattr(func, POLICY_CONFLICTS_ATTR, None) is None:
        setattr(func, POLICY_CONFLICTS_ATTR, [])
    return func


def get_policy_metadata(func: Callable[..., Any]) -> Dict[str, Any]:
    return _current_metadata(func)


def get_policy_metadata_conflicts(func: Callable[..., Any]) -> List[str]:
    conflicts = getattr(func, POLICY_CONFLICTS_ATTR, None)
    if isinstance(conflicts, list):
        return list(conflicts)
    return []


def compare_metadata_with_registry(func: Callable[..., Any], registry_policy: Any) -> List[str]:
    metadata = get_policy_metadata(func)
    if registry_policy is None:
        return []
    conflicts: List[str] = []
    if metadata.get("public") != bool(getattr(registry_policy, "public", False)):
        conflicts.append("public")
    if metadata.get("page") and metadata.get("page") != str(getattr(registry_policy, "page", "") or ""):
        conflicts.append("page")
    if metadata.get("minimum_role") and metadata.get("minimum_role") != str(getattr(registry_policy, "minimum_role", "") or ""):
        conflicts.append("minimum_role")
    return conflicts


def public_endpoint() -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            metadata["public"] = True
        return _attach_metadata(func, updater)
    return decorator


def policy_page(page: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            value = str(page or "").strip()
            if not value:
                _append_conflict(func, "policy_page vazio")
                return
            if metadata.get("page") and metadata.get("page") != value:
                _append_conflict(func, f"policy_page conflitante: {metadata.get('page')} vs {value}")
            metadata["page"] = value
        return _attach_metadata(func, updater)
    return decorator


def policy_action(
    *,
    method: Optional[str] = None,
    action_name: Optional[str] = None,
    name_by_method: Optional[Dict[str, str]] = None,
    required: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            action_meta = metadata.setdefault("action", {"required": False, "name_by_method": {}})
            action_meta["required"] = bool(required)
            current_map = action_meta.setdefault("name_by_method", {})
            input_map: Dict[str, str] = {}
            if isinstance(name_by_method, dict):
                for key, value in name_by_method.items():
                    method_key = str(key or "").strip().upper()
                    action_value = str(value or "").strip()
                    if method_key and action_value:
                        input_map[method_key] = action_value
            if method and action_name:
                method_key = str(method).strip().upper()
                action_value = str(action_name).strip()
                if method_key and action_value:
                    input_map[method_key] = action_value
            for method_key, action_value in input_map.items():
                existing_value = current_map.get(method_key)
                if existing_value and existing_value != action_value:
                    _append_conflict(func, f"policy_action conflitante para método {method_key}")
                current_map[method_key] = action_value
        return _attach_metadata(func, updater)
    return decorator


def policy_scope(
    *,
    scopes_any: Optional[List[str]] = None,
    scopes_all: Optional[List[str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            scope_meta = metadata.setdefault("scope", {"scopes_any": [], "scopes_all": []})
            merged_any = _copy_list((scope_meta.get("scopes_any") or []) + (scopes_any or []))
            merged_all = _copy_list((scope_meta.get("scopes_all") or []) + (scopes_all or []))
            scope_meta["scopes_any"] = merged_any
            scope_meta["scopes_all"] = merged_all
        return _attach_metadata(func, updater)
    return decorator


def policy_override(
    *,
    required: bool = True,
    approver_minimum_role: Optional[str] = None,
    reason_required: bool = True,
    ttl_seconds: int = 300,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            override_meta = metadata.setdefault(
                "override",
                {"required": False, "approver_minimum_role": None, "reason_required": True, "ttl_seconds": 300},
            )
            override_meta["required"] = bool(required)
            override_meta["approver_minimum_role"] = str(approver_minimum_role or "").strip() or None
            override_meta["reason_required"] = bool(reason_required)
            override_meta["ttl_seconds"] = int(ttl_seconds)
            if override_meta["ttl_seconds"] < 30 or override_meta["ttl_seconds"] > 900:
                _append_conflict(func, "policy_override ttl_seconds fora de contrato")
        return _attach_metadata(func, updater)
    return decorator


def policy_min_role(minimum_role: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def updater(metadata: Dict[str, Any]) -> None:
            role = str(minimum_role or "").strip().lower()
            if not role:
                _append_conflict(func, "policy_min_role vazio")
                return
            try:
                level = role_level_for(role)
            except ValueError:
                _append_conflict(func, f"policy_min_role inválido: {role}")
                return
            if metadata.get("minimum_role") and metadata.get("minimum_role") != role:
                _append_conflict(func, f"policy_min_role conflitante: {metadata.get('minimum_role')} vs {role}")
            metadata["minimum_role"] = role
            metadata["minimum_role_level"] = level
        return _attach_metadata(func, updater)
    return decorator


def with_policy_metadata(metadata: Dict[str, Any]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any):
            return func(*args, **kwargs)
        def updater(current: Dict[str, Any]) -> None:
            for key, value in (metadata or {}).items():
                current[key] = value
        wrapped_func = _attach_metadata(wrapped, updater)
        return wrapped_func
    return decorator
