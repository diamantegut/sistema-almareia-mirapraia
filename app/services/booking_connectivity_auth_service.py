import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from app.services.logger_service import LoggerService
from app.services.ota_booking_integration_service import OTABookingIntegrationService
from app.services.system_config_manager import OTA_BOOKING_TOKEN_CACHE_FILE
from app.utils.lock import file_lock


class BookingConnectivityAuthService:
    REFRESH_SAFETY_SECONDS = 300

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    @classmethod
    def _load_cache(cls) -> Dict[str, Any]:
        if not os.path.exists(OTA_BOOKING_TOKEN_CACHE_FILE):
            return {}
        try:
            with open(OTA_BOOKING_TOKEN_CACHE_FILE, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _save_cache(cls, cache: Dict[str, Any]) -> None:
        with file_lock(OTA_BOOKING_TOKEN_CACHE_FILE):
            with open(OTA_BOOKING_TOKEN_CACHE_FILE, 'w', encoding='utf-8') as handle:
                json.dump(cache, handle, indent=4, ensure_ascii=False)

    @staticmethod
    def _parse_iso(dt_str: str) -> Optional[datetime]:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except Exception:
            return None

    @classmethod
    def _is_token_valid(cls, cached: Dict[str, Any]) -> bool:
        token = str(cached.get('access_token') or '')
        if not token:
            return False
        expires_at = cls._parse_iso(str(cached.get('expires_at') or ''))
        if not expires_at:
            return False
        return expires_at > (cls._now() + timedelta(seconds=cls.REFRESH_SAFETY_SECONDS))

    @staticmethod
    def _token_endpoint(integration: Dict[str, Any]) -> str:
        explicit = str(integration.get('auth_url') or '').strip()
        if explicit:
            return explicit
        secure = str(integration.get('base_url_secure_supply') or '').strip()
        if secure:
            return f"{secure.rstrip('/')}/oauth2/token"
        supply = str(integration.get('base_url_supply') or '').strip()
        return f"{supply.rstrip('/')}/oauth2/token" if supply else ''

    @classmethod
    def _credentials(cls, integration_id: str) -> Dict[str, Any]:
        integration = OTABookingIntegrationService.get_integration(integration_id=integration_id, include_secret=True)
        if not integration:
            return {}
        return {
            'integration': integration,
            'client_id': str(integration.get('client_id') or '').strip(),
            'client_secret': str(integration.get('client_secret') or '').strip(),
            'machine_account_name': str(integration.get('machine_account_name') or '').strip(),
            'token_url': cls._token_endpoint(integration),
        }

    @classmethod
    def _request_new_token(cls, integration_id: str, user: str) -> Dict[str, Any]:
        creds = cls._credentials(integration_id)
        client_id = creds.get('client_id') or ''
        client_secret = creds.get('client_secret') or ''
        token_url = creds.get('token_url') or ''
        machine_account_name = creds.get('machine_account_name') or ''
        if not client_id or not client_secret or not token_url:
            message = 'Credenciais incompletas para autenticação Booking.com.'
            LoggerService.log_acao(
                acao='Falha autenticação Booking.com',
                entidade='Integrações OTA',
                detalhes={'integration_id': integration_id, 'message': message},
                nivel_severidade='WARNING',
                departamento_id='Administração',
                colaborador_id=user,
            )
            return {'success': False, 'message': message}
        payload = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
        }
        if machine_account_name:
            payload['machine_account_name'] = machine_account_name
        try:
            response = requests.post(
                token_url,
                data=payload,
                headers={'Accept': 'application/json'},
                timeout=10,
            )
            ok = 200 <= int(response.status_code) < 300
            data = {}
            try:
                data = response.json() if response.content else {}
            except Exception:
                data = {}
            if not ok:
                message = f'Falha ao autenticar ({response.status_code}).'
                LoggerService.log_acao(
                    acao='Falha autenticação Booking.com',
                    entidade='Integrações OTA',
                    detalhes={
                        'integration_id': integration_id,
                        'http_status': int(response.status_code),
                        'token_url': token_url,
                    },
                    nivel_severidade='WARNING',
                    departamento_id='Administração',
                    colaborador_id=user,
                )
                return {'success': False, 'message': message, 'http_status': int(response.status_code)}
            access_token = str(data.get('access_token') or data.get('token') or '').strip()
            expires_in = int(data.get('expires_in') or 3600)
            token_type = str(data.get('token_type') or 'Bearer')
            if not access_token:
                message = 'Resposta de autenticação sem token.'
                LoggerService.log_acao(
                    acao='Falha autenticação Booking.com',
                    entidade='Integrações OTA',
                    detalhes={'integration_id': integration_id, 'message': message},
                    nivel_severidade='WARNING',
                    departamento_id='Administração',
                    colaborador_id=user,
                )
                return {'success': False, 'message': message}
            expires_at = cls._now() + timedelta(seconds=max(30, expires_in))
            cache = cls._load_cache()
            cache[str(integration_id)] = {
                'access_token': access_token,
                'token_type': token_type,
                'expires_at': expires_at.isoformat(timespec='seconds'),
                'expires_in': int(expires_in),
                'refreshed_at': cls._now().isoformat(timespec='seconds'),
            }
            cls._save_cache(cache)
            OTABookingIntegrationService.register_auth_success(
                integration_id=integration_id,
                user=user,
                authenticated_at=cls._now().isoformat(timespec='seconds'),
            )
            LoggerService.log_acao(
                acao='Autenticação Booking.com bem-sucedida',
                entidade='Integrações OTA',
                detalhes={'integration_id': integration_id, 'expires_at': expires_at.isoformat(timespec='seconds')},
                nivel_severidade='INFO',
                departamento_id='Administração',
                colaborador_id=user,
            )
            return {
                'success': True,
                'token_type': token_type,
                'expires_in': int(expires_in),
                'expires_at': expires_at.isoformat(timespec='seconds'),
            }
        except Exception as exc:
            message = f'Erro ao solicitar token: {exc}'
            LoggerService.log_acao(
                acao='Falha autenticação Booking.com',
                entidade='Integrações OTA',
                detalhes={'integration_id': integration_id, 'error': str(exc)},
                nivel_severidade='ERROR',
                departamento_id='Administração',
                colaborador_id=user,
            )
            return {'success': False, 'message': message}

    @classmethod
    def get_access_token(cls, integration_id: str, user: str = 'Sistema', force_refresh: bool = False) -> Dict[str, Any]:
        cache = cls._load_cache()
        cached = cache.get(str(integration_id)) if isinstance(cache, dict) else None
        if not force_refresh and isinstance(cached, dict) and cls._is_token_valid(cached):
            return {
                'success': True,
                'access_token': str(cached.get('access_token') or ''),
                'token_type': str(cached.get('token_type') or 'Bearer'),
                'expires_at': str(cached.get('expires_at') or ''),
                'cached': True,
            }
        refresh = cls._request_new_token(integration_id=integration_id, user=user)
        if not refresh.get('success'):
            return refresh
        cache = cls._load_cache()
        latest = cache.get(str(integration_id), {})
        return {
            'success': True,
            'access_token': str(latest.get('access_token') or ''),
            'token_type': str(latest.get('token_type') or 'Bearer'),
            'expires_at': str(latest.get('expires_at') or ''),
            'cached': False,
        }

    @classmethod
    def manual_auth_test(cls, integration_id: str, user: str) -> Dict[str, Any]:
        return cls.get_access_token(integration_id=integration_id, user=user, force_refresh=True)

    @classmethod
    def request_with_auth(
        cls,
        *,
        integration_id: str,
        method: str,
        url: str,
        user: str,
        timeout: int = 10,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        token_result = cls.get_access_token(integration_id=integration_id, user=user, force_refresh=False)
        if not token_result.get('success'):
            return {'success': False, 'message': token_result.get('message', 'Falha de autenticação.')}
        token = str(token_result.get('access_token') or '')
        headers = dict(kwargs.pop('headers', {}) or {})
        headers['Authorization'] = f"Bearer {token}"
        headers.setdefault('Accept', 'application/json')
        try:
            response = requests.request(method=method.upper(), url=url, headers=headers, timeout=timeout, **kwargs)
            if int(response.status_code) == 401:
                renewed = cls.get_access_token(integration_id=integration_id, user=user, force_refresh=True)
                if renewed.get('success'):
                    retry_headers = dict(headers)
                    retry_headers['Authorization'] = f"Bearer {renewed.get('access_token')}"
                    response = requests.request(method=method.upper(), url=url, headers=retry_headers, timeout=timeout, **kwargs)
            return {
                'success': 200 <= int(response.status_code) < 300,
                'http_status': int(response.status_code),
                'text': response.text[:500] if response.text else '',
            }
        except Exception as exc:
            LoggerService.log_acao(
                acao='Falha chamada Connectivity API Booking.com',
                entidade='Integrações OTA',
                detalhes={'integration_id': integration_id, 'url': url, 'error': str(exc)},
                nivel_severidade='ERROR',
                departamento_id='Administração',
                colaborador_id=user,
            )
            return {'success': False, 'message': f'Erro de comunicação: {exc}'}

    @classmethod
    def health_check(cls, integration_id: str, user: str) -> Dict[str, Any]:
        integration = OTABookingIntegrationService.get_integration(integration_id=integration_id, include_secret=False)
        if not integration:
            return {'success': False, 'message': 'Integração não encontrada.'}
        base_url = str(integration.get('base_url_supply') or integration.get('base_url_secure_supply') or '').strip()
        if not base_url:
            return {'success': False, 'message': 'Base URL não configurada.'}
        call = cls.request_with_auth(
            integration_id=integration_id,
            method='GET',
            url=base_url,
            user=user,
            timeout=8,
        )
        last_auth = str(integration.get('ultima_autenticacao') or '')
        if call.get('success'):
            return {
                'success': True,
                'message': 'Health check da integração OK.',
                'http_status': call.get('http_status'),
                'ultima_autenticacao_sucesso': last_auth,
            }
        return {
            'success': False,
            'message': call.get('message') or f"Health check com falha ({call.get('http_status')}).",
            'http_status': call.get('http_status'),
            'ultima_autenticacao_sucesso': last_auth,
        }

    @classmethod
    def connectivity_availability(
        cls,
        *,
        integration_id: str,
        user: str,
        start_date: str,
        end_date: str,
        room_type_id: Optional[str] = None,
        property_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        integration = OTABookingIntegrationService.get_integration(integration_id=integration_id, include_secret=False)
        if not integration:
            return {'success': False, 'message': 'Integração não encontrada.'}
        base_url = str(integration.get('base_url_supply') or integration.get('base_url_secure_supply') or '').strip()
        if not base_url:
            return {'success': False, 'message': 'Base URL não configurada.'}
        endpoint = f"{base_url.rstrip('/')}/availability"
        params: Dict[str, Any] = {
            'start_date': str(start_date or '').strip(),
            'end_date': str(end_date or '').strip(),
        }
        property_id_value = str(property_id or integration.get('property_id_booking') or '').strip()
        if property_id_value:
            params['property_id'] = property_id_value
        room_type_value = str(room_type_id or '').strip()
        if room_type_value:
            params['room_type_id'] = room_type_value
        if not params.get('start_date') or not params.get('end_date'):
            return {'success': False, 'message': 'start_date e end_date são obrigatórios.'}
        call = cls.request_with_auth(
            integration_id=integration_id,
            method='GET',
            url=endpoint,
            user=user,
            timeout=12,
            params=params,
        )
        LoggerService.log_acao(
            acao='Consulta disponibilidade Connectivity Booking.com',
            entidade='Integrações OTA',
            detalhes={
                'integration_id': integration_id,
                'endpoint': endpoint,
                'params': params,
                'success': bool(call.get('success')),
                'http_status': call.get('http_status'),
            },
            nivel_severidade='INFO' if call.get('success') else 'WARNING',
            departamento_id='Administração',
            colaborador_id=user,
        )
        return {
            'success': bool(call.get('success')),
            'http_status': call.get('http_status'),
            'message': call.get('message') or ('Disponibilidade consultada com sucesso.' if call.get('success') else 'Falha ao consultar disponibilidade.'),
            'response_preview': call.get('text') or '',
            'endpoint': endpoint,
            'params': params,
        }
