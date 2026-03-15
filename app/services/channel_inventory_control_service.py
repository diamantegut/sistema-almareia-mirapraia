import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    BLACKOUT_DATES_FILE,
    BLACKOUT_DATES_LOGS_FILE,
    CHANNEL_ALLOTMENTS_FILE,
    CHANNEL_ALLOTMENTS_LOGS_FILE,
    CHANNEL_SALES_RESTRICTIONS_FILE,
    CHANNEL_SALES_RESTRICTIONS_LOGS_FILE,
)


class ChannelInventoryControlService:
    CHANNEL_ALIASES = {
        'booking': 'Booking.com',
        'booking.com': 'Booking.com',
        'expedia': 'Expedia',
        'motor': 'Motor de Reservas',
        'motor de reservas': 'Motor de Reservas',
        'recepcao': 'Recepção',
        'recepção': 'Recepção',
        'direto': 'Recepção',
        'telefone': 'Telefone',
        'whatsapp': 'WhatsApp',
        'airbnb': 'Airbnb',
    }
    ALL_CATEGORIES_VALUE = '__ALL__'

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
    def _normalize_channel(cls, channel: Any) -> str:
        raw = str(channel or '').strip()
        key = raw.lower().replace('ç', 'c').replace('ã', 'a').replace('á', 'a').replace('é', 'e').replace('ê', 'e')
        key = ' '.join(key.split())
        return cls.CHANNEL_ALIASES.get(key, raw or 'Recepção')

    @classmethod
    def _normalize_category(cls, category: Any) -> str:
        raw = str(category or '').strip()
        if not raw:
            raise ValueError('Categoria obrigatória')
        if raw.lower() in ('todas', 'todos', 'hotel inteiro', 'hotel', '*'):
            return cls.ALL_CATEGORIES_VALUE
        return InventoryRestrictionService.normalize_category(raw)

    @classmethod
    def _normalize_status(cls, status: Any) -> str:
        return 'active' if str(status or '').strip().lower() in ('active', 'ativo', '1', 'true') else 'inactive'

    @classmethod
    def _stay_dates(cls, checkin: str, checkout: str) -> List[str]:
        start = PeriodSelectorService.parse_date(checkin).date()
        end = PeriodSelectorService.parse_date(checkout).date()
        out = []
        current = start
        while current < end:
            out.append(current.isoformat())
            current = current.fromordinal(current.toordinal() + 1)
        return out

    @classmethod
    def _load_channel_rules(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(CHANNEL_SALES_RESTRICTIONS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_channel_rules(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(CHANNEL_SALES_RESTRICTIONS_FILE):
            cls._save_json(CHANNEL_SALES_RESTRICTIONS_FILE, rows)

    @classmethod
    def _load_channel_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(CHANNEL_SALES_RESTRICTIONS_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_channel_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(CHANNEL_SALES_RESTRICTIONS_LOGS_FILE):
            cls._save_json(CHANNEL_SALES_RESTRICTIONS_LOGS_FILE, rows)

    @classmethod
    def _load_blackouts(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(BLACKOUT_DATES_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_blackouts(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(BLACKOUT_DATES_FILE):
            cls._save_json(BLACKOUT_DATES_FILE, rows)

    @classmethod
    def _load_blackout_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(BLACKOUT_DATES_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_blackout_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(BLACKOUT_DATES_LOGS_FILE):
            cls._save_json(BLACKOUT_DATES_LOGS_FILE, rows)

    @classmethod
    def _load_allotments(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(CHANNEL_ALLOTMENTS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_allotments(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(CHANNEL_ALLOTMENTS_FILE):
            cls._save_json(CHANNEL_ALLOTMENTS_FILE, rows)

    @classmethod
    def _load_allotment_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(CHANNEL_ALLOTMENTS_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_allotment_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(CHANNEL_ALLOTMENTS_LOGS_FILE):
            cls._save_json(CHANNEL_ALLOTMENTS_LOGS_FILE, rows)

    @classmethod
    def apply_channel_restriction(
        cls,
        *,
        category: str,
        channel: str,
        start_date: str,
        end_date: str,
        status: str,
        user: str,
        reason: str = '',
        weekdays: Optional[List[str]] = None,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        normalized_status = cls._normalize_status(status)
        clean_reason = str(reason or '').strip()
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays)
        dates = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        if not dates:
            return {'updated': 0, 'dates': []}
        rows = cls._load_channel_rules()
        logs = cls._load_channel_logs()
        now = datetime.now().isoformat()
        updated = 0
        for day in dates:
            key_match = None
            previous_status = 'inactive'
            for idx, row in enumerate(rows):
                if (
                    str(row.get('category')) == normalized_category
                    and str(row.get('channel')) == normalized_channel
                    and str(row.get('date')) == day
                ):
                    key_match = idx
                    previous_status = str(row.get('status') or 'inactive')
                    break
            payload = {
                'category': normalized_category,
                'channel': normalized_channel,
                'date': day,
                'status': normalized_status,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
            }
            if key_match is None:
                rows.append(payload)
            else:
                rows[key_match] = payload
            if previous_status != normalized_status:
                updated += 1
            logs.append({
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'channel': normalized_channel,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'previous_status': previous_status,
                'new_status': normalized_status,
                'reason': clean_reason,
                'origin': origin,
                'weekdays': normalized_weekdays,
            })
        cls._save_channel_rules(rows)
        cls._save_channel_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou fechamento por canal',
            entidade='Revenue Management',
            detalhes={'category': normalized_category, 'channel': normalized_channel, 'status': normalized_status, 'reason': clean_reason, 'dates': dates},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'updated': updated,
            'dates': dates,
            'category': normalized_category,
            'channel': normalized_channel,
            'status': normalized_status,
            'reason': clean_reason,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def is_channel_open_for_period(cls, *, category: str, channel: str, checkin: str, checkout: str) -> bool:
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        restricted = {
            (str(row.get('category')), str(row.get('channel')), str(row.get('date'))): str(row.get('status') or 'inactive')
            for row in cls._load_channel_rules()
        }
        for day in cls._stay_dates(checkin, checkout):
            direct_key = (normalized_category, normalized_channel, day)
            all_category_key = (cls.ALL_CATEGORIES_VALUE, normalized_channel, day)
            if restricted.get(direct_key) == 'active' or restricted.get(all_category_key) == 'active':
                return False
        return True

    @classmethod
    def list_channel_restrictions(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_channel_rules()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
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
            if channel_norm and str(row.get('channel')) != channel_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (item.get('date') or '', item.get('category') or '', item.get('channel') or ''))
        return out

    @classmethod
    def list_channel_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_channel_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            day_text = str(row.get('day_affected') or '')
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
            if channel_norm and str(row.get('channel')) != channel_norm:
                continue
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def apply_blackout(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        status: str,
        reason: str,
        user: str,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_category = cls._normalize_category(category)
        normalized_status = cls._normalize_status(status)
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório')
        dates = PeriodSelectorService.expand_dates(start_date, end_date, [])
        if not dates:
            return {'updated': 0, 'dates': []}
        rows = cls._load_blackouts()
        logs = cls._load_blackout_logs()
        now = datetime.now().isoformat()
        updated = 0
        for day in dates:
            key_match = None
            previous_status = 'inactive'
            for idx, row in enumerate(rows):
                if str(row.get('category')) == normalized_category and str(row.get('date')) == day:
                    key_match = idx
                    previous_status = str(row.get('status') or 'inactive')
                    break
            payload = {
                'category': normalized_category,
                'date': day,
                'status': normalized_status,
                'reason': clean_reason,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
            }
            if key_match is None:
                rows.append(payload)
            else:
                rows[key_match] = payload
            if previous_status != normalized_status:
                updated += 1
            logs.append({
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'previous_status': previous_status,
                'new_status': normalized_status,
                'reason': clean_reason,
                'origin': origin,
            })
        cls._save_blackouts(rows)
        cls._save_blackout_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou blackout de venda',
            entidade='Revenue Management',
            detalhes={'category': normalized_category, 'status': normalized_status, 'reason': clean_reason, 'dates': dates},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'updated': updated,
            'dates': dates,
            'category': normalized_category,
            'status': normalized_status,
            'reason': clean_reason,
            'period': {'start_date': start_date, 'end_date': end_date},
        }

    @classmethod
    def is_blackout_for_period(cls, *, category: str, checkin: str, checkout: str) -> bool:
        normalized_category = cls._normalize_category(category)
        active = {
            (str(row.get('category')), str(row.get('date'))): str(row.get('status') or 'inactive')
            for row in cls._load_blackouts()
        }
        for day in cls._stay_dates(checkin, checkout):
            if active.get((normalized_category, day)) == 'active':
                return True
            if active.get((cls.ALL_CATEGORIES_VALUE, day)) == 'active':
                return True
        return False

    @classmethod
    def list_blackouts(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_blackouts()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
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
    def list_blackout_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_blackout_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            day_text = str(row.get('day_affected') or '')
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
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def _category_capacity(cls, category: str) -> int:
        from app.services.reservation_service import ReservationService
        mapping = ReservationService().get_room_mapping()
        return len(mapping.get(category, []))

    @classmethod
    def apply_allotment(
        cls,
        *,
        category: str,
        channel: str,
        rooms: int,
        start_date: str,
        end_date: str,
        user: str,
        weekdays: Optional[List[str]] = None,
        origin: str = 'manual',
    ) -> Dict[str, Any]:
        normalized_category = cls._normalize_category(category)
        if normalized_category == cls.ALL_CATEGORIES_VALUE:
            raise ValueError('Allotment exige categoria específica')
        normalized_channel = cls._normalize_channel(channel)
        try:
            room_quota = int(rooms)
        except Exception:
            raise ValueError('Quantidade de quartos inválida')
        if room_quota < 0:
            raise ValueError('Quantidade de quartos inválida')
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays)
        dates = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        if not dates:
            return {'updated': 0, 'dates': []}
        rows = cls._load_allotments()
        remaining_rows = [
            row for row in rows
            if not (
                str(row.get('category')) == normalized_category
                and str(row.get('channel')) == normalized_channel
                and str(row.get('date')) in set(dates)
            )
        ]
        now = datetime.now().isoformat()
        staged = list(remaining_rows)
        for day in dates:
            staged.append({
                'category': normalized_category,
                'channel': normalized_channel,
                'date': day,
                'rooms': room_quota,
                'updated_at': now,
                'updated_by': user,
                'origin': origin,
            })
        capacity = cls._category_capacity(normalized_category)
        per_day_total = {}
        for row in staged:
            if str(row.get('category')) != normalized_category:
                continue
            day = str(row.get('date'))
            per_day_total[day] = per_day_total.get(day, 0) + int(row.get('rooms') or 0)
        for day in dates:
            if per_day_total.get(day, 0) > capacity:
                raise ValueError(f'Allotment excede capacidade da categoria em {day}.')
        logs = cls._load_allotment_logs()
        for day in dates:
            logs.append({
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'channel': normalized_channel,
                'period_start': start_date,
                'period_end': end_date,
                'day_affected': day,
                'rooms': room_quota,
                'origin': origin,
                'weekdays': normalized_weekdays,
            })
        cls._save_allotments(staged)
        cls._save_allotment_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou allotment por canal',
            entidade='Revenue Management',
            detalhes={'category': normalized_category, 'channel': normalized_channel, 'rooms': room_quota, 'dates': dates},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'updated': len(dates),
            'dates': dates,
            'category': normalized_category,
            'channel': normalized_channel,
            'rooms': room_quota,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def list_allotments(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_allotments()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
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
            if channel_norm and str(row.get('channel')) != channel_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (item.get('date') or '', item.get('category') or '', item.get('channel') or ''))
        return out

    @classmethod
    def list_allotment_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_allotment_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
        user_norm = str(user or '').strip().lower()
        out = []
        for row in rows:
            day_text = str(row.get('day_affected') or '')
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
            if channel_norm and str(row.get('channel')) != channel_norm:
                continue
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def _reservation_status_allows_count(cls, status: Any) -> bool:
        text = str(status or '').strip().lower()
        return 'cancel' not in text

    @classmethod
    def _reservation_overlap_day(cls, reservation: Dict[str, Any], day_iso: str) -> bool:
        try:
            checkin = PeriodSelectorService.parse_date(str(reservation.get('checkin'))).date()
            checkout = PeriodSelectorService.parse_date(str(reservation.get('checkout'))).date()
            day = PeriodSelectorService.parse_date(day_iso).date()
            return checkin <= day < checkout
        except Exception:
            return False

    @classmethod
    def validate_allotment_availability(
        cls,
        *,
        category: str,
        channel: str,
        checkin: str,
        checkout: str,
    ) -> Dict[str, Any]:
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        allotment_map = {}
        for row in cls._load_allotments():
            if str(row.get('category')) != normalized_category:
                continue
            if str(row.get('channel')) != normalized_channel:
                continue
            allotment_map[str(row.get('date'))] = int(row.get('rooms') or 0)
        days = cls._stay_dates(checkin, checkout)
        from app.services.reservation_service import ReservationService
        reservations = ReservationService().get_february_reservations()
        for day in days:
            quota = allotment_map.get(day)
            if quota is None:
                continue
            sold = 0
            for res in reservations:
                if not cls._reservation_status_allows_count(res.get('status')):
                    continue
                res_category = cls._normalize_category(res.get('category'))
                res_channel = cls._normalize_channel(res.get('channel') or res.get('origin'))
                if res_category != normalized_category or res_channel != normalized_channel:
                    continue
                if cls._reservation_overlap_day(res, day):
                    sold += 1
            if sold >= quota:
                return {
                    'valid': False,
                    'message': f'Allotment esgotado para {normalized_channel} em {day} na categoria {normalized_category}.',
                    'day': day,
                    'quota': quota,
                    'sold': sold,
                }
        return {'valid': True, 'message': '', 'day': None}
