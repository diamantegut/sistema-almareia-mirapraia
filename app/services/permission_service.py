from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from flask import current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from jinja2 import TemplateNotFound
from werkzeug.routing import BuildError

from app.services.data_service import (
    DEPARTMENT_PERMISSIONS_FILE,
    USERS_FILE,
    load_department_permissions,
    load_users,
    normalize_text,
)
from app.services.authz.policy_decorators import compare_metadata_with_registry, get_policy_metadata, get_policy_metadata_conflicts
from app.utils.decorators import get_legacy_auth_metadata


_CACHE_TTL_SECONDS = 10.0
_USERS_CACHE: Dict[str, Any] = {"ts": 0.0, "mtime": None, "data": {}}
_DEPT_CACHE: Dict[str, Any] = {"ts": 0.0, "mtime": None, "data": {}}
_POLICY_REGISTRY_CACHE: Dict[str, Any] = {"ts": 0.0, "registry": None, "error": ""}
_OVERRIDE_SERVICE_SINGLETON: Any = None

OPERATIONAL_ROLLOUT_AREAS: Set[str] = {
    "recepcao",
    "restaurante_mirapraia",
    "cozinha",
    "estoque_principal",
    "fornecedores",
    "governanca",
    "manutencao",
}
PILOT_CRITICAL_AREAS: Set[str] = {
    "administracao_sistema",
    "auditoria_financeira",
    "financeiro",
    *OPERATIONAL_ROLLOUT_AREAS,
}
PILOT_ENDPOINT_AREA_HINTS: Dict[str, str] = {
    "admin": "administracao_sistema",
    "financial_audit": "auditoria_financeira",
    "finance": "financeiro",
    "reception": "recepcao",
    "guest": "recepcao",
    "restaurant": "restaurante_mirapraia",
    "menu": "restaurante_mirapraia",
    "kitchen": "cozinha",
    "stock": "estoque_principal",
    "suppliers": "fornecedores",
    "governance": "governanca",
    "maintenance": "manutencao",
}

CONVERGENCE_DEFAULT_AREAS: Set[str] = set(PILOT_CRITICAL_AREAS)


def _to_bool_env(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "t", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


def _csv_to_set(value: Any) -> Set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {chunk.strip() for chunk in raw.split(",") if chunk.strip()}


def _convergence_areas() -> Set[str]:
    configured = _csv_to_set(os.environ.get("AUTHZ_CONVERGENCE_AREAS"))
    return configured if configured else set(CONVERGENCE_DEFAULT_AREAS)


def _is_convergence_area(area: Optional[str]) -> bool:
    area_name = str(area or "").strip()
    if not area_name:
        return False
    return area_name in _convergence_areas()


def _legacy_checks_bypassed_for_area(area: Optional[str]) -> bool:
    if not _is_convergence_area(area):
        return False
    return _to_bool_env(os.environ.get("AUTHZ_CONVERGENCE_SKIP_LEGACY_CHECKS"), True)


def _legacy_fallback_enabled_for_area(area: Optional[str]) -> bool:
    if not _is_convergence_area(area):
        return True
    return _to_bool_env(os.environ.get("AUTHZ_CONVERGENCE_LEGACY_FALLBACK_ENABLED"), True)


def _global_deny_by_default_enabled() -> bool:
    return _to_bool_env(os.environ.get("AUTHZ_GLOBAL_DENY_BY_DEFAULT_ENABLED"), False)


def _global_deny_by_default_ready() -> bool:
    return _to_bool_env(os.environ.get("AUTHZ_GLOBAL_DENY_BY_DEFAULT_READY"), False)


def _dev_fail_on_policy_missing_enabled() -> bool:
    if not _to_bool_env(os.environ.get("AUTHZ_DEV_FAIL_ON_POLICY_MISSING"), False):
        return False
    mode = str(os.environ.get("AUTHZ_MODE", "shadow") or "shadow").strip().lower()
    if mode == "production":
        return False
    env_name = str(os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower()
    if env_name == "production":
        return False
    return True


def _resolve_policy_missing_sensitive(endpoint: str, runtime_flags: Any) -> bool:
    if _global_deny_by_default_enabled():
        return True
    return _is_sensitive_hint(endpoint, runtime_flags)


def _safe_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _load_users_cached() -> Dict[str, Any]:
    now = time.time()
    mtime = _safe_mtime(USERS_FILE)
    if (
        isinstance(_USERS_CACHE.get("data"), dict)
        and (now - float(_USERS_CACHE.get("ts", 0.0))) <= _CACHE_TTL_SECONDS
        and _USERS_CACHE.get("mtime") == mtime
    ):
        return _USERS_CACHE["data"]
    loaded = load_users()
    data = loaded if isinstance(loaded, dict) else {}
    _USERS_CACHE["ts"] = now
    _USERS_CACHE["mtime"] = mtime
    _USERS_CACHE["data"] = data
    return data


def _load_department_permissions_cached() -> Dict[str, Any]:
    now = time.time()
    mtime = _safe_mtime(DEPARTMENT_PERMISSIONS_FILE)
    if (
        isinstance(_DEPT_CACHE.get("data"), dict)
        and (now - float(_DEPT_CACHE.get("ts", 0.0))) <= _CACHE_TTL_SECONDS
        and _DEPT_CACHE.get("mtime") == mtime
    ):
        return _DEPT_CACHE["data"]
    loaded = load_department_permissions()
    data = loaded if isinstance(loaded, dict) else {}
    _DEPT_CACHE["ts"] = now
    _DEPT_CACHE["mtime"] = mtime
    _DEPT_CACHE["data"] = data
    return data


ROLE_LEVELS: Dict[str, int] = {
    "colaborador": 10,
    "supervisor": 20,
    "gerente": 30,
    "admin": 40,
    "super": 50,
}


def normalize_role(role: Any) -> str:
    role_s = normalize_text(str(role or ""))
    if "admin" in role_s:
        return "admin"
    if role_s == "super":
        return "super"
    if "gerente" in role_s:
        return "gerente"
    if "supervisor" in role_s:
        return "supervisor"
    if role_s in ("financeiro", "rh", "recepcao", "cozinha", "estoque", "governanca", "conferencia"):
        return "colaborador"
    return "colaborador"


def role_level(role: Any) -> int:
    return ROLE_LEVELS.get(normalize_role(role), ROLE_LEVELS["colaborador"])


AREA_BLUEPRINT_MAP: Dict[str, str] = {
    "kitchen": "cozinha",
    "stock": "estoque_principal",
    "suppliers": "fornecedores",
    "maintenance": "manutencao",
    "restaurant": "restaurante_mirapraia",
    "menu": "restaurante_mirapraia",
    "reception": "recepcao",
    "guest": "recepcao",
    "governance": "governanca",
    "quality": "conferencia",
    "assets": "conferencia",
    "finance": "financeiro",
    "hr": "recursos_humanos",
}


AREA_LABELS: Dict[str, str] = {
    "cozinha": "Cozinha",
    "estoque_principal": "Estoque Principal",
    "fornecedores": "Fornecedores",
    "manutencao": "Manutenção",
    "restaurante_mirapraia": "Restaurante Mirapraia",
    "recepcao": "Recepção",
    "administracao_sistema": "Administração do Sistema",
    "auditoria_financeira": "Auditoria Financeira",
    "governanca": "Governança",
    "conferencia": "Conferência",
    "financeiro": "Financeiro",
    "recursos_humanos": "Recursos Humanos",
}


LEVEL_RESTRICTED_PAGES: Dict[str, str] = {
    "finance.finance_reconciliation": "supervisor",
    "finance.fiscal_emission_page": "supervisor",
    "finance.api_fiscal_pool_emit": "gerente",
    "finance.api_fiscal_print": "supervisor",
    "menu.menu_security_dashboard": "supervisor",
    "menu.api_menu_checkpoint": "gerente",
    "menu.api_menu_integrity_check": "gerente",
}


def area_for_endpoint(endpoint: Optional[str]) -> Optional[str]:
    if not endpoint or "." not in endpoint:
        return None
    prefix = endpoint.split(".", 1)[0]
    return AREA_BLUEPRINT_MAP.get(prefix)


def _empty_profile() -> Dict[str, Any]:
    return {"version": 2, "areas": {}, "level_pages": []}


def _normalize_profile(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _empty_profile()
    areas_in = raw.get("areas") if isinstance(raw.get("areas"), dict) else {}
    level_pages_in = raw.get("level_pages") if isinstance(raw.get("level_pages"), list) else []

    areas_out: Dict[str, Any] = {}
    for area_key, area_val in areas_in.items():
        if area_key not in AREA_LABELS:
            continue
        if not isinstance(area_val, dict):
            continue
        all_flag = bool(area_val.get("all"))
        pages_in = area_val.get("pages") if isinstance(area_val.get("pages"), dict) else {}
        pages_out = {str(k): bool(v) for k, v in pages_in.items()}
        areas_out[area_key] = {"all": all_flag, "pages": pages_out}

    level_pages_out = [str(p) for p in level_pages_in if isinstance(p, (str, int))]
    return {"version": 2, "areas": areas_out, "level_pages": level_pages_out}


def derive_legacy_profile(user_role: Any, user_department: Any, legacy_permissions: Any) -> Dict[str, Any]:
    profile = _empty_profile()
    r_level = role_level(user_role)
    role_norm = normalize_text(str(user_role or ""))

    if r_level >= ROLE_LEVELS["gerente"]:
        profile["areas"] = {k: {"all": True, "pages": {}} for k in AREA_LABELS.keys()}
        return profile

    dept_norm = normalize_text(str(user_department or ""))
    perm_list: List[str] = []
    if isinstance(legacy_permissions, (list, tuple, set)):
        perm_list = [normalize_text(str(p)) for p in legacy_permissions]

    def grant(area_key: str) -> None:
        profile["areas"][area_key] = {"all": True, "pages": {}}

    if "recepcao" in dept_norm or role_norm == "recepcao":
        grant("recepcao")
        grant("restaurante_mirapraia")
    if "servico" in dept_norm or "restaurante" in dept_norm:
        grant("restaurante_mirapraia")
    if "estoque" in dept_norm:
        grant("estoque_principal")
    if "fornecedor" in dept_norm:
        grant("fornecedores")
    if "manutencao" in dept_norm or "manutencao" in role_norm:
        grant("manutencao")
    if "cozinha" in dept_norm:
        grant("cozinha")
    if "governanca" in dept_norm:
        grant("governanca")
    if "conferencia" in dept_norm or "qualidade" in dept_norm:
        grant("conferencia")
    if "finance" in dept_norm:
        grant("financeiro")
    if "recursos" in dept_norm or dept_norm == "rh":
        grant("recursos_humanos")
    if role_norm in ("financeiro", "rh", "cozinha", "estoque", "governanca", "conferencia", "manutencao", "fornecedores"):
        if role_norm == "financeiro":
            grant("financeiro")
        if role_norm == "rh":
            grant("recursos_humanos")
        if role_norm == "cozinha":
            grant("cozinha")
        if role_norm == "estoque":
            grant("estoque_principal")
        if role_norm == "fornecedores":
            grant("fornecedores")
        if role_norm == "governanca":
            grant("governanca")
        if role_norm == "conferencia":
            grant("conferencia")
        if role_norm == "manutencao":
            grant("manutencao")

    if "recepcao" in perm_list or "principal" in perm_list:
        grant("recepcao")
        grant("restaurante_mirapraia")
    if any("restaurante" in p for p in perm_list) or "restaurante_full_access" in perm_list:
        grant("restaurante_mirapraia")
    if "rh" in perm_list:
        grant("recursos_humanos")
    if "financeiro" in perm_list:
        grant("financeiro")
    if "governanca" in perm_list:
        grant("governanca")
    if "conferencia" in perm_list:
        grant("conferencia")
    if "estoque" in perm_list:
        grant("estoque_principal")
    if any("fornecedor" in p for p in perm_list):
        grant("fornecedores")
    if "manutencao" in perm_list:
        grant("manutencao")
    if "cozinha" in perm_list:
        grant("cozinha")

    if r_level >= ROLE_LEVELS["supervisor"]:
        grant("restaurante_mirapraia")

    return profile


def merge_profiles(*profiles: Dict[str, Any]) -> Dict[str, Any]:
    merged = _empty_profile()
    merged_areas: Dict[str, Any] = {}
    merged_level_pages: Set[str] = set()

    for p in profiles:
        p_norm = _normalize_profile(p)
        for area_key, area_val in (p_norm.get("areas") or {}).items():
            if area_key not in AREA_LABELS:
                continue
            cur = merged_areas.get(area_key, {"all": False, "pages": {}})
            cur_all = bool(cur.get("all"))
            new_all = bool(area_val.get("all"))
            pages = cur.get("pages") if isinstance(cur.get("pages"), dict) else {}
            new_pages = area_val.get("pages") if isinstance(area_val.get("pages"), dict) else {}
            for ep, v in new_pages.items():
                if v:
                    pages[str(ep)] = True
            merged_areas[area_key] = {"all": cur_all or new_all, "pages": pages}

        for ep in p_norm.get("level_pages") or []:
            merged_level_pages.add(str(ep))

    merged["areas"] = merged_areas
    merged["level_pages"] = sorted(list(merged_level_pages))
    return merged


def effective_profile_for_user(username: str, users: Dict[str, Any], department_permissions: Dict[str, Any]) -> Dict[str, Any]:
    user_data = users.get(username) if isinstance(users, dict) else None
    if not isinstance(user_data, dict):
        return _empty_profile()

    user_profile = _normalize_profile(user_data.get("permissions_v2"))
    dept_name = user_data.get("department")
    dept_key = str(dept_name or "")
    dept_profile = _normalize_profile((department_permissions or {}).get(dept_key))

    if user_profile.get("areas") or user_profile.get("level_pages"):
        return merge_profiles(dept_profile, user_profile)

    legacy = derive_legacy_profile(user_data.get("role"), user_data.get("department"), user_data.get("permissions"))
    return merge_profiles(dept_profile, legacy)


def list_permission_definitions(app) -> Dict[str, Any]:
    pages_by_area: Dict[str, List[Dict[str, Any]]] = {k: [] for k in AREA_LABELS.keys()}
    for rule in app.url_map.iter_rules():
        endpoint = getattr(rule, "endpoint", None)
        if not endpoint or endpoint.startswith("static"):
            continue
        area_key = area_for_endpoint(endpoint)
        if not area_key:
            continue
        pages_by_area[area_key].append(
            {
                "endpoint": endpoint,
                "path": str(rule.rule),
                "methods": sorted([m for m in (rule.methods or set()) if m not in ("HEAD", "OPTIONS")]),
                "label": endpoint.split(".", 1)[1].replace("_", " ").title() if "." in endpoint else endpoint,
                "level_min_role": LEVEL_RESTRICTED_PAGES.get(endpoint),
            }
        )

    for area_key in pages_by_area.keys():
        pages_by_area[area_key].sort(key=lambda x: (x.get("path") or "", x.get("endpoint") or ""))

    return {
        "areas": [{"key": k, "label": v} for k, v in AREA_LABELS.items()],
        "pages_by_area": pages_by_area,
        "level_restricted_pages": LEVEL_RESTRICTED_PAGES,
    }


def is_allowed_for_endpoint(
    endpoint: Optional[str],
    *,
    user: str,
    user_role: Any,
    profile: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    if not endpoint:
        return True, None

    if role_level(user_role) >= ROLE_LEVELS["admin"]:
        return True, None

    area_key = area_for_endpoint(endpoint)
    if not area_key:
        return True, None

    min_role = LEVEL_RESTRICTED_PAGES.get(endpoint)
    if min_role:
        if role_level(user_role) < ROLE_LEVELS.get(min_role, ROLE_LEVELS["supervisor"]):
            return False, "Acesso restrito por nível hierárquico."
        level_pages = set(_normalize_profile(profile).get("level_pages") or [])
        if endpoint not in level_pages:
            return False, "Acesso não autorizado para este nível."

    p_norm = _normalize_profile(profile)
    area_val = (p_norm.get("areas") or {}).get(area_key) or {}
    if bool(area_val.get("all")):
        return True, None

    pages = area_val.get("pages") if isinstance(area_val.get("pages"), dict) else {}
    if pages.get(endpoint):
        return True, None

    return False, "Acesso restrito."


def enforce_request_access():
    if request.path.startswith("/static") or request.path.startswith("/login") or request.path.startswith("/logout"):
        return None
    if request.endpoint in (None, ""):
        return None
    if request.endpoint.startswith("auth."):
        return None
    if "user" not in session:
        return None
    probe_state = getattr(g, "authz_probe_state", None)
    if isinstance(probe_state, dict) and bool(probe_state.get("new_authority_active")):
        return None

    users = _load_users_cached()
    dept_perms = _load_department_permissions_cached()

    username = session.get("user")
    if not username or username not in users:
        return None

    user_data = users.get(username) if isinstance(users, dict) else None
    if not isinstance(user_data, dict):
        return None

    profile = effective_profile_for_user(username, users, dept_perms)
    allowed, msg = is_allowed_for_endpoint(
        request.endpoint,
        user=username,
        user_role=session.get("role"),
        profile=profile,
    )
    if allowed:
        return None

    wants_json = ("application/json" in (request.headers.get("Content-Type") or "")) or (
        request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        return jsonify({"success": False, "error": msg or "Acesso restrito"}), 403
    flash(msg or "Acesso restrito.")
    return redirect(url_for("main.index"))


def _current_request_id() -> str:
    existing = str(getattr(g, "request_id", "") or "").strip()
    if existing:
        return existing
    header_value = str(request.headers.get("X-Request-ID") or "").strip()
    if header_value:
        g.request_id = header_value
        return header_value
    generated = uuid.uuid4().hex
    g.request_id = generated
    return generated


def _load_policy_registry_cached() -> Tuple[Any, str]:
    from app.services.authz.policy_registry import PolicyRegistry

    now = time.time()
    if _POLICY_REGISTRY_CACHE.get("registry") is not None and (now - float(_POLICY_REGISTRY_CACHE.get("ts", 0.0))) <= 10.0:
        return _POLICY_REGISTRY_CACHE.get("registry"), ""
    try:
        registry = PolicyRegistry.from_files()
        _POLICY_REGISTRY_CACHE["ts"] = now
        _POLICY_REGISTRY_CACHE["registry"] = registry
        _POLICY_REGISTRY_CACHE["error"] = ""
        return registry, ""
    except Exception as exc:
        err = str(exc)
        _POLICY_REGISTRY_CACHE["ts"] = now
        _POLICY_REGISTRY_CACHE["registry"] = None
        _POLICY_REGISTRY_CACHE["error"] = err
        return None, err


def _load_probe_runtime_flags():
    from app.services.authz.runtime_flags import load_runtime_flags

    return load_runtime_flags()


def _build_runtime_flags_for_pilot_audit(base_flags: Any):
    from app.services.authz.runtime_flags import build_runtime_flags

    return build_runtime_flags(
        authz_mode=base_flags.authz_mode,
        warn_enforce_sensitive_only=base_flags.warn_enforce_sensitive_only,
        allow_sampling_enabled=False,
        allow_sampling_rate=1.0,
        allow_sampling_modules_full_log=set(base_flags.allow_sampling_modules_full_log or set()),
        enforce_areas=set(base_flags.enforce_areas or set()),
        sensitive_override_list=set(base_flags.sensitive_override_list or set()),
    )


def _is_shadow_eligible_request() -> bool:
    if request.path.startswith("/static"):
        return False
    if request.endpoint in (None, ""):
        return False
    return True


def _is_sensitive_hint(endpoint: str, runtime_flags: Any) -> bool:
    endpoint_name = str(endpoint or "").strip()
    if not endpoint_name:
        return False
    if endpoint_name in set(getattr(runtime_flags, "sensitive_override_list", set()) or set()):
        return True
    prefix = endpoint_name.split(".", 1)[0] if "." in endpoint_name else endpoint_name
    return prefix in {"admin", "finance", "financial_audit", "reception", "restaurant", "menu", "kitchen", "stock", "suppliers", "governance", "maintenance"}


def _shadow_audit_sink(event: Dict[str, Any]) -> None:
    current_app.logger.info("authz_shadow_decision %s", json.dumps(event, ensure_ascii=False, default=str))
    try:
        from app.services.logger_service import LoggerService

        payload = dict(event or {})
        endpoint = str(payload.get("endpoint") or "").strip()
        area = str(payload.get("area") or "").strip()
        if not area:
            module_name = str(payload.get("module") or "").strip()
            if not module_name and endpoint:
                module_name = endpoint.split(".", 1)[0] if "." in endpoint else endpoint
            area = {
                "finance": "financeiro",
                "admin": "administracao_sistema",
                "financial_audit": "auditoria_financeira",
            }.get(module_name, module_name or "unknown")
            payload["area"] = area
        action_name = str(payload.get("event_type") or "authz_decision").strip().lower()
        if action_name not in ("authz_decision", "authz_override"):
            action_name = "authz_decision"
        LoggerService.log_acao(
            acao=action_name,
            entidade="AuthZ",
            detalhes=payload,
            nivel_severidade="INFO",
            departamento_id=area,
            colaborador_id=str(payload.get("executor_user") or session.get("user") or "Sistema"),
        )
    except Exception:
        return None


def _wants_json_response() -> bool:
    return ("application/json" in (request.headers.get("Content-Type") or "")) or (
        request.accept_mimetypes.best == "application/json"
    )


def _pilot_critical_area(endpoint: str, policy: Any) -> Optional[str]:
    policy_area = str(getattr(policy, "area", "") or "").strip()
    if policy_area in PILOT_CRITICAL_AREAS:
        return policy_area
    prefix = endpoint.split(".", 1)[0] if "." in endpoint else endpoint
    inferred = PILOT_ENDPOINT_AREA_HINTS.get(prefix)
    if inferred in PILOT_CRITICAL_AREAS:
        return inferred
    return None


def _pilot_stage_for_area(area: Optional[str]) -> str:
    area_name = str(area or "").strip()
    if area_name == "financeiro":
        return "pilot_critical_2_financeiro"
    if area_name in OPERATIONAL_ROLLOUT_AREAS:
        return "pilot_operational_3"
    if area_name in {"administracao_sistema", "auditoria_financeira"}:
        return "pilot_critical_1"
    return "non_pilot"


def _pilot_enforcement_enabled(area: str, runtime_flags: Any) -> bool:
    if not area or area not in PILOT_CRITICAL_AREAS:
        return False
    if runtime_flags.is_shadow_mode:
        return False
    return area in set(runtime_flags.enforce_areas or set())


def _pilot_deny_response(message: str, *, status_code: int = 403, extra: Optional[Dict[str, Any]] = None):
    payload = {"success": False, "error": message}
    if isinstance(extra, dict):
        payload.update(extra)
    if _wants_json_response():
        return jsonify(payload), status_code
    flash(message)
    return redirect(url_for("main.index"))


def build_authorization_required_response(
    *,
    route_key: str = "",
    module_key: str = "",
    sensitivity: str = "operacional_sensivel",
    message: str = "Você não possui acesso a esta área",
    context: Optional[Dict[str, Any]] = None,
    status_code: int = 403,
):
    endpoint = str(request.endpoint or "").strip()
    method = str(request.method or "GET").upper()
    route_key_value = str(route_key or endpoint).strip() or endpoint
    module_value = str(module_key or (endpoint.split(".", 1)[0] if "." in endpoint else "sistema")).strip() or "sistema"
    context_payload = context if isinstance(context, dict) else {}
    try:
        create_endpoint = url_for("reception.reception_create_operational_authz_request")
    except BuildError:
        create_endpoint = "/reception/authz-requests/create"
    payload = {
        "success": False,
        "error": message,
        "authorization_required": True,
        "authorization_request_available": True,
        "authorization_request": {
            "route_key": route_key_value,
            "endpoint": endpoint,
            "method": method,
            "action": f"action.{route_key_value}.{method.lower()}",
            "module": module_value,
            "sensitivity": str(sensitivity or "operacional_sensivel"),
            "create_endpoint": create_endpoint,
            "context": context_payload,
        },
    }
    if _wants_json_response() or str(request.path or "").startswith("/api/"):
        return jsonify(payload), status_code
    try:
        return render_template("access_restricted.html", auth_payload=payload), status_code
    except TemplateNotFound:
        flash(message)
        return redirect(url_for("main.index"))


def handle_authorization_flow_exception(exc: Exception):
    from app.services.authz.runtime_flags import load_runtime_flags

    endpoint = str(request.endpoint or "").strip()
    area = _pilot_critical_area(endpoint, None)
    mode = "shadow"
    try:
        mode = load_runtime_flags().authz_mode
    except Exception:
        mode = "shadow"
    trace_id = _current_request_id()
    current_app.logger.error(
        "authz_fail_closed_exception %s",
        json.dumps(
            {
                "area": area or "non_critical",
                "endpoint": endpoint,
                "mode": mode,
                "exception": f"{type(exc).__name__}: {str(exc)}",
                "trace_id": trace_id,
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    if area in PILOT_CRITICAL_AREAS and mode in ("warn_enforce", "enforce"):
        return _pilot_deny_response(
            "Acesso negado por falha de segurança no fluxo de autorização.",
            extra={
                "reason_code": "AUTHZ_FAIL_CLOSED_EXCEPTION",
                "pilot_critical_area": area,
                "trace_id": trace_id,
            },
        )
    return None


def _get_override_service():
    global _OVERRIDE_SERVICE_SINGLETON
    if _OVERRIDE_SERVICE_SINGLETON is None:
        from app.services.authz.override_service import OverrideService

        _OVERRIDE_SERVICE_SINGLETON = OverrideService(sink=_shadow_audit_sink)
    return _OVERRIDE_SERVICE_SINGLETON


def _record_shadow_trace(payload: Dict[str, Any]) -> None:
    if not bool(getattr(current_app, "testing", False)):
        return
    trace = current_app.extensions.setdefault("authz_shadow_trace", [])
    if isinstance(trace, list):
        trace.append(payload)


def run_shadow_authorization_probe():
    if getattr(g, "_authz_shadow_done", False):
        return None
    g._authz_shadow_done = True
    if not _is_shadow_eligible_request():
        return None

    from app.services.authz.audit_authz import emit_authz_decision_event
    from app.services.authz.compatibility_adapter import build_grant_from_session
    from app.services.authz.permission_engine import evaluate

    runtime_flags = _load_probe_runtime_flags()
    endpoint = str(request.endpoint or "").strip()
    request_context: Dict[str, Any] = {
        "request_id": _current_request_id(),
        "endpoint": endpoint,
        "method": request.method,
        "action": request.method,
        "authenticated": bool(session.get("user")),
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
    }

    registry, registry_error = _load_policy_registry_cached()
    policy = None
    if registry is not None:
        policy = registry.get_policy(endpoint)
        if policy is None:
            request_context["policy_missing_sensitive"] = _resolve_policy_missing_sensitive(endpoint, runtime_flags)
    else:
        request_context["policy_missing_sensitive"] = _resolve_policy_missing_sensitive(endpoint, runtime_flags)
        request_context["policy_registry_error"] = registry_error

    users = _load_users_cached()
    dept_perms = _load_department_permissions_cached()
    grants = None
    username = str(session.get("user") or "").strip()
    if username:
        try:
            grants = build_grant_from_session(
                dict(session),
                users=users,
                department_permissions=dept_perms,
                policy_registry=registry,
            )
            request_context["executor_user"] = grants.user.username
            request_context["role"] = grants.user.role
            request_context["department"] = grants.user.department
        except Exception as exc:
            request_context["grant_build_error"] = str(exc)

    pilot_area = _pilot_critical_area(endpoint, policy)
    if pilot_area:
        request_context["pilot_critical_area"] = pilot_area
        request_context["pilot_stage"] = _pilot_stage_for_area(pilot_area)
    if policy is not None:
        request_context["classification"] = str(getattr(policy.sensitivity, "classification", "operacional") or "operacional")
    legacy_metadata = {}
    decorator_conflicts: List[str] = []
    decorator_registry_conflicts: List[str] = []
    view_func = current_app.view_functions.get(endpoint)
    is_public_by_decorator = False
    if callable(view_func):
        legacy_metadata = get_legacy_auth_metadata(view_func)
        is_public_by_decorator = bool(get_policy_metadata(view_func).get("public"))
        decorator_conflicts = get_policy_metadata_conflicts(view_func)
        decorator_registry_conflicts = compare_metadata_with_registry(view_func, policy)
    is_public_by_registry = False
    if registry is not None and hasattr(registry, "is_public_endpoint"):
        try:
            is_public_by_registry = bool(registry.is_public_endpoint(endpoint))
        except Exception:
            is_public_by_registry = False
    endpoint_policy_missing = bool(policy is None and not is_public_by_decorator and not is_public_by_registry)
    if endpoint_policy_missing and _dev_fail_on_policy_missing_enabled():
        current_app.logger.error(
            "authz_dev_policy_missing request_id=%s endpoint=%s area=%s stage=%s mode=%s",
            request_context.get("request_id"),
            endpoint,
            pilot_area or "non_pilot",
            _pilot_stage_for_area(pilot_area),
            runtime_flags.authz_mode,
        )
        raise RuntimeError(f"AUTHZ_DEV_POLICY_MISSING endpoint={endpoint}")

    decision = evaluate(
        request_context=request_context,
        policy=policy,
        grants=grants,
        runtime_flags=runtime_flags,
    )

    audit_runtime_flags = _build_runtime_flags_for_pilot_audit(runtime_flags) if pilot_area else runtime_flags
    emit_result = emit_authz_decision_event(
        decision_payload=decision,
        runtime_flags=audit_runtime_flags,
        request_context=request_context,
        grants_payload=grants,
        policy_payload=policy,
        sink=_shadow_audit_sink,
    )

    legacy_allowed: Optional[bool] = None
    parity_conflict = False
    if username and username in users:
        profile = effective_profile_for_user(username, users, dept_perms)
        legacy_allowed, _ = is_allowed_for_endpoint(
            endpoint,
            user=username,
            user_role=session.get("role"),
            profile=profile,
        )
        new_allowed = decision.decision == "ALLOW"
        parity_conflict = bool(legacy_allowed != new_allowed)
        if parity_conflict:
            current_app.logger.warning(
                "authz_shadow_parity_conflict request_id=%s endpoint=%s area=%s legacy=%s new=%s reason=%s",
                request_context.get("request_id"),
                endpoint,
                pilot_area or "non_pilot",
                legacy_allowed,
                new_allowed,
                decision.reason_code,
            )

    current_app.logger.info(
        "authz_pilot_critical_probe request_id=%s endpoint=%s area=%s stage=%s mode=%s decision=%s reason=%s",
        request_context.get("request_id"),
        endpoint,
        pilot_area or "non_pilot",
        _pilot_stage_for_area(pilot_area),
        runtime_flags.authz_mode,
        decision.decision,
        decision.reason_code,
    )
    legacy_decorator_present = bool(legacy_metadata.get("login_required") or legacy_metadata.get("role_required"))
    convergence_area = _is_convergence_area(pilot_area)
    legacy_checks_bypassed = _legacy_checks_bypassed_for_area(pilot_area)
    legacy_fallback_enabled = _legacy_fallback_enabled_for_area(pilot_area)
    manual_redundancy_residual = bool(parity_conflict and decision.decision == "ALLOW" and legacy_allowed is False)
    endpoint_new_only = bool(convergence_area and legacy_checks_bypassed and decision.decision == "ALLOW")
    endpoint_legacy_dependency = bool(convergence_area and legacy_decorator_present)
    legacy_fallback_used = bool(convergence_area and (not legacy_checks_bypassed) and legacy_fallback_enabled and legacy_allowed is not None)
    endpoint_new_without_policy = bool(convergence_area and endpoint_policy_missing)
    endpoint_registry_only = bool(policy is not None and not callable(view_func))
    endpoint_decorator_registry_conflict = bool(len(decorator_registry_conflicts) > 0)
    g.authz_probe_state = {
        "new_authority_active": bool(endpoint_new_only),
        "pilot_area": pilot_area,
        "endpoint": endpoint,
    }
    current_app.logger.info(
        "authz_convergence_probe request_id=%s endpoint=%s area=%s stage=%s new_only=%s legacy_dependency=%s fallback_used=%s manual_redundancy=%s policy_found=%s deny_default_enabled=%s deny_default_ready=%s endpoint_policy_missing=%s endpoint_new_without_policy=%s endpoint_registry_only=%s endpoint_decorator_registry_conflict=%s",
        request_context.get("request_id"),
        endpoint,
        pilot_area or "non_pilot",
        _pilot_stage_for_area(pilot_area),
        endpoint_new_only,
        endpoint_legacy_dependency,
        legacy_fallback_used,
        manual_redundancy_residual,
        policy is not None,
        _global_deny_by_default_enabled(),
        _global_deny_by_default_ready(),
        endpoint_policy_missing,
        endpoint_new_without_policy,
        endpoint_registry_only,
        endpoint_decorator_registry_conflict,
    )

    blocked_by_pilot = False
    if pilot_area and _pilot_enforcement_enabled(pilot_area, runtime_flags):
        if decision.decision == "DENY":
            blocked_by_pilot = True
            response = _pilot_deny_response(
                "Acesso negado pelo piloto crítico de autorização.",
                extra={
                    "reason_code": decision.reason_code,
                    "pilot_critical_area": pilot_area,
                },
            )
        elif decision.decision == "REQUIRE_OVERRIDE":
            blocked_by_pilot = True
            override_id = ""
            try:
                override_service = _get_override_service()
                override_record = override_service.create_from_engine_decision(
                    decision=decision,
                    request_context=request_context,
                    executor_user=str(request_context.get("executor_user") or session.get("user") or "unknown"),
                    request_reason=str(request.headers.get("X-Override-Reason") or "pilot_critical_override_required"),
                )
                override_id = override_record.override_id
            except Exception as exc:
                current_app.logger.warning(
                    "authz_pilot_override_request_failed request_id=%s endpoint=%s error=%s",
                    request_context.get("request_id"),
                    endpoint,
                    str(exc),
                )
            response = _pilot_deny_response(
                "Override obrigatório para esta operação no piloto crítico.",
                extra={
                    "reason_code": decision.reason_code,
                    "pilot_critical_area": pilot_area,
                    "override_id": override_id,
                },
            )
        else:
            response = None
    else:
        response = None

    _record_shadow_trace(
        {
            "request_id": request_context.get("request_id"),
            "endpoint": endpoint,
            "pilot_critical_area": pilot_area,
            "decision": decision.decision,
            "reason_code": decision.reason_code,
            "legacy_allowed": legacy_allowed,
            "parity_conflict": parity_conflict,
            "audit_emitted": emit_result.emitted,
            "policy_missing": policy is None,
            "policy_invalid": decision.reason_code in ("AUTHZ_POLICY_INVALID_SCHEMA", "AUTHZ_POLICY_INVALID_CONFLICT"),
            "pilot_blocked": blocked_by_pilot,
            "global_deny_by_default_enabled": _global_deny_by_default_enabled(),
            "global_deny_by_default_ready": _global_deny_by_default_ready(),
            "legacy_fallback_enabled": legacy_fallback_enabled,
            "legacy_checks_bypassed": legacy_checks_bypassed,
            "legacy_fallback_used": legacy_fallback_used,
            "endpoint_new_only": endpoint_new_only,
            "endpoint_legacy_dependency": endpoint_legacy_dependency,
            "endpoint_manual_redundancy_residual": manual_redundancy_residual,
            "legacy_decorator_present": legacy_decorator_present,
            "decorator_policy_conflicts": list(decorator_conflicts),
            "decorator_registry_conflicts": list(decorator_registry_conflicts),
            "endpoint_policy_missing": endpoint_policy_missing,
            "endpoint_new_without_policy": endpoint_new_without_policy,
            "endpoint_registry_only": endpoint_registry_only,
            "endpoint_decorator_registry_conflict": endpoint_decorator_registry_conflict,
        }
    )
    return response


def legacy_tokens_from_profile(profile: Dict[str, Any]) -> List[str]:
    p = _normalize_profile(profile)
    tokens: Set[str] = set()
    areas = p.get("areas") or {}

    def has_area(area_key: str) -> bool:
        a = areas.get(area_key) or {}
        if bool(a.get("all")):
            return True
        pages = a.get("pages") if isinstance(a.get("pages"), dict) else {}
        return any(bool(v) for v in pages.values())

    if has_area("recepcao"):
        tokens.add("recepcao")
        tokens.add("principal")
    if has_area("restaurante_mirapraia"):
        tokens.add("restaurante_full_access")
        tokens.add("restaurante")
    if has_area("recursos_humanos"):
        tokens.add("rh")
    if has_area("financeiro"):
        tokens.add("financeiro")
    if has_area("governanca"):
        tokens.add("governanca")
    if has_area("conferencia"):
        tokens.add("conferencia")
    if has_area("estoque_principal"):
        tokens.add("estoque")
    if has_area("cozinha"):
        tokens.add("cozinha")

    return sorted(list(tokens))
