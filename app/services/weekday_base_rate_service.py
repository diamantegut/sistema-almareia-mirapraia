import json
from datetime import datetime
from typing import Any, Dict, List

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.system_config_manager import REVENUE_WEEKDAY_BASE_RATES_FILE


class WeekdayBaseRateService:
    WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    @classmethod
    def _load_json(cls, path: str, fallback: Any) -> Any:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return fallback

    @classmethod
    def _save_json(cls, path: str, payload: Any) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    @classmethod
    def _empty_config(cls) -> Dict[str, Dict[str, float]]:
        return {cat: {k: 0.0 for k in cls.WEEKDAY_KEYS} for cat in ('alma', 'mar', 'areia')}

    @classmethod
    def _default_from_rules(cls) -> Dict[str, Dict[str, float]]:
        from app.services.revenue_management_service import RevenueManagementService
        rules = RevenueManagementService._load_rules()
        out = cls._empty_config()
        for category in ('alma', 'mar', 'areia'):
            base = float((rules.get(category) or {}).get('base_bar') or 0.0)
            for key in cls.WEEKDAY_KEYS:
                out[category][key] = base
        return out

    @classmethod
    def _normalize_row(cls, incoming: Dict[str, Any], defaults: Dict[str, float]) -> Dict[str, float]:
        weekday_rate = incoming.get('weekday_rate')
        weekend_rate = incoming.get('weekend_rate')
        out = {}
        for key in cls.WEEKDAY_KEYS:
            raw_val = incoming.get(key, defaults.get(key, 0.0))
            if key in ('sat', 'sun') and weekend_rate not in (None, ''):
                raw_val = weekend_rate
            if key in ('mon', 'tue', 'wed', 'thu', 'fri') and weekday_rate not in (None, ''):
                raw_val = weekday_rate
            try:
                val = float(raw_val)
            except Exception:
                val = float(defaults.get(key, 0.0))
            out[key] = max(0.0, round(val, 2))
        return out

    @classmethod
    def get_rates(cls) -> Dict[str, Dict[str, float]]:
        loaded = cls._load_json(REVENUE_WEEKDAY_BASE_RATES_FILE, {})
        defaults = cls._default_from_rules()
        out = cls._empty_config()
        for category in ('alma', 'mar', 'areia'):
            row = loaded.get(category) if isinstance(loaded, dict) and isinstance(loaded.get(category), dict) else {}
            out[category] = cls._normalize_row(row, defaults[category])
        return out

    @classmethod
    def save_rates(cls, payload: Dict[str, Any], user: str) -> Dict[str, Dict[str, float]]:
        current = cls.get_rates()
        for category in ('alma', 'mar', 'areia'):
            if category not in payload:
                continue
            incoming = payload.get(category) if isinstance(payload.get(category), dict) else {}
            current[category] = cls._normalize_row(incoming, current[category])
        with file_lock(REVENUE_WEEKDAY_BASE_RATES_FILE):
            cls._save_json(REVENUE_WEEKDAY_BASE_RATES_FILE, current)
        LoggerService.log_acao(
            acao='Atualizou tarifa base por dia da semana',
            entidade='Revenue Management',
            detalhes={'categories': list(payload.keys())},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return current

    @classmethod
    def weekday_key_for_date(cls, date_str: str) -> str:
        day = datetime.strptime(date_str, '%Y-%m-%d').weekday()
        return cls.WEEKDAY_KEYS[day]

    @classmethod
    def base_for_day(cls, category: str, date_str: str, fallback: float) -> float:
        from app.services.revenue_management_service import RevenueManagementService
        rates = cls.get_rates()
        bucket = RevenueManagementService._normalize_category(category)
        weekday_key = cls.weekday_key_for_date(date_str)
        row = rates.get(bucket) or {}
        try:
            value = float(row.get(weekday_key, fallback))
        except Exception:
            value = float(fallback)
        if value <= 0:
            return float(fallback)
        return round(value, 2)

    @classmethod
    def base_total_for_period(cls, category: str, dates: List[str], fallback_daily: float) -> float:
        total = 0.0
        for day in dates:
            total += cls.base_for_day(category, day, fallback_daily)
        return round(total, 2)
