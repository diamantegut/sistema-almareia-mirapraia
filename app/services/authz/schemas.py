from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


ROLE_LEVELS: Dict[str, int] = {
    "colaborador": 1,
    "supervisor": 2,
    "gerente": 3,
    "admin": 4,
}

SENSITIVITY_CLASSIFICATIONS = (
    "operacional",
    "sensivel",
    "destrutiva",
    "sistemica",
)

DECISION_TYPES = ("ALLOW", "DENY", "REQUIRE_OVERRIDE")

POLICY_STATUS_VALUES = ("active", "migrating", "deprecated", "disabled")


def normalize_role_name(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role not in ROLE_LEVELS:
        raise ValueError(f"role inválido: {value}")
    return role


def role_level_for(value: Any) -> int:
    role = normalize_role_name(value)
    return ROLE_LEVELS[role]


def validate_override_ttl(value: Any) -> int:
    ttl = int(value)
    if ttl < 30 or ttl > 900:
        raise ValueError("override.ttl_seconds deve estar entre 30 e 900")
    return ttl


@dataclass(frozen=True)
class ActionPolicy:
    required: bool = False
    name_by_method: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: Dict[str, str] = {}
        for method, action_name in (self.name_by_method or {}).items():
            method_key = str(method or "").strip().upper()
            action = str(action_name or "").strip()
            if not method_key:
                raise ValueError("action.name_by_method contém método inválido")
            if not action:
                raise ValueError("action.name_by_method contém action vazia")
            normalized[method_key] = action
        object.__setattr__(self, "name_by_method", normalized)
        if self.required and not normalized:
            raise ValueError("action.required=true exige name_by_method")


@dataclass(frozen=True)
class OverridePolicy:
    required: bool = False
    approver_minimum_role: Optional[str] = None
    reason_required: bool = True
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        ttl = validate_override_ttl(self.ttl_seconds)
        object.__setattr__(self, "ttl_seconds", ttl)
        if self.required:
            if not self.approver_minimum_role:
                raise ValueError("override.required=true exige approver_minimum_role")
            role = normalize_role_name(self.approver_minimum_role)
            object.__setattr__(self, "approver_minimum_role", role)
        elif self.approver_minimum_role:
            role = normalize_role_name(self.approver_minimum_role)
            object.__setattr__(self, "approver_minimum_role", role)


@dataclass(frozen=True)
class ScopePolicy:
    scopes_any: List[str] = field(default_factory=list)
    scopes_all: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        scopes_any = [str(item).strip() for item in (self.scopes_any or []) if str(item).strip()]
        scopes_all = [str(item).strip() for item in (self.scopes_all or []) if str(item).strip()]
        object.__setattr__(self, "scopes_any", scopes_any)
        object.__setattr__(self, "scopes_all", scopes_all)


@dataclass(frozen=True)
class SensitivityPolicy:
    classification: str
    is_sensitive: bool = False
    is_critical: bool = False
    is_destructive: bool = False
    is_systemic: bool = False

    def __post_init__(self) -> None:
        classification = str(self.classification or "").strip().lower()
        if classification not in SENSITIVITY_CLASSIFICATIONS:
            raise ValueError("classification inválida")
        object.__setattr__(self, "classification", classification)
        is_destructive = bool(self.is_destructive or classification == "destrutiva")
        is_systemic = bool(self.is_systemic or classification == "sistemica")
        is_sensitive = bool(self.is_sensitive or classification in ("sensivel", "destrutiva", "sistemica"))
        is_critical = bool(self.is_critical or classification == "sistemica")
        object.__setattr__(self, "is_destructive", is_destructive)
        object.__setattr__(self, "is_systemic", is_systemic)
        object.__setattr__(self, "is_sensitive", is_sensitive)
        object.__setattr__(self, "is_critical", is_critical)


@dataclass(frozen=True)
class PolicySchema:
    endpoint: str
    area: str
    public: bool
    page: str
    action: ActionPolicy = field(default_factory=ActionPolicy)
    override: OverridePolicy = field(default_factory=OverridePolicy)
    scope: ScopePolicy = field(default_factory=ScopePolicy)
    minimum_role: str = "colaborador"
    minimum_role_level: int = 1
    sensitivity: SensitivityPolicy = field(default_factory=lambda: SensitivityPolicy(classification="operacional"))
    policy_status: str = "active"
    policy_version: str = ""
    policy_hash: str = ""

    def __post_init__(self) -> None:
        endpoint = str(self.endpoint or "").strip()
        area = str(self.area or "").strip()
        page = str(self.page or "").strip()
        if not endpoint:
            raise ValueError("policy.endpoint é obrigatório")
        if not area:
            raise ValueError("policy.area é obrigatório")
        if not page:
            raise ValueError("policy.page é obrigatório")
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "area", area)
        object.__setattr__(self, "page", page)

        role = normalize_role_name(self.minimum_role)
        role_level = int(self.minimum_role_level)
        if role_level != ROLE_LEVELS[role]:
            raise ValueError("minimum_role incompatível com minimum_role_level")
        object.__setattr__(self, "minimum_role", role)
        object.__setattr__(self, "minimum_role_level", role_level)

        policy_status = str(self.policy_status or "").strip().lower()
        if policy_status not in POLICY_STATUS_VALUES:
            raise ValueError("policy_status inválido")
        object.__setattr__(self, "policy_status", policy_status)

        policy_version = str(self.policy_version or "").strip()
        policy_hash = str(self.policy_hash or "").strip()
        if not policy_version:
            raise ValueError("policy_version é obrigatório")
        if not policy_hash:
            raise ValueError("policy_hash é obrigatório")
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "policy_hash", policy_hash)

        if self.public and self.action.required:
            raise ValueError("endpoint público não pode exigir action.required")


@dataclass(frozen=True)
class GrantUser:
    username: str
    department: str
    role: str
    role_level: int

    def __post_init__(self) -> None:
        username = str(self.username or "").strip()
        department = str(self.department or "").strip()
        if not username:
            raise ValueError("grant.user.username é obrigatório")
        if not department:
            raise ValueError("grant.user.department é obrigatório")
        role = normalize_role_name(self.role)
        role_level = int(self.role_level)
        if role_level != ROLE_LEVELS[role]:
            raise ValueError("grant.user.role incompatível com role_level")
        object.__setattr__(self, "username", username)
        object.__setattr__(self, "department", department)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "role_level", role_level)


@dataclass(frozen=True)
class GrantPermissions:
    pages: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)
    can_request_override: bool = False
    can_approve_override: bool = False
    approve_min_role: Optional[str] = None

    def __post_init__(self) -> None:
        pages = [str(item).strip() for item in (self.pages or []) if str(item).strip()]
        actions = [str(item).strip() for item in (self.actions or []) if str(item).strip()]
        scopes = [str(item).strip() for item in (self.scopes or []) if str(item).strip()]
        object.__setattr__(self, "pages", pages)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "scopes", scopes)
        if self.approve_min_role:
            role = normalize_role_name(self.approve_min_role)
            object.__setattr__(self, "approve_min_role", role)
        if self.can_approve_override and not self.approve_min_role:
            raise ValueError("can_approve_override=true exige approve_min_role")


@dataclass(frozen=True)
class GrantSchema:
    user: GrantUser
    grants: GrantPermissions
    source_permissions_v2: bool = False
    source_legacy_tokens_used: bool = False
    resolved_at: str = ""

    def __post_init__(self) -> None:
        resolved_at = str(self.resolved_at or "").strip()
        if not resolved_at:
            raise ValueError("grant.resolved_at é obrigatório")
        object.__setattr__(self, "resolved_at", resolved_at)


@dataclass(frozen=True)
class DecisionSchema:
    decision: str
    reason_code: str
    required: Dict[str, Any] = field(default_factory=dict)
    missing: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = ""
    policy_hash: str = ""
    request_id: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        decision = str(self.decision or "").strip().upper()
        if decision not in DECISION_TYPES:
            raise ValueError("decision inválida")
        reason_code = str(self.reason_code or "").strip()
        policy_version = str(self.policy_version or "").strip()
        policy_hash = str(self.policy_hash or "").strip()
        request_id = str(self.request_id or "").strip()
        if not reason_code:
            raise ValueError("reason_code é obrigatório")
        if not policy_version:
            raise ValueError("policy_version é obrigatório")
        if not policy_hash:
            raise ValueError("policy_hash é obrigatório")
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "policy_hash", policy_hash)
        object.__setattr__(self, "request_id", request_id)
        normalized_trace: List[Dict[str, Any]] = []
        for item in (self.trace or []):
            if isinstance(item, dict):
                normalized_trace.append(item)
        object.__setattr__(self, "trace", normalized_trace)
