from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import os

from app.services.channel_inventory_planner_service import ChannelInventoryPlannerService
from app.services.channel_manager_service import ChannelManagerService
from app.services.channel_restriction_service import ChannelRestrictionService
from app.services.channel_sync_log_service import ChannelSyncLogService
from app.services.ota_booking_rm_service import OTABookingRMService
from app.services.period_selector_service import PeriodSelectorService
from app.services.revenue_management_service import RevenueManagementService
from app.services.system_config_manager import (
    CHANNEL_ALLOTMENTS_FILE,
    CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE,
    CHANNEL_MANAGER_CHANNELS_FILE,
    CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE,
    CHANNEL_MANAGER_COMMISSIONS_FILE,
    CHANNEL_MANAGER_RESTRICTIONS_FILE,
    CHANNEL_MANAGER_SYNC_LOGS_FILE,
    CHANNEL_MANAGER_TARIFFS_FILE,
    OTA_BOOKING_INTEGRATIONS_FILE,
    PROMOTIONAL_PACKAGES_FILE,
    REVENUE_PROMOTIONS_FILE,
)


class ChannelManagerDashboardService:
    @classmethod
    def _normalize_channel(cls, value: Any) -> str:
        return RevenueManagementService._channel_label(RevenueManagementService._normalize_channel(value))

    @classmethod
    def _date_range(cls, start_date: str, end_date: str) -> Dict[str, Any]:
        start = PeriodSelectorService.parse_date(start_date).date()
        end = PeriodSelectorService.parse_date(end_date).date()
        if end < start:
            start, end = end, start
        return {'start': start, 'end': end, 'days': max(1, (end - start).days + 1)}

    @classmethod
    def _merged_sync_logs(cls, *, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        internal = ChannelSyncLogService.list_logs(start_date=start_date, end_date=end_date)
        ota_raw = OTABookingRMService.list_sync_logs(start_date=start_date, end_date=end_date)
        type_map = {
            'envio_tarifas': 'tarifa',
            'envio_disponibilidade': 'disponibilidade',
            'open_close': 'open_close',
            'cta_ctd': 'cta',
            'min_stay': 'min_stay',
            'stop_sell': 'open_close',
            'autenticacao': 'autenticacao',
            'pacote': 'pacote',
        }
        ota_rows: List[Dict[str, Any]] = []
        for row in (ota_raw or []):
            if not isinstance(row, dict):
                continue
            mapped_type = type_map.get(str(row.get('type') or row.get('distribution_type') or '').strip().lower(), 'tarifa')
            ota_rows.append({
                'id': row.get('id'),
                'timestamp': row.get('timestamp'),
                'user': row.get('user') or 'Sistema',
                'channel': cls._normalize_channel(row.get('channel') or 'Booking.com'),
                'sync_type': mapped_type,
                'category': row.get('category') or '',
                'period': row.get('period') or {},
                'payload_sent': row.get('payload') or {},
                'response_received': row.get('response') or row.get('response_preview') or {},
                'status': str(row.get('status') or '').strip().lower() or ('erro' if str(row.get('error_message') or '').strip() else 'sucesso'),
                'attempts': int(row.get('attempts') or 1),
                'error_message': row.get('error_message') or '',
            })
        rows = []
        for row in (internal or []):
            if not isinstance(row, dict):
                continue
            normalized = dict(row)
            normalized['channel'] = cls._normalize_channel(row.get('channel') or '')
            rows.append(normalized)
        rows.extend(ota_rows)
        rows.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return rows

    @classmethod
    def _extract_tariff_values(cls, payload: Any) -> List[float]:
        values: List[float] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_norm = str(key or '').strip().lower()
                if isinstance(value, (int, float)) and key_norm in ('tarifa', 'tarifa_ota', 'tarifa_canal', 'rate', 'price', 'amount'):
                    values.append(float(value))
                elif isinstance(value, (dict, list)):
                    values.extend(cls._extract_tariff_values(value))
        elif isinstance(payload, list):
            for item in payload:
                values.extend(cls._extract_tariff_values(item))
        return [value for value in values if value >= 0]

    @classmethod
    def _commission_pct_by_channel(cls) -> Dict[str, float]:
        from app.services.channel_commission_service import ChannelCommissionService

        rows = (ChannelCommissionService.get_commission_rules() or {}).get('channels') or []
        mapped: Dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            channel = cls._normalize_channel(row.get('channel_name') or '')
            try:
                mapped[channel] = max(0.0, min(1.0, float(row.get('default_commission_pct') or 0.0)))
            except Exception:
                mapped[channel] = 0.0
        channels = ChannelManagerService.list_channels()
        for row in channels:
            if not isinstance(row, dict):
                continue
            channel = cls._normalize_channel(row.get('name') or '')
            if channel in mapped:
                continue
            try:
                mapped[channel] = max(0.0, min(1.0, float(row.get('default_commission') or 0.0) / 100.0))
            except Exception:
                mapped[channel] = 0.0
        return mapped

    @classmethod
    def _revpar_denominator(cls, *, start_date: str, days: int, category: Optional[str]) -> float:
        sim = RevenueManagementService.simulate_projection(start_date=start_date, days=days, advanced_mode=True)
        rows = sim.get('rows') or []
        category_filter = RevenueManagementService._normalize_category(category) if category else ''
        total_available = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if category_filter and RevenueManagementService._normalize_category(row.get('category')) != category_filter:
                continue
            try:
                total_available += max(0.0, float(row.get('available_rooms') or 0.0))
            except Exception:
                continue
        return max(1.0, total_available)

    @classmethod
    def _build_alerts(
        cls,
        *,
        channels: List[Dict[str, Any]],
        sync_logs: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
        category: Optional[str],
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        now = datetime.now()
        active_channels = [cls._normalize_channel(item.get('name') or '') for item in channels if bool(item.get('active', True))]
        by_channel_logs: Dict[str, List[Dict[str, Any]]] = {}
        for row in sync_logs:
            ch = cls._normalize_channel(row.get('channel') or '')
            by_channel_logs.setdefault(ch, []).append(row)
        for channel in active_channels:
            rows = by_channel_logs.get(channel, [])
            newest = None
            for row in rows:
                try:
                    ts = datetime.fromisoformat(str(row.get('timestamp') or ''))
                except Exception:
                    continue
                if newest is None or ts > newest:
                    newest = ts
            if newest is None or (now - newest) > timedelta(hours=48):
                alerts.append({'type': 'canal_sem_sincronizacao', 'severity': 'warning', 'channel': channel, 'message': f'Canal {channel} sem sincronização recente.'})
            has_tariff_sent = any(
                str(row.get('sync_type') or '').strip().lower() == 'tarifa'
                and str(row.get('status') or '').strip().lower() in ('sucesso', 'enviado')
                for row in rows
            )
            if not has_tariff_sent:
                alerts.append({'type': 'tarifa_nao_enviada', 'severity': 'warning', 'channel': channel, 'message': f'Canal {channel} sem envio de tarifa no período.'})
        auth_errors = [
            row for row in sync_logs
            if str(row.get('sync_type') or '').strip().lower() == 'autenticacao'
            and str(row.get('status') or '').strip().lower() in ('erro', 'failed')
        ]
        for row in auth_errors[:10]:
            alerts.append({
                'type': 'erro_autenticacao',
                'severity': 'critical',
                'channel': cls._normalize_channel(row.get('channel') or 'Booking.com'),
                'message': str(row.get('error_message') or row.get('response_received') or 'Erro de autenticação no canal.'),
            })
        restrictions = ChannelRestrictionService.list_restrictions(
            start_date=start_date,
            end_date=end_date,
            category=category,
            status='active',
        )
        conflict_map: Dict[str, Dict[str, Any]] = {}
        for row in restrictions:
            if not isinstance(row, dict):
                continue
            key = f"{row.get('channel')}|{row.get('category')}|{row.get('date')}"
            slot = conflict_map.setdefault(key, {'cta': False, 'ctd': False, 'min_stay': 0, 'max_stay': 0, 'meta': row})
            rtype = str(row.get('restriction_type') or '')
            value = row.get('value')
            if rtype == 'cta':
                slot['cta'] = bool(value)
            elif rtype == 'ctd':
                slot['ctd'] = bool(value)
            elif rtype == 'min_stay':
                try:
                    slot['min_stay'] = max(slot['min_stay'], int(value or 0))
                except Exception:
                    pass
            elif rtype == 'max_stay':
                try:
                    slot['max_stay'] = max(slot['max_stay'], int(value or 0))
                except Exception:
                    pass
        for slot in conflict_map.values():
            meta = slot.get('meta') or {}
            if slot.get('cta') and slot.get('ctd'):
                alerts.append({
                    'type': 'regra_conflitante',
                    'severity': 'warning',
                    'channel': cls._normalize_channel(meta.get('channel') or ''),
                    'message': f"CTA e CTD ativos no mesmo dia ({meta.get('date')}).",
                })
            min_stay = int(slot.get('min_stay') or 0)
            max_stay = int(slot.get('max_stay') or 0)
            if max_stay > 0 and min_stay > max_stay:
                alerts.append({
                    'type': 'regra_conflitante',
                    'severity': 'warning',
                    'channel': cls._normalize_channel(meta.get('channel') or ''),
                    'message': f"Min stay {min_stay} maior que max stay {max_stay} em {meta.get('date')}.",
                })
        categories = [category] if category else ['areia', 'mar_familia', 'mar', 'alma_banheira', 'alma', 'alma_diamante']
        for cat in categories:
            snapshot = ChannelInventoryPlannerService.build_snapshot(
                category=cat,
                start_date=start_date,
                end_date=end_date,
                weekdays=[],
            )
            for row in (snapshot.get('rows') or []):
                if not isinstance(row, dict):
                    continue
                capacity = int(row.get('capacity_real') or 0)
                sold = int(row.get('sold_existing_total') or 0)
                allotment = int(row.get('allotment_total') or 0)
                shared_pool = int(row.get('shared_available_pool') or 0)
                if sold > capacity or allotment > capacity or shared_pool < 0:
                    alerts.append({
                        'type': 'inventario_inconsistente',
                        'severity': 'critical',
                        'channel': '',
                        'message': f"Inventário inconsistente em {cat} no dia {row.get('date')}.",
                    })
                    break
        return alerts

    @classmethod
    def _recommended_structure_status(cls) -> List[Dict[str, Any]]:
        mapping = [
            ('channels', CHANNEL_MANAGER_CHANNELS_FILE),
            ('channel_integrations', OTA_BOOKING_INTEGRATIONS_FILE),
            ('channel_category_mappings', CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE),
            ('channel_commission_rules', CHANNEL_MANAGER_COMMISSIONS_FILE),
            ('channel_inventory_rules', CHANNEL_MANAGER_TARIFFS_FILE),
            ('channel_restrictions', CHANNEL_MANAGER_RESTRICTIONS_FILE),
            ('channel_daily_rates', CHANNEL_MANAGER_TARIFFS_FILE),
            ('channel_sync_logs', CHANNEL_MANAGER_SYNC_LOGS_FILE),
            ('channel_audit_logs', CHANNEL_MANAGER_COMMERCIAL_AUDIT_FILE),
            ('channel_allotments', CHANNEL_ALLOTMENTS_FILE),
            ('channel_promotions', REVENUE_PROMOTIONS_FILE),
            ('channel_packages', PROMOTIONAL_PACKAGES_FILE),
        ]
        out = []
        for table_name, path in mapping:
            out.append({
                'name': table_name,
                'storage': path,
                'exists': os.path.exists(path),
            })
        return out

    @classmethod
    def build_dashboard(
        cls,
        *,
        start_date: str,
        end_date: str,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        period = cls._date_range(start_date, end_date)
        start_iso = period['start'].isoformat()
        end_iso = period['end'].isoformat()
        perf = RevenueManagementService.channel_performance_report(start_date=start_iso, end_date=end_iso, category=category)
        sync_logs = cls._merged_sync_logs(start_date=start_iso, end_date=end_iso)
        commission_pct = cls._commission_pct_by_channel()
        revpar_denom = cls._revpar_denominator(start_date=start_iso, days=int(period['days']), category=category)
        indicator_rows: List[Dict[str, Any]] = []
        for row in (perf.get('items') or []):
            channel = cls._normalize_channel(row.get('label') or row.get('channel') or '')
            revenue = float(row.get('total_revenue') or 0.0)
            commission_total = round(revenue * float(commission_pct.get(channel) or 0.0), 2)
            tariff_sent_values: List[float] = []
            for log in sync_logs:
                if cls._normalize_channel(log.get('channel') or '') != channel:
                    continue
                if str(log.get('sync_type') or '').strip().lower() != 'tarifa':
                    continue
                if str(log.get('status') or '').strip().lower() not in ('sucesso', 'enviado'):
                    continue
                tariff_sent_values.extend(cls._extract_tariff_values(log.get('payload_sent')))
            average_sent_tariff = round(sum(tariff_sent_values) / len(tariff_sent_values), 2) if tariff_sent_values else round(float(row.get('adr') or 0.0), 2)
            indicator_rows.append({
                'channel': channel,
                'receita': round(revenue, 2),
                'reservas': int(row.get('reservations_count') or 0),
                'adr': round(float(row.get('adr') or 0.0), 2),
                'lead_time_medio': round(float(row.get('lead_time_avg_days') or 0.0), 2),
                'cancelamentos': int(row.get('cancellations') or 0),
                'comissao_total': commission_total,
                'revpar': round(revenue / revpar_denom, 2),
                'tarifa_media_enviada': average_sent_tariff,
            })
        indicator_rows.sort(key=lambda item: (float(item.get('receita') or 0.0), int(item.get('reservas') or 0)), reverse=True)
        channels = ChannelManagerService.list_channels()
        alerts = cls._build_alerts(
            channels=channels,
            sync_logs=sync_logs,
            start_date=start_iso,
            end_date=end_iso,
            category=category,
        )
        summary = {
            'receita_total': round(sum(float(item.get('receita') or 0.0) for item in indicator_rows), 2),
            'reservas_total': int(sum(int(item.get('reservas') or 0) for item in indicator_rows)),
            'cancelamentos_total': int(sum(int(item.get('cancelamentos') or 0) for item in indicator_rows)),
            'comissao_total': round(sum(float(item.get('comissao_total') or 0.0) for item in indicator_rows), 2),
            'revpar_medio': round(sum(float(item.get('revpar') or 0.0) for item in indicator_rows) / max(1, len(indicator_rows)), 2),
            'alertas_ativos': len(alerts),
            'canais_monitorados': len(indicator_rows),
        }
        return {
            'start_date': start_iso,
            'end_date': end_iso,
            'category': category or None,
            'summary': summary,
            'indicators': indicator_rows,
            'alerts': alerts,
            'alerts_count': len(alerts),
            'recommended_structure': cls._recommended_structure_status(),
            'flow': [
                'Revenue Management',
                'Tarifa Base',
                'Regras Comerciais',
                'Ajuste por Canal',
                'Comissão / gross-up',
                'Inventário / Restrições',
                'Sincronização OTA',
                'Logs / Auditoria',
            ],
        }
