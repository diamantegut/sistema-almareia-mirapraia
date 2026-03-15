from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.booking_connectivity_auth_service import BookingConnectivityAuthService
from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.ota_booking_integration_service import OTABookingIntegrationService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import (
    OTA_BOOKING_CATEGORY_MAPPING_FILE,
    OTA_BOOKING_CHANNEL_CTA_CTD_FILE,
    OTA_BOOKING_COMMERCIAL_AUDIT_FILE,
    OTA_BOOKING_COMMERCIAL_RESTRICTIONS_FILE,
    OTA_BOOKING_DISTRIBUTION_LOGS_FILE,
    OTA_BOOKING_ERROR_LOGS_FILE,
    OTA_BOOKING_PENDING_RATES_FILE,
    OTA_BOOKING_STATUS_HISTORY_FILE,
)


class OTABookingRMService:
    BOOKING_CATEGORY_OPTIONS = [
        {'key': 'areia', 'label': 'Areia'},
        {'key': 'mar_familia', 'label': 'Mar Família'},
        {'key': 'mar', 'label': 'Mar'},
        {'key': 'alma_banheira', 'label': 'Alma com Banheira'},
        {'key': 'alma', 'label': 'Alma'},
        {'key': 'alma_diamante', 'label': 'Alma Diamante'},
    ]

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
    def _append_log(cls, file_path: str, item: Dict[str, Any]) -> None:
        rows = cls._load_json(file_path, [])
        rows.append(item)
        cls._save_json(file_path, rows)

    @classmethod
    def _replace_rows(cls, file_path: str, rows: List[Dict[str, Any]]) -> None:
        cls._save_json(file_path, rows if isinstance(rows, list) else [])

    @classmethod
    def _normalize_booking_category(cls, category: Any) -> str:
        from app.services.revenue_management_service import RevenueManagementService

        return RevenueManagementService._normalize_booking_category(category)

    @classmethod
    def _category_matches(cls, rule_category: Any, target_category: Any) -> bool:
        left = cls._normalize_booking_category(rule_category)
        right = cls._normalize_booking_category(target_category)
        return left == right or str(rule_category or '').strip() in ('*', 'all', 'all_booking_categories')

    @classmethod
    def _append_commercial_audit(cls, item: Dict[str, Any]) -> None:
        rows = cls._load_json(OTA_BOOKING_COMMERCIAL_AUDIT_FILE, [])
        rows.append(item)
        cls._save_json(OTA_BOOKING_COMMERCIAL_AUDIT_FILE, rows)

    @classmethod
    def _load_category_mapping_rows(cls) -> List[Dict[str, Any]]:
        rows = cls._load_json(OTA_BOOKING_CATEGORY_MAPPING_FILE, [])
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            category = cls._normalize_booking_category(row.get('category'))
            out.append({
                'id': str(row.get('id') or str(uuid.uuid4())),
                'category': category,
                'room_type_id_booking': str(row.get('room_type_id_booking') or '').strip(),
                'rate_plan_id_booking': str(row.get('rate_plan_id_booking') or '').strip(),
                'status': 'active' if str(row.get('status') or 'active').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo') else 'inactive',
                'updated_at': str(row.get('updated_at') or ''),
                'user': str(row.get('user') or ''),
            })
        return out

    @classmethod
    def list_category_mappings(cls) -> Dict[str, Any]:
        from app.services.channel_category_mapping_service import ChannelCategoryMappingService

        payload = ChannelCategoryMappingService.list_mappings(channel_name='Booking.com')
        channels = payload.get('channels') if isinstance(payload, dict) else []
        first = channels[0] if isinstance(channels, list) and channels else {}
        items = first.get('items') if isinstance(first, dict) else []
        out_items: List[Dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            mappings = item.get('mappings') if isinstance(item, dict) else []
            out_items.append({
                'category': item.get('category'),
                'category_label': item.get('category_label'),
                'mappings': [
                    {
                        **row,
                        'room_type_id_booking': row.get('external_room_type_id'),
                        'rate_plan_id_booking': row.get('external_rate_plan_id'),
                    }
                    for row in (mappings or [])
                ],
                'active_complete_count': item.get('active_complete_count'),
                'incomplete_count': item.get('incomplete_count'),
                'missing_integration': bool(item.get('missing_mapping')),
            })
        return {
            'items': out_items,
            'missing_categories': first.get('missing_categories') or [],
            'is_complete': bool(first.get('is_complete')),
        }

    @classmethod
    def save_category_mappings(cls, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        from app.services.channel_category_mapping_service import ChannelCategoryMappingService

        items = payload.get('items') if isinstance(payload, dict) else []
        channel_payload = {
            'channels': [
                {
                    'channel_name': 'Booking.com',
                    'items': [
                        {
                            'category': item.get('category'),
                            'mappings': [
                                {
                                    **mapping,
                                    'external_room_type_id': mapping.get('external_room_type_id') or mapping.get('room_type_id_booking'),
                                    'external_rate_plan_id': mapping.get('external_rate_plan_id') or mapping.get('rate_plan_id_booking'),
                                }
                                for mapping in ((item.get('mappings') if isinstance(item, dict) else []) or [])
                                if isinstance(mapping, dict)
                            ],
                        }
                        for item in (items if isinstance(items, list) else [])
                        if isinstance(item, dict)
                    ],
                }
            ]
        }
        ChannelCategoryMappingService.save_mappings(
            payload=channel_payload,
            user=user,
            reason=reason,
        )
        snapshot = cls.list_category_mappings()
        cls._append_commercial_audit({
            'id': str(uuid.uuid4()),
            'changed_at': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'event_type': 'mapeamento_categoria_booking',
            'previous': {'summary': 'atualizado'},
            'current': {'missing_categories': snapshot.get('missing_categories') or []},
            'motivo': clean_reason,
        })
        return snapshot

    @classmethod
    def _resolve_rate_mappings_for_category(cls, category: str, required_rate_plan: str = '') -> List[Dict[str, Any]]:
        from app.services.channel_category_mapping_service import ChannelCategoryMappingService

        rows = ChannelCategoryMappingService.resolve_rate_mappings_for_channel_category(
            channel_name='Booking.com',
            category=category,
            required_rate_plan=required_rate_plan,
        )
        return [
            {
                **row,
                'room_type_id_booking': row.get('external_room_type_id'),
                'rate_plan_id_booking': row.get('external_rate_plan_id'),
            }
            for row in rows
        ]

    @classmethod
    def _build_rate_payload_rows(cls, calendar_rows: List[Dict[str, Any]], required_rate_plan: str = '') -> List[Dict[str, Any]]:
        rows = calendar_rows if isinstance(calendar_rows, list) else []
        cache: Dict[str, List[Dict[str, Any]]] = {}
        missing: List[str] = []
        out: List[Dict[str, Any]] = []
        for row in rows:
            category = cls._normalize_booking_category(row.get('category'))
            if category not in cache:
                cache[category] = cls._resolve_rate_mappings_for_category(category, required_rate_plan)
                if not cache[category]:
                    label = next((str(item.get('label') or category) for item in cls.BOOKING_CATEGORY_OPTIONS if str(item.get('key')) == category), category)
                    missing.append(label)
            for mapping in cache.get(category, []):
                out.append({
                    'date': row.get('date'),
                    'category': category,
                    'room_type_id_booking': mapping.get('room_type_id_booking'),
                    'rate_plan_id_booking': mapping.get('rate_plan_id_booking'),
                    'tarifa_direta': row.get('tarifa_direta'),
                    'tarifa_ota_final': row.get('tarifa_ota'),
                    'comissao_percentual': row.get('comissao_ota_percentual'),
                    'liquido_estimado_hotel': row.get('liquido_estimado_hotel'),
                })
        if missing:
            raise ValueError(f"Mapeamento Booking incompleto para: {', '.join(sorted(set(missing)))}.")
        return out

    @classmethod
    def list_commercial_audit(cls, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_json(OTA_BOOKING_COMMERCIAL_AUDIT_FILE, [])
        start_dt = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end_dt = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = str(row.get('changed_at') or '')
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start_dt and day < start_dt:
                continue
            if end_dt and day > end_dt:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('changed_at') or '', reverse=True)
        return out

    @classmethod
    def _first_booking_integration(cls) -> Optional[Dict[str, Any]]:
        integrations = OTABookingIntegrationService.list_integrations()
        for item in integrations:
            if str(item.get('nome_ota') or '').strip().lower() == 'booking.com':
                return item
        return integrations[0] if integrations else None

    @classmethod
    def resolve_integration_id(cls, integration_id: Optional[str] = None) -> str:
        raw = str(integration_id or '').strip()
        if raw:
            return raw
        integration = cls._first_booking_integration()
        if not integration:
            raise ValueError('Integração Booking.com não configurada.')
        resolved = str(integration.get('id') or '').strip()
        if not resolved:
            raise ValueError('Integração Booking.com inválida.')
        return resolved

    @classmethod
    def get_integration_module_status(cls, integration_id: Optional[str], user: str) -> Dict[str, Any]:
        integration = OTABookingIntegrationService.get_integration(integration_id) if integration_id else cls._first_booking_integration()
        if not integration:
            return {
                'integration': None,
                'status': 'not_configured',
                'auth': {'success': False, 'message': 'Integração Booking.com não cadastrada.'},
                'health': {'success': False, 'message': 'Integração Booking.com não cadastrada.'},
            }
        resolved_id = str(integration.get('id') or '')
        auth = BookingConnectivityAuthService.get_access_token(resolved_id, user=user, force_refresh=False)
        health = BookingConnectivityAuthService.health_check(resolved_id, user=user)
        status = 'online' if bool(auth.get('success')) and bool(health.get('success')) else 'degraded'
        snapshot = {
            'checked_at': datetime.now().isoformat(timespec='seconds'),
            'integration_id': resolved_id,
            'status': status,
            'auth_success': bool(auth.get('success')),
            'health_success': bool(health.get('success')),
            'auth_message': auth.get('message') or '',
            'health_message': health.get('message') or '',
            'user': user,
        }
        cls._append_log(OTA_BOOKING_STATUS_HISTORY_FILE, snapshot)
        return {
            'integration': integration,
            'status': status,
            'auth': auth,
            'health': health,
        }

    @classmethod
    def get_commercial_rules(cls) -> Dict[str, Any]:
        from app.services.revenue_management_service import RevenueManagementService

        return RevenueManagementService.get_booking_commercial_config()

    @classmethod
    def save_commercial_rules(cls, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        from app.services.revenue_management_service import RevenueManagementService

        return RevenueManagementService.save_booking_commercial_config(payload=payload, user=user, reason=reason)

    @classmethod
    def _integration_base_url(cls, integration_id: str) -> str:
        integration = OTABookingIntegrationService.get_integration(integration_id)
        if not integration:
            return ''
        base_url = str(integration.get('base_url_supply') or integration.get('base_url_secure_supply') or '').strip()
        return base_url.rstrip('/')

    @classmethod
    def _send_distribution(
        cls,
        *,
        integration_id: str,
        distribution_type: str,
        endpoint_path: str,
        payload: Dict[str, Any],
        user: str,
        method: str = 'POST',
        log_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base_url = cls._integration_base_url(integration_id)
        if not base_url:
            raise ValueError('Base URL da integração Booking.com não configurada.')
        endpoint = f"{base_url}/{endpoint_path.lstrip('/')}"
        call = BookingConnectivityAuthService.request_with_auth(
            integration_id=integration_id,
            method=method,
            url=endpoint,
            user=user,
            timeout=15,
            json=payload,
            headers={'Content-Type': 'application/json'},
        )
        item = {
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'integration_id': integration_id,
            'distribution_type': distribution_type,
            'endpoint': endpoint,
            'payload': payload,
            'status': 'enviado' if bool(call.get('success')) else 'erro',
            'success': bool(call.get('success')),
            'http_status': call.get('http_status'),
            'response_preview': call.get('text') or call.get('message') or '',
            'error_message': '' if bool(call.get('success')) else str(call.get('message') or ''),
            'attempts': 1,
            'user': user,
        }
        if isinstance(log_context, dict):
            item.update(log_context)
        cls._append_log(OTA_BOOKING_DISTRIBUTION_LOGS_FILE, item)
        if not call.get('success'):
            cls._append_log(OTA_BOOKING_ERROR_LOGS_FILE, {
                **item,
                'error_message': call.get('message') or f"Falha {distribution_type}",
            })
        LoggerService.log_acao(
            acao=f'OTA Distribution Booking: {distribution_type}',
            entidade='Revenue Management',
            detalhes={'integration_id': integration_id, 'success': bool(call.get('success')), 'http_status': call.get('http_status')},
            nivel_severidade='INFO' if call.get('success') else 'WARNING',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'success': bool(call.get('success')),
            'distribution_type': distribution_type,
            'endpoint': endpoint,
            'http_status': call.get('http_status'),
            'response_preview': item['response_preview'],
            'payload': payload,
            'status': item.get('status'),
            'log_id': item.get('id'),
        }

    @classmethod
    def apply_channel_cta_ctd(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        restriction_type: str,
        active: bool,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        normalized_type = str(restriction_type or '').strip().lower()
        if normalized_type not in ('cta', 'ctd'):
            raise ValueError('Tipo inválido. Use CTA ou CTD.')
        normalized_category = cls._normalize_booking_category(category)
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para CTA/CTD no canal Booking.')
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays or [])
        dates = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        rows = cls._load_json(OTA_BOOKING_CHANNEL_CTA_CTD_FILE, [])
        if not isinstance(rows, list):
            rows = []
        remaining = [
            row for row in rows
            if not (
                str(row.get('category') or '') == normalized_category
                and str(row.get('restriction_type') or '').strip().lower() == normalized_type
                and str(row.get('date') or '') in set(dates)
            )
        ]
        for day in dates:
            remaining.append({
                'id': str(uuid.uuid4()),
                'category': normalized_category,
                'restriction_type': normalized_type,
                'date': day,
                'status': 'active' if bool(active) else 'inactive',
                'motivo': clean_reason,
                'updated_at': datetime.now().isoformat(timespec='seconds'),
                'user': user,
            })
        cls._replace_rows(OTA_BOOKING_CHANNEL_CTA_CTD_FILE, remaining)
        cls._append_commercial_audit({
            'id': str(uuid.uuid4()),
            'changed_at': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'event_type': normalized_type.upper(),
            'category': normalized_category,
            'previous': {'status': 'mixed'},
            'current': {'status': 'active' if bool(active) else 'inactive', 'dates': dates},
            'motivo': clean_reason,
        })
        return {
            'updated': len(dates),
            'dates': dates,
            'category': normalized_category,
            'restriction_type': normalized_type,
            'status': 'active' if bool(active) else 'inactive',
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def resolve_channel_cta_ctd(cls, *, category: str, date: str) -> Dict[str, Any]:
        normalized_category = cls._normalize_booking_category(category)
        rows = cls._load_json(OTA_BOOKING_CHANNEL_CTA_CTD_FILE, [])
        if not isinstance(rows, list):
            rows = []
        cta_active = False
        ctd_active = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get('date') or '') != str(date):
                continue
            if not cls._category_matches(row.get('category'), normalized_category):
                continue
            if str(row.get('status') or '') != 'active':
                continue
            rtype = str(row.get('restriction_type') or '').strip().lower()
            if rtype == 'cta':
                cta_active = True
            if rtype == 'ctd':
                ctd_active = True
        labels: List[str] = []
        if cta_active:
            labels.append('cta')
        if ctd_active:
            labels.append('ctd')
        return {'cta': cta_active, 'ctd': ctd_active, 'labels': labels}

    @classmethod
    def apply_commercial_restriction(
        cls,
        *,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        rule_type: str,
        active: bool,
        value: Any,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        normalized_type = str(rule_type or '').strip().lower()
        if normalized_type not in ('min_stay', 'max_stay', 'pacote_obrigatorio', 'promocao_ota'):
            raise ValueError('Tipo de regra comercial inválido.')
        normalized_category = cls._normalize_booking_category(category)
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para regra comercial Booking.')
        normalized_weekdays = PeriodSelectorService.normalize_weekdays(weekdays or [])
        dates = PeriodSelectorService.expand_dates(start_date, end_date, normalized_weekdays)
        rows = cls._load_json(OTA_BOOKING_COMMERCIAL_RESTRICTIONS_FILE, [])
        if not isinstance(rows, list):
            rows = []
        remaining = [
            row for row in rows
            if not (
                str(row.get('category') or '') == normalized_category
                and str(row.get('rule_type') or '').strip().lower() == normalized_type
                and str(row.get('date') or '') in set(dates)
            )
        ]
        for day in dates:
            remaining.append({
                'id': str(uuid.uuid4()),
                'category': normalized_category,
                'rule_type': normalized_type,
                'date': day,
                'status': 'active' if bool(active) else 'inactive',
                'value': value,
                'motivo': clean_reason,
                'updated_at': datetime.now().isoformat(timespec='seconds'),
                'user': user,
            })
        cls._replace_rows(OTA_BOOKING_COMMERCIAL_RESTRICTIONS_FILE, remaining)
        cls._append_commercial_audit({
            'id': str(uuid.uuid4()),
            'changed_at': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'event_type': normalized_type,
            'category': normalized_category,
            'previous': {'status': 'mixed'},
            'current': {'status': 'active' if bool(active) else 'inactive', 'value': value, 'dates': dates},
            'motivo': clean_reason,
        })
        return {
            'updated': len(dates),
            'dates': dates,
            'category': normalized_category,
            'rule_type': normalized_type,
            'status': 'active' if bool(active) else 'inactive',
            'value': value,
            'period': {'start_date': start_date, 'end_date': end_date, 'weekdays': normalized_weekdays},
        }

    @classmethod
    def resolve_commercial_restrictions(cls, *, category: str, date: str) -> Dict[str, Any]:
        normalized_category = cls._normalize_booking_category(category)
        rows = cls._load_json(OTA_BOOKING_COMMERCIAL_RESTRICTIONS_FILE, [])
        if not isinstance(rows, list):
            rows = []
        out = {
            'min_stay_nights': 1,
            'max_stay_nights': 0,
            'pacote_obrigatorio': False,
            'promocao_ota': '',
            'labels': [],
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get('date') or '') != str(date):
                continue
            if not cls._category_matches(row.get('category'), normalized_category):
                continue
            if str(row.get('status') or '') != 'active':
                continue
            rtype = str(row.get('rule_type') or '').strip().lower()
            value = row.get('value')
            if rtype == 'min_stay':
                try:
                    out['min_stay_nights'] = max(int(out['min_stay_nights']), int(value or 1))
                except Exception:
                    out['min_stay_nights'] = max(int(out['min_stay_nights']), 1)
                out['labels'].append(f"min_stay_{out['min_stay_nights']}")
            elif rtype == 'max_stay':
                try:
                    max_value = max(1, int(value or 0))
                    current = int(out['max_stay_nights'] or 0)
                    out['max_stay_nights'] = max_value if current <= 0 else min(current, max_value)
                except Exception:
                    continue
                out['labels'].append(f"max_stay_{out['max_stay_nights']}")
            elif rtype == 'pacote_obrigatorio':
                out['pacote_obrigatorio'] = bool(value) if isinstance(value, bool) else str(value or '').strip().lower() in ('1', 'true', 'yes', 'sim', 'active')
                if out['pacote_obrigatorio']:
                    out['labels'].append('pacote_obrigatorio')
            elif rtype == 'promocao_ota':
                promo = str(value or '').strip()
                if promo:
                    out['promocao_ota'] = promo
                    out['labels'].append(f"promo_{promo}")
        return out

    @classmethod
    def send_rates(
        cls,
        *,
        integration_id: str,
        category: str,
        rate_plan_id_booking: str = '',
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        user: str,
        mode: str = 'manual',
    ) -> Dict[str, Any]:
        from app.services.revenue_management_service import RevenueManagementService

        rate_plan = str(rate_plan_id_booking or '').strip()
        calendar = RevenueManagementService.calendar_direct_vs_ota(
            category=category,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays or [],
        )
        rate_rows = cls._build_rate_payload_rows(calendar.get('rows') or [], rate_plan)
        payload = {
            'category': category,
            'rate_plan_id_booking': rate_plan,
            'start_date': start_date,
            'end_date': end_date,
            'weekdays': weekdays or [],
            'rates': rate_rows,
        }
        if mode == 'lote':
            queued = cls.queue_rate_distribution(
                integration_id=integration_id,
                category=category,
                rate_plan_id_booking=rate_plan,
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                user=user,
            )
            return {
                'success': True,
                'distribution_type': 'envio_tarifas',
                'status': 'pendente',
                'queued': queued.get('queued', 0),
                'queue_ids': queued.get('queue_ids', []),
            }
        return cls._send_distribution(
            integration_id=integration_id,
            distribution_type='envio_tarifas',
            endpoint_path='rates',
            payload=payload,
            user=user,
            method='POST',
            log_context={
                'mode': mode,
                'rate_plan_id_booking': rate_plan,
            },
        )

    @classmethod
    def queue_rate_distribution(
        cls,
        *,
        integration_id: str,
        category: str,
        rate_plan_id_booking: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        user: str,
    ) -> Dict[str, Any]:
        from app.services.revenue_management_service import RevenueManagementService

        rate_plan = str(rate_plan_id_booking or '').strip()
        calendar = RevenueManagementService.calendar_direct_vs_ota(
            category=category,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays or [],
        )
        rate_rows = cls._build_rate_payload_rows(calendar.get('rows') or [], rate_plan)
        pending = cls._load_json(OTA_BOOKING_PENDING_RATES_FILE, [])
        if not isinstance(pending, list):
            pending = []
        ids: List[str] = []
        for row in rate_rows:
            item = {
                'id': str(uuid.uuid4()),
                'created_at': datetime.now().isoformat(timespec='seconds'),
                'integration_id': integration_id,
                'distribution_type': 'envio_tarifas',
                'status': 'pendente',
                'attempts': 0,
                'last_error': '',
                'payload': {
                    'category': row.get('category'),
                    'room_type_id_booking': row.get('room_type_id_booking'),
                    'rate_plan_id_booking': row.get('rate_plan_id_booking'),
                    'date': row.get('date'),
                    'tarifa_ota_final': row.get('tarifa_ota_final'),
                    'tarifa_direta': row.get('tarifa_direta'),
                    'comissao_percentual': row.get('comissao_percentual'),
                    'liquido_estimado_hotel': row.get('liquido_estimado_hotel'),
                },
                'user': user,
            }
            pending.append(item)
            ids.append(item['id'])
        cls._replace_rows(OTA_BOOKING_PENDING_RATES_FILE, pending)
        return {'queued': len(ids), 'queue_ids': ids}

    @classmethod
    def process_pending_rate_distributions(
        cls,
        *,
        integration_id: str,
        user: str,
        limit: int = 100,
    ) -> Dict[str, Any]:
        pending = cls._load_json(OTA_BOOKING_PENDING_RATES_FILE, [])
        if not isinstance(pending, list):
            pending = []
        processed = 0
        sent = 0
        failed = 0
        for item in pending:
            if processed >= max(1, int(limit)):
                break
            if str(item.get('status') or '') != 'pendente':
                continue
            payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
            date_value = str(payload.get('date') or '').strip()
            day_payload = {
                'rate_plan_id_booking': payload.get('rate_plan_id_booking'),
                'room_type_id_booking': payload.get('room_type_id_booking'),
                'category': payload.get('category'),
                'rates': [
                    {
                        'date': date_value,
                        'room_type_id_booking': payload.get('room_type_id_booking'),
                        'rate_plan_id_booking': payload.get('rate_plan_id_booking'),
                        'tarifa_ota_final': payload.get('tarifa_ota_final'),
                        'tarifa_direta': payload.get('tarifa_direta'),
                        'comissao_percentual': payload.get('comissao_percentual'),
                        'liquido_estimado_hotel': payload.get('liquido_estimado_hotel'),
                    }
                ],
            }
            call = cls._send_distribution(
                integration_id=integration_id,
                distribution_type='envio_tarifas',
                endpoint_path='rates',
                payload=day_payload,
                user=user,
                method='POST',
                log_context={
                    'mode': 'lote',
                    'queue_id': item.get('id'),
                    'queue_date': date_value,
                    'rate_plan_id_booking': payload.get('rate_plan_id_booking'),
                    'status': 'reprocessado' if int(item.get('attempts') or 0) > 0 else 'enviado',
                    'attempts': int(item.get('attempts') or 0) + 1,
                },
            )
            processed += 1
            if call.get('success'):
                item['status'] = 'enviado'
                item['processed_at'] = datetime.now().isoformat(timespec='seconds')
                sent += 1
            else:
                item['status'] = 'erro'
                item['attempts'] = int(item.get('attempts') or 0) + 1
                item['last_error'] = str(call.get('response_preview') or call.get('message') or 'Falha no envio')
                item['processed_at'] = datetime.now().isoformat(timespec='seconds')
                failed += 1
        cls._replace_rows(OTA_BOOKING_PENDING_RATES_FILE, pending)
        return {
            'processed': processed,
            'sent': sent,
            'failed': failed,
        }

    @classmethod
    def reprocess_failed_rate_distributions(cls, *, queue_ids: Optional[List[str]], user: str) -> Dict[str, Any]:
        pending = cls._load_json(OTA_BOOKING_PENDING_RATES_FILE, [])
        if not isinstance(pending, list):
            pending = []
        wanted = {str(item).strip() for item in (queue_ids or []) if str(item).strip()}
        reset = 0
        for item in pending:
            if str(item.get('status') or '') != 'erro':
                continue
            if wanted and str(item.get('id') or '') not in wanted:
                continue
            item['status'] = 'pendente'
            item['reprocess_requested_at'] = datetime.now().isoformat(timespec='seconds')
            item['reprocess_requested_by'] = user
            reset += 1
        cls._replace_rows(OTA_BOOKING_PENDING_RATES_FILE, pending)
        return {'requeued': reset}

    @classmethod
    def send_availability(
        cls,
        *,
        integration_id: str,
        payload: Dict[str, Any],
        user: str,
    ) -> Dict[str, Any]:
        return cls._send_distribution(
            integration_id=integration_id,
            distribution_type='envio_disponibilidade',
            endpoint_path='availability',
            payload=payload,
            user=user,
            method='POST',
        )

    @classmethod
    def send_open_close(
        cls,
        *,
        integration_id: str,
        category: str,
        rate_plan_id_booking: Optional[str],
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        status: str,
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        from app.services.channel_inventory_control_service import ChannelInventoryControlService

        restriction = ChannelInventoryControlService.apply_channel_restriction(
            category=category,
            channel='Booking.com',
            start_date=start_date,
            end_date=end_date,
            status=status,
            user=user,
            reason=reason,
            weekdays=weekdays or [],
            origin='ota_distribution',
        )
        payload = {
            'category': restriction.get('category'),
            'channel': 'Booking.com',
            'rate_plan_id_booking': str(rate_plan_id_booking or '').strip(),
            'status': restriction.get('status'),
            'period': restriction.get('period'),
            'reason': reason,
            'dates': restriction.get('dates') or [],
        }
        cls._append_commercial_audit({
            'id': str(uuid.uuid4()),
            'changed_at': datetime.now().isoformat(timespec='seconds'),
            'user': user,
            'event_type': 'open_close',
            'category': str(restriction.get('category') or ''),
            'previous': {'status': 'aberto' if str(status or '') != 'active' else 'fechado'},
            'current': {'status': 'fechado' if str(status or '') == 'active' else 'aberto', 'dates': restriction.get('dates') or []},
            'motivo': reason,
        })
        return cls._send_distribution(
            integration_id=integration_id,
            distribution_type='envio_open_close',
            endpoint_path='restrictions/open-close',
            payload=payload,
            user=user,
            method='POST',
        )

    @classmethod
    def send_min_stay(
        cls,
        *,
        integration_id: str,
        payload: Dict[str, Any],
        user: str,
    ) -> Dict[str, Any]:
        category = str(payload.get('category') or '').strip()
        period = {'start_date': payload.get('start_date'), 'end_date': payload.get('end_date'), 'weekdays': payload.get('weekdays') or []}
        min_stay_value = payload.get('min_stay_nights')
        reason = str(payload.get('reason') or '').strip()
        cls.apply_commercial_restriction(
            category=category,
            start_date=str(period.get('start_date') or ''),
            end_date=str(period.get('end_date') or period.get('start_date') or ''),
            weekdays=period.get('weekdays') or [],
            rule_type='min_stay',
            active=True,
            value=min_stay_value,
            reason=reason or 'Atualização de min_stay',
            user=user,
        )
        return cls._send_distribution(
            integration_id=integration_id,
            distribution_type='envio_min_stay',
            endpoint_path='restrictions/min-stay',
            payload=payload,
            user=user,
            method='POST',
        )

    @classmethod
    def send_cta_ctd(
        cls,
        *,
        integration_id: str,
        payload: Dict[str, Any],
        user: str,
    ) -> Dict[str, Any]:
        category = str(payload.get('category') or '').strip()
        start_date = str(payload.get('start_date') or '')
        end_date = str(payload.get('end_date') or start_date)
        weekdays = payload.get('weekdays') or []
        active = bool(payload.get('active', True))
        reason = str(payload.get('reason') or '').strip()
        request_cta = bool(payload.get('cta'))
        request_ctd = bool(payload.get('ctd'))
        if not request_cta and not request_ctd:
            raise ValueError('Informe ao menos CTA ou CTD.')
        results: List[Dict[str, Any]] = []
        if request_cta:
            cls.apply_channel_cta_ctd(
                category=category,
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                restriction_type='cta',
                active=active,
                reason=reason or 'Atualização CTA',
                user=user,
            )
            results.append(cls._send_distribution(
                integration_id=integration_id,
                distribution_type='envio_cta',
                endpoint_path='restrictions/arrival-departure',
                payload={**payload, 'type': 'CTA'},
                user=user,
                method='POST',
            ))
        if request_ctd:
            cls.apply_channel_cta_ctd(
                category=category,
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                restriction_type='ctd',
                active=active,
                reason=reason or 'Atualização CTD',
                user=user,
            )
            results.append(cls._send_distribution(
                integration_id=integration_id,
                distribution_type='envio_ctd',
                endpoint_path='restrictions/arrival-departure',
                payload={**payload, 'type': 'CTD'},
                user=user,
                method='POST',
            ))
        all_success = all(bool(item.get('success')) for item in results)
        return {
            'success': all_success,
            'distribution_type': 'envio_cta_ctd',
            'results': results,
            'status': 'enviado' if all_success else 'erro',
        }

    @classmethod
    def send_stop_sell(
        cls,
        *,
        integration_id: str,
        category: str,
        start_date: str,
        end_date: str,
        weekdays: Optional[List[str]],
        reason: str,
        user: str,
    ) -> Dict[str, Any]:
        return cls.send_open_close(
            integration_id=integration_id,
            category=category,
            rate_plan_id_booking='',
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays,
            status='active',
            reason=reason,
            user=user,
        )

    @classmethod
    def list_distribution_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        distribution_type: Optional[str] = None,
        success: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(OTA_BOOKING_DISTRIBUTION_LOGS_FILE, [])
        start_dt = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end_dt = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        type_norm = str(distribution_type or '').strip().lower()
        status_norm = str(status or '').strip().lower()
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = str(row.get('timestamp') or '')
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start_dt and day < start_dt:
                continue
            if end_dt and day > end_dt:
                continue
            if type_norm and str(row.get('distribution_type') or '').strip().lower() != type_norm:
                continue
            if status_norm and str(row.get('status') or '').strip().lower() != status_norm:
                continue
            if success is not None and bool(row.get('success')) != bool(success):
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def list_sync_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        distribution = cls.list_distribution_logs(start_date=start_date, end_date=end_date)
        status_norm = str(status or '').strip().lower()
        status_rows = cls._load_json(OTA_BOOKING_STATUS_HISTORY_FILE, [])
        auth_rows: List[Dict[str, Any]] = []
        for item in (status_rows or []):
            if not isinstance(item, dict):
                continue
            auth_success = bool(item.get('auth_success'))
            row = {
                'id': str(uuid.uuid4()),
                'timestamp': item.get('checked_at'),
                'user': item.get('user') or 'Sistema',
                'type': 'autenticacao',
                'payload': {'integration_id': item.get('integration_id')},
                'response': {'message': item.get('auth_message') or ''},
                'status': 'sucesso' if auth_success else 'erro',
                'error_message': '' if auth_success else str(item.get('auth_message') or ''),
                'attempts': 1,
            }
            auth_rows.append(row)
        out: List[Dict[str, Any]] = []
        for row in distribution:
            mapped_status = str(row.get('status') or '')
            translated = 'sucesso' if mapped_status in ('enviado', 'reprocessado') else ('erro' if mapped_status == 'erro' else mapped_status)
            normalized = {
                'id': row.get('id'),
                'timestamp': row.get('timestamp'),
                'user': row.get('user') or 'Sistema',
                'type': str(row.get('distribution_type') or '').replace('envio_', ''),
                'payload': row.get('payload') or {},
                'response': row.get('response_preview') or '',
                'status': translated,
                'error_message': row.get('error_message') or '',
                'attempts': int(row.get('attempts') or 1),
            }
            out.append(normalized)
        out.extend(auth_rows)
        if status_norm:
            out = [row for row in out if str(row.get('status') or '').strip().lower() == status_norm]
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out

    @classmethod
    def list_pending_rate_distributions(
        cls,
        *,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(OTA_BOOKING_PENDING_RATES_FILE, [])
        if not isinstance(rows, list):
            rows = []
        status_norm = str(status or '').strip().lower()
        start_dt = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end_dt = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if status_norm and str(row.get('status') or '').strip().lower() != status_norm:
                continue
            created_at = str(row.get('created_at') or '')
            try:
                created_day = datetime.fromisoformat(created_at).date()
            except Exception:
                created_day = None
            if start_dt and created_day and created_day < start_dt:
                continue
            if end_dt and created_day and created_day > end_dt:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('created_at') or '', reverse=True)
        return out

    @classmethod
    def list_error_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(OTA_BOOKING_ERROR_LOGS_FILE, [])
        start_dt = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end_dt = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = str(row.get('timestamp') or '')
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start_dt and day < start_dt:
                continue
            if end_dt and day > end_dt:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def build_audit_snapshot(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.channel_inventory_control_service import ChannelInventoryControlService
        from app.services.revenue_management_service import RevenueManagementService

        distribution_logs = cls.list_distribution_logs(start_date=start_date, end_date=end_date)
        error_logs = cls.list_error_logs(start_date=start_date, end_date=end_date)
        pending_rate_logs = cls.list_pending_rate_distributions(start_date=start_date, end_date=end_date)
        commission_logs = RevenueManagementService.list_booking_commission_logs(
            start_date=start_date,
            end_date=end_date,
        )
        inventory_logs = ChannelInventoryControlService.list_channel_logs(
            start_date=start_date,
            end_date=end_date,
            channel='Booking.com',
        )
        return {
            'distribution_logs': distribution_logs,
            'error_logs': error_logs,
            'pending_rate_logs': pending_rate_logs,
            'commercial_audit_logs': cls.list_commercial_audit(start_date=start_date, end_date=end_date),
            'commission_logs': commission_logs,
            'inventory_logs': inventory_logs,
            'counts': {
                'distribution': len(distribution_logs),
                'errors': len(error_logs),
                'pending_rates': len([item for item in pending_rate_logs if str(item.get('status') or '') == 'pendente']),
                'commission_changes': len(commission_logs),
                'inventory_changes': len(inventory_logs),
            },
        }
