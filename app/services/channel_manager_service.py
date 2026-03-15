from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_CHANNELS_FILE,
    CHANNEL_MANAGER_CHANNELS_LOGS_FILE,
)


class ChannelManagerService:
    COMMERCIAL_MODELS = {
        'direta_sem_comissao',
        'comissao_percentual',
        'net_rate',
        'tarifa_manual',
    }
    CHANNEL_TYPES = {
        'direto',
        'ota',
        'motor',
        'recepcao',
        'parceiro',
    }
    DEFAULT_CHANNELS = [
        {
            'name': 'Venda Direta',
            'channel_type': 'direto',
            'active': True,
            'distribution_priority': 10,
            'commercial_model': 'direta_sem_comissao',
            'default_commission': 0.0,
            'allows_custom_rate': False,
            'allows_custom_restrictions': True,
            'allows_allotment': True,
            'notes': '',
        },
        {
            'name': 'Booking.com',
            'channel_type': 'ota',
            'active': True,
            'distribution_priority': 20,
            'commercial_model': 'comissao_percentual',
            'default_commission': 15.0,
            'allows_custom_rate': True,
            'allows_custom_restrictions': True,
            'allows_allotment': True,
            'notes': '',
        },
        {
            'name': 'Expedia',
            'channel_type': 'ota',
            'active': True,
            'distribution_priority': 30,
            'commercial_model': 'comissao_percentual',
            'default_commission': 15.0,
            'allows_custom_rate': True,
            'allows_custom_restrictions': True,
            'allows_allotment': True,
            'notes': '',
        },
        {
            'name': 'Motor de Reservas',
            'channel_type': 'motor',
            'active': True,
            'distribution_priority': 15,
            'commercial_model': 'direta_sem_comissao',
            'default_commission': 0.0,
            'allows_custom_rate': True,
            'allows_custom_restrictions': True,
            'allows_allotment': True,
            'notes': '',
        },
        {
            'name': 'Recepção',
            'channel_type': 'recepcao',
            'active': True,
            'distribution_priority': 5,
            'commercial_model': 'direta_sem_comissao',
            'default_commission': 0.0,
            'allows_custom_rate': False,
            'allows_custom_restrictions': True,
            'allows_allotment': True,
            'notes': '',
        },
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
    def _normalize_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or '').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo')

    @classmethod
    def _normalize_channel(cls, row: Dict[str, Any], *, existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        name = str(row.get('name') or '').strip()
        if len(name) < 2:
            raise ValueError('Nome do canal é obrigatório.')
        channel_type = str(row.get('channel_type') or '').strip().lower()
        if channel_type not in cls.CHANNEL_TYPES:
            raise ValueError('Tipo de canal inválido.')
        commercial_model = str(row.get('commercial_model') or '').strip().lower()
        if commercial_model not in cls.COMMERCIAL_MODELS:
            raise ValueError('Modelo comercial inválido.')
        try:
            commission = round(max(0.0, float(row.get('default_commission') or 0.0)), 2)
        except Exception:
            commission = 0.0
        if commercial_model in ('direta_sem_comissao',) and commission != 0:
            commission = 0.0
        if commercial_model == 'comissao_percentual' and commission > 100:
            raise ValueError('Comissão percentual não pode ser maior que 100.')
        try:
            priority = int(row.get('distribution_priority') or 999)
        except Exception:
            priority = 999
        now = datetime.now().isoformat(timespec='seconds')
        return {
            'id': str(row.get('id') or (existing or {}).get('id') or str(uuid.uuid4())),
            'name': name,
            'channel_type': channel_type,
            'active': cls._normalize_bool(row.get('active', (existing or {}).get('active', True))),
            'distribution_priority': max(1, priority),
            'commercial_model': commercial_model,
            'default_commission': commission,
            'allows_custom_rate': cls._normalize_bool(row.get('allows_custom_rate', (existing or {}).get('allows_custom_rate', False))),
            'allows_custom_restrictions': cls._normalize_bool(row.get('allows_custom_restrictions', (existing or {}).get('allows_custom_restrictions', True))),
            'allows_allotment': cls._normalize_bool(row.get('allows_allotment', (existing or {}).get('allows_allotment', True))),
            'notes': str(row.get('notes') or '').strip(),
            'created_at': str((existing or {}).get('created_at') or now),
            'updated_at': now,
            'updated_by': str(row.get('updated_by') or (existing or {}).get('updated_by') or 'Sistema'),
        }

    @classmethod
    def _append_log(cls, item: Dict[str, Any]) -> None:
        rows = cls._load_json(CHANNEL_MANAGER_CHANNELS_LOGS_FILE, [])
        rows.append(item)
        cls._save_json(CHANNEL_MANAGER_CHANNELS_LOGS_FILE, rows)

    @classmethod
    def _ensure_defaults(cls) -> List[Dict[str, Any]]:
        existing = cls._load_json(CHANNEL_MANAGER_CHANNELS_FILE, [])
        if isinstance(existing, list) and existing:
            return existing
        now = datetime.now().isoformat(timespec='seconds')
        rows = []
        for item in cls.DEFAULT_CHANNELS:
            rows.append({
                **item,
                'id': str(uuid.uuid4()),
                'created_at': now,
                'updated_at': now,
                'updated_by': 'Sistema',
            })
        cls._save_json(CHANNEL_MANAGER_CHANNELS_FILE, rows)
        return rows

    @classmethod
    def list_channels(cls) -> List[Dict[str, Any]]:
        rows = cls._ensure_defaults()
        out = [row for row in rows if isinstance(row, dict)]
        out.sort(key=lambda item: (int(item.get('distribution_priority') or 999), str(item.get('name') or '').lower()))
        return out

    @classmethod
    def save_channels(cls, *, items: List[Dict[str, Any]], user: str, reason: str) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para salvar canais.')
        current = cls.list_channels()
        current_by_id = {str(item.get('id') or ''): item for item in current}
        payload_items = items if isinstance(items, list) else []
        normalized_rows: List[Dict[str, Any]] = []
        for item in payload_items:
            if not isinstance(item, dict):
                continue
            row_id = str(item.get('id') or '').strip()
            existing = current_by_id.get(row_id)
            merged = {**(existing or {}), **item, 'updated_by': user}
            normalized = cls._normalize_channel(merged, existing=existing)
            normalized_rows.append(normalized)
            cls._append_log({
                'id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'user': user,
                'action': 'upsert_channel',
                'reason': clean_reason,
                'channel_id': normalized.get('id'),
                'channel_name': normalized.get('name'),
                'before': existing or {},
                'after': normalized,
            })
        cls._save_json(CHANNEL_MANAGER_CHANNELS_FILE, normalized_rows)
        LoggerService.log_acao(
            acao='Atualizou cadastro de canais de venda',
            entidade='Channel Manager',
            detalhes={'updated': len(normalized_rows), 'reason': clean_reason},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'items': cls.list_channels(),
            'count': len(normalized_rows),
        }

    @classmethod
    def list_channel_logs(cls, *, limit: int = 200) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_CHANNELS_LOGS_FILE, [])
        out = [row for row in rows if isinstance(row, dict)]
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out[:max(1, int(limit))]
