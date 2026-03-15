import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet

from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    OTA_BOOKING_INTEGRATIONS_FILE,
    OTA_BOOKING_SECRET_KEY_FILE,
)
from app.utils.lock import file_lock


class OTABookingIntegrationService:
    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec='seconds')

    @classmethod
    def _load_key(cls) -> bytes:
        if os.path.exists(OTA_BOOKING_SECRET_KEY_FILE):
            with open(OTA_BOOKING_SECRET_KEY_FILE, 'rb') as handle:
                return handle.read()
        key = Fernet.generate_key()
        with open(OTA_BOOKING_SECRET_KEY_FILE, 'wb') as handle:
            handle.write(key)
        return key

    @classmethod
    def _cipher(cls) -> Fernet:
        return Fernet(cls._load_key())

    @classmethod
    def _encrypt_secret(cls, raw_secret: str) -> str:
        if not raw_secret:
            return ''
        token = cls._cipher().encrypt(str(raw_secret).encode('utf-8'))
        return token.decode('utf-8')

    @classmethod
    def _decrypt_secret(cls, encrypted_secret: str) -> str:
        if not encrypted_secret:
            return ''
        try:
            return cls._cipher().decrypt(encrypted_secret.encode('utf-8')).decode('utf-8')
        except Exception:
            return ''

    @classmethod
    def _load_rows(cls) -> List[Dict[str, Any]]:
        if not os.path.exists(OTA_BOOKING_INTEGRATIONS_FILE):
            return []
        try:
            with open(OTA_BOOKING_INTEGRATIONS_FILE, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    @classmethod
    def _save_rows(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(OTA_BOOKING_INTEGRATIONS_FILE):
            with open(OTA_BOOKING_INTEGRATIONS_FILE, 'w', encoding='utf-8') as handle:
                json.dump(rows, handle, indent=4, ensure_ascii=False)

    @staticmethod
    def _normalize_status(value: Any) -> str:
        text = str(value or '').strip().lower()
        return 'active' if text in ('active', 'ativo', '1', 'true') else 'inactive'

    @staticmethod
    def _normalize_environment(value: Any) -> str:
        text = str(value or '').strip().lower()
        if text in ('producao', 'production', 'prod'):
            return 'producao'
        return 'teste'

    @staticmethod
    def _mask_secret(secret: str) -> str:
        if not secret:
            return ''
        if len(secret) <= 4:
            return '*' * len(secret)
        return f"{secret[:2]}{'*' * (len(secret) - 4)}{secret[-2:]}"

    @classmethod
    def _public_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        decrypted = cls._decrypt_secret(str(row.get('client_secret_encrypted') or ''))
        status = str(row.get('status') or 'inactive')
        last_test = str(row.get('ultimo_teste_conexao') or '')
        test_state = str(row.get('ultimo_teste_status') or '')
        visible_status = 'Inativa'
        if status == 'active':
            visible_status = 'Ativa'
        connection_status = 'Nunca testada'
        if last_test:
            connection_status = 'Conexão OK' if test_state == 'success' else 'Falha na conexão'
        current_status = 'Inativa'
        if status == 'active' and test_state == 'success':
            current_status = 'Operacional'
        elif status == 'active':
            current_status = 'Aguardando teste'
        payload = dict(row)
        payload.pop('client_secret_encrypted', None)
        payload['client_secret_masked'] = cls._mask_secret(decrypted)
        payload['status_label'] = visible_status
        payload['connection_status_label'] = connection_status
        payload['status_atual_label'] = current_status
        payload['tipo_autenticacao'] = 'token'
        return payload

    @classmethod
    def list_integrations(cls) -> List[Dict[str, Any]]:
        rows = cls._load_rows()
        rows.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)
        return [cls._public_row(row) for row in rows]

    @classmethod
    def get_integration(cls, integration_id: str, include_secret: bool = False) -> Optional[Dict[str, Any]]:
        rows = cls._load_rows()
        for row in rows:
            if str(row.get('id')) != str(integration_id):
                continue
            data = cls._public_row(row)
            if include_secret:
                data['client_secret'] = cls._decrypt_secret(str(row.get('client_secret_encrypted') or ''))
            return data
        return None

    @classmethod
    def upsert_integration(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        rows = cls._load_rows()
        now = cls._now_iso()
        integration_id = str(payload.get('id') or payload.get('integration_id') or '').strip()
        existing = None
        existing_index = -1
        for idx, row in enumerate(rows):
            if str(row.get('id')) == integration_id and integration_id:
                existing = row
                existing_index = idx
                break
        if not existing:
            existing = {
                'id': str(uuid.uuid4()),
                'created_at': now,
                'created_by': user,
                'ultima_autenticacao': '',
                'ultimo_teste_conexao': '',
                'ultimo_teste_status': '',
                'ultimo_teste_mensagem': '',
                'ultima_sincronizacao': '',
            }
        clean = dict(existing)
        clean['nome_ota'] = str(payload.get('nome_ota') or clean.get('nome_ota') or 'Booking.com').strip() or 'Booking.com'
        clean['status'] = cls._normalize_status(payload.get('status') or clean.get('status'))
        clean['ambiente'] = cls._normalize_environment(payload.get('ambiente') or clean.get('ambiente'))
        clean['tipo_autenticacao'] = 'token'
        clean['machine_account_name'] = str(payload.get('machine_account_name') or clean.get('machine_account_name') or '').strip()
        clean['client_id'] = str(payload.get('client_id') or clean.get('client_id') or '').strip()
        raw_secret = str(payload.get('client_secret') or '').strip()
        if raw_secret:
            clean['client_secret_encrypted'] = cls._encrypt_secret(raw_secret)
        else:
            clean['client_secret_encrypted'] = str(clean.get('client_secret_encrypted') or '')
        clean['property_id_booking'] = str(payload.get('property_id_booking') or clean.get('property_id_booking') or '').strip()
        clean['hotel_code_booking'] = str(payload.get('hotel_code_booking') or clean.get('hotel_code_booking') or '').strip()
        clean['base_url_supply'] = str(payload.get('base_url_supply') or clean.get('base_url_supply') or '').strip()
        clean['base_url_secure_supply'] = str(payload.get('base_url_secure_supply') or clean.get('base_url_secure_supply') or '').strip()
        clean['observacoes'] = str(payload.get('observacoes') or clean.get('observacoes') or '').strip()
        sync_value = str(payload.get('ultima_sincronizacao') or '').strip()
        if sync_value:
            clean['ultima_sincronizacao'] = sync_value
        clean['updated_at'] = now
        clean['updated_by'] = user
        if existing_index >= 0:
            rows[existing_index] = clean
            acao = 'Editou integração OTA Booking.com'
        else:
            rows.append(clean)
            acao = 'Criou integração OTA Booking.com'
        cls._save_rows(rows)
        LoggerService.log_acao(
            acao=acao,
            entidade='Integrações OTA',
            detalhes={
                'id': clean.get('id'),
                'nome_ota': clean.get('nome_ota'),
                'ambiente': clean.get('ambiente'),
                'status': clean.get('status'),
                'property_id_booking': clean.get('property_id_booking'),
                'hotel_code_booking': clean.get('hotel_code_booking'),
            },
            nivel_severidade='INFO',
            departamento_id='Administração',
            colaborador_id=user,
        )
        return cls._public_row(clean)

    @classmethod
    def register_auth_success(cls, integration_id: str, user: str, authenticated_at: Optional[str] = None) -> None:
        rows = cls._load_rows()
        when = str(authenticated_at or cls._now_iso())
        for idx, row in enumerate(rows):
            if str(row.get('id')) != str(integration_id):
                continue
            row['ultima_autenticacao'] = when
            row['updated_at'] = cls._now_iso()
            row['updated_by'] = user
            rows[idx] = row
            cls._save_rows(rows)
            break

    @classmethod
    def register_sync(cls, integration_id: str, user: str) -> Optional[Dict[str, Any]]:
        rows = cls._load_rows()
        for idx, row in enumerate(rows):
            if str(row.get('id')) != str(integration_id):
                continue
            row['ultima_sincronizacao'] = cls._now_iso()
            row['updated_at'] = cls._now_iso()
            row['updated_by'] = user
            rows[idx] = row
            cls._save_rows(rows)
            return cls._public_row(row)
        return None

    @classmethod
    def _update_test_result(
        cls,
        integration_id: str,
        success: bool,
        message: str,
        user: str,
        http_status: Optional[int] = None,
    ) -> None:
        rows = cls._load_rows()
        for idx, row in enumerate(rows):
            if str(row.get('id')) != str(integration_id):
                continue
            row['ultimo_teste_conexao'] = cls._now_iso()
            row['ultimo_teste_status'] = 'success' if success else 'failed'
            row['ultimo_teste_mensagem'] = str(message or '')
            if http_status is not None:
                row['ultimo_teste_http_status'] = int(http_status)
            row['updated_at'] = cls._now_iso()
            row['updated_by'] = user
            rows[idx] = row
            cls._save_rows(rows)
            break

    @classmethod
    def test_connection(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        from app.services.booking_connectivity_auth_service import BookingConnectivityAuthService
        integration_id = str(payload.get('integration_id') or payload.get('id') or '').strip()
        if not integration_id:
            message = 'Salve a integração antes de testar a autenticação.'
            return {'success': False, 'message': message}
        auth_result = BookingConnectivityAuthService.manual_auth_test(integration_id=integration_id, user=user)
        if not auth_result.get('success'):
            message = str(auth_result.get('message') or 'Falha ao autenticar com Booking.com.')
            cls._update_test_result(integration_id, success=False, message=message, user=user)
            return {'success': False, 'message': message}
        health_result = BookingConnectivityAuthService.health_check(integration_id=integration_id, user=user)
        if health_result.get('success'):
            cls._update_test_result(
                integration_id=integration_id,
                success=True,
                message=str(health_result.get('message') or 'Autenticação e health check OK.'),
                user=user,
                http_status=health_result.get('http_status'),
            )
            return {
                'success': True,
                'message': str(health_result.get('message') or 'Autenticação e health check OK.'),
                'http_status': health_result.get('http_status'),
                'expires_at': auth_result.get('expires_at'),
            }
        message = str(health_result.get('message') or 'Autenticação OK, mas health check falhou.')
        cls._update_test_result(
            integration_id=integration_id,
            success=False,
            message=message,
            user=user,
            http_status=health_result.get('http_status'),
        )
        return {
            'success': False,
            'message': message,
            'http_status': health_result.get('http_status'),
            'expires_at': auth_result.get('expires_at'),
        }
