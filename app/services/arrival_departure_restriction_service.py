import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    ARRIVAL_DEPARTURE_RESTRICTIONS_FILE,
    ARRIVAL_DEPARTURE_RESTRICTIONS_LOGS_FILE,
)


class ArrivalDepartureRestrictionService:
    VALID_TYPES = {'cta', 'ctd'}
    VALID_STATUS = {'active', 'inactive'}

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
    def _load_restrictions(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(ARRIVAL_DEPARTURE_RESTRICTIONS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_restrictions(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(ARRIVAL_DEPARTURE_RESTRICTIONS_FILE):
            cls._save_json(ARRIVAL_DEPARTURE_RESTRICTIONS_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(ARRIVAL_DEPARTURE_RESTRICTIONS_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(ARRIVAL_DEPARTURE_RESTRICTIONS_LOGS_FILE):
            cls._save_json(ARRIVAL_DEPARTURE_RESTRICTIONS_LOGS_FILE, rows)

    @classmethod
    def _normalize_type(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        return text if text in cls.VALID_TYPES else ''

    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        return text if text in cls.VALID_STATUS else 'inactive'

    @classmethod
    def apply_restriction(
        cls,
        *,
        restriction_type: str,
        category: str,
        start_date: str,
        end_date: str,
        status: str,
        user: str,
        reason: str,
        weekdays: Optional[List[str]] = None,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_type = cls._normalize_type(restriction_type)
        if not normalized_type:
            raise ValueError('Tipo de restrição inválido')
        normalized_category = InventoryRestrictionService.normalize_category(category)
        if not normalized_category:
            raise ValueError('Categoria obrigatória')
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório')
        normalized_status = cls._normalize_status(status)
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays if normalized_type == 'cta' else [])
        dates = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        if not dates:
            return {'updated': 0, 'dates': []}
        restrictions = cls._load_restrictions()
        logs = cls._load_logs()
        now = datetime.now().isoformat()
        updated = 0
        for day in dates:
            key_match = None
            previous_status = 'inactive'
            for idx, row in enumerate(restrictions):
                if (
                    str(row.get('category')) == normalized_category
                    and str(row.get('date')) == day
                    and str(row.get('restriction_type')) == normalized_type
                ):
                    key_match = idx
                    previous_status = str(row.get('status') or 'inactive')
                    break
            payload_row = {
                'restriction_type': normalized_type,
                'category': normalized_category,
                'date': day,
                'status': normalized_status,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
                'reason': clean_reason,
            }
            if key_match is None:
                restrictions.append(payload_row)
            else:
                restrictions[key_match] = payload_row
            if previous_status != normalized_status:
                updated += 1
            log_item = {
                'timestamp': now,
                'user': user,
                'restriction_type': normalized_type,
                'category': normalized_category,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'previous_status': previous_status,
                'new_status': normalized_status,
                'origin': origin,
                'reason': clean_reason,
                'weekdays': normalized_weekdays,
            }
            logs.append(log_item)
            LoggerService.log_acao(
                acao='Atualizou restrição CTA/CTD',
                entidade='Revenue Management',
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
            'restriction_type': normalized_type,
            'category': normalized_category,
            'status': normalized_status,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def list_restrictions(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        restriction_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_restrictions()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = InventoryRestrictionService.normalize_category(category) if category else ''
        type_norm = cls._normalize_type(restriction_type) if restriction_type else ''
        status_norm = cls._normalize_status(status) if status else ''
        out = []
        for row in rows:
            day_text = str(row.get('date') or '')
            try:
                day = PeriodSelectorService.parse_date(day_text).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category')) != category_norm:
                continue
            if type_norm and str(row.get('restriction_type')) != type_norm:
                continue
            if status_norm and str(row.get('status')) != status_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (item.get('date') or '', item.get('restriction_type') or '', item.get('category') or ''))
        return out

    @classmethod
    def list_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user: Optional[str] = None,
        category: Optional[str] = None,
        restriction_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = InventoryRestrictionService.normalize_category(category) if category else ''
        type_norm = cls._normalize_type(restriction_type) if restriction_type else ''
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            day_text = str(row.get('day_affected') or row.get('date') or '')
            try:
                day = PeriodSelectorService.parse_date(day_text).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category')) != category_norm:
                continue
            if type_norm and str(row.get('restriction_type')) != type_norm:
                continue
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def validate_period(cls, *, category: str, checkin: str, checkout: str) -> Dict[str, Any]:
        normalized_category = InventoryRestrictionService.normalize_category(category)
        checkin_day = PeriodSelectorService.parse_date(checkin).date().isoformat()
        checkout_day = PeriodSelectorService.parse_date(checkout).date().isoformat()
        active = {}
        for row in cls._load_restrictions():
            if str(row.get('status')) != 'active':
                continue
            key = (str(row.get('category')), str(row.get('date')), str(row.get('restriction_type')))
            active[key] = row
        cta_key = (normalized_category, checkin_day, 'cta')
        if cta_key in active:
            return {
                'valid': False,
                'message': f'Check-in indisponível em {checkin_day} para esta categoria (CTA ativo).',
                'restriction': active[cta_key],
            }
        ctd_key = (normalized_category, checkout_day, 'ctd')
        if ctd_key in active:
            return {
                'valid': False,
                'message': f'Check-out indisponível em {checkout_day} para esta categoria (CTD ativo).',
                'restriction': active[ctd_key],
            }
        return {'valid': True, 'message': '', 'restriction': None}
