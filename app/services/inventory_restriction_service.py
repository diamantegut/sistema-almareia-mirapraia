import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import INVENTORY_RESTRICTIONS_FILE, INVENTORY_RESTRICTION_LOGS_FILE


class InventoryRestrictionService:
    CATEGORY_ALIASES = {
        'areia': 'Suíte Areia',
        'suite areia': 'Suíte Areia',
        'suíte areia': 'Suíte Areia',
        'mar familia': 'Suíte Mar Família',
        'mar família': 'Suíte Mar Família',
        'suite mar familia': 'Suíte Mar Família',
        'suíte mar família': 'Suíte Mar Família',
        'mar': 'Suíte Mar',
        'suite mar': 'Suíte Mar',
        'suíte mar': 'Suíte Mar',
        'alma com banheira': 'Suíte Alma c/ Banheira',
        'alma banheira': 'Suíte Alma c/ Banheira',
        'suite alma c/ banheira': 'Suíte Alma c/ Banheira',
        'suíte alma c/ banheira': 'Suíte Alma c/ Banheira',
        'alma': 'Suíte Alma',
        'suite alma': 'Suíte Alma',
        'suíte alma': 'Suíte Alma',
        'alma diamante': 'Suíte Master Diamante',
        'master diamante': 'Suíte Master Diamante',
        'suite master diamante': 'Suíte Master Diamante',
        'suíte master diamante': 'Suíte Master Diamante',
    }
    DEFAULT_STATUS = 'open'

    @staticmethod
    def _parse_date(value: Any) -> datetime:
        text = str(value or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(text)

    @classmethod
    def normalize_category(cls, category: Any) -> str:
        raw = str(category or '').strip()
        key = raw.lower().replace('á', 'a').replace('â', 'a').replace('ã', 'a').replace('ç', 'c')
        key = key.replace('é', 'e').replace('ê', 'e').replace('í', 'i').replace('ó', 'o').replace('ô', 'o').replace('ú', 'u')
        key = ' '.join(key.split())
        return cls.CATEGORY_ALIASES.get(key, raw)

    @staticmethod
    def _load_json(path: str, fallback: Any) -> Any:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception:
            return fallback

    @staticmethod
    def _save_json(path: str, payload: Any) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    @classmethod
    def _load_restrictions(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(INVENTORY_RESTRICTIONS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_restrictions(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(INVENTORY_RESTRICTIONS_FILE):
            cls._save_json(INVENTORY_RESTRICTIONS_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(INVENTORY_RESTRICTION_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(INVENTORY_RESTRICTION_LOGS_FILE):
            cls._save_json(INVENTORY_RESTRICTION_LOGS_FILE, rows)

    @classmethod
    def _dates_for_rule(cls, start_date: str, end_date: str, weekdays: Optional[List[str]] = None) -> List[str]:
        return PeriodSelectorService.expand_dates(start_date, end_date, weekdays)

    @classmethod
    def apply_restriction(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        status: str,
        user: str,
        reason: str,
        weekdays: Optional[List[str]] = None,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_category = cls.normalize_category(category)
        clean_reason = str(reason or '').strip()
        if not normalized_category:
            raise ValueError('Categoria obrigatória')
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório')
        new_status = 'closed' if str(status).lower() in ('closed', 'fechado', '0', 'false') else 'open'
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays)
        dates = cls._dates_for_rule(start_date, end_date, normalized_weekdays)
        if not dates:
            return {'updated': 0, 'dates': []}
        restrictions = cls._load_restrictions()
        logs = cls._load_logs()
        now = datetime.now().isoformat()
        updated = 0
        for day in dates:
            key_match = None
            previous_status = cls.DEFAULT_STATUS
            for idx, row in enumerate(restrictions):
                if str(row.get('category')) == normalized_category and str(row.get('date')) == day:
                    key_match = idx
                    previous_status = str(row.get('status') or cls.DEFAULT_STATUS)
                    break
            payload_row = {
                'category': normalized_category,
                'date': day,
                'status': new_status,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
                'reason': clean_reason,
            }
            if key_match is None:
                restrictions.append(payload_row)
            else:
                restrictions[key_match] = payload_row
            if previous_status != new_status:
                updated += 1
            log_item = {
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'previous_status': previous_status,
                'new_status': new_status,
                'origin': origin,
                'reason': clean_reason,
                'weekdays': normalized_weekdays,
            }
            logs.append(log_item)
            LoggerService.log_acao(
                acao='Atualizou restrição de inventário',
                entidade='Inventário',
                detalhes=log_item,
                nivel_severidade='INFO',
                departamento_id='Recepção',
                colaborador_id=user,
            )
        cls._save_restrictions(restrictions)
        cls._save_logs(logs)
        return {
            'updated': updated,
            'dates': dates,
            'category': normalized_category,
            'status': new_status,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def get_status_for_day(cls, category: str, day: str) -> str:
        normalized_category = cls.normalize_category(category)
        date_key = cls._parse_date(day).date().isoformat()
        for row in cls._load_restrictions():
            if str(row.get('category')) == normalized_category and str(row.get('date')) == date_key:
                return str(row.get('status') or cls.DEFAULT_STATUS)
        return cls.DEFAULT_STATUS

    @classmethod
    def is_open_for_period(cls, category: str, checkin: str, checkout: str) -> bool:
        start = cls._parse_date(checkin).date()
        end = cls._parse_date(checkout).date()
        if end < start:
            start, end = end, start
        normalized_category = cls.normalize_category(category)
        restricted = {(str(row.get('category')), str(row.get('date'))): str(row.get('status') or cls.DEFAULT_STATUS) for row in cls._load_restrictions()}
        current = start
        while current < end:
            key = (normalized_category, current.isoformat())
            if restricted.get(key) == 'closed':
                return False
            current += timedelta(days=1)
        return True

    @classmethod
    def closed_categories_for_day(cls, day: str) -> List[str]:
        date_key = cls._parse_date(day).date().isoformat()
        closed = []
        for row in cls._load_restrictions():
            if str(row.get('date')) == date_key and str(row.get('status')) == 'closed':
                closed.append(str(row.get('category')))
        return sorted(set(closed))

    @classmethod
    def list_restrictions(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_restrictions()
        category_norm = cls.normalize_category(category) if category else None
        start = cls._parse_date(start_date).date() if start_date else None
        end = cls._parse_date(end_date).date() if end_date else None
        out = []
        for row in rows:
            day = str(row.get('date') or '')
            cat = str(row.get('category') or '')
            if category_norm and cat != category_norm:
                continue
            try:
                day_date = cls._parse_date(day).date()
            except Exception:
                continue
            if start and day_date < start:
                continue
            if end and day_date > end:
                continue
            out.append(row)
        out.sort(key=lambda item: (item.get('date') or '', item.get('category') or ''))
        return out

    @classmethod
    def list_logs(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, user: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_logs()
        category_norm = cls.normalize_category(category) if category else None
        start = cls._parse_date(start_date).date() if start_date else None
        end = cls._parse_date(end_date).date() if end_date else None
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            day = str(row.get('day_affected') or row.get('date') or '')
            cat = str(row.get('category') or '')
            row_user = str(row.get('user') or '').strip().lower()
            try:
                day_date = cls._parse_date(day).date()
            except Exception:
                continue
            if start and day_date < start:
                continue
            if end and day_date > end:
                continue
            if category_norm and cat != category_norm:
                continue
            if user_norm and row_user != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out
