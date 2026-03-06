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
    REVENUE_BAR_RULES_FILE,
    REVENUE_EVENTS_FILE,
)


class RevenueManagementService:
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
        'max_increase_pct': 0.28,
        'max_reduction_pct': 0.22,
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
        for key in ('season_by_month', 'revpar_target', 'channel_weights', 'category_limits', 'occupancy_thresholds'):
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
        for key in ('season_by_month', 'revpar_target', 'channel_weights', 'category_limits', 'occupancy_thresholds'):
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
                lead_time_factor = 1.0
                if avg_lead_time > 0:
                    days_to_arrival = max((day_dt.date() - today).days, 0)
                    lead_time_factor = max(0.65, min(1.35, 1.0 + ((days_to_arrival - avg_lead_time) / max(avg_lead_time, 1.0)) * 0.08))
                blended = max(confirmed_occ_pct, historical_avg * event_factor * lead_time_factor)
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
    def auto_demand_tariff_adjustment(
        cls,
        *,
        start_date: str,
        days: int = 30,
        category: Optional[str] = None,
        revpar_target: Optional[float] = None,
    ) -> Dict[str, Any]:
        forecast = cls.occupancy_forecast(start_date=start_date, days=days, category=category)
        pickup = cls.pickup_analysis(start_date=start_date, days=days, category=category)
        pickup_index = {str(item.get('date')): item for item in (pickup.get('rows') or []) if isinstance(item, dict)}
        rules = cls._load_rules()
        advanced = cls._load_advanced_config()
        out_rows: List[Dict[str, Any]] = []
        for row in (forecast.get('rows') or []):
            if not isinstance(row, dict):
                continue
            day_iso = str(row.get('date') or '')
            bucket = cls._normalize_category(row.get('category'))
            limits = advanced.get('category_limits', {}).get(bucket, {})
            default_rule = rules.get(bucket, {})
            base_bar = WeekdayBaseRateService.base_for_day(category=bucket, date_str=day_iso, fallback=float(default_rule.get('base_bar') or 0.0))
            min_bar = float(limits.get('min_bar', default_rule.get('min_bar', 0.0)))
            max_bar = float(limits.get('max_bar', default_rule.get('max_bar', 0.0)))
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
            if projected > 85.0:
                occ_factor = 1.15
                strategy = 'aumentar'
            elif projected >= 65.0:
                occ_factor = 1.00
                strategy = 'manter'
            elif projected >= 40.0:
                occ_factor = 0.94
                strategy = 'reduzir_leve'
            else:
                occ_factor = 0.82
                strategy = 'reduzir_forte_ou_promocao'
            target = float(revpar_target or row.get('target_revpar') or cls._target_revpar_for_day(cls._parse_date(day_iso), advanced))
            revpar_gap_factor = 1.0
            if target > 0:
                estimated_revpar_current = float(base_bar) * (projected / 100.0)
                gap = target - estimated_revpar_current
                if gap > 0 and projected >= 65.0:
                    revpar_gap_factor = 1.03
                elif gap < 0 and projected < 50.0:
                    revpar_gap_factor = 0.97
            suggested = float(base_bar) * occ_factor * pickup_bias * revpar_gap_factor
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
                'strategy': strategy,
                'package_required': package_required,
                'package_message': package_message,
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
