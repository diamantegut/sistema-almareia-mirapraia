from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE,
    CHANNEL_MANAGER_TARIFFS_LOGS_FILE,
)


class ChannelCommercialAuditService:
    EVENTS = {
        'mudanca_comissao',
        'mudanca_tarifa',
        'mudanca_inventario',
        'alteracao_open_close',
        'alteracao_cta_ctd',
        'alteracao_min_stay',
        'alteracao_pacote',
        'alteracao_promocao',
    }

    @classmethod
    def _load_json(cls, path: str, fallback: Any) -> Any:
        from app.services.revenue_management_service import RevenueManagementService

        loaded = RevenueManagementService._load_json(path, fallback)
        if isinstance(fallback, list):
            return loaded if isinstance(loaded, list) else []
        return loaded

    @classmethod
    def _save_json(cls, path: str, payload: Any) -> None:
        from app.services.revenue_management_service import RevenueManagementService

        with file_lock(path):
            RevenueManagementService._save_json(path, payload)

    @classmethod
    def _normalize_event(cls, event_type: Any) -> str:
        text = str(event_type or '').strip().lower()
        if text not in cls.EVENTS:
            raise ValueError('Evento de auditoria comercial inválido.')
        return text

    @classmethod
    def append_event(
        cls,
        *,
        event_type: str,
        channel: str,
        category: str,
        previous_value: Any,
        new_value: Any,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para auditoria comercial.')
        now = datetime.now().isoformat(timespec='seconds')
        row = {
            'id': str(uuid.uuid4()),
            'timestamp': now,
            'user': str(user or 'Sistema'),
            'event_type': cls._normalize_event(event_type),
            'channel': str(channel or '').strip(),
            'category': str(category or '').strip(),
            'previous_value': previous_value,
            'new_value': new_value,
            'reason': clean_reason,
        }
        rows = cls._load_json(CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE, [])
        rows.append(row)
        cls._save_json(CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE, rows)
        return row

    @classmethod
    def list_events(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_type: Optional[str] = None,
        channel: Optional[str] = None,
        category: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        event_filter = str(event_type or '').strip().lower()
        channel_filter = str(channel or '').strip().lower()
        category_filter = str(category or '').strip().lower()
        user_filter = str(user or '').strip().lower()
        out: List[Dict[str, Any]] = []
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
            if event_filter and str(row.get('event_type') or '').strip().lower() != event_filter:
                continue
            if channel_filter and str(row.get('channel') or '').strip().lower() != channel_filter:
                continue
            if category_filter and str(row.get('category') or '').strip().lower() != category_filter:
                continue
            if user_filter and str(row.get('user') or '').strip().lower() != user_filter:
                continue
            out.append(row)
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out

    @classmethod
    def _event_from_restriction_type(cls, restriction_type: str) -> str:
        text = str(restriction_type or '').strip().lower()
        if text in ('cta', 'ctd'):
            return 'alteracao_cta_ctd'
        if text == 'min_stay':
            return 'alteracao_min_stay'
        if text == 'pacote_obrigatorio':
            return 'alteracao_pacote'
        if text == 'promocao_especifica':
            return 'alteracao_promocao'
        if text in ('aberto_fechado', 'stop_sell'):
            return 'alteracao_open_close'
        return 'alteracao_open_close'

    @classmethod
    def list_consolidated(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_type: Optional[str] = None,
        channel: Optional[str] = None,
        category: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        out.extend(cls.list_events(
            start_date=start_date,
            end_date=end_date,
            event_type=event_type,
            channel=channel,
            category=category,
            user=user,
        ))
        try:
            from app.services.channel_commission_service import ChannelCommissionService

            for row in ChannelCommissionService.list_audit_logs(
                start_date=start_date,
                end_date=end_date,
                channel=channel,
                user=user,
            ):
                out.append({
                    'id': row.get('id'),
                    'timestamp': row.get('timestamp'),
                    'user': row.get('user'),
                    'event_type': 'mudanca_comissao',
                    'channel': row.get('channel'),
                    'category': row.get('category') or '',
                    'previous_value': row.get('previous_value'),
                    'new_value': row.get('new_value'),
                    'reason': row.get('reason') or '',
                })
        except Exception:
            pass
        try:
            tariff_logs = cls._load_json(CHANNEL_MANAGER_TARIFFS_LOGS_FILE, [])
            for row in tariff_logs:
                if not isinstance(row, dict):
                    continue
                out.append({
                    'id': row.get('id') or str(uuid.uuid4()),
                    'timestamp': row.get('timestamp') or row.get('updated_at'),
                    'user': row.get('user') or row.get('updated_by'),
                    'event_type': 'mudanca_tarifa',
                    'channel': row.get('channel_name') or row.get('channel'),
                    'category': row.get('category') or '',
                    'previous_value': row.get('before') or {},
                    'new_value': row.get('after') or row.get('rule') or {},
                    'reason': row.get('reason') or row.get('motivo') or '',
                })
        except Exception:
            pass
        try:
            from app.services.channel_inventory_planner_service import ChannelInventoryPlannerService

            for row in ChannelInventoryPlannerService.list_audit_logs(
                start_date=start_date,
                end_date=end_date,
                category=category,
                channel=channel,
                user=user,
            ):
                out.append({
                    'id': row.get('id'),
                    'timestamp': row.get('timestamp'),
                    'user': row.get('user'),
                    'event_type': 'mudanca_inventario',
                    'channel': row.get('channel') or '',
                    'category': row.get('category') or '',
                    'previous_value': row.get('previous_value') or {},
                    'new_value': row.get('new_value') or row.get('new_value') or {},
                    'reason': row.get('reason') or '',
                })
        except Exception:
            pass
        try:
            from app.services.channel_restriction_service import ChannelRestrictionService

            for row in ChannelRestrictionService.list_audit_logs(
                start_date=start_date,
                end_date=end_date,
                category=category,
                channel=channel,
                user=user,
            ):
                out.append({
                    'id': row.get('id'),
                    'timestamp': row.get('timestamp'),
                    'user': row.get('user'),
                    'event_type': cls._event_from_restriction_type(str(row.get('restriction_type') or '')),
                    'channel': row.get('channel') or '',
                    'category': row.get('category') or '',
                    'previous_value': {'status': row.get('previous_status')},
                    'new_value': {'status': row.get('status'), 'value': row.get('value')},
                    'reason': row.get('reason') or '',
                })
        except Exception:
            pass
        out = [row for row in out if isinstance(row, dict)]
        event_filter = str(event_type or '').strip().lower()
        channel_filter = str(channel or '').strip().lower()
        category_filter = str(category or '').strip().lower()
        user_filter = str(user or '').strip().lower()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        filtered: List[Dict[str, Any]] = []
        for row in out:
            ts = str(row.get('timestamp') or '')
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if event_filter and str(row.get('event_type') or '').strip().lower() != event_filter:
                continue
            if channel_filter and str(row.get('channel') or '').strip().lower() != channel_filter:
                continue
            if category_filter and str(row.get('category') or '').strip().lower() != category_filter:
                continue
            if user_filter and str(row.get('user') or '').strip().lower() != user_filter:
                continue
            filtered.append(row)
        filtered.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return filtered
