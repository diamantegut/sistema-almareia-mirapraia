from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.services.authz.schemas import (
    ActionPolicy,
    OverridePolicy,
    PolicySchema,
    ScopePolicy,
    SensitivityPolicy,
)


DEFAULT_POLICY_FILE = Path(__file__).resolve().parents[3] / "data" / "authz" / "policies_v1.json"
DEFAULT_PUBLIC_FILE = Path(__file__).resolve().parents[3] / "data" / "authz" / "public_endpoints_v1.json"
FALLBACK_POLICY_FILE = Path(__file__).resolve().parent / "defaults" / "policies_v1.json"
FALLBACK_PUBLIC_FILE = Path(__file__).resolve().parent / "defaults" / "public_endpoints_v1.json"


class PolicyRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyLookup:
    endpoint: str
    found: bool
    policy: Optional[PolicySchema]
    is_public: bool
    reason_code: str


@dataclass(frozen=True)
class PolicyIntegrityReport:
    schema_errors: List[str]
    public_conflicts: List[str]
    missing_endpoints: List[str]
    version_hash_errors: List[str]

    @property
    def is_ok(self) -> bool:
        return not (self.schema_errors or self.public_conflicts or self.missing_endpoints or self.version_hash_errors)


@dataclass(frozen=True)
class PolicyRegistry:
    policy_version: str
    policy_hash: str
    policies_by_endpoint: Dict[str, PolicySchema]
    public_endpoints: Set[str]

    @classmethod
    def from_files(
        cls,
        policy_file: Path | str = DEFAULT_POLICY_FILE,
        public_file: Path | str = DEFAULT_PUBLIC_FILE,
    ) -> "PolicyRegistry":
        policy_path = Path(policy_file)
        public_path = Path(public_file)
        policy_payload = cls._load_json(policy_path, fallback_path=FALLBACK_POLICY_FILE if policy_path == DEFAULT_POLICY_FILE else None)
        public_payload = cls._load_json(public_path, fallback_path=FALLBACK_PUBLIC_FILE if public_path == DEFAULT_PUBLIC_FILE else None)

        policy_version = str(policy_payload.get("policy_version") or "").strip()
        policy_hash = str(policy_payload.get("policy_hash") or "").strip()
        if not policy_version:
            raise PolicyRegistryError("policy_version do registry é obrigatório")
        if not policy_hash:
            raise PolicyRegistryError("policy_hash do registry é obrigatório")

        raw_policies = policy_payload.get("policies")
        if not isinstance(raw_policies, list):
            raise PolicyRegistryError("policies deve ser uma lista")

        policies_by_endpoint: Dict[str, PolicySchema] = {}
        for item in raw_policies:
            policy = cls._build_policy(item)
            if policy.endpoint in policies_by_endpoint:
                raise PolicyRegistryError(f"endpoint duplicado no registry: {policy.endpoint}")
            if policy.policy_version != policy_version:
                raise PolicyRegistryError(f"policy_version divergente no endpoint: {policy.endpoint}")
            policies_by_endpoint[policy.endpoint] = policy

        public_version = str(public_payload.get("policy_version") or "").strip()
        if public_version != policy_version:
            raise PolicyRegistryError("policy_version divergente entre policies e public_endpoints")
        raw_public = public_payload.get("endpoints")
        if not isinstance(raw_public, list):
            raise PolicyRegistryError("public_endpoints.endpoints deve ser uma lista")
        public_endpoints = cls._validate_public_endpoints(raw_public)

        for endpoint in public_endpoints:
            existing = policies_by_endpoint.get(endpoint)
            if existing and not existing.public:
                raise PolicyRegistryError(f"conflito policy/public no endpoint: {endpoint}")

        return cls(
            policy_version=policy_version,
            policy_hash=policy_hash,
            policies_by_endpoint=policies_by_endpoint,
            public_endpoints=public_endpoints,
        )

    @staticmethod
    def _load_json(path: Path, fallback_path: Optional[Path] = None) -> Dict[str, Any]:
        selected = path
        if not path.exists():
            if fallback_path is None or not fallback_path.exists():
                raise PolicyRegistryError(f"arquivo não encontrado: {path}")
            selected = fallback_path
        try:
            loaded = json.loads(selected.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PolicyRegistryError(f"json inválido: {selected}") from exc
        if not isinstance(loaded, dict):
            raise PolicyRegistryError(f"payload inválido (esperado objeto): {selected}")
        return loaded

    @staticmethod
    def _validate_public_endpoints(items: List[Any]) -> Set[str]:
        result: Set[str] = set()
        for endpoint in items:
            endpoint_name = str(endpoint or "").strip()
            if not endpoint_name:
                raise PolicyRegistryError("public_endpoints contém endpoint vazio")
            if endpoint_name in result:
                raise PolicyRegistryError(f"public_endpoints duplicado: {endpoint_name}")
            result.add(endpoint_name)
        return result

    @staticmethod
    def _build_policy(raw: Any) -> PolicySchema:
        if not isinstance(raw, dict):
            raise PolicyRegistryError("policy inválida: esperado objeto")
        try:
            action_raw = raw.get("action") if isinstance(raw.get("action"), dict) else {}
            override_raw = raw.get("override") if isinstance(raw.get("override"), dict) else {}
            scope_raw = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
            sensitivity_raw = raw.get("sensitivity") if isinstance(raw.get("sensitivity"), dict) else {}
            return PolicySchema(
                endpoint=raw.get("endpoint"),
                area=raw.get("area"),
                public=bool(raw.get("public", False)),
                page=raw.get("page"),
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
                minimum_role=raw.get("minimum_role", "colaborador"),
                minimum_role_level=raw.get("minimum_role_level", 1),
                sensitivity=SensitivityPolicy(
                    classification=sensitivity_raw.get("classification", "operacional"),
                    is_sensitive=bool(sensitivity_raw.get("is_sensitive", False)),
                    is_critical=bool(sensitivity_raw.get("is_critical", False)),
                    is_destructive=bool(sensitivity_raw.get("is_destructive", False)),
                    is_systemic=bool(sensitivity_raw.get("is_systemic", False)),
                ),
                policy_status=raw.get("policy_status", "active"),
                policy_version=raw.get("policy_version"),
                policy_hash=raw.get("policy_hash"),
            )
        except ValueError as exc:
            raise PolicyRegistryError(f"policy inválida para endpoint={raw.get('endpoint')}: {exc}") from exc

    def get_policy(self, endpoint: str) -> Optional[PolicySchema]:
        endpoint_name = str(endpoint or "").strip()
        if not endpoint_name:
            return None
        return self.policies_by_endpoint.get(endpoint_name)

    def is_public_endpoint(self, endpoint: str) -> bool:
        endpoint_name = str(endpoint or "").strip()
        if not endpoint_name:
            return False
        policy = self.policies_by_endpoint.get(endpoint_name)
        if policy:
            return policy.public
        return endpoint_name in self.public_endpoints

    def lookup(self, endpoint: str) -> PolicyLookup:
        endpoint_name = str(endpoint or "").strip()
        policy = self.get_policy(endpoint_name)
        if policy:
            return PolicyLookup(
                endpoint=endpoint_name,
                found=True,
                policy=policy,
                is_public=policy.public,
                reason_code="AUTHZ_ALLOW_POLICY_FOUND",
            )
        if endpoint_name in self.public_endpoints:
            return PolicyLookup(
                endpoint=endpoint_name,
                found=False,
                policy=None,
                is_public=True,
                reason_code="AUTHZ_POLICY_MISSING_NON_SENSITIVE",
            )
        return PolicyLookup(
            endpoint=endpoint_name,
            found=False,
            policy=None,
            is_public=False,
            reason_code="AUTHZ_POLICY_MISSING_NON_SENSITIVE",
        )

    def validate_integrity_report(self, expected_endpoints: Optional[Set[str]] = None) -> PolicyIntegrityReport:
        schema_errors: List[str] = []
        public_conflicts: List[str] = []
        missing_endpoints: List[str] = []
        version_hash_errors: List[str] = []
        if not self.policy_version:
            version_hash_errors.append("registry policy_version vazio")
        if not self.policy_hash:
            version_hash_errors.append("registry policy_hash vazio")
        for endpoint, policy in self.policies_by_endpoint.items():
            if policy.policy_version != self.policy_version:
                version_hash_errors.append(f"policy_version divergente: {endpoint}")
            if not policy.policy_hash:
                version_hash_errors.append(f"policy_hash vazio: {endpoint}")
            if endpoint in self.public_endpoints and not policy.public:
                public_conflicts.append(f"conflito public endpoint: {endpoint}")

        if expected_endpoints:
            normalized_expected = {str(item).strip() for item in expected_endpoints if str(item).strip()}
            for endpoint in sorted(normalized_expected):
                if endpoint not in self.policies_by_endpoint and endpoint not in self.public_endpoints:
                    missing_endpoints.append(f"endpoint sem policy/public declaration: {endpoint}")

        return PolicyIntegrityReport(
            schema_errors=schema_errors,
            public_conflicts=public_conflicts,
            missing_endpoints=missing_endpoints,
            version_hash_errors=version_hash_errors,
        )

    def validate_integrity(self, expected_endpoints: Optional[Set[str]] = None) -> List[str]:
        report = self.validate_integrity_report(expected_endpoints=expected_endpoints)
        flattened: List[str] = []
        flattened.extend(report.schema_errors)
        flattened.extend(report.public_conflicts)
        flattened.extend(report.missing_endpoints)
        flattened.extend(report.version_hash_errors)
        return flattened
