from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random
from typing import Any, Callable, Dict, Optional, Tuple

from app.services.authz.runtime_flags import RuntimeFlags


CRITICAL_MODULES = {
    "admin",
    "finance",
    "financial_audit",
    "auth",
    "hr",
}

FORCED_LOG_CLASSIFICATIONS = {"sensivel", "destrutiva", "sistemica"}


@dataclass(frozen=True)
class AuditEmitResult:
    emitted: bool
    event_type: str
    reason: str
    error: str = ""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_str(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return text
    return default


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _extract_module(endpoint: str) -> str:
    endpoint_name = _safe_str(endpoint, "")
    if "." in endpoint_name:
        return endpoint_name.split(".", 1)[0]
    return endpoint_name


def _extract_decision_and_reason(decision_payload: Any) -> Tuple[str, str]:
    decision = _safe_str(getattr(decision_payload, "decision", None), "")
    reason_code = _safe_str(getattr(decision_payload, "reason_code", None), "")
    if not decision and isinstance(decision_payload, dict):
        decision = _safe_str(decision_payload.get("decision"), "")
    if not reason_code and isinstance(decision_payload, dict):
        reason_code = _safe_str(decision_payload.get("reason_code"), "")
    return decision, reason_code


def build_authz_decision_event(
    *,
    decision_payload: Any,
    request_context: Optional[Dict[str, Any]] = None,
    grants_payload: Any = None,
    policy_payload: Any = None,
) -> Dict[str, Any]:
    context = _to_dict(request_context)
    decision, reason_code = _extract_decision_and_reason(decision_payload)
    endpoint = _safe_str(context.get("endpoint"), _safe_str(getattr(policy_payload, "endpoint", None), "unknown.endpoint"))
    action = _safe_str(context.get("action"), _safe_str(context.get("method"), "GET"))
    policy_version = _safe_str(
        getattr(decision_payload, "policy_version", None),
        _safe_str(context.get("policy_version"), _safe_str(getattr(policy_payload, "policy_version", None), "unknown")),
    )
    policy_hash = _safe_str(
        getattr(decision_payload, "policy_hash", None),
        _safe_str(context.get("policy_hash"), _safe_str(getattr(policy_payload, "policy_hash", None), "unknown")),
    )
    required = _to_dict(getattr(decision_payload, "required", None))
    missing = _to_dict(getattr(decision_payload, "missing", None))
    if isinstance(decision_payload, dict):
        required = _to_dict(decision_payload.get("required")) or required
        missing = _to_dict(decision_payload.get("missing")) or missing

    grant_user = getattr(grants_payload, "user", None)
    role = _safe_str(getattr(grant_user, "role", None), _safe_str(context.get("role"), "unknown"))
    department = _safe_str(getattr(grant_user, "department", None), _safe_str(context.get("department"), "unknown"))
    executor_user = _safe_str(getattr(grant_user, "username", None), _safe_str(context.get("executor_user"), "unknown"))
    classification = _safe_str(
        context.get("classification"),
        _safe_str(getattr(getattr(policy_payload, "sensitivity", None), "classification", None), "operacional"),
    )

    return {
        "event_type": "authz_decision",
        "decision": decision or "UNKNOWN",
        "reason_code": reason_code or "AUTHZ_POLICY_INVALID_SCHEMA",
        "action": action,
        "endpoint": endpoint,
        "executor_user": executor_user,
        "role": role,
        "department": department,
        "request_id": _safe_str(context.get("request_id"), _safe_str(getattr(decision_payload, "request_id", None), "")),
        "timestamp": _safe_str(context.get("timestamp"), _now_iso()),
        "ip": _safe_str(context.get("ip"), "unknown"),
        "user_agent": _safe_str(context.get("user_agent"), "unknown"),
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "required": required,
        "missing": missing,
        "classification": classification,
        "module": _extract_module(endpoint),
    }


def build_authz_override_event(
    *,
    decision_event: Dict[str, Any],
    approver_user: str,
    reason: str,
    result: str,
    ttl_seconds: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    base = _to_dict(decision_event)
    return {
        "event_type": "authz_override",
        "action": _safe_str(base.get("action"), "UNKNOWN"),
        "endpoint": _safe_str(base.get("endpoint"), "unknown.endpoint"),
        "executor_user": _safe_str(base.get("executor_user"), "unknown"),
        "approver_user": _safe_str(approver_user, "unknown"),
        "reason": _safe_str(reason, "sem_motivo"),
        "result": _safe_str(result, "unknown"),
        "timestamp": _safe_str(timestamp, _now_iso()),
        "request_id": _safe_str(base.get("request_id"), ""),
        "policy_version": _safe_str(base.get("policy_version"), "unknown"),
        "policy_hash": _safe_str(base.get("policy_hash"), "unknown"),
        "ttl_seconds": int(ttl_seconds) if ttl_seconds is not None else None,
    }


def should_log_authz_decision(event: Dict[str, Any], runtime_flags: RuntimeFlags, *, random_value: Optional[float] = None) -> bool:
    payload = _to_dict(event)
    decision = _safe_str(payload.get("decision"), "").upper()
    classification = _safe_str(payload.get("classification"), "operacional").lower()
    module_name = _safe_str(payload.get("module"), _extract_module(_safe_str(payload.get("endpoint"), "")))

    if decision in ("DENY", "REQUIRE_OVERRIDE"):
        return True
    if classification in FORCED_LOG_CLASSIFICATIONS:
        return True
    if module_name in CRITICAL_MODULES:
        return True
    if decision != "ALLOW":
        return True

    if not runtime_flags.allow_sampling_enabled:
        return True
    if runtime_flags.should_log_allow_full(module_name):
        return True

    value = random.random() if random_value is None else float(random_value)
    return value <= float(runtime_flags.allow_sampling_rate)


def emit_authz_decision_event(
    *,
    decision_payload: Any,
    runtime_flags: RuntimeFlags,
    request_context: Optional[Dict[str, Any]] = None,
    grants_payload: Any = None,
    policy_payload: Any = None,
    sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    random_value: Optional[float] = None,
) -> AuditEmitResult:
    try:
        event = build_authz_decision_event(
            decision_payload=decision_payload,
            request_context=request_context,
            grants_payload=grants_payload,
            policy_payload=policy_payload,
        )
        if not should_log_authz_decision(event, runtime_flags, random_value=random_value):
            return AuditEmitResult(emitted=False, event_type="authz_decision", reason="sampled_out")
        if sink is not None:
            sink(event)
        return AuditEmitResult(emitted=True, event_type="authz_decision", reason="emitted")
    except Exception as exc:
        return AuditEmitResult(emitted=False, event_type="authz_decision", reason="emit_error", error=_safe_str(exc, "erro"))


def emit_authz_override_event(
    *,
    decision_event: Dict[str, Any],
    approver_user: str,
    reason: str,
    result: str,
    sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ttl_seconds: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> AuditEmitResult:
    try:
        event = build_authz_override_event(
            decision_event=decision_event,
            approver_user=approver_user,
            reason=reason,
            result=result,
            ttl_seconds=ttl_seconds,
            timestamp=timestamp,
        )
        if sink is not None:
            sink(event)
        return AuditEmitResult(emitted=True, event_type="authz_override", reason="emitted")
    except Exception as exc:
        return AuditEmitResult(emitted=False, event_type="authz_override", reason="emit_error", error=_safe_str(exc, "erro"))
