from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_RESTRICTIONS_AUDIT_FILE,
    CHANNEL_MANAGER_RESTRICTIONS_FILE,
)


class ChannelRestrictionService:
    RESTRICTION_TYPES = {
        'aberto_fechado',
        'stop_sell',
        'cta',
        'ctd',
        'min_stay',
        'max_stay',
        'pacote_obrigatorio',
        'promocao_especifica',
    }

    @classmethod
    def _load_json(cls, file_path: str, fallback: Any) -> Any:
        from app.services.revenue_management_service import RevenueManagementService

        loaded = RevenueManagementService._load_json(file_path, fallback)
        if isinstance(fallback, list):
            return loaded if isinstance(loaded, list) else []
        if isinstance(fallback, dict):
            return loaded if isinstance(loaded, dict) else {}
        return loaded

    @classmethod
    def _save_json(cls, file_path: str, payload: Any) -> None:
        from app.services.revenue_management_service import RevenueManagementService

        with file_lock(file_path):
            RevenueManagementService._save_json(file_path, payload)

    @classmethod
    def _normalize_category(cls, category: Any) -> str:
        return ChannelInventoryControlService._normalize_category(category)

    @classmethod
    def _normalize_channel(cls, channel_name: Any) -> str:
        return ChannelInventoryControlService._normalize_channel(channel_name)

    @classmethod
    def _normalize_status(cls, status: Any) -> str:
        return 'active' if str(status or '').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo') else 'inactive'

    @classmethod
    def _normalize_type(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        if text not in cls.RESTRICTION_TYPES:
            raise ValueError('Tipo de restrição inválido.')
        return text

    @classmethod
    def _normalize_weekdays(cls, weekdays: Optional[List[str]]) -> List[str]:
        return PeriodSelectorService.normalize_weekdays(weekdays or [])

    @classmethod
    def _normalize_value(cls, restriction_type: str, value: Any) -> Any:
        if restriction_type in ('min_stay', 'max_stay'):
            try:
                return max(0, int(value or 0))
            except Exception:
                return 0
        if restriction_type == 'aberto_fechado':
            text = str(value or 'closed').strip().lower()
            return 'open' if text in ('open', 'aberto', 'ativo') else 'closed'
        if restriction_type in ('pacote_obrigatorio', 'promocao_especifica'):
            return str(value or '').strip()
        return bool(str(value or 'true').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo'))

    @classmethod
    def _append_audit(cls, row: Dict[str, Any]) -> None:
        rows = cls._load_json(CHANNEL_MANAGER_RESTRICTIONS_AUDIT_FILE, [])
        rows.append(row)
        cls._save_json(CHANNEL_MANAGER_RESTRICTIONS_AUDIT_FILE, rows)

    @classmethod
    def apply_restriction(
        cls,
        *,
        category: str,
        channel: str,
        restriction_type: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        status: str,
        value: Any,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para restrição por canal.')
        normalized_type = cls._normalize_type(restriction_type)
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        normalized_status = cls._normalize_status(status)
        normalized_weekdays = cls._normalize_weekdays(weekdays)
        days = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        rows = cls._load_json(CHANNEL_MANAGER_RESTRICTIONS_FILE, [])
        now = datetime.now().isoformat(timespec='seconds')
        day_set = set(days)
        remaining = [
            row for row in rows
            if not (
                isinstance(row, dict)
                and str(row.get('category') or '') == normalized_category
                and str(row.get('channel') or '') == normalized_channel
                and str(row.get('restriction_type') or '') == normalized_type
                and str(row.get('date') or '') in day_set
            )
        ]
        normalized_value = cls._normalize_value(normalized_type, value)
        for day in days:
            remaining.append({
                'id': str(uuid.uuid4()),
                'category': normalized_category,
                'channel': normalized_channel,
                'restriction_type': normalized_type,
                'date': day,
                'status': normalized_status,
                'value': normalized_value,
                'reason': clean_reason,
                'updated_at': now,
                'updated_by': user,
            })
            cls._append_audit({
                'id': str(uuid.uuid4()),
                'timestamp': now,
                'user': user,
                'category': normalized_category,
                'channel': normalized_channel,
                'restriction_type': normalized_type,
                'day_affected': day,
                'status': normalized_status,
                'value': normalized_value,
                'reason': clean_reason,
                'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
            })
        cls._save_json(CHANNEL_MANAGER_RESTRICTIONS_FILE, remaining)
        LoggerService.log_acao(
            acao='Atualizou restrições por canal',
            entidade='Channel Manager',
            detalhes={
                'category': normalized_category,
                'channel': normalized_channel,
                'restriction_type': normalized_type,
                'status': normalized_status,
                'value': normalized_value,
                'reason': clean_reason,
                'dates': days,
            },
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'updated': len(days),
            'dates': days,
            'category': normalized_category,
            'channel': normalized_channel,
            'restriction_type': normalized_type,
            'status': normalized_status,
            'value': normalized_value,
        }

    @classmethod
    def list_restrictions(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
        restriction_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_RESTRICTIONS_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
        type_norm = str(restriction_type or '').strip().lower()
        status_norm = cls._normalize_status(status) if status else ''
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            day_text = str(row.get('date') or '')
            try:
                day = PeriodSelectorService.parse_date(day_text).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category') or '') != category_norm:
                continue
            if channel_norm and str(row.get('channel') or '') != channel_norm:
                continue
            if type_norm and str(row.get('restriction_type') or '') != type_norm:
                continue
            if status_norm and str(row.get('status') or '') != status_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (str(item.get('date') or ''), str(item.get('category') or ''), str(item.get('channel') or ''), str(item.get('restriction_type') or '')))
        return out

    @classmethod
    def list_audit_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        channel: Optional[str] = None,
        user: Optional[str] = None,
        restriction_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_RESTRICTIONS_AUDIT_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        category_norm = cls._normalize_category(category) if category else ''
        channel_norm = cls._normalize_channel(channel) if channel else ''
        user_norm = str(user or '').strip().lower()
        type_norm = str(restriction_type or '').strip().lower()
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            day_text = str(row.get('day_affected') or '')
            try:
                day = PeriodSelectorService.parse_date(day_text).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if category_norm and str(row.get('category') or '') != category_norm:
                continue
            if channel_norm and str(row.get('channel') or '') != channel_norm:
                continue
            if user_norm and str(row.get('user') or '').strip().lower() != user_norm:
                continue
            if type_norm and str(row.get('restriction_type') or '') != type_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out

    @classmethod
    def resolve_day_rules(cls, *, category: str, channel: str, day: str) -> Dict[str, Any]:
        normalized_category = cls._normalize_category(category)
        normalized_channel = cls._normalize_channel(channel)
        rules = cls.list_restrictions(
            start_date=day,
            end_date=day,
            category=normalized_category,
            channel=normalized_channel,
            status='active',
        )
        resolved: Dict[str, Any] = {
            'aberto_fechado': None,
            'stop_sell': False,
            'cta': False,
            'ctd': False,
            'min_stay': 0,
            'max_stay': 0,
            'pacote_obrigatorio': '',
            'promocao_especifica': '',
        }
        for row in rules:
            rtype = str(row.get('restriction_type') or '')
            value = row.get('value')
            if rtype == 'aberto_fechado':
                resolved[rtype] = str(value or 'closed')
            elif rtype in ('stop_sell', 'cta', 'ctd'):
                resolved[rtype] = bool(value)
            elif rtype in ('min_stay', 'max_stay'):
                try:
                    resolved[rtype] = max(0, int(value or 0))
                except Exception:
                    resolved[rtype] = 0
            elif rtype in ('pacote_obrigatorio', 'promocao_especifica'):
                resolved[rtype] = str(value or '')
        labels: List[str] = []
        if resolved.get('aberto_fechado') == 'closed':
            labels.append('fechado')
        if resolved.get('stop_sell'):
            labels.append('stop_sell')
        if resolved.get('cta'):
            labels.append('CTA')
        if resolved.get('ctd'):
            labels.append('CTD')
        if int(resolved.get('min_stay') or 0) > 0:
            labels.append(f"min {int(resolved.get('min_stay') or 0)}")
        if int(resolved.get('max_stay') or 0) > 0:
            labels.append(f"max {int(resolved.get('max_stay') or 0)}")
        if str(resolved.get('pacote_obrigatorio') or '').strip():
            labels.append(f"pacote {str(resolved.get('pacote_obrigatorio'))}")
        if str(resolved.get('promocao_especifica') or '').strip():
            labels.append(f"promo {str(resolved.get('promocao_especifica'))}")
        resolved['labels'] = labels
        return resolved
