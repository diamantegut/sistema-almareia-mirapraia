from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app import create_app
from app.services.authz.policy_coverage import CRITICAL_KEYWORDS, classify_operation, discover_endpoints_by_prefix
from app.services.authz.policy_registry import DEFAULT_POLICY_FILE, PolicyRegistry
from app.services.authz.schemas import role_level_for


ROLE_NOT_IN_PATTERN = re.compile(r"session\.get\('role'\)\s+not\s+in\s+\[([^\]]+)\]")
ROLE_NOT_EQ_PATTERN = re.compile(r"session\.get\('role'\)\s*!=\s*['\"]([a-zA-Z_]+)['\"]")
PERMISSION_TOKEN_PATTERN = re.compile(r"['\"]([a-zA-Z0-9_\.:-]+)['\"]\s+not\s+in\s+session\.get\('permissions'")

SUPPORTED_ROLES = {"admin", "gerente", "supervisor", "colaborador"}
ROLE_FALLBACK_ORDER = ("admin", "gerente", "supervisor", "colaborador")


def scan_manual_authorization_patterns(base_dir: Optional[Path | str] = None) -> List[Dict[str, Any]]:
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[3] / "app"
    results: List[Dict[str, Any]] = []
    keywords = (
        "session.get('role')",
        "session.get(\"role\")",
        "has_permission",
        "has_role",
        "is_admin",
        "is_manager",
        "current_user",
        "request.user",
        "session.get('permissions')",
        "session.get(\"permissions\")",
    )
    for file_path in root.rglob("*.py"):
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines, start=1):
            if any(item in line for item in keywords):
                results.append(
                    {
                        "file": str(file_path),
                        "line": index,
                        "snippet": line.strip(),
                    }
                )
    return results


def build_endpoint_permission_map(area_prefix: str = "finance", app: Any = None) -> Dict[str, Dict[str, Any]]:
    flask_app = app if app is not None else create_app()
    endpoints = discover_endpoints_by_prefix(area_prefix=area_prefix, app=flask_app)
    mapping: Dict[str, Dict[str, Any]] = {}
    for row in endpoints:
        endpoint = str(row.get("endpoint") or "").strip()
        if not endpoint:
            continue
        view_func = flask_app.view_functions.get(endpoint)
        source_text = ""
        if view_func is not None:
            try:
                source_text = inspect.getsource(view_func)
            except Exception:
                source_text = ""
        allowed_roles, permission_tokens = _extract_authorization_constraints(source_text)
        critical = bool(row.get("is_critical")) or _contains_critical_keyword(endpoint) or _contains_critical_keyword(str(row.get("path") or ""))
        methods = [str(item).strip().upper() for item in (row.get("methods") or []) if str(item).strip()]
        mapping[endpoint] = {
            "endpoint": endpoint,
            "path": str(row.get("path") or ""),
            "methods": methods,
            "handler": str(row.get("handler") or endpoint),
            "operation_type": classify_operation(endpoint, methods),
            "allowed_roles": sorted(list(allowed_roles)),
            "permission_tokens": sorted(list(permission_tokens)),
            "is_critical": critical,
            "required_minimum_role": _derive_minimum_role(allowed_roles, critical),
            "required_scopes_any": _derive_scopes_any(methods, critical),
            "required_scopes_all": ["scope.department"],
        }
    return mapping


def generate_policies_from_endpoint_map(
    endpoint_permission_map: Dict[str, Dict[str, Any]],
    *,
    policy_version: str,
    policy_hash: str,
) -> List[Dict[str, Any]]:
    policies: List[Dict[str, Any]] = []
    for endpoint, info in sorted(endpoint_permission_map.items()):
        methods = [str(item).strip().upper() for item in (info.get("methods") or []) if str(item).strip()]
        minimum_role = str(info.get("required_minimum_role") or "supervisor")
        minimum_role_level = role_level_for(minimum_role)
        critical = bool(info.get("is_critical"))
        write_methods = [item for item in methods if item in ("POST", "PUT", "PATCH", "DELETE")]
        action_map = {method: f"action.finance.{endpoint.split('.', 1)[1]}.{method.lower()}" for method in write_methods}
        override_required = critical
        sensitivity_class = "destrutiva" if critical else "sensivel"
        policies.append(
            {
                "endpoint": endpoint,
                "area": "financeiro",
                "public": False,
                "page": f"page.finance.{endpoint.split('.', 1)[1]}",
                "action": {
                    "required": bool(action_map),
                    "name_by_method": action_map,
                },
                "override": {
                    "required": override_required,
                    "approver_minimum_role": "gerente" if override_required else None,
                    "reason_required": True,
                    "ttl_seconds": 300,
                },
                "scope": {
                    "scopes_any": list(info.get("required_scopes_any") or []),
                    "scopes_all": list(info.get("required_scopes_all") or []),
                },
                "minimum_role": minimum_role,
                "minimum_role_level": minimum_role_level,
                "sensitivity": {
                    "classification": sensitivity_class,
                    "is_sensitive": True,
                    "is_critical": critical,
                    "is_destructive": critical,
                    "is_systemic": False,
                },
                "policy_status": "active",
                "policy_version": policy_version,
                "policy_hash": policy_hash,
            }
        )
    return policies


def compare_manual_permissions_with_registry(area_prefix: str = "finance", app: Any = None) -> List[Dict[str, Any]]:
    flask_app = app if app is not None else create_app()
    endpoint_permission_map = build_endpoint_permission_map(area_prefix=area_prefix, app=flask_app)
    registry = PolicyRegistry.from_files()
    conflicts: List[Dict[str, Any]] = []
    for endpoint, info in sorted(endpoint_permission_map.items()):
        policy = registry.get_policy(endpoint)
        if policy is None:
            conflicts.append(
                {
                    "endpoint": endpoint,
                    "type": "missing_policy",
                    "manual_required_role": info.get("required_minimum_role"),
                    "manual_critical": info.get("is_critical"),
                }
            )
            continue
        manual_role_level = role_level_for(str(info.get("required_minimum_role") or "colaborador"))
        if int(getattr(policy, "minimum_role_level", 1)) < manual_role_level:
            conflicts.append(
                {
                    "endpoint": endpoint,
                    "type": "role_weaker_than_manual",
                    "policy_minimum_role_level": int(getattr(policy, "minimum_role_level", 1)),
                    "manual_minimum_role_level": manual_role_level,
                }
            )
        if bool(info.get("is_critical")) and not bool(getattr(getattr(policy, "override", None), "required", False)):
            conflicts.append(
                {
                    "endpoint": endpoint,
                    "type": "critical_without_override",
                    "policy_override_required": bool(getattr(getattr(policy, "override", None), "required", False)),
                    "manual_critical": True,
                }
            )
    return conflicts


def sync_finance_policies_from_manual_checks(policy_file: Optional[Path | str] = None, app: Any = None) -> Dict[str, Any]:
    flask_app = app if app is not None else create_app()
    path = Path(policy_file) if policy_file is not None else DEFAULT_POLICY_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    policies = payload.get("policies") if isinstance(payload.get("policies"), list) else []
    policy_version = str(payload.get("policy_version") or "").strip()
    policy_hash = str(payload.get("policy_hash") or "").strip()
    generated = generate_policies_from_endpoint_map(
        build_endpoint_permission_map(area_prefix="finance", app=flask_app),
        policy_version=policy_version,
        policy_hash=policy_hash,
    )
    by_endpoint: Dict[str, Dict[str, Any]] = {}
    for item in policies:
        endpoint = str((item or {}).get("endpoint") or "").strip()
        if endpoint:
            by_endpoint[endpoint] = item
    created = 0
    updated = 0
    for item in generated:
        endpoint = str(item.get("endpoint") or "").strip()
        if not endpoint:
            continue
        existing = by_endpoint.get(endpoint)
        if existing is None:
            policies.append(item)
            created += 1
            continue
        merged = _merge_policy_conservative(existing, item)
        if merged != existing:
            for key, value in merged.items():
                existing[key] = value
            updated += 1
    payload["policies"] = policies
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"created": created, "updated": updated, "total_generated": len(generated)}


def _extract_authorization_constraints(source_text: str) -> Tuple[Set[str], Set[str]]:
    roles: Set[str] = set()
    permissions: Set[str] = set()
    if not source_text:
        return roles, permissions
    for match in ROLE_NOT_IN_PATTERN.finditer(source_text):
        raw = str(match.group(1) or "").strip()
        items = [item.strip().strip("'").strip('"').lower() for item in raw.split(",") if item.strip()]
        for item in items:
            if item in SUPPORTED_ROLES:
                roles.add(item)
    for match in ROLE_NOT_EQ_PATTERN.finditer(source_text):
        role = str(match.group(1) or "").strip().lower()
        if role in SUPPORTED_ROLES:
            roles.add(role)
    for match in PERMISSION_TOKEN_PATTERN.finditer(source_text):
        token = str(match.group(1) or "").strip().lower()
        if token:
            permissions.add(token)
    return roles, permissions


def _derive_minimum_role(allowed_roles: Set[str], is_critical: bool) -> str:
    if is_critical:
        return "gerente"
    if not allowed_roles:
        return "supervisor"
    if "admin" in allowed_roles and len(allowed_roles) == 1:
        return "admin"
    if "gerente" in allowed_roles and not ("supervisor" in allowed_roles or "colaborador" in allowed_roles):
        return "gerente"
    if "supervisor" in allowed_roles:
        return "supervisor"
    if "colaborador" in allowed_roles:
        return "colaborador"
    if "gerente" in allowed_roles:
        return "gerente"
    for role in ROLE_FALLBACK_ORDER:
        if role in allowed_roles:
            return role
    return "supervisor"


def _derive_scopes_any(methods: List[str], is_critical: bool) -> List[str]:
    methods_upper = [str(item or "").strip().upper() for item in (methods or []) if str(item or "").strip()]
    if is_critical:
        return ["scope.finance.write"]
    if any(method in ("POST", "PUT", "PATCH", "DELETE") for method in methods_upper):
        return ["scope.finance.write"]
    return ["scope.finance.read"]


def _contains_critical_keyword(value: str) -> bool:
    text = str(value or "").strip().lower()
    return any(keyword in text for keyword in CRITICAL_KEYWORDS + ("close", "delete"))


def _merge_policy_conservative(existing: Dict[str, Any], generated: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(existing)
    existing_level = int(existing.get("minimum_role_level", 1) or 1)
    generated_level = int(generated.get("minimum_role_level", 1) or 1)
    if generated_level > existing_level:
        out["minimum_role"] = generated.get("minimum_role")
        out["minimum_role_level"] = generated_level
    existing_override = existing.get("override") if isinstance(existing.get("override"), dict) else {}
    generated_override = generated.get("override") if isinstance(generated.get("override"), dict) else {}
    if bool(generated_override.get("required", False)) and not bool(existing_override.get("required", False)):
        out["override"] = generated_override
    existing_scope = existing.get("scope") if isinstance(existing.get("scope"), dict) else {}
    generated_scope = generated.get("scope") if isinstance(generated.get("scope"), dict) else {}
    out["scope"] = {
        "scopes_any": sorted(list(set(existing_scope.get("scopes_any") or []) | set(generated_scope.get("scopes_any") or []))),
        "scopes_all": sorted(list(set(existing_scope.get("scopes_all") or []) | set(generated_scope.get("scopes_all") or []))),
    }
    return out
