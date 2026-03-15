from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Set


AUTHZ_MODES = ("shadow", "warn_enforce", "enforce")


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "t", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


def _to_float(value: Any, default: float = 0.2) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _to_set_csv(value: Any) -> Set[str]:
    if value is None:
        return set()
    raw = str(value).strip()
    if not raw:
        return set()
    return {chunk.strip() for chunk in raw.split(",") if chunk.strip()}


@dataclass(frozen=True)
class RuntimeFlags:
    authz_mode: str = "shadow"
    warn_enforce_sensitive_only: bool = True
    allow_sampling_enabled: bool = True
    allow_sampling_rate: float = 0.2
    allow_sampling_modules_full_log: Set[str] = field(default_factory=set)
    enforce_areas: Set[str] = field(default_factory=set)
    sensitive_override_list: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        mode = str(self.authz_mode or "").strip().lower()
        if mode not in AUTHZ_MODES:
            raise ValueError("authz_mode inválido")
        object.__setattr__(self, "authz_mode", mode)
        object.__setattr__(self, "allow_sampling_rate", _to_float(self.allow_sampling_rate))
        object.__setattr__(self, "allow_sampling_modules_full_log", set(self.allow_sampling_modules_full_log or set()))
        object.__setattr__(self, "enforce_areas", set(self.enforce_areas or set()))
        object.__setattr__(self, "sensitive_override_list", set(self.sensitive_override_list or set()))

    @property
    def is_shadow_mode(self) -> bool:
        return self.authz_mode == "shadow"

    @property
    def is_warn_enforce_mode(self) -> bool:
        return self.authz_mode == "warn_enforce"

    @property
    def is_enforce_mode(self) -> bool:
        return self.authz_mode == "enforce"

    def should_log_allow_full(self, module_name: str) -> bool:
        module_key = str(module_name or "").strip()
        return module_key in self.allow_sampling_modules_full_log

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authz_mode": self.authz_mode,
            "warn_enforce_sensitive_only": self.warn_enforce_sensitive_only,
            "allow_sampling_enabled": self.allow_sampling_enabled,
            "allow_sampling_rate": self.allow_sampling_rate,
            "allow_sampling_modules_full_log": sorted(self.allow_sampling_modules_full_log),
            "enforce_areas": sorted(self.enforce_areas),
            "sensitive_override_list": sorted(self.sensitive_override_list),
        }


def load_runtime_flags(env: Dict[str, Any] | None = None) -> RuntimeFlags:
    source = env if env is not None else os.environ
    return RuntimeFlags(
        authz_mode=str(source.get("AUTHZ_MODE", "shadow")).strip().lower(),
        warn_enforce_sensitive_only=_to_bool(source.get("AUTHZ_WARN_ENFORCE_SENSITIVE_ONLY"), True),
        allow_sampling_enabled=_to_bool(source.get("AUTHZ_ALLOW_SAMPLING_ENABLED"), True),
        allow_sampling_rate=_to_float(source.get("AUTHZ_ALLOW_SAMPLING_RATE"), 0.2),
        allow_sampling_modules_full_log=_to_set_csv(source.get("AUTHZ_ALLOW_FULL_LOG_MODULES")),
        enforce_areas=_to_set_csv(source.get("AUTHZ_ENFORCE_AREAS")),
        sensitive_override_list=_to_set_csv(source.get("AUTHZ_SENSITIVE_OVERRIDE_LIST")),
    )


def build_runtime_flags(**kwargs: Any) -> RuntimeFlags:
    return RuntimeFlags(**kwargs)


def merge_sensitive_override(base_sensitive_endpoints: Iterable[str], flags: RuntimeFlags) -> Set[str]:
    base = {str(item).strip() for item in base_sensitive_endpoints if str(item).strip()}
    return base | flags.sensitive_override_list
