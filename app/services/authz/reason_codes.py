from __future__ import annotations

from typing import Dict, Set


ALLOW_CODES: Set[str] = {
    "AUTHZ_ALLOW_PUBLIC",
    "AUTHZ_ALLOW_PAGE_ONLY",
    "AUTHZ_ALLOW_PAGE_ACTION_SCOPE",
    "AUTHZ_ALLOW_ADMIN_BYPASS",
}

DENY_CODES: Set[str] = {
    "AUTHZ_DENY_UNAUTHENTICATED",
    "AUTHZ_DENY_MISSING_PAGE",
    "AUTHZ_DENY_MISSING_ACTION",
    "AUTHZ_DENY_MISSING_SCOPE",
    "AUTHZ_DENY_INSUFFICIENT_ROLE",
}

REQUIRE_OVERRIDE_CODES: Set[str] = {
    "AUTHZ_REQUIRE_OVERRIDE",
}

POLICY_MISSING_CODES: Set[str] = {
    "AUTHZ_POLICY_MISSING_NON_SENSITIVE",
    "AUTHZ_POLICY_MISSING_SENSITIVE",
}

POLICY_INVALID_CODES: Set[str] = {
    "AUTHZ_POLICY_INVALID_SCHEMA",
    "AUTHZ_POLICY_INVALID_CONFLICT",
}

POLICY_CONFLICT_CODES: Set[str] = {
    "AUTHZ_POLICY_CONFLICT_REGISTRY_DECORATOR",
    "AUTHZ_POLICY_CONFLICT_REGISTRY_LEGACY",
}

ALL_REASON_CODES: Set[str] = (
    ALLOW_CODES
    | DENY_CODES
    | REQUIRE_OVERRIDE_CODES
    | POLICY_MISSING_CODES
    | POLICY_INVALID_CODES
    | POLICY_CONFLICT_CODES
)

REASON_GROUPS: Dict[str, Set[str]] = {
    "allow": ALLOW_CODES,
    "deny": DENY_CODES,
    "require_override": REQUIRE_OVERRIDE_CODES,
    "policy_missing": POLICY_MISSING_CODES,
    "policy_invalid": POLICY_INVALID_CODES,
    "policy_conflict": POLICY_CONFLICT_CODES,
}


def is_valid_reason_code(value: str) -> bool:
    return str(value or "").strip() in ALL_REASON_CODES


def reason_group(value: str) -> str:
    code = str(value or "").strip()
    for group_name, codes in REASON_GROUPS.items():
        if code in codes:
            return group_name
    return "unknown"
