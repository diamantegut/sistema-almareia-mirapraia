from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.channel_manager_service import ChannelManagerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_COMMISSIONS_AUDIT_FILE,
    CHANNEL_MANAGER_COMMISSIONS_FILE,
)


class ChannelCommissionService:
    MODELS = {
        'comissao_percentual',
        'net_rate',
        'direta_sem_comissao',
        'tarifa_liquida',
        'gross_up_automatico',
    }

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

        with file_lock(path):
            RevenueManagementService._save_json(path, payload)

    @classmethod
    def _normalize_channel(cls, value: Any) -> str:
        return ChannelInventoryControlService._normalize_channel(value)

    @classmethod
    def _normalize_category(cls, value: Any) -> str:
        return ChannelInventoryControlService._normalize_category(value)

    @classmethod
    def _normalize_pct(cls, value: Any, *, fallback: float = 0.0) -> float:
        try:
            num = float(value)
        except Exception:
            num = float(fallback)
        if num > 1.0:
            num = num / 100.0
        return max(0.0, min(1.0, num))

    @classmethod
    def _normalize_model(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        if text not in cls.MODELS:
            raise ValueError('Modelo comercial de comissão inválido.')
        return text

    @classmethod
    def _channel_default_model(cls, channel_name: str) -> str:
        rows = ChannelManagerService.list_channels()
        for row in rows:
            if str(row.get('name') or '') == str(channel_name):
                model = str(row.get('commercial_model') or '').strip().lower()
                if model == 'net_rate':
                    return 'net_rate'
                if model == 'direta_sem_comissao':
                    return 'direta_sem_comissao'
                return 'comissao_percentual'
        return 'comissao_percentual'

    @classmethod
    def _append_audit(cls, row: Dict[str, Any]) -> None:
        rows = cls._load_json(CHANNEL_MANAGER_COMMISSIONS_AUDIT_FILE, [])
        rows.append(row)
        cls._save_json(CHANNEL_MANAGER_COMMISSIONS_AUDIT_FILE, rows)

    @classmethod
    def _normalize_rule(cls, payload: Dict[str, Any], *, current: Optional[Dict[str, Any]], user: str) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec='seconds')
        channel_name = cls._normalize_channel(payload.get('channel_name') if 'channel_name' in payload else (current or {}).get('channel_name'))
        model = cls._normalize_model(payload.get('commercial_model') if 'commercial_model' in payload else (current or {}).get('commercial_model') or cls._channel_default_model(channel_name))
        global_pct = cls._normalize_pct(payload.get('default_commission_pct') if 'default_commission_pct' in payload else (current or {}).get('default_commission_pct') or 0.0)
        if model == 'direta_sem_comissao':
            global_pct = 0.0
        by_category: Dict[str, float] = {}
        source_by_category = payload.get('commission_by_category') if 'commission_by_category' in payload else (current or {}).get('commission_by_category') or {}
        if isinstance(source_by_category, dict):
            for key, value in source_by_category.items():
                by_category[cls._normalize_category(key)] = cls._normalize_pct(value, fallback=0.0)
        by_period: List[Dict[str, Any]] = []
        source_periods = payload.get('commission_by_period') if 'commission_by_period' in payload else (current or {}).get('commission_by_period') or []
        for item in source_periods:
            if not isinstance(item, dict):
                continue
            by_period.append({
                'start_date': str(item.get('start_date') or ''),
                'end_date': str(item.get('end_date') or item.get('start_date') or ''),
                'weekdays': PeriodSelectorService.normalize_weekdays(item.get('weekdays') or []),
                'category': cls._normalize_category(item.get('category')) if str(item.get('category') or '').strip() else '',
                'commission_pct': cls._normalize_pct(item.get('commission_pct'), fallback=global_pct),
            })
        net_map: Dict[str, float] = {}
        source_net = payload.get('net_target_by_category') if 'net_target_by_category' in payload else (current or {}).get('net_target_by_category') or {}
        if isinstance(source_net, dict):
            for key, value in source_net.items():
                try:
                    net_map[cls._normalize_category(key)] = max(0.0, float(value or 0.0))
                except Exception:
                    continue
        return {
            'channel_name': channel_name,
            'commercial_model': model,
            'default_commission_pct': global_pct,
            'commission_by_category': by_category,
            'commission_by_period': by_period,
            'net_target_by_category': net_map,
            'updated_at': now,
            'updated_by': user,
            'created_at': str((current or {}).get('created_at') or now),
        }

    @classmethod
    def get_commission_rules(cls) -> Dict[str, Any]:
        rows = cls._load_json(CHANNEL_MANAGER_COMMISSIONS_FILE, [])
        channels = [row for row in rows if isinstance(row, dict)]
        channels.sort(key=lambda item: str(item.get('channel_name') or ''))
        return {'channels': channels, 'count': len(channels)}

    @classmethod
    def save_commission_rules(cls, *, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para salvar comissão por canal.')
        rows = cls._load_json(CHANNEL_MANAGER_COMMISSIONS_FILE, [])
        current_map = {str(item.get('channel_name') or ''): item for item in rows if isinstance(item, dict)}
        for incoming in (payload.get('channels') if isinstance(payload.get('channels'), list) else []):
            if not isinstance(incoming, dict):
                continue
            key = cls._normalize_channel(incoming.get('channel_name'))
            current = current_map.get(key)
            normalized = cls._normalize_rule(incoming, current=current, user=user)
            current_map[key] = normalized
            cls._append_audit({
                'id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'user': user,
                'event_type': 'mudanca_comissao',
                'channel': key,
                'category': '',
                'previous_value': current or {},
                'new_value': normalized,
                'reason': clean_reason,
            })
        merged = list(current_map.values())
        merged.sort(key=lambda item: str(item.get('channel_name') or ''))
        cls._save_json(CHANNEL_MANAGER_COMMISSIONS_FILE, merged)
        return {'channels': merged, 'count': len(merged)}

    @classmethod
    def _pick_commission_pct(cls, *, rule: Dict[str, Any], category: str, day_iso: str) -> float:
        for period in (rule.get('commission_by_period') or []):
            if not isinstance(period, dict):
                continue
            if str(period.get('category') or '').strip() and cls._normalize_category(period.get('category')) != category:
                continue
            days = PeriodSelectorService.expand_dates(
                period.get('start_date'),
                period.get('end_date') or period.get('start_date'),
                period.get('weekdays') or [],
            )
            if day_iso in set(days):
                return cls._normalize_pct(period.get('commission_pct'), fallback=rule.get('default_commission_pct') or 0.0)
        by_cat = rule.get('commission_by_category') or {}
        if isinstance(by_cat, dict) and category in by_cat:
            return cls._normalize_pct(by_cat.get(category), fallback=rule.get('default_commission_pct') or 0.0)
        return cls._normalize_pct(rule.get('default_commission_pct'), fallback=0.0)

    @classmethod
    def resolve_commission(
        cls,
        *,
        channel_name: str,
        category: str,
        day_iso: str,
    ) -> Dict[str, Any]:
        channel = cls._normalize_channel(channel_name)
        bucket = cls._normalize_category(category)
        rows = cls._load_json(CHANNEL_MANAGER_COMMISSIONS_FILE, [])
        rule = next((item for item in rows if isinstance(item, dict) and str(item.get('channel_name') or '') == channel), None)
        if not rule:
            model = cls._channel_default_model(channel)
            return {'channel_name': channel, 'commercial_model': model, 'commission_pct': 0.0, 'net_target': 0.0}
        pct = cls._pick_commission_pct(rule=rule, category=bucket, day_iso=day_iso)
        net_map = rule.get('net_target_by_category') or {}
        net_target = 0.0
        if isinstance(net_map, dict):
            try:
                net_target = max(0.0, float(net_map.get(bucket) or 0.0))
            except Exception:
                net_target = 0.0
        return {
            'channel_name': channel,
            'commercial_model': str(rule.get('commercial_model') or 'comissao_percentual'),
            'commission_pct': pct,
            'net_target': net_target,
        }

    @classmethod
    def calculate_channel_tariff(
        cls,
        *,
        channel_name: str,
        category: str,
        day_iso: str,
        direct_tariff: float,
    ) -> Dict[str, Any]:
        resolved = cls.resolve_commission(channel_name=channel_name, category=category, day_iso=day_iso)
        model = str(resolved.get('commercial_model') or 'comissao_percentual')
        commission = float(resolved.get('commission_pct') or 0.0)
        direct = max(0.0, float(direct_tariff or 0.0))
        net_target = max(0.0, float(resolved.get('net_target') or 0.0))
        if model == 'direta_sem_comissao':
            channel_tariff = direct
            commission = 0.0
        elif model == 'gross_up_automatico':
            denominator = max(1.0 - commission, 0.0001)
            channel_tariff = direct / denominator
        elif model in ('net_rate', 'tarifa_liquida'):
            net_value = net_target if net_target > 0 else direct * (1.0 - commission)
            denominator = max(1.0 - commission, 0.0001)
            channel_tariff = net_value / denominator if commission > 0 else net_value
        else:
            channel_tariff = direct
        net = channel_tariff * (1.0 - commission)
        return {
            'channel_name': resolved.get('channel_name'),
            'commercial_model': model,
            'commission_pct': round(commission, 6),
            'tarifa_direta': round(direct, 2),
            'tarifa_canal': round(channel_tariff, 2),
            'liquido_estimado_hotel': round(net, 2),
            'comissao_valor': round(max(0.0, channel_tariff - net), 2),
            'day': day_iso,
            'category': cls._normalize_category(category),
        }

    @classmethod
    def list_audit_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_COMMISSIONS_AUDIT_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        channel_filter = cls._normalize_channel(channel) if channel else ''
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
            if channel_filter and str(row.get('channel') or '') != channel_filter:
                continue
            if user_filter and str(row.get('user') or '').strip().lower() != user_filter:
                continue
            out.append(row)
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out
