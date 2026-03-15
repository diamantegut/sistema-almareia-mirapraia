from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

from app.services.authz.reason_codes import (
    ALL_REASON_CODES,
    is_valid_reason_code,
)
from app.services.authz.runtime_flags import RuntimeFlags
from app.services.authz.trace_recorder import finish_trace, record_step, start_trace
from app.services.authz.schemas import (
    ActionPolicy,
    DecisionSchema,
    GrantSchema,
    OverridePolicy,
    PolicySchema,
    ScopePolicy,
    SensitivityPolicy,
    role_level_for,
)


SENSITIVE_CLASSIFICATIONS = {"sensivel", "destrutiva", "sistemica"}


@dataclass(frozen=True)
class EvaluationInput:
    request_context: Dict[str, Any]
    policy: Optional[PolicySchema]
    grants: Optional[GrantSchema]
    runtime_flags: RuntimeFlags


def _is_sensitive(policy: Optional[PolicySchema], request_context: Dict[str, Any]) -> bool:
    if policy is not None:
        return policy.sensitivity.classification in SENSITIVE_CLASSIFICATIONS
    return bool(request_context.get("policy_missing_sensitive", False))


def _mode_decision(runtime_flags: RuntimeFlags, *, sensitive: bool, deny_code: str, allow_code: str) -> str:
    if runtime_flags.is_shadow_mode:
        return "ALLOW"
    if runtime_flags.is_warn_enforce_mode:
        if runtime_flags.warn_enforce_sensitive_only:
            return "DENY" if sensitive else "ALLOW"
        return "DENY"
    if runtime_flags.is_enforce_mode:
        return "DENY"
    return "DENY"


def _coerce_policy(policy: Any) -> Tuple[Optional[PolicySchema], Optional[str]]:
    if policy is None:
        return None, None
    if isinstance(policy, PolicySchema):
        return policy, None
    if isinstance(policy, dict):
        try:
            action_raw = policy.get("action") if isinstance(policy.get("action"), dict) else {}
            override_raw = policy.get("override") if isinstance(policy.get("override"), dict) else {}
            scope_raw = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
            sensitivity_raw = policy.get("sensitivity") if isinstance(policy.get("sensitivity"), dict) else {}
            parsed = PolicySchema(
                endpoint=policy.get("endpoint"),
                area=policy.get("area"),
                public=bool(policy.get("public", False)),
                page=policy.get("page"),
                action=ActionPolicy(
                    required=bool(action_raw.get("required", False)),
                    name_by_method=action_raw.get("name_by_method", {}) or {},
                ),
                override=OverridePolicy(
                    required=bool(override_raw.get("required", False)),
                    approver_minimum_role=override_raw.get("approver_minimum_role"),
                    reason_required=bool(override_raw.get("reason_required", True)),
                    ttl_seconds=override_raw.get("ttl_seconds", 300),
                ),
                scope=ScopePolicy(
                    scopes_any=scope_raw.get("scopes_any", []) or [],
                    scopes_all=scope_raw.get("scopes_all", []) or [],
                ),
                minimum_role=policy.get("minimum_role", "colaborador"),
                minimum_role_level=policy.get("minimum_role_level", 1),
                sensitivity=SensitivityPolicy(
                    classification=sensitivity_raw.get("classification", "operacional"),
                    is_sensitive=bool(sensitivity_raw.get("is_sensitive", False)),
                    is_critical=bool(sensitivity_raw.get("is_critical", False)),
                    is_destructive=bool(sensitivity_raw.get("is_destructive", False)),
                    is_systemic=bool(sensitivity_raw.get("is_systemic", False)),
                ),
                policy_status=policy.get("policy_status", "active"),
                policy_version=policy.get("policy_version"),
                policy_hash=policy.get("policy_hash"),
            )
            return parsed, None
        except ValueError:
            return None, "AUTHZ_POLICY_INVALID_SCHEMA"
    return None, "AUTHZ_POLICY_INVALID_SCHEMA"


def _normalize_policy_version_hash(policy: Optional[PolicySchema], request_context: Dict[str, Any]) -> Tuple[str, str]:
    policy_version = str(getattr(policy, "policy_version", "") or request_context.get("policy_version") or "unknown").strip()
    policy_hash = str(getattr(policy, "policy_hash", "") or request_context.get("policy_hash") or "unknown").strip()
    if not policy_version:
        policy_version = "unknown"
    if not policy_hash:
        policy_hash = "unknown"
    return policy_version, policy_hash


def _build_decision(
    *,
    decision: str,
    reason_code: str,
    policy: Optional[PolicySchema],
    request_context: Dict[str, Any],
    required: Optional[Dict[str, Any]] = None,
    missing: Optional[Dict[str, Any]] = None,
    trace: Optional[list[Dict[str, Any]]] = None,
) -> DecisionSchema:
    if reason_code not in ALL_REASON_CODES and not is_valid_reason_code(reason_code):
        raise ValueError(f"reason_code não oficial: {reason_code}")
    policy_version, policy_hash = _normalize_policy_version_hash(policy, request_context)
    return DecisionSchema(
        decision=decision,
        reason_code=reason_code,
        required=required or {},
        missing=missing or {},
        policy_version=policy_version,
        policy_hash=policy_hash,
        request_id=str(request_context.get("request_id") or "").strip(),
        trace=list(trace or []),
    )


def _trace_enabled(request_context: Dict[str, Any]) -> bool:
    value = request_context.get("trace_enabled", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _trace_step(trace_state: Dict[str, Any], step: str, input_data: Optional[Dict[str, Any]] = None, result: Optional[Dict[str, Any]] = None) -> None:
    record_step(trace_state, step=step, input_data=input_data, result=result)


def _decision_with_trace(
    *,
    trace_state: Dict[str, Any],
    decision: str,
    reason_code: str,
    policy: Optional[PolicySchema],
    request_context: Dict[str, Any],
    required: Optional[Dict[str, Any]] = None,
    missing: Optional[Dict[str, Any]] = None,
) -> DecisionSchema:
    trace_payload = finish_trace(trace_state, decision=decision, reason_code=reason_code)
    return _build_decision(
        decision=decision,
        reason_code=reason_code,
        policy=policy,
        request_context=request_context,
        required=required,
        missing=missing,
        trace=trace_payload,
    )


def _has_page(grants: GrantSchema, required_page: str, policy: Optional[PolicySchema] = None) -> bool:
    pages = set(grants.grants.pages)
    if required_page in pages:
        return True
    page_parts = required_page.split(".")
    if len(page_parts) >= 3:
        area_wildcard = f"page.{page_parts[1]}.*"
        if area_wildcard in pages:
            return True
    if policy is not None:
        policy_area_wildcard = f"page.{policy.area}.*"
        if policy_area_wildcard in pages:
            return True
    return False


def _required_action_for_method(policy: PolicySchema, method: str) -> Optional[str]:
    if not policy.action.required:
        return None
    method_norm = str(method or "").strip().upper()
    return str(policy.action.name_by_method.get(method_norm) or "").strip() or None


def _transitional_wildcard_allowed(required_action: str, policy: PolicySchema, request_context: Dict[str, Any]) -> bool:
    if not bool(request_context.get("allow_legacy_wildcard_transitional", False)):
        return False
    if policy.sensitivity.classification in SENSITIVE_CLASSIFICATIONS:
        return False
    if policy.override.required:
        return False
    return required_action.startswith("action.")


def _has_action(grants: GrantSchema, required_action: str, policy: PolicySchema, request_context: Dict[str, Any]) -> bool:
    actions = set(grants.grants.actions)
    if required_action in actions:
        return True
    if not _transitional_wildcard_allowed(required_action, policy, request_context):
        return False
    parts = required_action.split(".")
    if len(parts) < 3:
        return False
    module_name = parts[1]
    return f"action.{module_name}.*" in actions


def _missing_scopes(policy: PolicySchema, grants: GrantSchema) -> Set[str]:
    user_scopes = set(grants.grants.scopes)
    missing: Set[str] = set()
    for scope in policy.scope.scopes_all:
        if scope not in user_scopes:
            missing.add(scope)
    if policy.scope.scopes_any:
        if not any(scope in user_scopes for scope in policy.scope.scopes_any):
            missing.update(set(policy.scope.scopes_any))
    return missing


def _handle_policy_missing(
    *,
    request_context: Dict[str, Any],
    runtime_flags: RuntimeFlags,
    trace_state: Optional[Dict[str, Any]] = None,
) -> DecisionSchema:
    sensitive = bool(request_context.get("policy_missing_sensitive", False))
    reason_code = "AUTHZ_POLICY_MISSING_SENSITIVE" if sensitive else "AUTHZ_POLICY_MISSING_NON_SENSITIVE"
    decision = _mode_decision(
        runtime_flags,
        sensitive=sensitive,
        deny_code=reason_code,
        allow_code=reason_code,
    )
    return _decision_with_trace(
        trace_state=trace_state or start_trace(enabled=False),
        decision=decision,
        reason_code=reason_code,
        policy=None,
        request_context=request_context,
        required={"endpoint": str(request_context.get("endpoint") or "").strip()},
        missing={"policy": True},
    )


def evaluate(
    request_context: Dict[str, Any],
    policy: Any,
    grants: Optional[GrantSchema],
    runtime_flags: RuntimeFlags,
) -> DecisionSchema:
    context = request_context if isinstance(request_context, dict) else {}
    trace_state = start_trace(enabled=_trace_enabled(context), request_context=context)
    _trace_step(
        trace_state,
        "policy_lookup",
        {"has_policy_payload": policy is not None},
        {"policy_type": type(policy).__name__ if policy is not None else "None"},
    )
    policy_obj, policy_error = _coerce_policy(policy)
    _trace_step(
        trace_state,
        "policy_lookup_result",
        {"policy_error": policy_error},
        {
            "policy_found": policy_obj is not None,
            "policy_endpoint": str(getattr(policy_obj, "endpoint", "") or ""),
            "policy_public": bool(getattr(policy_obj, "public", False)) if policy_obj is not None else False,
        },
    )

    if policy_obj is None and policy_error is None:
        _trace_step(
            trace_state,
            "policy_missing",
            {"policy_missing_sensitive": bool(context.get("policy_missing_sensitive", False))},
            {"mode": runtime_flags.authz_mode},
        )
        return _handle_policy_missing(request_context=context, runtime_flags=runtime_flags, trace_state=trace_state)

    if policy_error:
        decision = "ALLOW" if runtime_flags.is_shadow_mode else "DENY"
        _trace_step(trace_state, "policy_invalid", {"policy_error": policy_error}, {"decision": decision})
        return _decision_with_trace(
            trace_state=trace_state,
            decision=decision,
            reason_code=policy_error,
            policy=policy_obj,
            request_context=context,
            missing={"policy": "invalid"},
        )

    assert policy_obj is not None

    hybrid_conflict = str(context.get("hybrid_conflict") or "").strip().lower()
    if hybrid_conflict in ("registry_decorator", "registry_legacy"):
        reason_code = (
            "AUTHZ_POLICY_CONFLICT_REGISTRY_DECORATOR"
            if hybrid_conflict == "registry_decorator"
            else "AUTHZ_POLICY_CONFLICT_REGISTRY_LEGACY"
        )
        sensitive = _is_sensitive(policy_obj, context)
        decision = _mode_decision(runtime_flags, sensitive=sensitive, deny_code=reason_code, allow_code=reason_code)
        _trace_step(
            trace_state,
            "policy_conflict",
            {"hybrid_conflict": hybrid_conflict, "sensitive": sensitive},
            {"decision": decision, "reason_code": reason_code},
        )
        return _decision_with_trace(
            trace_state=trace_state,
            decision=decision,
            reason_code=reason_code,
            policy=policy_obj,
            request_context=context,
            required={"hybrid_conflict": hybrid_conflict},
            missing={"conflict": hybrid_conflict},
        )

    if policy_obj.public:
        _trace_step(trace_state, "public_endpoint", {"public": True}, {"decision": "ALLOW"})
        return _decision_with_trace(
            trace_state=trace_state,
            decision="ALLOW",
            reason_code="AUTHZ_ALLOW_PUBLIC",
            policy=policy_obj,
            request_context=context,
        )

    authenticated = bool(context.get("authenticated", False))
    _trace_step(trace_state, "authentication", {"authenticated": authenticated}, {"ok": authenticated})
    if not authenticated:
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_UNAUTHENTICATED",
            policy=policy_obj,
            request_context=context,
            missing={"authenticated": False},
        )

    _trace_step(trace_state, "grant_schema_check", {"grants_type": type(grants).__name__ if grants is not None else "None"}, {"is_valid_grant_schema": isinstance(grants, GrantSchema)})
    if not isinstance(grants, GrantSchema):
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_MISSING_PAGE",
            policy=policy_obj,
            request_context=context,
            required={"page": policy_obj.page},
            missing={"grant_schema": True},
        )

    user_role_level = int(grants.user.role_level)
    _trace_step(
        trace_state,
        "role_check",
        {
            "user_role": grants.user.role,
            "user_role_level": user_role_level,
            "minimum_role": policy_obj.minimum_role,
            "minimum_role_level": policy_obj.minimum_role_level,
        },
        {"allowed": user_role_level >= int(policy_obj.minimum_role_level)},
    )
    if user_role_level < int(policy_obj.minimum_role_level):
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_INSUFFICIENT_ROLE",
            policy=policy_obj,
            request_context=context,
            required={
                "minimum_role": policy_obj.minimum_role,
                "minimum_role_level": policy_obj.minimum_role_level,
            },
            missing={"role_level": user_role_level},
        )

    has_page = _has_page(grants, policy_obj.page, policy_obj)
    _trace_step(trace_state, "page_check", {"required_page": policy_obj.page}, {"allowed": has_page})
    if not has_page:
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_MISSING_PAGE",
            policy=policy_obj,
            request_context=context,
            required={"page": policy_obj.page},
            missing={"page": policy_obj.page},
        )

    method = str(context.get("method") or "GET").strip().upper()
    required_action = _required_action_for_method(policy_obj, method)
    _trace_step(trace_state, "action_requirement", {"method": method}, {"required_action": required_action, "action_required": policy_obj.action.required})
    if policy_obj.action.required and not required_action:
        decision = "ALLOW" if runtime_flags.is_shadow_mode else "DENY"
        return _decision_with_trace(
            trace_state=trace_state,
            decision=decision,
            reason_code="AUTHZ_POLICY_INVALID_CONFLICT",
            policy=policy_obj,
            request_context=context,
            required={"method": method},
            missing={"action_for_method": method},
        )
    has_action = True if not required_action else _has_action(grants, required_action, policy_obj, context)
    _trace_step(trace_state, "action_check", {"required_action": required_action}, {"allowed": has_action})
    if required_action and not has_action:
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_MISSING_ACTION",
            policy=policy_obj,
            request_context=context,
            required={"action": required_action},
            missing={"action": required_action},
        )

    ambiguous_scope = bool(context.get("ambiguous_scope", False))
    missing_scopes = _missing_scopes(policy_obj, grants)
    if ambiguous_scope and (policy_obj.scope.scopes_any or policy_obj.scope.scopes_all):
        missing_scopes.update(set(policy_obj.scope.scopes_any))
        missing_scopes.update(set(policy_obj.scope.scopes_all))
    if missing_scopes:
        _trace_step(
            trace_state,
            "scope_check",
            {"scopes_any": policy_obj.scope.scopes_any, "scopes_all": policy_obj.scope.scopes_all, "ambiguous_scope": ambiguous_scope},
            {"allowed": False, "missing_scopes": sorted(missing_scopes)},
        )
        return _decision_with_trace(
            trace_state=trace_state,
            decision="DENY",
            reason_code="AUTHZ_DENY_MISSING_SCOPE",
            policy=policy_obj,
            request_context=context,
            required={
                "scopes_any": policy_obj.scope.scopes_any,
                "scopes_all": policy_obj.scope.scopes_all,
            },
            missing={"scopes": sorted(missing_scopes)},
        )
    _trace_step(
        trace_state,
        "scope_check",
        {"scopes_any": policy_obj.scope.scopes_any, "scopes_all": policy_obj.scope.scopes_all, "ambiguous_scope": ambiguous_scope},
        {"allowed": True, "missing_scopes": []},
    )

    if policy_obj.override.required:
        approved = bool(context.get("override_approved", False))
        if approved:
            age_seconds = context.get("override_age_seconds")
            if age_seconds is not None and float(age_seconds) > float(policy_obj.override.ttl_seconds):
                approved = False
        _trace_step(
            trace_state,
            "override_check",
            {
                "override_required": True,
                "override_approved": bool(context.get("override_approved", False)),
                "override_age_seconds": context.get("override_age_seconds"),
                "ttl_seconds": policy_obj.override.ttl_seconds,
            },
            {"allowed": approved},
        )
        if not approved:
            return _decision_with_trace(
                trace_state=trace_state,
                decision="REQUIRE_OVERRIDE",
                reason_code="AUTHZ_REQUIRE_OVERRIDE",
                policy=policy_obj,
                request_context=context,
                required={
                    "override_required": True,
                    "approver_minimum_role": policy_obj.override.approver_minimum_role,
                    "ttl_seconds": policy_obj.override.ttl_seconds,
                },
                missing={"override_approved": False},
            )
    else:
        _trace_step(trace_state, "override_check", {"override_required": False}, {"allowed": True})

    if bool(context.get("admin_bypass", False)) and user_role_level >= role_level_for("admin"):
        _trace_step(trace_state, "admin_bypass_check", {"admin_bypass": True, "user_role_level": user_role_level}, {"allowed": True})
        return _decision_with_trace(
            trace_state=trace_state,
            decision="ALLOW",
            reason_code="AUTHZ_ALLOW_ADMIN_BYPASS",
            policy=policy_obj,
            request_context=context,
        )
    _trace_step(trace_state, "admin_bypass_check", {"admin_bypass": bool(context.get("admin_bypass", False)), "user_role_level": user_role_level}, {"allowed": False})

    allow_reason = "AUTHZ_ALLOW_PAGE_ACTION_SCOPE" if required_action else "AUTHZ_ALLOW_PAGE_ONLY"
    return _decision_with_trace(
        trace_state=trace_state,
        decision="ALLOW",
        reason_code=allow_reason,
        policy=policy_obj,
        request_context=context,
        required={"page": policy_obj.page, "action": required_action},
    )
