import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    INVENTORY_PROTECTION_LOGS_FILE,
    INVENTORY_PROTECTION_RULES_FILE,
)


class InventoryProtectionService:
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
    def _load_rules(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(INVENTORY_PROTECTION_RULES_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_rules(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(INVENTORY_PROTECTION_RULES_FILE):
            cls._save_json(INVENTORY_PROTECTION_RULES_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(INVENTORY_PROTECTION_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(INVENTORY_PROTECTION_LOGS_FILE):
            cls._save_json(INVENTORY_PROTECTION_LOGS_FILE, rows)

    @classmethod
    def apply_rule(
        cls,
        *,
        category: str,
        protected_rooms: int,
        start_date: str,
        end_date: str,
        status: str,
        user: str,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_category = InventoryRestrictionService.normalize_category(category)
        if not normalized_category:
            raise ValueError('Categoria obrigatória')
        try:
            protected = int(protected_rooms)
        except Exception:
            raise ValueError('Quantidade de quartos protegidos inválida')
        if protected < 0:
            raise ValueError('Quantidade de quartos protegidos inválida')
        normalized_status = 'active' if str(status or '').strip().lower() in ('active', 'ativo', '1', 'true') else 'inactive'
        dates = PeriodSelectorService.expand_dates(start_date, end_date, [])
        if not dates:
            return {'updated': 0, 'dates': []}
        rows = cls._load_rules()
        logs = cls._load_logs()
        now = datetime.now().isoformat()
        updated = 0
        for day in dates:
            key_match = None
            previous = {'status': 'inactive', 'protected_rooms': 0}
            for idx, row in enumerate(rows):
                if str(row.get('category')) == normalized_category and str(row.get('date')) == day:
                    key_match = idx
                    previous = {
                        'status': str(row.get('status') or 'inactive'),
                        'protected_rooms': int(row.get('protected_rooms') or 0),
                    }
                    break
            payload = {
                'category': normalized_category,
                'date': day,
                'status': normalized_status,
                'protected_rooms': protected,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
            }
            if key_match is None:
                rows.append(payload)
            else:
                rows[key_match] = payload
            if previous.get('status') != normalized_status or int(previous.get('protected_rooms') or 0) != protected:
                updated += 1
            logs.append({
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'previous_status': previous.get('status'),
                'new_status': normalized_status,
                'previous_protected_rooms': int(previous.get('protected_rooms') or 0),
                'new_protected_rooms': protected,
                'origin': origin,
            })
        cls._save_rules(rows)
        cls._save_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou proteção de inventário',
            entidade='Revenue Management',
            detalhes={'category': normalized_category, 'protected_rooms': protected, 'status': normalized_status, 'dates': dates},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'updated': updated,
            'dates': dates,
            'category': normalized_category,
            'protected_rooms': protected,
            'status': normalized_status,
            'period': {'start_date': start_date, 'end_date': end_date},
        }

    @classmethod
    def _active_protected_for_day(cls, category: str, day_iso: str) -> int:
        normalized_category = InventoryRestrictionService.normalize_category(category)
        protected = 0
        for row in cls._load_rules():
            if str(row.get('status')) != 'active':
                continue
            if str(row.get('category')) != normalized_category:
                continue
            if str(row.get('date')) != day_iso:
                continue
            protected = max(protected, int(row.get('protected_rooms') or 0))
        return protected

    @classmethod
    def _category_capacity(cls, category: str) -> int:
        from app.services.reservation_service import ReservationService
        mapping = ReservationService().get_room_mapping()
        normalized = InventoryRestrictionService.normalize_category(category)
        return len(mapping.get(normalized, []))

    @classmethod
    def _reservation_status_allows_count(cls, status: Any) -> bool:
        text = str(status or '').strip().lower()
        return 'cancel' not in text

    @classmethod
    def _reservation_overlaps_day(cls, reservation: Dict[str, Any], day_iso: str) -> bool:
        try:
            day = PeriodSelectorService.parse_date(day_iso).date()
            checkin = PeriodSelectorService.parse_date(str(reservation.get('checkin'))).date()
            checkout = PeriodSelectorService.parse_date(str(reservation.get('checkout'))).date()
            return checkin <= day < checkout
        except Exception:
            return False

    @classmethod
    def validate_sale(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
    ) -> Dict[str, Any]:
        normalized_category = InventoryRestrictionService.normalize_category(category)
        capacity = cls._category_capacity(normalized_category)
        if capacity <= 0:
            return {'valid': True, 'message': '', 'day': None}
        from app.services.reservation_service import ReservationService
        reservations = ReservationService().get_february_reservations()
        stay_days = []
        start = PeriodSelectorService.parse_date(checkin).date()
        end = PeriodSelectorService.parse_date(checkout).date()
        current = start
        while current < end:
            stay_days.append(current.isoformat())
            current = current.fromordinal(current.toordinal() + 1)
        for day in stay_days:
            protected = cls._active_protected_for_day(normalized_category, day)
            if protected <= 0:
                continue
            allowed = max(capacity - protected, 0)
            sold = 0
            for reservation in reservations:
                if not isinstance(reservation, dict):
                    continue
                if not cls._reservation_status_allows_count(reservation.get('status')):
                    continue
                if InventoryRestrictionService.normalize_category(reservation.get('category')) != normalized_category:
                    continue
                if cls._reservation_overlaps_day(reservation, day):
                    sold += 1
            if sold >= allowed:
                return {
                    'valid': False,
                    'message': f'Proteção de inventário ativa em {day}: {protected} quarto(s) reservado(s) para venda de última hora.',
                    'day': day,
                    'capacity': capacity,
                    'protected_rooms': protected,
                    'allowed_for_presale': allowed,
                    'sold': sold,
                }
        return {'valid': True, 'message': '', 'day': None}

    @classmethod
    def list_rules(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_rules()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = InventoryRestrictionService.normalize_category(category) if category else ''
        out = []
        for row in rows:
            try:
                day = PeriodSelectorService.parse_date(str(row.get('date') or '')).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category')) != category_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (item.get('date') or '', item.get('category') or ''))
        return out

    @classmethod
    def list_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = InventoryRestrictionService.normalize_category(category) if category else ''
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            try:
                day = PeriodSelectorService.parse_date(str(row.get('day_affected') or '')).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category')) != category_norm:
                continue
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out
