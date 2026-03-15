from __future__ import annotations

from typing import Any, Dict, List, Optional

from app import create_app
from app.services.authz.policy_decorators import get_policy_metadata
from app.services.authz.policy_registry import PolicyRegistry


CRITICAL_KEYWORDS = ("refund", "close_day", "transfer", "adjustment", "reversal")


def discover_endpoints_by_prefix(area_prefix: str = "finance", app: Any = None) -> List[Dict[str, Any]]:
    prefix = str(area_prefix or "").strip().strip(".")
    endpoint_prefix = f"{prefix}."
    flask_app = app if app is not None else create_app()
    rows: List[Dict[str, Any]] = []
    for rule in flask_app.url_map.iter_rules():
        endpoint = str(getattr(rule, "endpoint", "") or "").strip()
        if not endpoint.startswith(endpoint_prefix):
            continue
        methods = sorted([method for method in (rule.methods or set()) if method not in ("HEAD", "OPTIONS")])
        operation_type = classify_operation(endpoint, methods)
        rows.append(
            {
                "endpoint": endpoint,
                "path": str(rule.rule),
                "methods": methods,
                "handler": endpoint,
                "operation_type": operation_type,
                "is_critical": bool(_is_critical_operation(endpoint)),
            }
        )
    rows.sort(key=lambda item: (item["endpoint"], item["path"]))
    return rows


def classify_operation(endpoint: str, methods: List[str]) -> str:
    endpoint_name = str(endpoint or "").strip().lower()
    if _is_critical_operation(endpoint_name):
        return "critical"
    methods_upper = [str(item or "").strip().upper() for item in (methods or []) if str(item or "").strip()]
    if "DELETE" in methods_upper or "delete" in endpoint_name:
        return "delete"
    if "PUT" in methods_upper or "PATCH" in methods_upper or "update" in endpoint_name:
        return "update"
    if "POST" in methods_upper:
        return "create"
    if "GET" in methods_upper:
        return "view"
    return "view"


def _is_critical_operation(endpoint: str) -> bool:
    endpoint_name = str(endpoint or "").strip().lower()
    return any(keyword in endpoint_name for keyword in CRITICAL_KEYWORDS)


def check_policy_coverage(area_prefix: str = "finance", app: Any = None) -> Dict[str, Any]:
    prefix = str(area_prefix or "").strip().strip(".")
    endpoint_prefix = f"{prefix}."
    flask_app = app if app is not None else create_app()
    registry = PolicyRegistry.from_files()
    endpoints: List[str] = sorted(
        {
            str(rule.endpoint).strip()
            for rule in flask_app.url_map.iter_rules()
            if str(getattr(rule, "endpoint", "") or "").startswith(endpoint_prefix)
        }
    )
    covered: List[str] = [endpoint for endpoint in endpoints if registry.get_policy(endpoint) is not None]
    missing: List[str] = [endpoint for endpoint in endpoints if endpoint not in set(covered)]
    total = len(endpoints)
    covered_total = len(covered)
    coverage_ratio = float(covered_total / total) if total > 0 else 1.0
    return {
        "area_prefix": prefix,
        "finance_endpoints_total": total,
        "finance_policy_covered": covered_total,
        "finance_policy_missing": len(missing),
        "coverage_ratio": coverage_ratio,
        "missing_endpoints": missing,
        "endpoints": discover_endpoints_by_prefix(prefix, flask_app),
    }


def build_global_policy_coverage_report(app: Any = None, registry: Optional[PolicyRegistry] = None) -> Dict[str, Any]:
    flask_app = app if app is not None else create_app()
    policy_registry = registry if registry is not None else PolicyRegistry.from_files()
    flask_endpoints = sorted(
        {
            str(getattr(rule, "endpoint", "") or "").strip()
            for rule in flask_app.url_map.iter_rules()
            if str(getattr(rule, "endpoint", "") or "").strip()
        }
    )
    ignored: List[str] = []
    public_marked: List[str] = []
    checked: List[str] = []
    missing: List[str] = []
    for endpoint in flask_endpoints:
        if endpoint == "static" or endpoint.endswith(".static"):
            ignored.append(endpoint)
            continue
        if "health" in endpoint.lower():
            ignored.append(endpoint)
            continue
        view_func = flask_app.view_functions.get(endpoint)
        is_public_by_decorator = False
        if callable(view_func):
            metadata = get_policy_metadata(view_func)
            is_public_by_decorator = bool(metadata.get("public"))
        is_public_by_registry = policy_registry.is_public_endpoint(endpoint)
        if is_public_by_decorator or is_public_by_registry:
            public_marked.append(endpoint)
            continue
        checked.append(endpoint)
        if policy_registry.get_policy(endpoint) is None:
            missing.append(endpoint)
    registry_only = sorted(
        [
            endpoint
            for endpoint in policy_registry.policies_by_endpoint.keys()
            if endpoint not in set(flask_endpoints)
        ]
    )
    return {
        "flask_endpoints_total": len(flask_endpoints),
        "checked_endpoints_total": len(checked),
        "covered_endpoints_total": len(checked) - len(missing),
        "missing_endpoints_total": len(missing),
        "ignored_endpoints": sorted(ignored),
        "public_endpoints_ignored": sorted(public_marked),
        "checked_endpoints": sorted(checked),
        "missing_endpoints": sorted(missing),
        "registry_only_endpoints": registry_only,
    }
