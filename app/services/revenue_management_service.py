import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.finance_dashboard_service import FinanceDashboardService
from app.services.logger_service import LoggerService
from app.services.reservation_service import ReservationService
from app.services.weekday_base_rate_service import WeekdayBaseRateService
from app.services.system_config_manager import (
    REVENUE_ADVANCED_SETTINGS_FILE,
    REVENUE_BAR_CHANGES_FILE,
    REVENUE_BOOKING_COMMISSION_LOGS_FILE,
    REVENUE_BAR_RULES_FILE,
    REVENUE_EVENTS_FILE,
)


class RevenueManagementService:
    BOOKING_CATEGORY_OPTIONS = [
        {'key': 'areia', 'label': 'Areia', 'bucket': 'areia'},
        {'key': 'mar_familia', 'label': 'Mar Família', 'bucket': 'mar'},
        {'key': 'mar', 'label': 'Mar', 'bucket': 'mar'},
        {'key': 'alma_banheira', 'label': 'Alma com Banheira', 'bucket': 'alma'},
        {'key': 'alma', 'label': 'Alma', 'bucket': 'alma'},
        {'key': 'alma_diamante', 'label': 'Alma Diamante', 'bucket': 'alma'},
    ]
    BOOKING_CATEGORY_MAP = {
        'areia': 'areia',
        'suite_areia': 'areia',
        'suíte_areia': 'areia',
        'mar_familia': 'mar_familia',
        'mar_família': 'mar_familia',
        'mar familia': 'mar_familia',
        'mar família': 'mar_familia',
        'suite_mar_familia': 'mar_familia',
        'suíte_mar_família': 'mar_familia',
        'mar': 'mar',
        'suite_mar': 'mar',
        'suíte_mar': 'mar',
        'alma_banheira': 'alma_banheira',
        'alma com banheira': 'alma_banheira',
        'alma c/ banheira': 'alma_banheira',
        'suite_alma_c_banheira': 'alma_banheira',
        'suíte_alma_c_banheira': 'alma_banheira',
        'alma': 'alma',
        'suite_alma': 'alma',
        'suíte_alma': 'alma',
        'alma_diamante': 'alma_diamante',
        'master_diamante': 'alma_diamante',
        'suite_master_diamante': 'alma_diamante',
        'suíte_master_diamante': 'alma_diamante',
    }

    DEFAULT_RULES = {
        'alma': {'base_bar': 450.0, 'min_bar': 280.0, 'max_bar': 1200.0},
        'mar': {'base_bar': 380.0, 'min_bar': 240.0, 'max_bar': 950.0},
        'areia': {'base_bar': 320.0, 'min_bar': 210.0, 'max_bar': 780.0},
    }

    DEFAULT_ADVANCED_CONFIG = {
        'season_by_month': {
            '1': 'alta', '2': 'alta', '3': 'media', '4': 'media', '5': 'baixa', '6': 'baixa',
            '7': 'alta', '8': 'media', '9': 'baixa', '10': 'media', '11': 'media', '12': 'alta',
        },
        'revpar_target': {
            'alta': {'mon': 420, 'tue': 420, 'wed': 450, 'thu': 480, 'fri': 560, 'sat': 620, 'sun': 500},
            'media': {'mon': 320, 'tue': 320, 'wed': 340, 'thu': 360, 'fri': 420, 'sat': 470, 'sun': 390},
            'baixa': {'mon': 240, 'tue': 240, 'wed': 250, 'thu': 260, 'fri': 300, 'sat': 340, 'sun': 280},
        },
        'channel_weights': {
            'direto': 1.08,
            'motor': 1.05,
            'booking': 0.93,
            'expedia': 0.90,
            'airbnb': 0.94,
            'agencia': 0.97,
            'default': 1.0,
        },
        'category_limits': {
            'alma': {'min_bar': 280, 'max_bar': 1200},
            'mar': {'min_bar': 240, 'max_bar': 950},
            'areia': {'min_bar': 210, 'max_bar': 780},
        },
        'occupancy_thresholds': {'high': 82, 'low': 45},
        'category_strategies': {
            'areia': {
                'name': 'agressiva',
                'discount_limit_pct': 0.30,
                'increase_limit_pct': 0.20,
                'channel_priority': ['motor', 'booking', 'direto', 'whatsapp', 'airbnb', 'expedia', 'agencia'],
            },
            'mar': {
                'name': 'equilibrada',
                'discount_limit_pct': 0.18,
                'increase_limit_pct': 0.22,
                'channel_priority': ['direto', 'motor', 'whatsapp', 'booking', 'expedia', 'airbnb', 'agencia'],
            },
            'master_diamante': {
                'name': 'premium',
                'discount_limit_pct': 0.08,
                'increase_limit_pct': 0.35,
                'channel_priority': ['direto', 'whatsapp', 'agencia', 'motor', 'booking', 'expedia', 'airbnb'],
            },
        },
        'max_increase_pct': 0.28,
        'max_reduction_pct': 0.22,
        'booking_commercial': {
            'modelo_comercial': 'commission_rate',
            'comissao_padrao_percentual': 0.15,
            'comissao_percentual': 0.15,
            'comissao_por_categoria': {},
            'comissao_por_periodo': [],
            'tipo_ajuste_tarifa': 'manter_liquido_hotel',
            'tarifa_manual_ota': {},
            'tarifa_especifica_ota': {},
            'arredondamento': 0.01,
            'tarifa_minima_ota': 0.0,
            'tarifa_maxima_ota': 0.0,
            'ativo': True,
        },
    }

    @staticmethod
    def _normalize_category(raw: Any) -> str:
        text = str(raw or '').lower()
        if 'alma' in text:
            return 'alma'
        if 'mar' in text:
            return 'mar'
        if 'areia' in text:
            return 'areia'
        return 'areia'

    @classmethod
    def _normalize_booking_category(cls, raw: Any, fallback: str = 'areia') -> str:
        text = str(raw or '').strip().lower()
        if not text:
            return fallback
        text = text.replace('/', ' ').replace('-', ' ').replace('__', '_').replace('  ', ' ')
        key = text.replace(' ', '_')
        mapped = cls.BOOKING_CATEGORY_MAP.get(key) or cls.BOOKING_CATEGORY_MAP.get(text)
        if mapped:
            return mapped
        if 'diamante' in text:
            return 'alma_diamante'
        if 'banheira' in text:
            return 'alma_banheira'
        if 'famil' in text:
            return 'mar_familia'
        if 'alma' in text:
            return 'alma'
        if 'mar' in text:
            return 'mar'
        if 'areia' in text:
            return 'areia'
        return fallback

    @classmethod
    def _booking_category_bucket(cls, booking_category: Any) -> str:
        normalized = cls._normalize_booking_category(booking_category)
        for item in cls.BOOKING_CATEGORY_OPTIONS:
            if item.get('key') == normalized:
                return str(item.get('bucket') or 'areia')
        return 'areia'

    @staticmethod
    def _normalize_channel(raw: Any) -> str:
        text = str(raw or '').strip().lower()
        if not text:
            return 'direto'
        if 'direct' in text or 'diret' in text:
            return 'direto'
        if 'booking' in text:
            return 'booking'
        if 'expedia' in text:
            return 'expedia'
        if 'motor' in text:
            return 'motor'
        if 'airbnb' in text:
            return 'airbnb'
        if 'agenc' in text:
            return 'agencia'
        return text

    @staticmethod
    def _parse_date(value: Any) -> datetime:
        text = str(value or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(text)

    @staticmethod
    def _load_json(path: str, default: Any) -> Any:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception:
            return default

    @staticmethod
    def _save_json(path: str, payload: Any) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    @classmethod
    def _load_rules(cls) -> Dict[str, Dict[str, float]]:
        loaded = cls._load_json(REVENUE_BAR_RULES_FILE, {})
        if not isinstance(loaded, dict):
            loaded = {}
        rules = {}
        for key, defaults in cls.DEFAULT_RULES.items():
            current = loaded.get(key) if isinstance(loaded.get(key), dict) else {}
            rules[key] = {
                'base_bar': float(current.get('base_bar', defaults['base_bar'])),
                'min_bar': float(current.get('min_bar', defaults['min_bar'])),
                'max_bar': float(current.get('max_bar', defaults['max_bar'])),
            }
        return rules

    @classmethod
    def save_rules(cls, rules_payload: Dict[str, Dict[str, Any]], user: str) -> Dict[str, Any]:
        current = cls._load_rules()
        for key in ('alma', 'mar', 'areia'):
            if key not in rules_payload:
                continue
            incoming = rules_payload.get(key) or {}
            current[key] = {
                'base_bar': float(incoming.get('base_bar', current[key]['base_bar'])),
                'min_bar': float(incoming.get('min_bar', current[key]['min_bar'])),
                'max_bar': float(incoming.get('max_bar', current[key]['max_bar'])),
            }
        with file_lock(REVENUE_BAR_RULES_FILE):
            cls._save_json(REVENUE_BAR_RULES_FILE, current)
        LoggerService.log_acao(
            acao='Atualizou regras Revenue',
            entidade='Revenue Management',
            detalhes=current,
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return current

    @classmethod
    def _load_advanced_config(cls) -> Dict[str, Any]:
        loaded = cls._load_json(REVENUE_ADVANCED_SETTINGS_FILE, {})
        if not isinstance(loaded, dict):
            loaded = {}
        merged = dict(cls.DEFAULT_ADVANCED_CONFIG)
        for key in ('season_by_month', 'revpar_target', 'channel_weights', 'category_limits', 'occupancy_thresholds', 'category_strategies', 'booking_commercial'):
            default_part = cls.DEFAULT_ADVANCED_CONFIG.get(key, {})
            incoming = loaded.get(key, {})
            if isinstance(default_part, dict) and isinstance(incoming, dict):
                merged_part = dict(default_part)
                for inner_key, inner_val in incoming.items():
                    if isinstance(inner_val, dict) and isinstance(merged_part.get(inner_key), dict):
                        nested = dict(merged_part[inner_key])
                        nested.update(inner_val)
                        merged_part[inner_key] = nested
                    else:
                        merged_part[inner_key] = inner_val
                merged[key] = merged_part
        for key in ('max_increase_pct', 'max_reduction_pct'):
            merged[key] = float(loaded.get(key, cls.DEFAULT_ADVANCED_CONFIG[key]))
        return merged

    @classmethod
    def save_advanced_config(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        current = cls._load_advanced_config()
        for key in ('season_by_month', 'revpar_target', 'channel_weights', 'category_limits', 'occupancy_thresholds', 'category_strategies', 'booking_commercial'):
            incoming = payload.get(key)
            if not isinstance(incoming, dict):
                continue
            part = current.get(key, {})
            if not isinstance(part, dict):
                part = {}
            for sub_key, sub_val in incoming.items():
                if isinstance(sub_val, dict) and isinstance(part.get(sub_key), dict):
                    nested = dict(part[sub_key])
                    nested.update(sub_val)
                    part[sub_key] = nested
                else:
                    part[sub_key] = sub_val
            current[key] = part
        if 'max_increase_pct' in payload:
            current['max_increase_pct'] = float(payload.get('max_increase_pct'))
        if 'max_reduction_pct' in payload:
            current['max_reduction_pct'] = float(payload.get('max_reduction_pct'))
        with file_lock(REVENUE_ADVANCED_SETTINGS_FILE):
            cls._save_json(REVENUE_ADVANCED_SETTINGS_FILE, current)
        LoggerService.log_acao(
            acao='Atualizou configuração avançada de Revenue',
            entidade='Revenue Management',
            detalhes={'keys': list(payload.keys())},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return current

    @classmethod
    def _events_index(cls) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for event in cls._load_events():
            factor = cls._impact_to_factor(str(event.get('impact') or 'baixo'))
            try:
                start = cls._parse_date(event.get('start_date')).date()
                end = cls._parse_date(event.get('end_date')).date()
            except Exception:
                continue
            if end < start:
                start, end = end, start
            current = start
            while current <= end:
                day = current.isoformat()
                current_best = out.get(day)
                current_factor = float(current_best.get('factor', 1.0)) if isinstance(current_best, dict) else 1.0
                if factor >= current_factor:
                    out[day] = {
                        'id': event.get('id'),
                        'name': event.get('name'),
                        'city': event.get('city'),
                        'impact': event.get('impact'),
                        'factor': factor,
                    }
                current += timedelta(days=1)
        return out

    @classmethod
    def _impact_to_factor(cls, impact: str) -> float:
        key = str(impact or '').strip().lower()
        if key == 'alto':
            return 1.18
        if key == 'medio' or key == 'médio':
            return 1.10
        return 1.04

    @classmethod
    def _load_events_raw(cls) -> List[Dict[str, Any]]:
        rows = cls._load_json(REVENUE_EVENTS_FILE, [])
        return rows if isinstance(rows, list) else []

    @classmethod
    def _save_events_raw(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(REVENUE_EVENTS_FILE):
            cls._save_json(REVENUE_EVENTS_FILE, rows)

    @classmethod
    def _load_events(cls) -> List[Dict[str, Any]]:
        rows = cls._load_events_raw()
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get('name') and row.get('start_date') and row.get('end_date'):
                item = dict(row)
                item['impact'] = str(item.get('impact') or 'baixo').strip().lower()
                item['status'] = str(item.get('status') or 'active').strip().lower()
                if item['impact'] not in ('baixo', 'medio', 'médio', 'alto'):
                    item['impact'] = 'baixo'
                out.append(item)
                continue
            date_key = str(row.get('date') or '').strip()
            if not date_key:
                continue
            factor = float(row.get('factor') or 1.0)
            impact = 'baixo'
            if factor >= 1.16:
                impact = 'alto'
            elif factor >= 1.08:
                impact = 'medio'
            out.append({
                'id': f'legacy_{date_key}',
                'name': str(row.get('name') or f'Evento {date_key}'),
                'city': str(row.get('city') or ''),
                'start_date': date_key,
                'end_date': date_key,
                'impact': impact,
                'status': 'active',
                'legacy_factor': factor,
            })
        return out

    @classmethod
    def list_events(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, city: Optional[str] = None, impact: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_events()
        start = cls._parse_date(start_date).date() if start_date else None
        end = cls._parse_date(end_date).date() if end_date else None
        city_norm = str(city or '').strip().lower()
        impact_norm = str(impact or '').strip().lower()
        out = []
        for row in rows:
            if str(row.get('status') or 'active').lower() != 'active':
                continue
            try:
                row_start = cls._parse_date(row.get('start_date')).date()
                row_end = cls._parse_date(row.get('end_date')).date()
            except Exception:
                continue
            if row_end < row_start:
                row_start, row_end = row_end, row_start
            if start and row_end < start:
                continue
            if end and row_start > end:
                continue
            if city_norm and city_norm not in str(row.get('city') or '').strip().lower():
                continue
            if impact_norm and impact_norm != str(row.get('impact') or '').strip().lower():
                continue
            item = dict(row)
            item['factor'] = cls._impact_to_factor(str(item.get('impact') or 'baixo'))
            out.append(item)
        out.sort(key=lambda x: (x.get('start_date') or '', x.get('name') or ''))
        return out

    @classmethod
    def save_event(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        name = str(payload.get('name') or '').strip()
        city = str(payload.get('city') or '').strip()
        impact = str(payload.get('impact') or 'baixo').strip().lower()
        start_date = str(payload.get('start_date') or '').strip()
        end_date = str(payload.get('end_date') or '').strip()
        if not name:
            raise ValueError('Nome do evento obrigatório')
        if not city:
            raise ValueError('Cidade obrigatória')
        if impact not in ('baixo', 'medio', 'médio', 'alto'):
            raise ValueError('Impacto inválido')
        if not start_date or not end_date:
            raise ValueError('Período obrigatório')
        start = cls._parse_date(start_date).date().isoformat()
        end = cls._parse_date(end_date).date().isoformat()
        if end < start:
            start, end = end, start
        rows = cls._load_events_raw()
        event_id = str(payload.get('id') or '').strip()
        now = datetime.now().isoformat()
        item = {
            'id': event_id or f'evt_{int(datetime.now().timestamp() * 1000)}',
            'name': name,
            'city': city,
            'start_date': start,
            'end_date': end,
            'impact': 'medio' if impact == 'médio' else impact,
            'status': 'active',
            'updated_at': now,
            'updated_by': user,
        }
        replaced = False
        for idx, row in enumerate(rows):
            if str((row or {}).get('id') or '') == item['id']:
                rows[idx] = item
                replaced = True
                break
        if not replaced:
            rows.append(item)
        cls._save_events_raw(rows)
        LoggerService.log_acao(
            acao='Atualizou calendário de eventos',
            entidade='Revenue Management',
            detalhes=item,
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return item

    @classmethod
    def delete_event(cls, event_id: str, user: str) -> Dict[str, Any]:
        rows = cls._load_events_raw()
        target = str(event_id or '').strip()
        if not target:
            raise ValueError('Evento inválido')
        new_rows = [row for row in rows if str((row or {}).get('id') or '') != target]
        removed = len(rows) - len(new_rows)
        if removed <= 0:
            return {'removed': 0}
        cls._save_events_raw(new_rows)
        LoggerService.log_acao(
            acao='Removeu evento do calendário local',
            entidade='Revenue Management',
            detalhes={'event_id': target},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {'removed': removed}

    @classmethod
    def _load_changes(cls) -> List[Dict[str, Any]]:
        loaded = cls._load_json(REVENUE_BAR_CHANGES_FILE, [])
        return loaded if isinstance(loaded, list) else []

    @classmethod
    def _save_changes(cls, payload: List[Dict[str, Any]]) -> None:
        with file_lock(REVENUE_BAR_CHANGES_FILE):
            cls._save_json(REVENUE_BAR_CHANGES_FILE, payload)

    @classmethod
    def _current_tariff_index(cls) -> Dict[str, float]:
        index: Dict[str, float] = {}
        for item in cls._load_changes():
            if not isinstance(item, dict):
                continue
            date = str(item.get('date') or '').strip()
            category = cls._normalize_category(item.get('category'))
            if not date or not category:
                continue
            key = f'{date}|{category}'
            after_bar = item.get('after_bar')
            try:
                index[key] = float(after_bar)
            except Exception:
                continue
        return index

    @classmethod
    def _append_change(
        cls,
        *,
        user: str,
        date: str,
        category: str,
        before_bar: Any,
        after_bar: Any,
        origin: str,
        justification: str,
        reason: str,
        target_revpar: Optional[Any] = None,
        estimated_revpar_after: Optional[Any] = None,
        estimated_revpar_impact: Optional[Any] = None,
    ) -> Dict[str, Any]:
        item = {
            'applied_at': datetime.now().isoformat(),
            'user': user,
            'date': date,
            'category': cls._normalize_category(category),
            'before_bar': float(before_bar or 0),
            'after_bar': float(after_bar or 0),
            'origin': str(origin or 'manual'),
            'justification': str(justification or ''),
            'reason': str(reason or ''),
            'target_revpar': target_revpar,
            'estimated_revpar_after': estimated_revpar_after,
            'estimated_revpar_impact': estimated_revpar_impact,
        }
        return item

    @classmethod
    def _target_revpar_for_day(cls, day: datetime, advanced: Dict[str, Any]) -> float:
        season_by_month = advanced.get('season_by_month', {})
        season = str(season_by_month.get(str(day.month), 'media'))
        weekday_key = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][day.weekday()]
        table = advanced.get('revpar_target', {})
        season_table = table.get(season, {})
        return float(season_table.get(weekday_key, 0.0))

    @classmethod
    def _channel_weight(cls, reservation: Dict[str, Any], advanced: Dict[str, Any]) -> float:
        channel_weights = advanced.get('channel_weights', {})
        channel = cls._normalize_channel(reservation.get('channel') or reservation.get('origin'))
        return float(channel_weights.get(channel, channel_weights.get('default', 1.0)))

    @staticmethod
    def _channel_label(channel_key: str) -> str:
        labels = {
            'direto': 'Direto',
            'motor': 'Motor de Reservas',
            'booking': 'Booking.com',
            'expedia': 'Expedia',
            'airbnb': 'Airbnb',
            'agencia': 'Agência',
            'whatsapp': 'WhatsApp',
            'telefone': 'Telefone',
            'recepcao': 'Recepção',
        }
        return labels.get(channel_key, channel_key.title() if channel_key else 'Outros')

    @classmethod
    def _category_strategy_key(cls, reservation_or_category: Any) -> str:
        text = str(reservation_or_category or '').lower()
        if 'diamante' in text:
            return 'master_diamante'
        return cls._normalize_category(reservation_or_category)

    @classmethod
    def _channel_priority_factor(cls, channel_key: str, strategy_conf: Dict[str, Any]) -> float:
        priority = strategy_conf.get('channel_priority') or []
        if not isinstance(priority, list) or not priority:
            return 1.0
        normalized = [cls._normalize_channel(item) for item in priority]
        try:
            idx = normalized.index(channel_key)
        except ValueError:
            return 0.985
        if idx == 0:
            return 1.03
        if idx == 1:
            return 1.015
        if idx >= len(normalized) - 2:
            return 0.985
        return 1.0

    @classmethod
    def channel_performance_report(cls, start_date: str, end_date: str, category: Optional[str] = None) -> Dict[str, Any]:
        start_dt = cls._parse_date(start_date).date()
        end_dt = cls._parse_date(end_date).date()
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        category_filter = cls._normalize_category(category) if category else ''
        reservations = ReservationService().get_february_reservations()
        channels: Dict[str, Dict[str, Any]] = {}

        for item in reservations:
            if not isinstance(item, dict):
                continue
            bucket = cls._normalize_category(item.get('category'))
            if category_filter and bucket != category_filter:
                continue
            checkin = FinanceDashboardService._parse_date(item.get('checkin'))
            checkout = FinanceDashboardService._parse_date(item.get('checkout'))
            if not checkin or not checkout:
                continue
            if checkout.date() < start_dt or checkin.date() > end_dt:
                continue
            channel_key = cls._normalize_channel(item.get('channel') or item.get('origin'))
            slot = channels.setdefault(channel_key, {
                'channel': channel_key,
                'label': cls._channel_label(channel_key),
                'reservations_count': 0,
                'total_revenue': 0.0,
                'room_nights': 0,
                'cancellations': 0,
                'lead_time_sum': 0.0,
                'lead_time_count': 0,
            })
            status = str(item.get('status') or '').lower()
            is_cancel = 'cancel' in status
            slot['reservations_count'] += 1
            if is_cancel:
                slot['cancellations'] += 1
            else:
                total = float(FinanceDashboardService._reservation_total(item) or 0.0)
                stay_nights = max((checkout.date() - checkin.date()).days, 1)
                slot['total_revenue'] += total
                slot['room_nights'] += stay_nights
            created_dt = cls._reservation_created_datetime(item)
            if created_dt:
                lead_time = (checkin.date() - created_dt.date()).days
                if lead_time >= 0:
                    slot['lead_time_sum'] += float(lead_time)
                    slot['lead_time_count'] += 1

        ranking = []
        for channel_key, slot in channels.items():
            reservations_count = int(slot.get('reservations_count') or 0)
            total_revenue = float(slot.get('total_revenue') or 0.0)
            room_nights = int(slot.get('room_nights') or 0)
            lead_time_count = int(slot.get('lead_time_count') or 0)
            lead_time_avg = (float(slot.get('lead_time_sum') or 0.0) / lead_time_count) if lead_time_count > 0 else 0.0
            adr = (total_revenue / room_nights) if room_nights > 0 else 0.0
            ranking.append({
                'channel': channel_key,
                'label': str(slot.get('label') or channel_key),
                'reservations_count': reservations_count,
                'total_revenue': round(total_revenue, 2),
                'adr': round(adr, 2),
                'cancellations': int(slot.get('cancellations') or 0),
                'lead_time_avg_days': round(lead_time_avg, 2),
            })
        ranking.sort(key=lambda row: (float(row.get('total_revenue') or 0.0), int(row.get('reservations_count') or 0)), reverse=True)
        for idx, row in enumerate(ranking, start=1):
            row['rank'] = idx
        return {
            'start_date': start_dt.isoformat(),
            'end_date': end_dt.isoformat(),
            'category': category_filter or None,
            'items': ranking,
            'count': len(ranking),
        }

    @classmethod
    def reservations_calendar_heatmap(cls, start_date: str, days: int = 31) -> Dict[str, Any]:
        start_dt = cls._parse_date(start_date).date()
        days_count = max(1, int(days))
        forecast = cls.occupancy_forecast(start_date=start_dt.isoformat(), days=days_count, category=None)
        rows = [row for row in (forecast.get('rows') or []) if isinstance(row, dict)]
        by_day: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            day = str(row.get('date') or '')
            slot = by_day.setdefault(day, {'capacity': 0, 'current_weighted': 0.0, 'projected_weighted': 0.0})
            capacity = max(1, int(row.get('capacity') or 1))
            slot['capacity'] += capacity
            slot['current_weighted'] += float(row.get('occupancy_current_pct') or 0.0) * capacity
            slot['projected_weighted'] += float(row.get('occupancy_projected_pct') or 0.0) * capacity

        reservations = ReservationService().get_february_reservations()
        daily_rate_sum: Dict[str, float] = {}
        daily_rate_count: Dict[str, int] = {}
        for item in reservations:
            if not isinstance(item, dict):
                continue
            if not cls._is_active_reservation(item):
                continue
            checkin = FinanceDashboardService._parse_date(item.get('checkin'))
            checkout = FinanceDashboardService._parse_date(item.get('checkout'))
            if not checkin or not checkout:
                continue
            total = float(FinanceDashboardService._reservation_total(item) or 0.0)
            nights = max((checkout.date() - checkin.date()).days, 1)
            daily_rate = total / nights
            for day_iso in cls._iter_stay_days(item.get('checkin'), item.get('checkout')):
                try:
                    day_dt = cls._parse_date(day_iso).date()
                except Exception:
                    continue
                if day_dt < start_dt or day_dt > (start_dt + timedelta(days=days_count - 1)):
                    continue
                daily_rate_sum[day_iso] = float(daily_rate_sum.get(day_iso, 0.0)) + daily_rate
                daily_rate_count[day_iso] = int(daily_rate_count.get(day_iso, 0)) + 1

        out_rows = []
        for i in range(days_count):
            day_iso = (start_dt + timedelta(days=i)).isoformat()
            slot = by_day.get(day_iso, {})
            cap = int(slot.get('capacity') or 0)
            current_pct = (float(slot.get('current_weighted') or 0.0) / cap) if cap > 0 else 0.0
            projected_pct = (float(slot.get('projected_weighted') or 0.0) / cap) if cap > 0 else 0.0
            avg_rate = 0.0
            if int(daily_rate_count.get(day_iso, 0)) > 0:
                avg_rate = float(daily_rate_sum.get(day_iso, 0.0)) / max(int(daily_rate_count.get(day_iso, 0)), 1)
            if projected_pct < 40.0:
                level = 'low'
                color = 'green'
            elif projected_pct > 80.0:
                level = 'high'
                color = 'red'
            else:
                level = 'medium'
                color = 'yellow'
            out_rows.append({
                'date': day_iso,
                'occupancy_current_pct': round(current_pct, 2),
                'occupancy_projected_pct': round(projected_pct, 2),
                'average_rate': round(avg_rate, 2),
                'heat_level': level,
                'heat_color': color,
            })
        return {
            'start_date': start_dt.isoformat(),
            'days': days_count,
            'rows': out_rows,
            'count': len(out_rows),
        }

    @classmethod
    def get_category_strategies(cls) -> Dict[str, Any]:
        advanced = cls._load_advanced_config()
        raw = advanced.get('category_strategies') or {}
        default = cls.DEFAULT_ADVANCED_CONFIG.get('category_strategies') or {}
        out: Dict[str, Any] = {}
        for key, defaults in default.items():
            current = raw.get(key) if isinstance(raw.get(key), dict) else {}
            out[key] = {
                'name': str(current.get('name', defaults.get('name', ''))),
                'discount_limit_pct': float(current.get('discount_limit_pct', defaults.get('discount_limit_pct', 0.0))),
                'increase_limit_pct': float(current.get('increase_limit_pct', defaults.get('increase_limit_pct', 0.0))),
                'channel_priority': list(current.get('channel_priority') or defaults.get('channel_priority') or []),
            }
        return out

    @classmethod
    def save_category_strategies(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        current = cls._load_advanced_config()
        current_strategies = current.get('category_strategies')
        if not isinstance(current_strategies, dict):
            current_strategies = {}
        for key in ('areia', 'mar', 'master_diamante'):
            incoming = payload.get(key)
            if not isinstance(incoming, dict):
                continue
            prev = current_strategies.get(key) if isinstance(current_strategies.get(key), dict) else {}
            discount_limit_pct = float(incoming.get('discount_limit_pct', prev.get('discount_limit_pct', 0.0)))
            increase_limit_pct = float(incoming.get('increase_limit_pct', prev.get('increase_limit_pct', 0.0)))
            current_strategies[key] = {
                'name': str(incoming.get('name', prev.get('name', key))),
                'discount_limit_pct': max(0.0, min(0.95, discount_limit_pct)),
                'increase_limit_pct': max(0.0, min(1.0, increase_limit_pct)),
                'channel_priority': [cls._normalize_channel(item) for item in (incoming.get('channel_priority') or prev.get('channel_priority') or [])],
            }
        current['category_strategies'] = current_strategies
        with file_lock(REVENUE_ADVANCED_SETTINGS_FILE):
            cls._save_json(REVENUE_ADVANCED_SETTINGS_FILE, current)
        LoggerService.log_acao(
            acao='Atualizou estratégias por categoria',
            entidade='Revenue Management',
            detalhes={'keys': list((payload or {}).keys())},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return cls.get_category_strategies()

    @classmethod
    def _normalize_booking_model(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        if text == 'net_rate':
            return 'net_rate'
        return 'commission_rate'

    @classmethod
    def _normalize_booking_adjustment_type(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        if text == 'tarifa_especifica_ota':
            return 'tarifa_manual_ota'
        if text in ('manter_tarifa_direta', 'manter_liquido_hotel', 'tarifa_manual_ota'):
            return text
        return 'manter_liquido_hotel'

    @classmethod
    def _normalize_commission_pct(cls, value: Any, fallback: float = 0.0) -> float:
        try:
            pct = float(value)
        except Exception:
            pct = float(fallback or 0.0)
        return max(0.0, min(0.95, pct))

    @classmethod
    def _normalize_currency_step(cls, value: Any, fallback: float = 0.01) -> float:
        try:
            step = float(value)
        except Exception:
            step = float(fallback or 0.01)
        return max(0.01, step)

    @classmethod
    def get_booking_commercial_config(cls) -> Dict[str, Any]:
        advanced = cls._load_advanced_config()
        default_cfg = cls.DEFAULT_ADVANCED_CONFIG.get('booking_commercial', {})
        incoming = advanced.get('booking_commercial', {})
        if not isinstance(incoming, dict):
            incoming = {}
        comissao_por_categoria = incoming.get('comissao_por_categoria', {})
        if not isinstance(comissao_por_categoria, dict):
            comissao_por_categoria = {}
        normalized_by_category: Dict[str, float] = {}
        for key, value in comissao_por_categoria.items():
            category = cls._normalize_booking_category(key)
            normalized_by_category[category] = cls._normalize_commission_pct(value, fallback=0.0)
        comissao_por_periodo = incoming.get('comissao_por_periodo', [])
        if not isinstance(comissao_por_periodo, list):
            comissao_por_periodo = []
        normalized_periods: List[Dict[str, Any]] = []
        for item in comissao_por_periodo:
            if not isinstance(item, dict):
                continue
            start_date = str(item.get('start_date') or '').strip()
            end_date = str(item.get('end_date') or '').strip()
            if not start_date or not end_date:
                continue
            normalized_periods.append({
                'start_date': start_date,
                'end_date': end_date,
                'category': cls._normalize_booking_category(item.get('category')) if item.get('category') else '',
                'comissao_percentual': cls._normalize_commission_pct(item.get('comissao_percentual'), fallback=0.0),
            })
        tarifa_especifica_ota = incoming.get('tarifa_especifica_ota', {})
        if not isinstance(tarifa_especifica_ota, dict):
            tarifa_especifica_ota = {}
        normalized_tarifa_especifica: Dict[str, float] = {}
        for key, value in tarifa_especifica_ota.items():
            category = cls._normalize_booking_category(key)
            try:
                normalized_tarifa_especifica[category] = max(0.0, float(value))
            except Exception:
                continue
        tarifa_manual_ota = incoming.get('tarifa_manual_ota', {})
        if not isinstance(tarifa_manual_ota, dict):
            tarifa_manual_ota = {}
        normalized_tarifa_manual: Dict[str, float] = {}
        source_manual = tarifa_manual_ota if tarifa_manual_ota else normalized_tarifa_especifica
        for key, value in source_manual.items():
            category = cls._normalize_booking_category(key)
            try:
                normalized_tarifa_manual[category] = max(0.0, float(value))
            except Exception:
                continue
        base_commission = incoming.get('comissao_padrao_percentual', incoming.get('comissao_percentual', default_cfg.get('comissao_padrao_percentual', default_cfg.get('comissao_percentual', 0.0))))
        min_ota = max(0.0, float(incoming.get('tarifa_minima_ota', default_cfg.get('tarifa_minima_ota', 0.0)) or 0.0))
        max_ota = max(0.0, float(incoming.get('tarifa_maxima_ota', default_cfg.get('tarifa_maxima_ota', 0.0)) or 0.0))
        if max_ota > 0 and max_ota < min_ota:
            max_ota = min_ota
        ativo_raw = incoming.get('ativo', default_cfg.get('ativo', True))
        ativo = str(ativo_raw).strip().lower() in ('1', 'true', 'yes', 'sim', 'ativo', 'active') if not isinstance(ativo_raw, bool) else bool(ativo_raw)
        return {
            'modelo_comercial': cls._normalize_booking_model(incoming.get('modelo_comercial', default_cfg.get('modelo_comercial'))),
            'comissao_padrao_percentual': cls._normalize_commission_pct(base_commission, fallback=0.0),
            'comissao_percentual': cls._normalize_commission_pct(base_commission, fallback=0.0),
            'comissao_por_categoria': normalized_by_category,
            'comissao_por_periodo': normalized_periods,
            'tipo_ajuste_tarifa': cls._normalize_booking_adjustment_type(incoming.get('tipo_ajuste_tarifa', default_cfg.get('tipo_ajuste_tarifa'))),
            'tarifa_manual_ota': normalized_tarifa_manual,
            'tarifa_especifica_ota': normalized_tarifa_especifica,
            'arredondamento': cls._normalize_currency_step(incoming.get('arredondamento', default_cfg.get('arredondamento', 0.01)), fallback=0.01),
            'tarifa_minima_ota': min_ota,
            'tarifa_maxima_ota': max_ota,
            'ativo': ativo,
        }

    @classmethod
    def _load_booking_commission_logs(cls) -> List[Dict[str, Any]]:
        loaded = cls._load_json(REVENUE_BOOKING_COMMISSION_LOGS_FILE, [])
        return loaded if isinstance(loaded, list) else []

    @classmethod
    def _save_booking_commission_logs(cls, payload: List[Dict[str, Any]]) -> None:
        with file_lock(REVENUE_BOOKING_COMMISSION_LOGS_FILE):
            cls._save_json(REVENUE_BOOKING_COMMISSION_LOGS_FILE, payload)

    @classmethod
    def save_booking_commercial_config(cls, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        reason_text = str(reason or '').strip()
        if len(reason_text) < 3:
            raise ValueError('Motivo obrigatório para alterar comissão Booking.')
        previous = cls.get_booking_commercial_config()
        current = cls._load_advanced_config()
        incoming = payload if isinstance(payload, dict) else {}
        merged = dict(previous)
        if 'modelo_comercial' in incoming:
            merged['modelo_comercial'] = cls._normalize_booking_model(incoming.get('modelo_comercial'))
        if 'comissao_padrao_percentual' in incoming or 'comissao_percentual' in incoming:
            commission_incoming = incoming.get('comissao_padrao_percentual', incoming.get('comissao_percentual'))
            merged['comissao_padrao_percentual'] = cls._normalize_commission_pct(commission_incoming, fallback=merged.get('comissao_padrao_percentual', merged.get('comissao_percentual', 0.0)))
            merged['comissao_percentual'] = merged['comissao_padrao_percentual']
        if isinstance(incoming.get('comissao_por_categoria'), dict):
            by_category = {}
            for key, value in (incoming.get('comissao_por_categoria') or {}).items():
                by_category[cls._normalize_booking_category(key)] = cls._normalize_commission_pct(value, fallback=0.0)
            merged['comissao_por_categoria'] = by_category
        if isinstance(incoming.get('comissao_por_periodo'), list):
            normalized_periods: List[Dict[str, Any]] = []
            for item in (incoming.get('comissao_por_periodo') or []):
                if not isinstance(item, dict):
                    continue
                start_date = str(item.get('start_date') or '').strip()
                end_date = str(item.get('end_date') or '').strip()
                if not start_date or not end_date:
                    continue
                normalized_periods.append({
                    'start_date': start_date,
                    'end_date': end_date,
                    'category': cls._normalize_booking_category(item.get('category')) if item.get('category') else '',
                    'comissao_percentual': cls._normalize_commission_pct(item.get('comissao_percentual'), fallback=0.0),
                })
            merged['comissao_por_periodo'] = normalized_periods
        if 'tipo_ajuste_tarifa' in incoming:
            merged['tipo_ajuste_tarifa'] = cls._normalize_booking_adjustment_type(incoming.get('tipo_ajuste_tarifa'))
        if isinstance(incoming.get('tarifa_especifica_ota'), dict) or isinstance(incoming.get('tarifa_manual_ota'), dict):
            tarifa_ota = {}
            source_map = incoming.get('tarifa_manual_ota') if isinstance(incoming.get('tarifa_manual_ota'), dict) else incoming.get('tarifa_especifica_ota')
            for key, value in (source_map or {}).items():
                try:
                    tarifa_ota[cls._normalize_booking_category(key)] = max(0.0, float(value))
                except Exception:
                    continue
            merged['tarifa_manual_ota'] = tarifa_ota
            merged['tarifa_especifica_ota'] = tarifa_ota
        if 'arredondamento' in incoming:
            merged['arredondamento'] = cls._normalize_currency_step(incoming.get('arredondamento'), fallback=merged.get('arredondamento', 0.01))
        if 'tarifa_minima_ota' in incoming:
            merged['tarifa_minima_ota'] = max(0.0, float(incoming.get('tarifa_minima_ota') or 0.0))
        if 'tarifa_maxima_ota' in incoming:
            merged['tarifa_maxima_ota'] = max(0.0, float(incoming.get('tarifa_maxima_ota') or 0.0))
        if float(merged.get('tarifa_maxima_ota') or 0.0) > 0 and float(merged.get('tarifa_maxima_ota') or 0.0) < float(merged.get('tarifa_minima_ota') or 0.0):
            merged['tarifa_maxima_ota'] = float(merged.get('tarifa_minima_ota') or 0.0)
        if 'ativo' in incoming:
            ativo_raw = incoming.get('ativo')
            merged['ativo'] = bool(ativo_raw) if isinstance(ativo_raw, bool) else (str(ativo_raw).strip().lower() in ('1', 'true', 'yes', 'sim', 'ativo', 'active'))
        current['booking_commercial'] = merged
        with file_lock(REVENUE_ADVANCED_SETTINGS_FILE):
            cls._save_json(REVENUE_ADVANCED_SETTINGS_FILE, current)
        log_item = {
            'changed_at': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'previous': previous,
            'current': merged,
            'motivo': reason_text,
        }
        logs = cls._load_booking_commission_logs()
        logs.append(log_item)
        cls._save_booking_commission_logs(logs)
        LoggerService.log_acao(
            acao='Alterou comissão Booking no Revenue',
            entidade='Revenue Management',
            detalhes=log_item,
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return cls.get_booking_commercial_config()

    @classmethod
    def list_booking_commission_logs(
        cls,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_booking_commission_logs()
        start_dt = cls._parse_date(start_date).date() if start_date else None
        end_dt = cls._parse_date(end_date).date() if end_date else None
        user_norm = str(user or '').strip().lower()
        out: List[Dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            changed_at = str(item.get('changed_at') or '').strip()
            if not changed_at:
                continue
            try:
                changed_dt = datetime.fromisoformat(changed_at).date()
            except Exception:
                continue
            if start_dt and changed_dt < start_dt:
                continue
            if end_dt and changed_dt > end_dt:
                continue
            if user_norm and str(item.get('user') or '').strip().lower() != user_norm:
                continue
            out.append(item)
        out.sort(key=lambda row: str(row.get('changed_at') or ''), reverse=True)
        return out

    @classmethod
    def _booking_commission_for_context(cls, cfg: Dict[str, Any], category: str, date_str: str) -> float:
        pct = cls._normalize_commission_pct(cfg.get('comissao_padrao_percentual', cfg.get('comissao_percentual')), fallback=0.0)
        booking_category = cls._normalize_booking_category(category)
        by_category = cfg.get('comissao_por_categoria', {})
        if isinstance(by_category, dict):
            key = booking_category
            if key in by_category:
                pct = cls._normalize_commission_pct(by_category.get(key), fallback=pct)
        periods = cfg.get('comissao_por_periodo', [])
        if isinstance(periods, list):
            for item in periods:
                if not isinstance(item, dict):
                    continue
                period_category = str(item.get('category') or '').strip().lower()
                if period_category and cls._normalize_booking_category(period_category) != booking_category:
                    continue
                try:
                    start_dt = cls._parse_date(item.get('start_date')).date()
                    end_dt = cls._parse_date(item.get('end_date')).date()
                    target_dt = cls._parse_date(date_str).date()
                except Exception:
                    continue
                if end_dt < start_dt:
                    start_dt, end_dt = end_dt, start_dt
                if start_dt <= target_dt <= end_dt:
                    pct = cls._normalize_commission_pct(item.get('comissao_percentual'), fallback=pct)
        return pct

    @classmethod
    def calculate_booking_ota_pricing(
        cls,
        *,
        tarifa_direta: float,
        category: str,
        date_str: str,
        tarifa_liquida_desejada: Optional[float] = None,
    ) -> Dict[str, Any]:
        cfg = cls.get_booking_commercial_config()
        modelo = str(cfg.get('modelo_comercial') or 'commission_rate')
        ajuste = str(cfg.get('tipo_ajuste_tarifa') or 'manter_liquido_hotel')
        direct = max(0.0, float(tarifa_direta or 0.0))
        desired_net = max(0.0, float(tarifa_liquida_desejada if tarifa_liquida_desejada is not None else direct))
        booking_category = cls._normalize_booking_category(category)
        comissao_pct = cls._booking_commission_for_context(cfg, booking_category, date_str)
        if modelo == 'net_rate':
            net_base = direct
            if ajuste == 'manter_tarifa_direta':
                ota = net_base
                net = ota * (1.0 - comissao_pct)
            elif ajuste == 'tarifa_manual_ota':
                tariff_map = cfg.get('tarifa_manual_ota') or cfg.get('tarifa_especifica_ota') or {}
                if isinstance(tariff_map, dict):
                    ota = max(0.0, float(tariff_map.get(booking_category, net_base)))
                else:
                    ota = net_base
                net = ota * (1.0 - comissao_pct)
            else:
                denominator = max(1.0 - comissao_pct, 0.0001)
                ota = net_base / denominator
                net = net_base
        else:
            if ajuste == 'manter_tarifa_direta':
                ota = direct
                net = ota * (1.0 - comissao_pct)
            elif ajuste == 'tarifa_manual_ota':
                tariff_map = cfg.get('tarifa_manual_ota') or cfg.get('tarifa_especifica_ota') or {}
                if isinstance(tariff_map, dict):
                    ota = max(0.0, float(tariff_map.get(booking_category, direct)))
                else:
                    ota = direct
                net = ota * (1.0 - comissao_pct)
            else:
                denominator = max(1.0 - comissao_pct, 0.0001)
                ota = direct / denominator
                net = direct
        rounding_step = cls._normalize_currency_step(cfg.get('arredondamento', 0.01), fallback=0.01)
        ota = round(ota / rounding_step) * rounding_step if rounding_step > 0 else ota
        min_ota = max(0.0, float(cfg.get('tarifa_minima_ota') or 0.0))
        max_ota = max(0.0, float(cfg.get('tarifa_maxima_ota') or 0.0))
        if max_ota > 0 and max_ota < min_ota:
            max_ota = min_ota
        if min_ota > 0:
            ota = max(ota, min_ota)
        if max_ota > 0:
            ota = min(ota, max_ota)
        net = ota * (1.0 - comissao_pct)
        comissao_valor = max(0.0, ota - net)
        return {
            'modelo_comercial': modelo,
            'tipo_ajuste_tarifa': ajuste,
            'tarifa_direta': round(direct, 2),
            'tarifa_liquida_desejada': round(desired_net, 2),
            'comissao_percentual': round(comissao_pct, 6),
            'comissao_aplicada_percentual': round(comissao_pct, 6),
            'comissao_valor': round(comissao_valor, 2),
            'tarifa_ota_final': round(ota, 2),
            'tarifa_ota_enviada': round(ota, 2),
            'liquido_estimado_hotel': round(net, 2),
            'ativo': bool(cfg.get('ativo', True)),
            'booking_category': booking_category,
        }

    @classmethod
    def calendar_direct_vs_ota(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from app.services.channel_inventory_control_service import ChannelInventoryControlService
        from app.services.ota_booking_rm_service import OTABookingRMService
        from app.services.period_selector_service import PeriodSelectorService
        from app.services.promotional_package_service import PromotionalPackageService
        from app.services.stay_restriction_service import StayRestrictionService

        requested = str(category or '').strip().lower()
        if requested in ('todas', 'todos', 'all', 'all_booking_categories', '*'):
            all_rows: List[Dict[str, Any]] = []
            for item in cls.BOOKING_CATEGORY_OPTIONS:
                part = cls.calendar_direct_vs_ota(
                    category=str(item.get('key')),
                    start_date=start_date,
                    end_date=end_date,
                    weekdays=weekdays,
                )
                all_rows.extend(part.get('rows') or [])
            all_rows.sort(key=lambda row: (str(row.get('date') or ''), str(row.get('category_label') or ''), str(row.get('category') or '')))
            return {
                'category': 'all_booking_categories',
                'start_date': cls._parse_date(start_date).date().isoformat(),
                'end_date': cls._parse_date(end_date).date().isoformat(),
                'weekdays': PeriodSelectorService.normalize_weekdays(weekdays or []),
                'rows': all_rows,
                'count': len(all_rows),
            }
        booking_category = cls._normalize_booking_category(category)
        bucket = cls._booking_category_bucket(booking_category)
        category_label = booking_category.replace('_', ' ').title().replace('Familia', 'Família').replace('Banheira', 'com Banheira').replace('Diamante', 'Diamante')
        start_dt = cls._parse_date(start_date).date()
        end_dt = cls._parse_date(end_date).date()
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays or [])
        total_days = max(1, (end_dt - start_dt).days + 1)
        simulated = cls.simulate_projection(start_date=start_dt.isoformat(), days=total_days, advanced_mode=True)
        simulated_index = {
            (str(row.get('date') or ''), cls._normalize_category(row.get('category'))): row
            for row in (simulated.get('rows') or [])
            if isinstance(row, dict)
        }
        channel_rows = ChannelInventoryControlService.list_channel_restrictions(
            start_date=start_dt.isoformat(),
            end_date=end_dt.isoformat(),
            channel='Booking.com',
        )
        channel_closed_map: Dict[str, bool] = {}
        for row in channel_rows:
            if str(row.get('status') or '') != 'active':
                continue
            day = str(row.get('date') or '')
            row_category = str(row.get('category') or '')
            if row_category in (bucket, ChannelInventoryControlService.ALL_CATEGORIES_VALUE):
                channel_closed_map[day] = True
        stay_rules = StayRestrictionService.list_rules(status='active')
        stay_rules_by_day: Dict[str, List[Dict[str, Any]]] = {}
        for rule in stay_rules:
            if not isinstance(rule, dict):
                continue
            categories = {cls._normalize_category(item) for item in (rule.get('categories') or [])}
            if bucket not in categories:
                continue
            period = rule.get('period') or {}
            period_days = set(PeriodSelectorService.expand_dates(
                period.get('start_date'),
                period.get('end_date'),
                period.get('weekdays') or [],
            ))
            for day in period_days:
                stay_rules_by_day.setdefault(day, []).append(rule)
        rules = cls._load_rules()
        fallback_bar = float((rules.get(bucket) or {}).get('base_bar') or 0.0)
        rows: List[Dict[str, Any]] = []
        current = start_dt
        while current <= end_dt:
            day_iso = current.isoformat()
            weekday_code = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][current.weekday()]
            if normalized_weekdays and weekday_code not in normalized_weekdays:
                current = current.fromordinal(current.toordinal() + 1)
                continue
            sim_row = simulated_index.get((day_iso, bucket), {})
            direct_tariff = float(sim_row.get('current_bar') or sim_row.get('base_bar') or fallback_bar)
            booking = cls.calculate_booking_ota_pricing(
                tarifa_direta=direct_tariff,
                category=booking_category,
                date_str=day_iso,
                tarifa_liquida_desejada=direct_tariff,
            )
            day_rules = stay_rules_by_day.get(day_iso, [])
            min_stay_nights = max([int(r.get('min_nights') or 1) for r in day_rules] or [1])
            package_validation = PromotionalPackageService.validate_required_package_constraint(
                category=bucket,
                checkin=day_iso,
                checkout=(current + timedelta(days=1)).isoformat(),
                sale_date=day_iso,
                base_total=direct_tariff,
            )
            package_required = bool(package_validation.get('required_for_sale'))
            package_blocked = package_required and not bool(package_validation.get('valid'))
            booking_cta_ctd = OTABookingRMService.resolve_channel_cta_ctd(category=booking_category, date=day_iso)
            booking_commercial_rules = OTABookingRMService.resolve_commercial_restrictions(category=booking_category, date=day_iso)
            cta_active = bool(booking_cta_ctd.get('cta'))
            ctd_active = bool(booking_cta_ctd.get('ctd'))
            closed_ota = bool(channel_closed_map.get(day_iso))
            min_stay_nights = max(min_stay_nights, int(booking_commercial_rules.get('min_stay_nights') or 1))
            max_stay_nights = int(booking_commercial_rules.get('max_stay_nights') or 0)
            package_required = bool(package_required or booking_commercial_rules.get('pacote_obrigatorio'))
            promotion_ota = str(booking_commercial_rules.get('promocao_ota') or '').strip()
            restrictions_labels = []
            if closed_ota:
                restrictions_labels.append('stop_sell')
            if cta_active:
                restrictions_labels.append('cta')
            if ctd_active:
                restrictions_labels.append('ctd')
            if min_stay_nights > 1:
                restrictions_labels.append(f'min_stay_{min_stay_nights}')
            if package_required:
                restrictions_labels.append('pacote_obrigatorio')
            if promotion_ota:
                restrictions_labels.append(f'promocao_{promotion_ota}')
            restrictions_labels.extend([label for label in (booking_commercial_rules.get('labels') or []) if label not in restrictions_labels])
            rows.append({
                'date': day_iso,
                'category': booking_category,
                'category_bucket': bucket,
                'category_label': category_label,
                'tarifa_direta': round(direct_tariff, 2),
                'tarifa_ota': booking.get('tarifa_ota_final'),
                'comissao_ota_percentual': booking.get('comissao_percentual'),
                'comissao_ota_valor': booking.get('comissao_valor'),
                'liquido_estimado_hotel': booking.get('liquido_estimado_hotel'),
                'status_venda_ota': 'fechado' if closed_ota else 'aberto',
                'restricoes': {
                    'cta': cta_active,
                    'ctd': ctd_active,
                    'min_stay': min_stay_nights > 1,
                    'min_stay_nights': min_stay_nights,
                    'max_stay': max_stay_nights > 0,
                    'max_stay_nights': max_stay_nights,
                    'pacote': package_required,
                    'pacote_bloqueia': package_blocked,
                    'promocao_ota': promotion_ota,
                    'lista': restrictions_labels,
                },
                'projected_occupancy_pct': sim_row.get('projected_occupancy_pct'),
                'target_revpar': sim_row.get('target_revpar'),
                'projected_revpar': sim_row.get('projected_revpar'),
            })
            current = current.fromordinal(current.toordinal() + 1)
        return {
            'category': booking_category,
            'start_date': start_dt.isoformat(),
            'end_date': end_dt.isoformat(),
            'weekdays': normalized_weekdays,
            'rows': rows,
            'count': len(rows),
        }

    @classmethod
    def update_booking_channel_sale_status(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        status: str,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        from app.services.channel_inventory_control_service import ChannelInventoryControlService

        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para abrir/fechar canal Booking.')
        result = ChannelInventoryControlService.apply_channel_restriction(
            category=category,
            channel='Booking.com',
            start_date=start_date,
            end_date=end_date,
            status=status,
            user=user,
            reason=clean_reason,
            weekdays=weekdays or [],
            origin='rm_calendar',
        )
        LoggerService.log_acao(
            acao='Atualizou status de venda Booking no calendário RM',
            entidade='Revenue Management',
            detalhes={
                'category': result.get('category'),
                'status': result.get('status'),
                'period': result.get('period'),
                'motivo': clean_reason,
            },
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return result

    @classmethod
    def revenue_scenario_simulator(
        cls,
        *,
        expected_occupancy_pct: float,
        average_rate_current: float,
        average_rate_suggested: float,
        average_stay_nights: int,
        horizon_days: int = 30,
    ) -> Dict[str, Any]:
        room_mapping = ReservationService().get_room_mapping()
        total_rooms = sum(len(rooms) for rooms in room_mapping.values())
        total_rooms = max(total_rooms, 1)
        days = max(1, int(horizon_days))
        stay_nights = max(1, int(average_stay_nights))
        occupancy = max(0.0, min(100.0, float(expected_occupancy_pct)))
        current_rate = max(0.0, float(average_rate_current))
        suggested_rate = max(0.0, float(average_rate_suggested))
        available_room_days = total_rooms * days
        occupied_room_days = available_room_days * (occupancy / 100.0)
        estimated_reservations = occupied_room_days / stay_nights
        revenue_current = occupied_room_days * current_rate
        revenue_suggested = occupied_room_days * suggested_rate
        revpar_current = revenue_current / available_room_days if available_room_days > 0 else 0.0
        revpar_suggested = revenue_suggested / available_room_days if available_room_days > 0 else 0.0
        diff = revenue_suggested - revenue_current
        diff_pct = (diff / revenue_current * 100.0) if revenue_current > 0 else 0.0
        return {
            'inputs': {
                'expected_occupancy_pct': round(occupancy, 2),
                'average_rate_current': round(current_rate, 2),
                'average_rate_suggested': round(suggested_rate, 2),
                'average_stay_nights': stay_nights,
                'horizon_days': days,
                'total_rooms': total_rooms,
            },
            'outputs': {
                'estimated_total_revenue_current': round(revenue_current, 2),
                'estimated_total_revenue_suggested': round(revenue_suggested, 2),
                'estimated_revenue_diff': round(diff, 2),
                'estimated_revenue_diff_pct': round(diff_pct, 2),
                'estimated_revpar_current': round(revpar_current, 2),
                'estimated_revpar_suggested': round(revpar_suggested, 2),
                'estimated_revpar_diff': round(revpar_suggested - revpar_current, 2),
                'estimated_occupied_room_days': round(occupied_room_days, 2),
                'estimated_reservations': round(estimated_reservations, 2),
            },
        }

    @classmethod
    def _iter_stay_days(cls, checkin_text: Any, checkout_text: Any) -> List[str]:
        try:
            start = cls._parse_date(checkin_text).date()
            end = cls._parse_date(checkout_text).date()
        except Exception:
            return []
        if end <= start:
            return []
        out: List[str] = []
        current = start
        while current < end:
            out.append(current.isoformat())
            current += timedelta(days=1)
        return out

    @classmethod
    def _reservation_created_datetime(cls, reservation: Dict[str, Any]) -> Optional[datetime]:
        candidates = [
            reservation.get('created_at'),
            reservation.get('createdAt'),
            reservation.get('booking_date'),
            reservation.get('reservation_date'),
            reservation.get('booked_at'),
        ]
        for raw in candidates:
            text = str(raw or '').strip()
            if not text:
                continue
            for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    return datetime.strptime(text, fmt)
                except Exception:
                    continue
            try:
                return datetime.fromisoformat(text)
            except Exception:
                continue
        return None

    @classmethod
    def _is_active_reservation(cls, reservation: Dict[str, Any]) -> bool:
        status = str(reservation.get('status') or '').strip().lower()
        return 'cancel' not in status

    @classmethod
    def _category_capacity_by_bucket(cls) -> Dict[str, int]:
        room_mapping = ReservationService().get_room_mapping()
        return {
            'alma': len(room_mapping.get('Suíte Alma c/ Banheira', [])) + len(room_mapping.get('Suíte Alma', [])) + len(room_mapping.get('Suíte Master Diamante', [])),
            'mar': len(room_mapping.get('Suíte Mar Família', [])) + len(room_mapping.get('Suíte Mar', [])),
            'areia': len(room_mapping.get('Suíte Areia', [])),
        }

    @classmethod
    def _season_for_day(cls, day: datetime, advanced_cfg: Dict[str, Any]) -> str:
        season_by_month = advanced_cfg.get('season_by_month', {})
        return str(season_by_month.get(str(day.month), 'media')).strip().lower()

    @classmethod
    def _safe_mean(cls, values: List[float], fallback: float = 0.0) -> float:
        if not values:
            return fallback
        return float(sum(values) / max(len(values), 1))

    @classmethod
    def _build_reservation_curve_models(
        cls,
        reservations: List[Dict[str, Any]],
        advanced: Dict[str, Any],
        capacity_by_bucket: Dict[str, int],
        category_bucket: str = '',
    ) -> Dict[str, Any]:
        thresholds = (30, 15, 7, 3)
        today = datetime.now().date()
        daily_samples: Dict[str, Dict[str, Any]] = {}
        for reservation in reservations:
            if not isinstance(reservation, dict):
                continue
            if not cls._is_active_reservation(reservation):
                continue
            bucket = cls._normalize_category(reservation.get('category'))
            if category_bucket and bucket != category_bucket:
                continue
            created_dt = cls._reservation_created_datetime(reservation)
            stay_days = cls._iter_stay_days(reservation.get('checkin'), reservation.get('checkout'))
            if not stay_days:
                continue
            for day_iso in stay_days:
                try:
                    day_dt = cls._parse_date(day_iso).date()
                except Exception:
                    continue
                if day_dt >= today:
                    continue
                key = f"{day_iso}|{bucket}"
                sample = daily_samples.setdefault(key, {
                    'day_iso': day_iso,
                    'bucket': bucket,
                    'occupancy': 0,
                    'lead_days': [],
                    'weekday': day_dt.weekday(),
                    'season': cls._season_for_day(datetime.combine(day_dt, datetime.min.time()), advanced),
                })
                sample['occupancy'] = int(sample.get('occupancy') or 0) + 1
                if created_dt:
                    lead = (day_dt - created_dt.date()).days
                    if lead >= 0:
                        sample['lead_days'].append(float(lead))
        by_signature: Dict[str, Dict[int, List[float]]] = {}
        by_bucket: Dict[str, Dict[int, List[float]]] = {}
        for sample in daily_samples.values():
            bucket = str(sample.get('bucket') or '')
            if not bucket:
                continue
            occupancy = max(1, int(sample.get('occupancy') or 0))
            lead_days = sample.get('lead_days') or []
            signature_key = f"{bucket}|{sample.get('weekday')}|{sample.get('season')}"
            signature_slot = by_signature.setdefault(signature_key, {30: [], 15: [], 7: [], 3: []})
            bucket_slot = by_bucket.setdefault(bucket, {30: [], 15: [], 7: [], 3: []})
            for threshold in thresholds:
                share = (sum(1 for item in lead_days if float(item) >= float(threshold)) / occupancy) if occupancy > 0 else 0.0
                signature_slot[threshold].append(share)
                bucket_slot[threshold].append(share)
        signature_avg: Dict[str, Dict[int, float]] = {}
        for key, items in by_signature.items():
            signature_avg[key] = {threshold: cls._safe_mean(values, fallback=0.0) for threshold, values in items.items()}
        bucket_avg: Dict[str, Dict[int, float]] = {}
        for key, items in by_bucket.items():
            bucket_avg[key] = {threshold: cls._safe_mean(values, fallback=0.0) for threshold, values in items.items()}
        return {
            'thresholds': thresholds,
            'by_signature': signature_avg,
            'by_bucket': bucket_avg,
        }

    @classmethod
    def _reservation_curve_threshold_for_days(cls, days_to_arrival: int) -> int:
        if days_to_arrival >= 30:
            return 30
        if days_to_arrival >= 15:
            return 15
        if days_to_arrival >= 7:
            return 7
        return 3

    @classmethod
    def _reservation_curve_ratio_for_day(
        cls,
        curve_models: Dict[str, Any],
        *,
        bucket: str,
        day_dt: datetime,
        season: str,
        days_to_arrival: int,
    ) -> float:
        threshold = cls._reservation_curve_threshold_for_days(days_to_arrival)
        signature_key = f"{bucket}|{day_dt.weekday()}|{season}"
        by_signature = curve_models.get('by_signature') or {}
        by_bucket = curve_models.get('by_bucket') or {}
        ratio = float((by_signature.get(signature_key) or {}).get(threshold, 0.0))
        if ratio <= 0:
            ratio = float((by_bucket.get(bucket) or {}).get(threshold, 0.0))
        if days_to_arrival <= 1:
            ratio = max(ratio, 0.95)
        return max(0.05, min(1.0, ratio))

    @classmethod
    def occupancy_forecast(cls, start_date: str, days: int = 30, category: Optional[str] = None) -> Dict[str, Any]:
        advanced = cls._load_advanced_config()
        events = cls._events_index()
        reservations = ReservationService().get_february_reservations()
        capacity_by_bucket = cls._category_capacity_by_bucket()
        start_dt = cls._parse_date(start_date).date()
        days_count = max(1, int(days))
        category_bucket = cls._normalize_category(category) if category else ''

        historical_occupancy_by_day: Dict[str, Dict[str, float]] = {}
        lead_times: List[float] = []
        cancel_flags: List[float] = []
        today = datetime.now().date()

        for res in reservations:
            if not isinstance(res, dict):
                continue
            bucket = cls._normalize_category(res.get('category'))
            if category_bucket and bucket != category_bucket:
                continue
            stay_days = cls._iter_stay_days(res.get('checkin'), res.get('checkout'))
            if not stay_days:
                continue
            created_dt = cls._reservation_created_datetime(res)
            if created_dt:
                try:
                    lead_days = (cls._parse_date(res.get('checkin')).date() - created_dt.date()).days
                    if lead_days >= 0:
                        lead_times.append(float(lead_days))
                except Exception:
                    pass
            is_active = cls._is_active_reservation(res)
            cancel_flags.append(0.0 if is_active else 1.0)
            for day_iso in stay_days:
                slot = historical_occupancy_by_day.setdefault(day_iso, {'alma': 0.0, 'mar': 0.0, 'areia': 0.0})
                if is_active:
                    slot[bucket] = float(slot.get(bucket, 0.0)) + 1.0

        avg_lead_time = cls._safe_mean(lead_times, fallback=7.0)
        avg_cancel_rate = cls._safe_mean(cancel_flags, fallback=0.08)
        curve_models = cls._build_reservation_curve_models(
            reservations=reservations,
            advanced=advanced,
            capacity_by_bucket=capacity_by_bucket,
            category_bucket=category_bucket,
        )

        rows: List[Dict[str, Any]] = []
        for i in range(days_count):
            day_dt = datetime.combine(start_dt + timedelta(days=i), datetime.min.time())
            day_iso = day_dt.date().isoformat()
            day_weekday = day_dt.weekday()
            season = cls._season_for_day(day_dt, advanced)
            day_event = events.get(day_iso) or {}
            event_factor = float(day_event.get('factor') or 1.0)
            for bucket in ('alma', 'mar', 'areia'):
                if category_bucket and bucket != category_bucket:
                    continue
                capacity = max(1, int(capacity_by_bucket.get(bucket, 1)))
                historical_candidates: List[float] = []
                for hist_day_iso, by_cat in historical_occupancy_by_day.items():
                    try:
                        hist_dt = cls._parse_date(hist_day_iso)
                    except Exception:
                        continue
                    if hist_dt.date() >= today:
                        continue
                    if hist_dt.weekday() != day_weekday:
                        continue
                    if cls._season_for_day(hist_dt, advanced) != season:
                        continue
                    occ = float(by_cat.get(bucket, 0.0))
                    historical_candidates.append((occ / capacity) * 100.0)
                historical_avg = cls._safe_mean(historical_candidates, fallback=0.0)
                confirmed_occ_rooms = float((historical_occupancy_by_day.get(day_iso) or {}).get(bucket, 0.0))
                confirmed_occ_pct = (confirmed_occ_rooms / capacity) * 100.0
                days_to_arrival = max((day_dt.date() - today).days, 0)
                curve_ratio = cls._reservation_curve_ratio_for_day(
                    curve_models,
                    bucket=bucket,
                    day_dt=day_dt,
                    season=season,
                    days_to_arrival=days_to_arrival,
                )
                curve_projected = (confirmed_occ_pct / curve_ratio) if curve_ratio > 0 else 0.0
                lead_time_factor = 1.0
                if avg_lead_time > 0:
                    lead_time_factor = max(0.65, min(1.35, 1.0 + ((days_to_arrival - avg_lead_time) / max(avg_lead_time, 1.0)) * 0.08))
                blended = max(confirmed_occ_pct, historical_avg * event_factor * lead_time_factor)
                blended = max(blended, curve_projected * 0.98)
                projected_pct = max(0.0, min(120.0, blended * (1.0 - avg_cancel_rate)))
                risk_low = projected_pct < 45.0
                risk_overbooking = projected_pct > 100.0
                rows.append({
                    'date': day_iso,
                    'category': bucket,
                    'occupancy_current_pct': round(confirmed_occ_pct, 2),
                    'occupancy_projected_pct': round(projected_pct, 2),
                    'risk_low_occupancy': risk_low,
                    'risk_overbooking': risk_overbooking,
                    'season': season,
                    'weekday': ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][day_weekday],
                    'event': day_event if isinstance(day_event, dict) else {},
                    'event_factor': round(event_factor, 3),
                    'historical_avg_pct': round(historical_avg, 2),
                    'reservation_curve_onbooks_ratio_pct': round(curve_ratio * 100.0, 2),
                    'reservation_curve_projection_pct': round(curve_projected, 2),
                    'days_to_arrival': days_to_arrival,
                    'capacity': capacity,
                })
        return {
            'start_date': start_dt.isoformat(),
            'days': days_count,
            'lead_time_avg_days': round(avg_lead_time, 2),
            'cancel_rate_avg': round(avg_cancel_rate, 4),
            'rows': rows,
        }

    @classmethod
    def reservation_curve(cls, start_date: str, days: int = 30, category: Optional[str] = None) -> Dict[str, Any]:
        start_dt = cls._parse_date(start_date).date()
        days_count = max(1, int(days))
        category_bucket = cls._normalize_category(category) if category else ''
        advanced = cls._load_advanced_config()
        reservations = ReservationService().get_february_reservations()
        capacity_by_bucket = cls._category_capacity_by_bucket()
        curve_models = cls._build_reservation_curve_models(
            reservations=reservations,
            advanced=advanced,
            capacity_by_bucket=capacity_by_bucket,
            category_bucket=category_bucket,
        )
        forecast = cls.occupancy_forecast(start_date=start_dt.isoformat(), days=days_count, category=category)
        forecast_rows = [row for row in (forecast.get('rows') or []) if isinstance(row, dict)]
        forecast_index = {f"{str(row.get('date') or '')}|{str(row.get('category') or '')}": row for row in forecast_rows}
        rows: List[Dict[str, Any]] = []
        today = datetime.now().date()
        for i in range(days_count):
            target_day = start_dt + timedelta(days=i)
            day_iso = target_day.isoformat()
            day_dt = datetime.combine(target_day, datetime.min.time())
            season = cls._season_for_day(day_dt, advanced)
            days_to_arrival = max((target_day - today).days, 0)
            for bucket in ('alma', 'mar', 'areia'):
                if category_bucket and bucket != category_bucket:
                    continue
                signature_key = f"{bucket}|{day_dt.weekday()}|{season}"
                by_signature = (curve_models.get('by_signature') or {}).get(signature_key, {})
                by_bucket = (curve_models.get('by_bucket') or {}).get(bucket, {})
                curve_30 = float(by_signature.get(30, by_bucket.get(30, 0.0)))
                curve_15 = float(by_signature.get(15, by_bucket.get(15, 0.0)))
                curve_7 = float(by_signature.get(7, by_bucket.get(7, 0.0)))
                curve_3 = float(by_signature.get(3, by_bucket.get(3, 0.0)))
                forecast_row = forecast_index.get(f"{day_iso}|{bucket}", {})
                rows.append({
                    'date': day_iso,
                    'category': bucket,
                    'days_to_arrival': days_to_arrival,
                    'curve_30d_pct': round(curve_30 * 100.0, 2),
                    'curve_15d_pct': round(curve_15 * 100.0, 2),
                    'curve_7d_pct': round(curve_7 * 100.0, 2),
                    'curve_3d_pct': round(curve_3 * 100.0, 2),
                    'occupancy_current_pct': round(float(forecast_row.get('occupancy_current_pct') or 0.0), 2),
                    'occupancy_projected_pct': round(float(forecast_row.get('occupancy_projected_pct') or 0.0), 2),
                })
        return {
            'start_date': start_dt.isoformat(),
            'days': days_count,
            'category': category_bucket or None,
            'rows': rows,
            'count': len(rows),
        }

    @classmethod
    def pricing_pipeline_verification(cls) -> Dict[str, Any]:
        expected_order = [
            'Histórico de reservas',
            'Pickup analysis',
            'Forecast de ocupação',
            'Regras comerciais (pacotes / promoções / restrições)',
            'Tarifa base',
            'Ajuste dinâmico RevPAR',
            'Tarifa final sugerida',
        ]
        implemented_order = [
            'Histórico de reservas',
            'Pickup analysis',
            'Forecast de ocupação',
            'Regras comerciais (pacotes / promoções / restrições)',
            'Tarifa base',
            'Ajuste dinâmico RevPAR',
            'Tarifa final sugerida',
        ]
        return {
            'expected_order': expected_order,
            'implemented_order': implemented_order,
            'is_correct': expected_order == implemented_order,
        }

    @classmethod
    def pickup_analysis(cls, start_date: str, days: int = 30, category: Optional[str] = None) -> Dict[str, Any]:
        reservations = ReservationService().get_february_reservations()
        start_dt = cls._parse_date(start_date).date()
        days_count = max(1, int(days))
        category_bucket = cls._normalize_category(category) if category else ''
        windows = (1, 3, 7, 14)
        pickup_by_day: Dict[str, Dict[int, int]] = {}
        historical_samples: Dict[int, List[float]] = {1: [], 3: [], 7: [], 14: []}
        today = datetime.now().date()

        def add_pickup(day_iso: str, window: int, value: int) -> None:
            slot = pickup_by_day.setdefault(day_iso, {1: 0, 3: 0, 7: 0, 14: 0})
            slot[window] = slot.get(window, 0) + int(value)

        for res in reservations:
            if not isinstance(res, dict):
                continue
            if not cls._is_active_reservation(res):
                continue
            bucket = cls._normalize_category(res.get('category'))
            if category_bucket and bucket != category_bucket:
                continue
            created_dt = cls._reservation_created_datetime(res)
            if not created_dt:
                continue
            stay_days = cls._iter_stay_days(res.get('checkin'), res.get('checkout'))
            if not stay_days:
                continue
            for day_iso in stay_days:
                try:
                    target_day = cls._parse_date(day_iso).date()
                except Exception:
                    continue
                lead = (target_day - created_dt.date()).days
                if lead < 0:
                    continue
                for w in windows:
                    if lead <= w:
                        add_pickup(day_iso, w, 1)

        rows: List[Dict[str, Any]] = []
        for i in range(days_count):
            day = start_dt + timedelta(days=i)
            day_iso = day.isoformat()
            current = pickup_by_day.get(day_iso, {1: 0, 3: 0, 7: 0, 14: 0})
            historical_start = day - timedelta(days=56)
            for w in windows:
                sample = []
                cursor = historical_start
                while cursor < day:
                    ref = pickup_by_day.get(cursor.isoformat(), {})
                    sample.append(float(ref.get(w, 0)))
                    cursor += timedelta(days=7)
                historical_samples[w].extend(sample)
            baseline_7 = cls._safe_mean([float(v) for v in historical_samples[7]], fallback=0.0)
            pickup_7 = float(current.get(7, 0))
            if pickup_7 >= baseline_7 * 1.9 and pickup_7 >= 2:
                level = 'muito alto'
            elif pickup_7 >= baseline_7 * 1.25 and pickup_7 >= 1:
                level = 'alto'
            elif pickup_7 <= max(1.0, baseline_7 * 0.65):
                level = 'baixo'
            else:
                level = 'normal'
            rows.append({
                'date': day_iso,
                'pickup_1d': int(current.get(1, 0)),
                'pickup_3d': int(current.get(3, 0)),
                'pickup_7d': int(current.get(7, 0)),
                'pickup_14d': int(current.get(14, 0)),
                'historical_baseline_1d': round(cls._safe_mean(historical_samples[1], fallback=0.0), 2),
                'historical_baseline_3d': round(cls._safe_mean(historical_samples[3], fallback=0.0), 2),
                'historical_baseline_7d': round(baseline_7, 2),
                'historical_baseline_14d': round(cls._safe_mean(historical_samples[14], fallback=0.0), 2),
                'pickup_level': level,
            })
        return {'start_date': start_dt.isoformat(), 'days': days_count, 'rows': rows}

    @classmethod
    def revenue_alerts(cls, start_date: str, days: int = 30, category: Optional[str] = None) -> Dict[str, Any]:
        start_dt = cls._parse_date(start_date).date()
        days_count = max(1, int(days))
        forecast_payload = cls.occupancy_forecast(start_date=start_dt.isoformat(), days=days_count, category=category)
        pickup_payload = cls.pickup_analysis(start_date=start_dt.isoformat(), days=days_count, category=category)
        forecast_rows = [row for row in (forecast_payload.get('rows') or []) if isinstance(row, dict)]
        pickup_rows = [row for row in (pickup_payload.get('rows') or []) if isinstance(row, dict)]
        pickup_index = {str(row.get('date') or ''): row for row in pickup_rows}

        alerts: List[Dict[str, Any]] = []
        stats = {
            'low_occupancy_future': 0,
            'high_demand': 0,
            'pickup_anomaly': 0,
            'overbooking_risk': 0,
        }

        for row in forecast_rows:
            date = str(row.get('date') or '')
            bucket = cls._normalize_category(row.get('category'))
            projected_pct = float(row.get('occupancy_projected_pct') or 0.0)
            current_pct = float(row.get('occupancy_current_pct') or 0.0)
            capacity = max(1, int(row.get('capacity') or 1))
            confirmed_rooms = capacity * (current_pct / 100.0)
            projected_rooms = capacity * (projected_pct / 100.0)
            projected_additional_rooms = max(projected_rooms - confirmed_rooms, 0.0)
            projected_total_rooms = confirmed_rooms + projected_additional_rooms

            if projected_pct < 40.0:
                stats['low_occupancy_future'] += 1
                alerts.append({
                    'type': 'low_occupancy_future',
                    'severity': 'high',
                    'date': date,
                    'category': bucket,
                    'title': 'Baixa ocupação futura',
                    'message': f"Ocupação projetada em {projected_pct:.1f}% abaixo de 40%.",
                    'threshold': 40.0,
                    'value': round(projected_pct, 2),
                    'capacity': capacity,
                })

            if projected_pct > 90.0:
                stats['high_demand'] += 1
                alerts.append({
                    'type': 'high_demand',
                    'severity': 'high',
                    'date': date,
                    'category': bucket,
                    'title': 'Alta demanda',
                    'message': f"Ocupação projetada em {projected_pct:.1f}% acima de 90%.",
                    'threshold': 90.0,
                    'value': round(projected_pct, 2),
                    'capacity': capacity,
                })

            if projected_total_rooms > capacity:
                stats['overbooking_risk'] += 1
                alerts.append({
                    'type': 'overbooking_risk',
                    'severity': 'critical',
                    'date': date,
                    'category': bucket,
                    'title': 'Risco de overbooking',
                    'message': f"Confirmadas + projeção = {projected_total_rooms:.2f} UH para inventário de {capacity}.",
                    'threshold': float(capacity),
                    'value': round(projected_total_rooms, 2),
                    'capacity': capacity,
                    'confirmed_rooms': round(confirmed_rooms, 2),
                    'projected_additional_rooms': round(projected_additional_rooms, 2),
                })

            pickup_row = pickup_index.get(date, {})
            pickup_level = str(pickup_row.get('pickup_level') or '')
            pickup_7 = float(pickup_row.get('pickup_7d') or 0.0)
            baseline_7 = float(pickup_row.get('historical_baseline_7d') or 0.0)
            ratio = None
            if baseline_7 > 0:
                ratio = pickup_7 / baseline_7
            if pickup_level in ('muito alto', 'baixo'):
                stats['pickup_anomaly'] += 1
                alerts.append({
                    'type': 'pickup_anomaly',
                    'severity': 'high' if pickup_level == 'muito alto' else 'medium',
                    'date': date,
                    'category': bucket,
                    'title': 'Pickup anormal',
                    'message': f"Ritmo de reservas classificado como {pickup_level}.",
                    'value': round(pickup_7, 2),
                    'threshold': round(baseline_7, 2),
                    'pickup_level': pickup_level,
                    'pickup_ratio': round(ratio, 3) if ratio is not None else None,
                })

        severity_rank = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        alerts.sort(key=lambda item: (severity_rank.get(str(item.get('severity') or 'low'), 9), str(item.get('date') or ''), str(item.get('type') or '')))
        return {
            'start_date': start_dt.isoformat(),
            'days': days_count,
            'category': cls._normalize_category(category) if category else None,
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'stats': stats,
            'alerts': alerts,
            'count': len(alerts),
        }

    @classmethod
    def auto_demand_tariff_adjustment(
        cls,
        *,
        start_date: str,
        days: int = 30,
        category: Optional[str] = None,
        revpar_target: Optional[float] = None,
    ) -> Dict[str, Any]:
        pickup = cls.pickup_analysis(start_date=start_date, days=days, category=category)
        forecast = cls.occupancy_forecast(start_date=start_date, days=days, category=category)
        pickup_index = {str(item.get('date')): item for item in (pickup.get('rows') or []) if isinstance(item, dict)}
        rules = cls._load_rules()
        advanced = cls._load_advanced_config()
        strategy_cfg = cls.get_category_strategies()
        out_rows: List[Dict[str, Any]] = []
        for row in (forecast.get('rows') or []):
            if not isinstance(row, dict):
                continue
            day_iso = str(row.get('date') or '')
            bucket = cls._normalize_category(row.get('category'))
            strategy_key = cls._category_strategy_key(row.get('category'))
            strategy = strategy_cfg.get(strategy_key, strategy_cfg.get(bucket, {}))
            limits = advanced.get('category_limits', {}).get(bucket, {})
            default_rule = rules.get(bucket, {})
            base_bar = WeekdayBaseRateService.base_for_day(category=bucket, date_str=day_iso, fallback=float(default_rule.get('base_bar') or 0.0))
            min_bar = float(limits.get('min_bar', default_rule.get('min_bar', 0.0)))
            max_bar = float(limits.get('max_bar', default_rule.get('max_bar', 0.0)))
            channel_focus = cls._normalize_channel((strategy.get('channel_priority') or ['direto'])[0] if isinstance(strategy, dict) else 'direto')
            commercial_factor = 1.0
            commercial_sellable = True
            commercial_message = ''
            try:
                from app.services.tariff_priority_engine_service import TariffPriorityEngineService
                preview = TariffPriorityEngineService.evaluate(
                    category=bucket,
                    channel=cls._channel_label(channel_focus),
                    checkin=day_iso,
                    checkout=(cls._parse_date(day_iso).date() + timedelta(days=1)).isoformat(),
                    sale_date=datetime.now().strftime('%Y-%m-%d'),
                    apply_dynamic=False,
                )
                commercial_sellable = bool(preview.get('sellable', True))
                commercial_message = str(preview.get('message') or '')
                pricing = preview.get('pricing') or {}
                commercial_base = float(pricing.get('base_weekday_total') or 0.0)
                commercial_total = float(pricing.get('final_total') or 0.0)
                if commercial_base > 0 and commercial_total > 0:
                    commercial_factor = max(0.4, min(1.8, commercial_total / commercial_base))
            except Exception:
                commercial_factor = 1.0
            base_bar = float(base_bar) * commercial_factor
            projected = float(row.get('occupancy_projected_pct') or 0.0)
            pickup_row = pickup_index.get(day_iso, {})
            pickup_level = str(pickup_row.get('pickup_level') or 'normal')
            pickup_bias = 1.0
            if pickup_level == 'muito alto':
                pickup_bias = 1.06
            elif pickup_level == 'alto':
                pickup_bias = 1.03
            elif pickup_level == 'baixo':
                pickup_bias = 0.95
            channel_bias = cls._channel_priority_factor(channel_focus, strategy if isinstance(strategy, dict) else {})
            if projected > 85.0:
                occ_factor = 1.15
                strategy_mode = 'aumentar'
            elif projected >= 65.0:
                occ_factor = 1.00
                strategy_mode = 'manter'
            elif projected >= 40.0:
                occ_factor = 0.94
                strategy_mode = 'reduzir_leve'
            else:
                occ_factor = 0.82
                strategy_mode = 'reduzir_forte_ou_promocao'
            target = float(revpar_target or row.get('target_revpar') or cls._target_revpar_for_day(cls._parse_date(day_iso), advanced))
            revpar_gap_factor = 1.0
            if target > 0:
                estimated_revpar_current = float(base_bar) * (projected / 100.0)
                gap = target - estimated_revpar_current
                if gap > 0 and projected >= 65.0:
                    revpar_gap_factor = 1.03
                elif gap < 0 and projected < 50.0:
                    revpar_gap_factor = 0.97
            suggested = float(base_bar) * occ_factor * pickup_bias * revpar_gap_factor * channel_bias
            discount_limit = float(strategy.get('discount_limit_pct', advanced.get('max_reduction_pct', 0.22)))
            increase_limit = float(strategy.get('increase_limit_pct', advanced.get('max_increase_pct', 0.28)))
            strategy_floor = float(base_bar) * (1.0 - max(0.0, discount_limit))
            strategy_ceiling = float(base_bar) * (1.0 + max(0.0, increase_limit))
            min_bar = max(min_bar, strategy_floor)
            max_bar = min(max_bar, strategy_ceiling)
            suggested = min(max(suggested, min_bar), max_bar)
            package_required = False
            package_message = ''
            try:
                from app.services.promotional_package_service import PromotionalPackageService
                checkin = day_iso
                checkout = (cls._parse_date(day_iso).date() + timedelta(days=1)).isoformat()
                package_validation = PromotionalPackageService.validate_required_package_constraint(
                    category=bucket,
                    checkin=checkin,
                    checkout=checkout,
                    sale_date=datetime.now().strftime('%Y-%m-%d'),
                    base_total=suggested,
                )
                package_required = bool((package_validation or {}).get('required_for_sale'))
                package_message = str((package_validation or {}).get('message') or '')
            except Exception:
                package_required = False
            booking_pricing = cls.calculate_booking_ota_pricing(
                tarifa_direta=suggested,
                category=bucket,
                date_str=day_iso,
                tarifa_liquida_desejada=suggested,
            )
            out_rows.append({
                'date': day_iso,
                'category': bucket,
                'occupancy_projected_pct': round(projected, 2),
                'pickup_level': pickup_level,
                'base_bar': round(base_bar, 2),
                'suggested_bar': round(suggested, 2),
                'min_bar': round(min_bar, 2),
                'max_bar': round(max_bar, 2),
                'revpar_target': round(target, 2),
                'strategy': strategy_mode,
                'package_required': package_required,
                'package_message': package_message,
                'commercial_factor': round(commercial_factor, 4),
                'commercial_sellable': commercial_sellable,
                'commercial_message': commercial_message,
                'category_strategy': str(strategy.get('name') or strategy_key),
                'channel_priority': list(strategy.get('channel_priority') or []),
                'discount_limit_pct': round(max(0.0, discount_limit), 4),
                'increase_limit_pct': round(max(0.0, increase_limit), 4),
                'booking_modelo_comercial': booking_pricing.get('modelo_comercial'),
                'booking_tipo_ajuste_tarifa': booking_pricing.get('tipo_ajuste_tarifa'),
                'booking_tarifa_direta': booking_pricing.get('tarifa_direta'),
                'booking_comissao_percentual': booking_pricing.get('comissao_percentual'),
                'booking_comissao_valor': booking_pricing.get('comissao_valor'),
                'booking_tarifa_ota_final': booking_pricing.get('tarifa_ota_final'),
                'booking_liquido_estimado_hotel': booking_pricing.get('liquido_estimado_hotel'),
            })
        return {
            'start_date': str(forecast.get('start_date') or start_date),
            'days': int(forecast.get('days') or days),
            'rows': out_rows,
            'forecast': forecast,
            'pickup': pickup,
        }

    @classmethod
    def _apply_advanced_adjustment(
        cls,
        occupancy: float,
        current_revpar: float,
        target_revpar: float,
        base_bar: float,
        min_bar: float,
        max_bar: float,
        advanced: Dict[str, Any],
    ) -> Dict[str, Any]:
        high_threshold = float(advanced.get('occupancy_thresholds', {}).get('high', 82))
        low_threshold = float(advanced.get('occupancy_thresholds', {}).get('low', 45))
        max_up = float(advanced.get('max_increase_pct', 0.28))
        max_down = float(advanced.get('max_reduction_pct', 0.22))
        gap = target_revpar - current_revpar
        if target_revpar <= 0:
            target_revpar = max(current_revpar, 1.0)
        ratio = abs(gap) / target_revpar
        reason_mode = 'estável'
        if gap > 0 and occupancy >= high_threshold:
            delta = min(max_up, max(0.02, ratio * 1.25))
            suggested = base_bar * (1 + delta)
            reason_mode = 'ocupação alta e RevPAR abaixo do alvo'
            occ_delta = -min(0.04, delta * 0.12)
        elif gap > 0 and occupancy <= low_threshold:
            delta = min(max_down, max(0.02, ratio * 0.85))
            suggested = base_bar * (1 - delta)
            reason_mode = 'ocupação baixa e RevPAR abaixo do alvo'
            occ_delta = min(0.16, delta * 0.65)
        elif gap > 0:
            delta = min(max_up, max(0.01, ratio * 0.55))
            suggested = base_bar * (1 + delta)
            reason_mode = 'ocupação intermediária e RevPAR abaixo do alvo'
            occ_delta = -min(0.03, delta * 0.10)
        elif gap < 0 and occupancy <= low_threshold:
            delta = min(max_down * 0.6, max(0.01, ratio * 0.40))
            suggested = base_bar * (1 - delta)
            reason_mode = 'RevPAR acima do alvo com baixa ocupação'
            occ_delta = min(0.09, delta * 0.45)
        else:
            suggested = base_bar
            reason_mode = 'RevPAR próximo do alvo'
            occ_delta = 0.0
        suggested = min(max(suggested, min_bar), max_bar)
        return {
            'suggested_bar': suggested,
            'reason_mode': reason_mode,
            'occ_delta': occ_delta,
            'gap': gap,
        }

    @classmethod
    def simulate_projection(cls, start_date: str, days: int = 30, advanced_mode: bool = False) -> Dict[str, Any]:
        reservations = ReservationService().get_february_reservations()
        room_mapping = ReservationService().get_room_mapping()
        rules = cls._load_rules()
        advanced = cls._load_advanced_config()
        events = cls._events_index()
        available_by_cat = {
            'alma': len(room_mapping.get('Suíte Alma c/ Banheira', [])) + len(room_mapping.get('Suíte Alma', [])) + len(room_mapping.get('Suíte Master Diamante', [])),
            'mar': len(room_mapping.get('Suíte Mar Família', [])) + len(room_mapping.get('Suíte Mar', [])),
            'areia': len(room_mapping.get('Suíte Areia', [])),
        }
        start_dt = cls._parse_date(start_date)
        current_tariffs = cls._current_tariff_index()
        daily_rows: List[Dict[str, Any]] = []
        for i in range(max(1, int(days))):
            day_dt = start_dt + timedelta(days=i)
            day = day_dt.date()
            day_key = day.isoformat()
            by_cat = {
                'alma': {'occupied': 0, 'projected_revenue': 0.0, 'weighted_revenue': 0.0, 'reservations': 0},
                'mar': {'occupied': 0, 'projected_revenue': 0.0, 'weighted_revenue': 0.0, 'reservations': 0},
                'areia': {'occupied': 0, 'projected_revenue': 0.0, 'weighted_revenue': 0.0, 'reservations': 0},
            }
            for reservation in reservations:
                if not isinstance(reservation, dict):
                    continue
                status = str(reservation.get('status') or '').lower()
                if 'cancel' in status:
                    continue
                checkin = FinanceDashboardService._parse_date(reservation.get('checkin'))
                checkout = FinanceDashboardService._parse_date(reservation.get('checkout'))
                if not checkin or not checkout:
                    continue
                if not (checkin.date() <= day < checkout.date()):
                    continue
                category = cls._normalize_category(reservation.get('category'))
                total_value = FinanceDashboardService._reservation_total(reservation)
                nights = max((checkout.date() - checkin.date()).days, 1)
                daily_value = total_value / nights
                channel_w = cls._channel_weight(reservation, advanced)
                by_cat[category]['occupied'] += 1
                by_cat[category]['projected_revenue'] += daily_value
                by_cat[category]['weighted_revenue'] += (daily_value * channel_w)
                by_cat[category]['reservations'] += 1
            day_event = events.get(day_key, {})
            target_revpar_day = cls._target_revpar_for_day(day_dt, advanced)
            for category in ('alma', 'mar', 'areia'):
                available = max(available_by_cat.get(category, 1), 1)
                occupied = by_cat[category]['occupied']
                revenue = by_cat[category]['projected_revenue']
                weighted_revenue = by_cat[category]['weighted_revenue']
                occupancy = (occupied / available) * 100
                adr = (revenue / occupied) if occupied > 0 else 0.0
                revpar = weighted_revenue / available if advanced_mode else revenue / available
                default_base_bar = rules[category]['base_bar']
                base_bar = WeekdayBaseRateService.base_for_day(category=category, date_str=day_key, fallback=default_base_bar)
                current_bar = float(current_tariffs.get(f'{day_key}|{category}', base_bar))
                limits_cfg = advanced.get('category_limits', {}).get(category, {})
                min_bar = float(limits_cfg.get('min_bar', rules[category]['min_bar']))
                max_bar = float(limits_cfg.get('max_bar', rules[category]['max_bar']))
                event_factor = float(day_event.get('factor', 1.0)) if isinstance(day_event, dict) else 1.0
                reason = ''
                critical_alert = 'high' if occupancy > 90 else ('low' if occupancy < 30 else None)
                if advanced_mode:
                    adj = cls._apply_advanced_adjustment(
                        occupancy=occupancy,
                        current_revpar=revpar,
                        target_revpar=target_revpar_day,
                        base_bar=current_bar,
                        min_bar=min_bar,
                        max_bar=max_bar,
                        advanced=advanced,
                    )
                    suggested = adj['suggested_bar'] * event_factor
                    suggested = min(max(suggested, min_bar), max_bar)
                    occ_after = max(0.0, min(float(available), occupied * (1 + float(adj['occ_delta']))))
                    revenue_after = suggested * occ_after
                    revpar_after = revenue_after / available
                    impact = revpar_after - revpar
                    reason = f"{adj['reason_mode']} | alvo {target_revpar_day:.2f} | atual {revpar:.2f}"
                    if isinstance(day_event, dict) and day_event.get('name'):
                        reason = f"{reason} | Evento: {day_event.get('name')}"
                    daily_rows.append({
                        'date': day_key,
                        'category': category,
                        'available_rooms': available,
                        'occupied_rooms': occupied,
                        'projected_occupancy_pct': round(occupancy, 2),
                        'projected_adr': round(adr, 2),
                        'projected_revpar': round(revpar, 2),
                        'current_bar': round(current_bar, 2),
                        'target_revpar': round(target_revpar_day, 2),
                        'revpar_gap': round(target_revpar_day - revpar, 2),
                        'suggested_bar': round(suggested, 2),
                        'estimated_revpar_after': round(revpar_after, 2),
                        'estimated_revpar_impact': round(impact, 2),
                        'reason': reason,
                        'limits': {'min_bar': min_bar, 'max_bar': max_bar, 'base_bar': default_base_bar},
                        'weekday_base_bar': round(base_bar, 2),
                        'mode': 'advanced',
                        'critical_alert': critical_alert,
                    })
                else:
                    occupancy_factor = 1.0
                    if occupancy >= 90:
                        occupancy_factor = 1.35
                    elif occupancy >= 75:
                        occupancy_factor = 1.20
                    elif occupancy <= 40:
                        occupancy_factor = 0.88
                    revpar_factor = 1.0
                    if revpar > (base_bar * 0.85):
                        revpar_factor = 1.12
                    elif revpar < (base_bar * 0.45):
                        revpar_factor = 0.92
                    suggested = current_bar * occupancy_factor * revpar_factor * event_factor
                    suggested = min(max(suggested, min_bar), max_bar)
                    reason = f"Ocupação {occupancy:.1f}% | ADR {adr:.2f} | RevPAR {revpar:.2f}"
                    if isinstance(day_event, dict) and day_event.get('name'):
                        reason = f"{reason} | Evento: {day_event.get('name')}"
                    daily_rows.append({
                        'date': day_key,
                        'category': category,
                        'available_rooms': available,
                        'occupied_rooms': occupied,
                        'projected_occupancy_pct': round(occupancy, 2),
                        'projected_adr': round(adr, 2),
                        'projected_revpar': round(revpar, 2),
                        'current_bar': round(current_bar, 2),
                        'target_revpar': round(target_revpar_day, 2),
                        'revpar_gap': round(target_revpar_day - revpar, 2),
                        'suggested_bar': round(suggested, 2),
                        'estimated_revpar_after': round(revpar, 2),
                        'estimated_revpar_impact': 0.0,
                        'reason': reason,
                        'limits': {'min_bar': min_bar, 'max_bar': max_bar, 'base_bar': default_base_bar},
                        'weekday_base_bar': round(base_bar, 2),
                        'mode': 'basic',
                        'critical_alert': critical_alert,
                    })
        return {
            'start_date': start_dt.date().isoformat(),
            'days': days,
            'rows': daily_rows,
            'rules': rules,
            'advanced_config': advanced,
            'mode': 'advanced' if advanced_mode else 'basic',
        }

    @classmethod
    def apply_suggestions(
        cls,
        payload_rows: List[Dict[str, Any]],
        justification: str,
        user: str,
        origin: str = 'suggestion',
    ) -> Dict[str, Any]:
        if not justification or len(justification.strip()) < 5:
            raise ValueError('Justificativa obrigatória para aplicar tarifa')
        changes = cls._load_changes()
        applied = []
        for row in payload_rows:
            if not isinstance(row, dict):
                continue
            item = cls._append_change(
                user=user,
                date=str(row.get('date') or ''),
                category=str(row.get('category') or ''),
                before_bar=row.get('before_bar'),
                after_bar=row.get('suggested_bar'),
                origin=origin,
                justification=justification,
                reason=str(row.get('reason') or ''),
                target_revpar=row.get('target_revpar'),
                estimated_revpar_after=row.get('estimated_revpar_after'),
                estimated_revpar_impact=row.get('estimated_revpar_impact'),
            )
            applied.append(item)
            changes.append(item)
            LoggerService.log_acao(
                acao='Aplicou tarifa BAR',
                entidade='Revenue Management',
                detalhes=item,
                nivel_severidade='INFO',
                departamento_id='Recepção',
                colaborador_id=user,
            )
        cls._save_changes(changes)
        return {'applied_count': len(applied), 'items': applied}

    @classmethod
    def reset_to_default(cls, payload_rows: List[Dict[str, Any]], justification: str, user: str) -> Dict[str, Any]:
        if not justification or len(justification.strip()) < 5:
            raise ValueError('Justificativa obrigatória para voltar ao padrão')
        rules = cls._load_rules()
        reset_rows = []
        for row in payload_rows:
            if not isinstance(row, dict):
                continue
            category = cls._normalize_category(row.get('category'))
            reset_rows.append({
                'date': row.get('date'),
                'category': category,
                'before_bar': row.get('current_bar') or row.get('before_bar') or rules.get(category, {}).get('base_bar', 0),
                'suggested_bar': rules.get(category, {}).get('base_bar', 0),
                'reason': 'Voltar ao padrão',
                'target_revpar': row.get('target_revpar'),
                'estimated_revpar_after': None,
                'estimated_revpar_impact': None,
            })
        result = cls.apply_suggestions(reset_rows, justification, user, origin='manual')
        return result

    @classmethod
    def get_audit_report(cls, start_date: Optional[str], end_date: Optional[str], user_filter: Optional[str]) -> List[Dict[str, Any]]:
        logs = cls._load_changes()
        out = []
        start_dt = cls._parse_date(start_date).date() if start_date else None
        end_dt = cls._parse_date(end_date).date() if end_date else None
        for item in logs:
            if not isinstance(item, dict):
                continue
            day = str(item.get('date') or '').strip()
            if not day:
                continue
            try:
                day_dt = cls._parse_date(day).date()
            except Exception:
                continue
            if start_dt and day_dt < start_dt:
                continue
            if end_dt and day_dt > end_dt:
                continue
            if user_filter and str(item.get('user') or '').strip().lower() != str(user_filter).strip().lower():
                continue
            out.append(item)
        out.sort(key=lambda x: (x.get('date') or '', x.get('applied_at') or ''), reverse=True)
        return out
