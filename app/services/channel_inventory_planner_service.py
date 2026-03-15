from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.inventory_protection_service import InventoryProtectionService
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_INVENTORY_AUDIT_FILE,
    CHANNEL_MANAGER_INVENTORY_PARTIAL_CLOSURES_FILE,
    CHANNEL_MANAGER_INVENTORY_SHARED_FILE,
)


class ChannelInventoryPlannerService:
    @classmethod
    def _load_json(cls, path: str, fallback: Any) -> Any:
        from app.services.revenue_management_service import RevenueManagementService

        loaded = RevenueManagementService._load_json(path, fallback)
        if isinstance(fallback, list):
            return loaded if isinstance(loaded, list) else []
        if isinstance(fallback, dict):
            return loaded if isinstance(loaded, dict) else {}
        return loaded

    @classmethod
    def _save_json(cls, path: str, payload: Any) -> None:
        from app.services.revenue_management_service import RevenueManagementService
        from app.services.cashier_service import file_lock

        with file_lock(path):
            RevenueManagementService._save_json(path, payload)

    @classmethod
    def _normalize_category(cls, category: Any) -> str:
        return ChannelInventoryControlService._normalize_category(category)

    @classmethod
    def _normalize_channel(cls, channel_name: Any) -> str:
        return ChannelInventoryControlService._normalize_channel(channel_name)

    @classmethod
    def _normalize_weekdays(cls, weekdays: Optional[List[str]]) -> List[str]:
        return PeriodSelectorService.normalize_weekdays(weekdays or [])

    @classmethod
    def _status_allows_count(cls, status: Any) -> bool:
        text = str(status or '').strip().lower()
        return 'cancel' not in text

    @classmethod
    def _reservation_overlaps_day(cls, reservation: Dict[str, Any], day_iso: str) -> bool:
        try:
            checkin = PeriodSelectorService.parse_date(str(reservation.get('checkin'))).date()
            checkout = PeriodSelectorService.parse_date(str(reservation.get('checkout'))).date()
            day = PeriodSelectorService.parse_date(day_iso).date()
            return checkin <= day < checkout
        except Exception:
            return False

    @classmethod
    def _category_capacity(cls, category: str) -> int:
        from app.services.reservation_service import ReservationService

        mapping = ReservationService().get_room_mapping()
        return len(mapping.get(category, []))

    @classmethod
    def _load_shared_rows(cls) -> List[Dict[str, Any]]:
        return cls._load_json(CHANNEL_MANAGER_INVENTORY_SHARED_FILE, [])

    @classmethod
    def _load_partial_rows(cls) -> List[Dict[str, Any]]:
        return cls._load_json(CHANNEL_MANAGER_INVENTORY_PARTIAL_CLOSURES_FILE, [])

    @classmethod
    def _append_audit(cls, item: Dict[str, Any]) -> None:
        rows = cls._load_json(CHANNEL_MANAGER_INVENTORY_AUDIT_FILE, [])
        rows.append(item)
        cls._save_json(CHANNEL_MANAGER_INVENTORY_AUDIT_FILE, rows)

    @classmethod
    def _shared_enabled_for_day(cls, *, category: str, day_iso: str) -> bool:
        normalized = cls._normalize_category(category)
        enabled = True
        for row in cls._load_shared_rows():
            if not isinstance(row, dict):
                continue
            if str(row.get('category') or '') != normalized:
                continue
            if str(row.get('date') or '') != str(day_iso):
                continue
            enabled = bool(row.get('shared_global_enabled'))
        return enabled

    @classmethod
    def _partial_closed_rooms(cls, *, category: str, channel: str, day_iso: str) -> int:
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        value = 0
        for row in cls._load_partial_rows():
            if not isinstance(row, dict):
                continue
            if str(row.get('category') or '') != normalized_category:
                continue
            if str(row.get('channel') or '') != normalized_channel:
                continue
            if str(row.get('date') or '') != str(day_iso):
                continue
            try:
                value = max(value, int(row.get('closed_rooms') or 0))
            except Exception:
                continue
        return value

    @classmethod
    def set_shared_inventory(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        shared_global_enabled: bool,
        user: str,
        reason: str,
    ) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para ajustar inventário compartilhado.')
        normalized_category = cls._normalize_category(category)
        days = PeriodSelectorService.expand_dates(start_date, end_date, cls._normalize_weekdays(weekdays))
        rows = cls._load_shared_rows()
        now = datetime.now().isoformat(timespec='seconds')
        updated = 0
        day_set = set(days)
        remaining = [
            row for row in rows
            if not (
                isinstance(row, dict)
                and str(row.get('category') or '') == normalized_category
                and str(row.get('date') or '') in day_set
            )
        ]
        for day in days:
            remaining.append({
                'id': str(uuid.uuid4()),
                'category': normalized_category,
                'date': day,
                'shared_global_enabled': bool(shared_global_enabled),
                'updated_at': now,
                'updated_by': user,
            })
            updated += 1
        cls._save_json(CHANNEL_MANAGER_INVENTORY_SHARED_FILE, remaining)
        cls._append_audit({
            'id': str(uuid.uuid4()),
            'timestamp': now,
            'user': user,
            'event_type': 'shared_inventory',
            'category': normalized_category,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': cls._normalize_weekdays(weekdays)},
            'new_value': bool(shared_global_enabled),
            'reason': clean_reason,
        })
        return {'updated': updated, 'dates': days, 'shared_global_enabled': bool(shared_global_enabled)}

    @classmethod
    def set_partial_closure(
        cls,
        *,
        category: str,
        channel: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        closed_rooms: int,
        user: str,
        reason: str,
    ) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para fechamento parcial por canal.')
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        try:
            rooms = max(0, int(closed_rooms))
        except Exception:
            raise ValueError('Quantidade inválida para fechamento parcial.')
        capacity = cls._category_capacity(normalized_category)
        if rooms > capacity:
            raise ValueError('Fechamento parcial não pode exceder capacidade real da categoria.')
        days = PeriodSelectorService.expand_dates(start_date, end_date, cls._normalize_weekdays(weekdays))
        now = datetime.now().isoformat(timespec='seconds')
        rows = cls._load_partial_rows()
        day_set = set(days)
        remaining = [
            row for row in rows
            if not (
                isinstance(row, dict)
                and str(row.get('category') or '') == normalized_category
                and str(row.get('channel') or '') == normalized_channel
                and str(row.get('date') or '') in day_set
            )
        ]
        for day in days:
            remaining.append({
                'id': str(uuid.uuid4()),
                'category': normalized_category,
                'channel': normalized_channel,
                'date': day,
                'closed_rooms': rooms,
                'updated_at': now,
                'updated_by': user,
            })
        cls._save_json(CHANNEL_MANAGER_INVENTORY_PARTIAL_CLOSURES_FILE, remaining)
        cls._append_audit({
            'id': str(uuid.uuid4()),
            'timestamp': now,
            'user': user,
            'event_type': 'partial_channel_closure',
            'category': normalized_category,
            'channel': normalized_channel,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': cls._normalize_weekdays(weekdays)},
            'new_value': rooms,
            'reason': clean_reason,
        })
        return {'updated': len(days), 'dates': days, 'closed_rooms': rooms}

    @classmethod
    def build_snapshot(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
    ) -> Dict[str, Any]:
        from app.services.channel_manager_service import ChannelManagerService
        from app.services.reservation_service import ReservationService

        normalized_category = cls._normalize_category(category)
        days = PeriodSelectorService.expand_dates(start_date, end_date, cls._normalize_weekdays(weekdays))
        channels = [cls._normalize_channel(item.get('name')) for item in ChannelManagerService.list_channels() if bool(item.get('active', True))]
        if 'Recepção' not in channels:
            channels.append('Recepção')
        allotments = ChannelInventoryControlService.list_allotments(
            start_date=start_date,
            end_date=end_date,
            category=normalized_category,
        )
        restrictions = ChannelInventoryControlService.list_channel_restrictions(
            start_date=start_date,
            end_date=end_date,
            category=normalized_category,
        )
        protections = InventoryProtectionService.list_rules(
            start_date=start_date,
            end_date=end_date,
            category=normalized_category,
        )
        reservations = ReservationService().get_february_reservations()
        capacity = cls._category_capacity(normalized_category)
        allotment_map: Dict[tuple, int] = {}
        for row in allotments:
            key = (str(row.get('date') or ''), cls._normalize_channel(row.get('channel')))
            allotment_map[key] = int(row.get('rooms') or 0)
        restriction_map: Dict[tuple, str] = {}
        for row in restrictions:
            key = (str(row.get('date') or ''), cls._normalize_channel(row.get('channel')))
            restriction_map[key] = str(row.get('status') or 'inactive')
        protection_map: Dict[str, int] = {}
        for row in protections:
            if str(row.get('status') or '') != 'active':
                continue
            day = str(row.get('date') or '')
            protection_map[day] = max(protection_map.get(day, 0), int(row.get('protected_rooms') or 0))
        rows: List[Dict[str, Any]] = []
        for day in days:
            sold_total = 0
            sold_by_channel: Dict[str, int] = {channel: 0 for channel in channels}
            for reservation in reservations:
                if not isinstance(reservation, dict):
                    continue
                if not cls._status_allows_count(reservation.get('status')):
                    continue
                if cls._normalize_category(reservation.get('category')) != normalized_category:
                    continue
                if not cls._reservation_overlaps_day(reservation, day):
                    continue
                sold_total += 1
                res_channel = cls._normalize_channel(reservation.get('channel') or reservation.get('origin'))
                sold_by_channel[res_channel] = sold_by_channel.get(res_channel, 0) + 1
            protected = int(protection_map.get(day, 0))
            shared_enabled = cls._shared_enabled_for_day(category=normalized_category, day_iso=day)
            available_real = max(capacity - sold_total - protected, 0)
            channels_rows = []
            total_allotment = 0
            for channel in channels:
                allotment = int(allotment_map.get((day, channel), 0))
                total_allotment += max(0, allotment)
                partial_closed = cls._partial_closed_rooms(category=normalized_category, channel=channel, day_iso=day)
                fully_closed = restriction_map.get((day, channel)) == 'active'
                sold_channel = int(sold_by_channel.get(channel, 0))
                channels_rows.append({
                    'channel': channel,
                    'allotment': allotment,
                    'sold_existing': sold_channel,
                    'partial_closed_rooms': partial_closed,
                    'fully_closed': fully_closed,
                })
            shared_pool = max(available_real - total_allotment, 0) if shared_enabled else 0
            for item in channels_rows:
                quota = int(item.get('allotment') or 0)
                base_available = quota if quota > 0 else shared_pool
                sellable_stock = max(base_available - int(item.get('partial_closed_rooms') or 0), 0)
                if item.get('fully_closed'):
                    sellable_stock = 0
                item['available_for_sale'] = max(sellable_stock - int(item.get('sold_existing') or 0), 0)
            rows.append({
                'date': day,
                'category': normalized_category,
                'capacity_real': capacity,
                'sold_existing_total': sold_total,
                'protected_rooms': protected,
                'shared_global_enabled': shared_enabled,
                'shared_available_pool': shared_pool,
                'allotment_total': total_allotment,
                'channels': channels_rows,
            })
        return {
            'category': normalized_category,
            'start_date': start_date,
            'end_date': end_date,
            'weekdays': cls._normalize_weekdays(weekdays),
            'rows': rows,
            'count': len(rows),
        }

    @classmethod
    def apply_inventory_plan(cls, *, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        reason = str(payload.get('motivo') or payload.get('reason') or '').strip()
        if len(reason) < 3:
            raise ValueError('Motivo obrigatório para ajustar inventário por canal.')
        category = payload.get('category')
        start_date = payload.get('start_date')
        end_date = payload.get('end_date') or payload.get('start_date')
        weekdays = payload.get('weekdays') or []
        results: Dict[str, Any] = {}
        if 'shared_global_enabled' in payload:
            results['shared'] = cls.set_shared_inventory(
                category=category,
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                shared_global_enabled=bool(payload.get('shared_global_enabled')),
                user=user,
                reason=reason,
            )
        channel = payload.get('channel')
        if 'allotment_rooms' in payload and channel:
            results['allotment'] = ChannelInventoryControlService.apply_allotment(
                category=category,
                channel=channel,
                rooms=payload.get('allotment_rooms'),
                start_date=start_date,
                end_date=end_date,
                user=user,
                weekdays=weekdays,
                origin='channel_inventory_planner',
            )
        if 'protected_rooms' in payload:
            status = 'active' if int(payload.get('protected_rooms') or 0) > 0 else 'inactive'
            results['protection'] = InventoryProtectionService.apply_rule(
                category=category,
                protected_rooms=payload.get('protected_rooms') or 0,
                start_date=start_date,
                end_date=end_date,
                status=status,
                user=user,
                origin='channel_inventory_planner',
            )
        if 'close_total' in payload and channel:
            results['close_total'] = ChannelInventoryControlService.apply_channel_restriction(
                category=category,
                channel=channel,
                start_date=start_date,
                end_date=end_date,
                status='active' if bool(payload.get('close_total')) else 'inactive',
                user=user,
                reason=reason,
                weekdays=weekdays,
                origin='channel_inventory_planner',
            )
        if 'close_partial_rooms' in payload and channel:
            results['close_partial'] = cls.set_partial_closure(
                category=category,
                channel=channel,
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                closed_rooms=int(payload.get('close_partial_rooms') or 0),
                user=user,
                reason=reason,
            )
        snapshot = cls.build_snapshot(
            category=category,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays,
        )
        LoggerService.log_acao(
            acao='Aplicou ajustes de inventário por canal',
            entidade='Channel Manager',
            detalhes={'category': category, 'period': {'start_date': start_date, 'end_date': end_date}, 'channel': channel},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {'results': results, 'snapshot': snapshot}

    @classmethod
    def list_audit_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_INVENTORY_AUDIT_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        normalized_category = cls._normalize_category(category) if category else ''
        normalized_channel = cls._normalize_channel(channel) if channel else ''
        user_filter = str(user or '').strip().lower()
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = str(row.get('timestamp') or '')
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if normalized_category and str(row.get('category') or '') != normalized_category:
                continue
            if normalized_channel and str(row.get('channel') or '') != normalized_channel:
                continue
            if user_filter and str(row.get('user') or '').strip().lower() != user_filter:
                continue
            out.append(row)
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out
