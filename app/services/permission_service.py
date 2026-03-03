from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from flask import current_app, flash, jsonify, redirect, request, session, url_for

from app.services.data_service import load_department_permissions, load_users, normalize_text


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
    "restaurante_mirapraia": "Restaurante Mirapraia",
    "recepcao": "Recepção",
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
    if role_norm in ("financeiro", "rh", "cozinha", "estoque", "governanca", "conferencia"):
        if role_norm == "financeiro":
            grant("financeiro")
        if role_norm == "rh":
            grant("recursos_humanos")
        if role_norm == "cozinha":
            grant("cozinha")
        if role_norm == "estoque":
            grant("estoque_principal")
        if role_norm == "governanca":
            grant("governanca")
        if role_norm == "conferencia":
            grant("conferencia")

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

    users = load_users()
    dept_perms = load_department_permissions()

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
