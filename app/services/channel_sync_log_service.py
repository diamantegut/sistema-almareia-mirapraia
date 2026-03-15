from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import CHANNEL_MANAGER_SYNC_LOGS_FILE


class ChannelSyncLogService:
    TYPES = {
        'tarifa',
        'disponibilidade',
        'open_close',
        'cta',
        'ctd',
        'min_stay',
        'pacote',
        'autenticacao',
    }

    @classmethod
    def _load_json(cls, path: str, fallback: Any) -> Any:
        from app.services.revenue_management_service import RevenueManagementService

        loaded = RevenueManagementService._load_json(path, fallback)
        if isinstance(fallback, list):
            return loaded if isinstance(loaded, list) else []
        return loaded

    @classmethod
    def _save_json(cls, path: str, payload: Any) -> None:
        from app.services.revenue_management_service import RevenueManagementService

        with file_lock(path):
            RevenueManagementService._save_json(path, payload)

    @classmethod
    def _normalize_status(cls, status: Any) -> str:
        text = str(status or '').strip().lower()
        if text in ('sucesso', 'success', 'ok', 'enviado'):
            return 'sucesso'
        if text in ('pendente', 'queued', 'pending'):
            return 'pendente'
        return 'erro'

    @classmethod
    def _normalize_type(cls, value: Any) -> str:
        text = str(value or '').strip().lower()
        if text not in cls.TYPES:
            raise ValueError('Tipo de sincronização inválido.')
        return text

    @classmethod
    def append_log(
        cls,
        *,
        channel: str,
        sync_type: str,
        category: str,
        start_date: str,
        end_date: str,
        payload_sent: Any,
        response_received: Any,
        status: str,
        attempts: int,
        error_message: str,
        user: str,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec='seconds')
        normalized_type = cls._normalize_type(sync_type)
        row = {
            'id': str(uuid.uuid4()),
            'timestamp': now,
            'user': str(user or 'Sistema'),
            'channel': str(channel or '').strip(),
            'sync_type': normalized_type,
            'category': str(category or '').strip(),
            'period': {
                'start_date': str(start_date or ''),
                'end_date': str(end_date or start_date or ''),
            },
            'payload_sent': payload_sent if isinstance(payload_sent, (dict, list, str, int, float, bool, type(None))) else str(payload_sent),
            'response_received': response_received if isinstance(response_received, (dict, list, str, int, float, bool, type(None))) else str(response_received),
            'status': cls._normalize_status(status),
            'attempts': max(1, int(attempts or 1)),
            'error_message': str(error_message or '').strip(),
        }
        rows = cls._load_json(CHANNEL_MANAGER_SYNC_LOGS_FILE, [])
        rows.append(row)
        cls._save_json(CHANNEL_MANAGER_SYNC_LOGS_FILE, rows)
        return row

    @classmethod
    def list_logs(
        cls,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        sync_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_SYNC_LOGS_FILE, [])
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        channel_filter = str(channel or '').strip().lower()
        type_filter = str(sync_type or '').strip().lower()
        status_filter = cls._normalize_status(status) if status else ''
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
            if channel_filter and str(row.get('channel') or '').strip().lower() != channel_filter:
                continue
            if type_filter and str(row.get('sync_type') or '').strip().lower() != type_filter:
                continue
            if status_filter and str(row.get('status') or '').strip().lower() != status_filter:
                continue
            out.append(row)
        out.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
        return out
