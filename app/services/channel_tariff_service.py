from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_TARIFFS_FILE,
    CHANNEL_MANAGER_TARIFFS_LOGS_FILE,
)


class ChannelTariffService:
    TARIFF_MODES = {
        'usar_tarifa_direta',
        'usar_tarifa_direta_grossup_comissao',
        'usar_tarifa_manual_canal',
        'usar_promocao_especifica_canal',
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
        from app.services.revenue_management_service import RevenueManagementService

        return RevenueManagementService._normalize_booking_category(category)

    @classmethod
    def _normalize_channel(cls, channel_name: Any) -> str:
        return ChannelInventoryControlService._normalize_channel(channel_name)

    @classmethod
    def _normalize_bool(cls, value: Any) -> bool:
        return str(value or '').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo')

    @classmethod
    def _normalize_pct(cls, value: Any, fallback: float = 0.0) -> float:
        try:
            raw = float(value if value is not None else fallback)
            if raw > 1:
                raw = raw / 100.0
            return max(0.0, min(1.0, raw))
        except Exception:
            return max(0.0, min(1.0, fallback))

    @classmethod
    def _normalize_mode(cls, value: Any, fallback: str = 'usar_tarifa_direta') -> str:
        mode = str(value or fallback).strip().lower()
        return mode if mode in cls.TARIFF_MODES else fallback

    @classmethod
    def _weekday_code(cls, day_iso: str) -> str:
        day = datetime.strptime(day_iso, '%Y-%m-%d').weekday()
        return ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][day]

    @classmethod
    def _date_in_period(cls, day_iso: str, period: Dict[str, Any]) -> bool:
        start = str(period.get('start_date') or '').strip()
        end = str(period.get('end_date') or start).strip()
        if not start:
            return False
        if day_iso < start or day_iso > end:
            return False
        weekdays = [str(item or '').strip().lower() for item in (period.get('weekdays') or []) if str(item or '').strip()]
        if weekdays and cls._weekday_code(day_iso) not in weekdays:
            return False
        return True

    @classmethod
    def _default_channel_rule(cls, channel_name: str) -> Dict[str, Any]:
        return {
            'channel_name': channel_name,
            'tariff_mode': 'usar_tarifa_direta',
            'global_commission_pct': 0.0,
            'commission_by_category': {},
            'commission_periods': [],
            'fixed_tariff_periods': [],
            'manual_tariff_by_category': {},
            'promotion_periods': [],
            'min_tariff': 0.0,
            'max_tariff': 0.0,
            'updated_at': '',
            'updated_by': '',
        }

    @classmethod
    def _normalize_rule(cls, payload: Dict[str, Any], *, fallback: Optional[Dict[str, Any]] = None, user: str = 'Sistema') -> Dict[str, Any]:
        current = fallback or cls._default_channel_rule(cls._normalize_channel(payload.get('channel_name')))
        channel_name = cls._normalize_channel(payload.get('channel_name') or current.get('channel_name'))
        mode = cls._normalize_mode(payload.get('tariff_mode'), fallback=str(current.get('tariff_mode') or 'usar_tarifa_direta'))
        commission_by_category: Dict[str, float] = {}
        incoming_category = payload.get('commission_by_category')
        if isinstance(incoming_category, dict):
            for key, value in incoming_category.items():
                commission_by_category[cls._normalize_category(key)] = cls._normalize_pct(value, fallback=0.0)
        else:
            commission_by_category = dict(current.get('commission_by_category') or {})
        commission_periods: List[Dict[str, Any]] = []
        for item in (payload.get('commission_periods') if isinstance(payload.get('commission_periods'), list) else current.get('commission_periods') or []):
            if not isinstance(item, dict):
                continue
            start_date = str(item.get('start_date') or '').strip()
            end_date = str(item.get('end_date') or start_date).strip()
            if not start_date:
                continue
            commission_periods.append({
                'id': str(item.get('id') or str(uuid.uuid4())),
                'start_date': start_date,
                'end_date': end_date,
                'weekdays': [str(v or '').strip().lower() for v in (item.get('weekdays') or []) if str(v or '').strip()],
                'category': cls._normalize_category(item.get('category')) if str(item.get('category') or '').strip() else '',
                'commission_pct': cls._normalize_pct(item.get('commission_pct'), fallback=0.0),
            })
        fixed_tariff_periods: List[Dict[str, Any]] = []
        for item in (payload.get('fixed_tariff_periods') if isinstance(payload.get('fixed_tariff_periods'), list) else current.get('fixed_tariff_periods') or []):
            if not isinstance(item, dict):
                continue
            start_date = str(item.get('start_date') or '').strip()
            end_date = str(item.get('end_date') or start_date).strip()
            if not start_date:
                continue
            try:
                tariff = max(0.0, float(item.get('tariff') or 0.0))
            except Exception:
                tariff = 0.0
            fixed_tariff_periods.append({
                'id': str(item.get('id') or str(uuid.uuid4())),
                'start_date': start_date,
                'end_date': end_date,
                'weekdays': [str(v or '').strip().lower() for v in (item.get('weekdays') or []) if str(v or '').strip()],
                'category': cls._normalize_category(item.get('category')) if str(item.get('category') or '').strip() else '',
                'tariff': tariff,
            })
        manual_tariff_by_category: Dict[str, float] = {}
        incoming_manual = payload.get('manual_tariff_by_category')
        if isinstance(incoming_manual, dict):
            for key, value in incoming_manual.items():
                try:
                    manual_tariff_by_category[cls._normalize_category(key)] = max(0.0, float(value))
                except Exception:
                    continue
        else:
            manual_tariff_by_category = dict(current.get('manual_tariff_by_category') or {})
        promotion_periods: List[Dict[str, Any]] = []
        for item in (payload.get('promotion_periods') if isinstance(payload.get('promotion_periods'), list) else current.get('promotion_periods') or []):
            if not isinstance(item, dict):
                continue
            start_date = str(item.get('start_date') or '').strip()
            end_date = str(item.get('end_date') or start_date).strip()
            if not start_date:
                continue
            ptype = str(item.get('promotion_type') or 'percent').strip().lower()
            if ptype not in ('percent', 'fixed_amount'):
                ptype = 'percent'
            try:
                pvalue = float(item.get('value') or 0.0)
            except Exception:
                pvalue = 0.0
            promotion_periods.append({
                'id': str(item.get('id') or str(uuid.uuid4())),
                'start_date': start_date,
                'end_date': end_date,
                'weekdays': [str(v or '').strip().lower() for v in (item.get('weekdays') or []) if str(v or '').strip()],
                'category': cls._normalize_category(item.get('category')) if str(item.get('category') or '').strip() else '',
                'promotion_type': ptype,
                'value': pvalue,
            })
        try:
            min_tariff = max(0.0, float(payload.get('min_tariff') if 'min_tariff' in payload else current.get('min_tariff') or 0.0))
        except Exception:
            min_tariff = max(0.0, float(current.get('min_tariff') or 0.0))
        try:
            max_tariff = max(0.0, float(payload.get('max_tariff') if 'max_tariff' in payload else current.get('max_tariff') or 0.0))
        except Exception:
            max_tariff = max(0.0, float(current.get('max_tariff') or 0.0))
        if max_tariff > 0 and max_tariff < min_tariff:
            max_tariff = min_tariff
        return {
            'channel_name': channel_name,
            'tariff_mode': mode,
            'global_commission_pct': cls._normalize_pct(payload.get('global_commission_pct') if 'global_commission_pct' in payload else current.get('global_commission_pct') or 0.0),
            'commission_by_category': commission_by_category,
            'commission_periods': commission_periods,
            'fixed_tariff_periods': fixed_tariff_periods,
            'manual_tariff_by_category': manual_tariff_by_category,
            'promotion_periods': promotion_periods,
            'min_tariff': min_tariff,
            'max_tariff': max_tariff,
            'updated_at': datetime.now().isoformat(timespec='seconds'),
            'updated_by': user,
        }

    @classmethod
    def _load_store(cls) -> Dict[str, Any]:
        raw = cls._load_json(CHANNEL_MANAGER_TARIFFS_FILE, {})
        if not isinstance(raw, dict):
            raw = {}
        channels = raw.get('channels')
        if not isinstance(channels, list):
            channels = []
        return {'channels': channels}

    @classmethod
    def _ensure_defaults(cls) -> Dict[str, Any]:
        from app.services.channel_manager_service import ChannelManagerService

        store = cls._load_store()
        channels = ChannelManagerService.list_channels()
        existing = {cls._normalize_channel(item.get('channel_name')): item for item in (store.get('channels') or []) if isinstance(item, dict)}
        out: List[Dict[str, Any]] = []
        for channel in channels:
            channel_name = cls._normalize_channel(channel.get('name'))
            rule = existing.get(channel_name) or cls._default_channel_rule(channel_name)
            out.append(cls._normalize_rule({'channel_name': channel_name, **rule}, fallback=rule, user=str(rule.get('updated_by') or 'Sistema')))
        store['channels'] = out
        cls._save_json(CHANNEL_MANAGER_TARIFFS_FILE, store)
        return store

    @classmethod
    def get_tariff_rules(cls) -> Dict[str, Any]:
        return cls._ensure_defaults()

    @classmethod
    def save_tariff_rules(cls, *, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para salvar regras tarifárias por canal.')
        store = cls._ensure_defaults()
        current_by_channel = {
            cls._normalize_channel(item.get('channel_name')): item
            for item in (store.get('channels') or [])
            if isinstance(item, dict)
        }
        incoming = payload.get('channels') if isinstance(payload, dict) else []
        if not isinstance(incoming, list):
            incoming = []
        updated: List[Dict[str, Any]] = []
        for item in incoming:
            if not isinstance(item, dict):
                continue
            channel_name = cls._normalize_channel(item.get('channel_name'))
            base = current_by_channel.get(channel_name) or cls._default_channel_rule(channel_name)
            normalized = cls._normalize_rule(item, fallback=base, user=user)
            updated.append(normalized)
            current_by_channel[channel_name] = normalized
        if updated:
            store['channels'] = list(current_by_channel.values())
            cls._save_json(CHANNEL_MANAGER_TARIFFS_FILE, store)
        logs = cls._load_json(CHANNEL_MANAGER_TARIFFS_LOGS_FILE, [])
        logs.append({
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'action': 'save_channel_tariff_rules',
            'reason': clean_reason,
            'updated_channels': [item.get('channel_name') for item in updated],
        })
        cls._save_json(CHANNEL_MANAGER_TARIFFS_LOGS_FILE, logs)
        LoggerService.log_acao(
            acao='Atualizou regras tarifárias por canal',
            entidade='Channel Manager',
            detalhes={'reason': clean_reason, 'updated_channels': [item.get('channel_name') for item in updated]},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return cls.get_tariff_rules()

    @classmethod
    def _pick_commission_pct(cls, *, rule: Dict[str, Any], category: str, day_iso: str) -> float:
        for period in (rule.get('commission_periods') or []):
            if not isinstance(period, dict):
                continue
            pcat = str(period.get('category') or '').strip()
            if pcat and cls._normalize_category(pcat) != category:
                continue
            if cls._date_in_period(day_iso, period):
                return cls._normalize_pct(period.get('commission_pct'), fallback=rule.get('global_commission_pct') or 0.0)
        by_category = rule.get('commission_by_category') or {}
        if isinstance(by_category, dict) and category in by_category:
            return cls._normalize_pct(by_category.get(category), fallback=rule.get('global_commission_pct') or 0.0)
        return cls._normalize_pct(rule.get('global_commission_pct'), fallback=0.0)

    @classmethod
    def _pick_fixed_tariff(cls, *, rule: Dict[str, Any], category: str, day_iso: str) -> Optional[float]:
        for period in (rule.get('fixed_tariff_periods') or []):
            if not isinstance(period, dict):
                continue
            pcat = str(period.get('category') or '').strip()
            if pcat and cls._normalize_category(pcat) != category:
                continue
            if cls._date_in_period(day_iso, period):
                try:
                    return max(0.0, float(period.get('tariff') or 0.0))
                except Exception:
                    return 0.0
        return None

    @classmethod
    def _apply_promotion(cls, *, rule: Dict[str, Any], category: str, day_iso: str, base_value: float) -> Optional[Dict[str, Any]]:
        for promo in (rule.get('promotion_periods') or []):
            if not isinstance(promo, dict):
                continue
            pcat = str(promo.get('category') or '').strip()
            if pcat and cls._normalize_category(pcat) != category:
                continue
            if not cls._date_in_period(day_iso, promo):
                continue
            ptype = str(promo.get('promotion_type') or 'percent').strip().lower()
            try:
                value = float(promo.get('value') or 0.0)
            except Exception:
                value = 0.0
            if ptype == 'fixed_amount':
                tariff = max(0.0, base_value - value)
                return {'tariff': tariff, 'rule': f'promocao_valor_{value:.2f}'}
            pct = cls._normalize_pct(value, fallback=0.0)
            tariff = max(0.0, base_value * (1.0 - pct))
            return {'tariff': tariff, 'rule': f'promocao_percentual_{round(pct * 100, 2)}'}
        return None

    @classmethod
    def calculate_tariffs(
        cls,
        *,
        channel_name: str,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from app.services.revenue_management_service import RevenueManagementService

        normalized_channel = cls._normalize_channel(channel_name)
        rules = cls.get_tariff_rules()
        by_channel = {
            cls._normalize_channel(item.get('channel_name')): item
            for item in (rules.get('channels') or [])
            if isinstance(item, dict)
        }
        rule = by_channel.get(normalized_channel) or cls._default_channel_rule(normalized_channel)
        calendar = RevenueManagementService.calendar_direct_vs_ota(
            category=category,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays or [],
        )
        rows = calendar.get('rows') or []
        out_rows: List[Dict[str, Any]] = []
        min_tariff = max(0.0, float(rule.get('min_tariff') or 0.0))
        max_tariff = max(0.0, float(rule.get('max_tariff') or 0.0))
        if max_tariff > 0 and max_tariff < min_tariff:
            max_tariff = min_tariff
        for row in rows:
            day_iso = str(row.get('date') or '')
            bucket = cls._normalize_category(row.get('category'))
            direct = max(0.0, float(row.get('tarifa_direta') or row.get('current_bar') or 0.0))
            commission = cls._pick_commission_pct(rule=rule, category=bucket, day_iso=day_iso)
            mode = cls._normalize_mode(rule.get('tariff_mode'))
            applied_rule = mode
            fixed_tariff = cls._pick_fixed_tariff(rule=rule, category=bucket, day_iso=day_iso)
            manual_map = rule.get('manual_tariff_by_category') or {}
            if not isinstance(manual_map, dict):
                manual_map = {}
            if fixed_tariff is not None:
                channel_tariff = fixed_tariff
                applied_rule = 'tarifa_fixa_periodo'
            elif mode == 'usar_tarifa_direta_grossup_comissao':
                denominator = max(1.0 - commission, 0.0001)
                channel_tariff = direct / denominator
                applied_rule = 'grossup_comissao'
            elif mode == 'usar_tarifa_manual_canal':
                channel_tariff = max(0.0, float(manual_map.get(bucket, direct) or 0.0))
                applied_rule = 'tarifa_manual_canal'
            elif mode == 'usar_promocao_especifica_canal':
                promo = cls._apply_promotion(rule=rule, category=bucket, day_iso=day_iso, base_value=direct)
                if promo:
                    channel_tariff = max(0.0, float(promo.get('tariff') or 0.0))
                    applied_rule = str(promo.get('rule') or 'promocao_especifica_canal')
                else:
                    channel_tariff = direct
                    applied_rule = 'promocao_especifica_canal_sem_regra'
            else:
                channel_tariff = direct
                applied_rule = 'tarifa_direta'
            if min_tariff > 0:
                channel_tariff = max(channel_tariff, min_tariff)
            if max_tariff > 0:
                channel_tariff = min(channel_tariff, max_tariff)
            net = channel_tariff * (1.0 - commission)
            out_rows.append({
                'date': day_iso,
                'category': bucket,
                'category_label': row.get('category_label') or bucket,
                'tarifa_direta': round(direct, 2),
                'tarifa_canal': round(channel_tariff, 2),
                'comissao_aplicada_percentual': round(commission, 6),
                'comissao_aplicada_valor': round(max(0.0, channel_tariff - net), 2),
                'liquido_estimado_hotel': round(net, 2),
                'regra_comercial_aplicada': applied_rule,
            })
        return {
            'channel_name': normalized_channel,
            'category': category,
            'start_date': start_date,
            'end_date': end_date,
            'weekdays': weekdays or [],
            'tariff_mode': rule.get('tariff_mode'),
            'min_tariff': min_tariff,
            'max_tariff': max_tariff,
            'rows': out_rows,
            'count': len(out_rows),
        }
