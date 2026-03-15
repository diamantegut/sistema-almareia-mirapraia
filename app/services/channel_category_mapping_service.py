from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.services.cashier_service import file_lock
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.logger_service import LoggerService
from app.services.system_config_manager import (
    CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE,
    CHANNEL_MANAGER_CATEGORY_MAPPINGS_LOGS_FILE,
)


class ChannelCategoryMappingService:
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
    def _internal_categories(cls) -> List[Dict[str, str]]:
        from app.services.revenue_management_service import RevenueManagementService

        options = RevenueManagementService.BOOKING_CATEGORY_OPTIONS
        return [{'key': str(item.get('key') or ''), 'label': str(item.get('label') or item.get('key') or '')} for item in options]

    @classmethod
    def _normalize_channel(cls, channel_name: Any) -> str:
        return ChannelInventoryControlService._normalize_channel(channel_name)

    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        return 'active' if str(value or '').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo') else 'inactive'

    @classmethod
    def _load_rows(cls) -> List[Dict[str, Any]]:
        rows = cls._load_json(CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE, [])
        out: List[Dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            out.append({
                'id': str(row.get('id') or str(uuid.uuid4())),
                'channel_name': cls._normalize_channel(row.get('channel_name')),
                'category': cls._normalize_category(row.get('category')),
                'external_room_type_id': str(row.get('external_room_type_id') or row.get('room_type_id_booking') or '').strip(),
                'external_rate_plan_id': str(row.get('external_rate_plan_id') or row.get('rate_plan_id_booking') or '').strip(),
                'status': cls._normalize_status(row.get('status')),
                'updated_at': str(row.get('updated_at') or ''),
                'updated_by': str(row.get('updated_by') or row.get('user') or ''),
            })
        return out

    @classmethod
    def _append_log(cls, item: Dict[str, Any]) -> None:
        logs = cls._load_json(CHANNEL_MANAGER_CATEGORY_MAPPINGS_LOGS_FILE, [])
        logs.append(item)
        cls._save_json(CHANNEL_MANAGER_CATEGORY_MAPPINGS_LOGS_FILE, logs)

    @classmethod
    def list_mappings(cls, *, channel_name: Optional[str] = None) -> Dict[str, Any]:
        from app.services.channel_manager_service import ChannelManagerService

        rows = cls._load_rows()
        channels = ChannelManagerService.list_channels()
        channel_names = [str(item.get('name') or '') for item in channels]
        if channel_name:
            wanted = cls._normalize_channel(channel_name)
            channel_names = [name for name in channel_names if cls._normalize_channel(name) == wanted]
            if not channel_names:
                channel_names = [wanted]
        by_channel: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for row in rows:
            channel = str(row.get('channel_name') or '')
            category = str(row.get('category') or '')
            by_channel.setdefault(channel, {}).setdefault(category, []).append(row)
        options = cls._internal_categories()
        channels_payload: List[Dict[str, Any]] = []
        missing_summary: Dict[str, List[str]] = {}
        for ch_name in channel_names:
            category_rows = by_channel.get(ch_name, {})
            category_items: List[Dict[str, Any]] = []
            missing_labels: List[str] = []
            for option in options:
                key = option['key']
                label = option['label']
                mappings = category_rows.get(key, [])
                valid = [
                    row for row in mappings
                    if str(row.get('status') or '') == 'active'
                    and str(row.get('external_room_type_id') or '').strip()
                    and str(row.get('external_rate_plan_id') or '').strip()
                ]
                incomplete = [
                    row for row in mappings
                    if not str(row.get('external_room_type_id') or '').strip()
                    or not str(row.get('external_rate_plan_id') or '').strip()
                ]
                if not valid:
                    missing_labels.append(label)
                category_items.append({
                    'category': key,
                    'category_label': label,
                    'mappings': mappings,
                    'active_complete_count': len(valid),
                    'incomplete_count': len(incomplete),
                    'missing_mapping': len(valid) == 0,
                })
            missing_summary[ch_name] = missing_labels
            channels_payload.append({
                'channel_name': ch_name,
                'items': category_items,
                'missing_categories': missing_labels,
                'is_complete': len(missing_labels) == 0,
            })
        return {
            'channels': channels_payload,
            'missing_by_channel': missing_summary,
        }

    @classmethod
    def save_mappings(cls, *, payload: Dict[str, Any], user: str, reason: str) -> Dict[str, Any]:
        clean_reason = str(reason or '').strip()
        if len(clean_reason) < 3:
            raise ValueError('Motivo obrigatório para salvar mapeamento de categorias por canal.')
        channels_input = payload.get('channels') if isinstance(payload, dict) else []
        if not isinstance(channels_input, list):
            channels_input = []
        out_rows: List[Dict[str, Any]] = []
        now = datetime.now().isoformat(timespec='seconds')
        for channel_item in channels_input:
            if not isinstance(channel_item, dict):
                continue
            channel_name = cls._normalize_channel(channel_item.get('channel_name'))
            items = channel_item.get('items') if isinstance(channel_item.get('items'), list) else []
            for category_item in items:
                if not isinstance(category_item, dict):
                    continue
                category = cls._normalize_category(category_item.get('category'))
                mappings = category_item.get('mappings') if isinstance(category_item.get('mappings'), list) else []
                for mapping in mappings:
                    if not isinstance(mapping, dict):
                        continue
                    out_rows.append({
                        'id': str(mapping.get('id') or str(uuid.uuid4())),
                        'channel_name': channel_name,
                        'category': category,
                        'external_room_type_id': str(mapping.get('external_room_type_id') or mapping.get('room_type_id_booking') or '').strip(),
                        'external_rate_plan_id': str(mapping.get('external_rate_plan_id') or mapping.get('rate_plan_id_booking') or '').strip(),
                        'status': cls._normalize_status(mapping.get('status', 'active')),
                        'updated_at': now,
                        'updated_by': user,
                    })
        cls._save_json(CHANNEL_MANAGER_CATEGORY_MAPPINGS_FILE, out_rows)
        snapshot = cls.list_mappings()
        for channel_name, missing in (snapshot.get('missing_by_channel') or {}).items():
            cls._append_log({
                'id': str(uuid.uuid4()),
                'timestamp': now,
                'user': user,
                'action': 'save_channel_category_mapping',
                'reason': clean_reason,
                'channel_name': channel_name,
                'missing_categories': missing,
            })
        LoggerService.log_acao(
            acao='Atualizou mapeamento de categorias por canal',
            entidade='Channel Manager',
            detalhes={'reason': clean_reason, 'rows': len(out_rows)},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return snapshot

    @classmethod
    def resolve_rate_mappings_for_channel_category(
        cls,
        *,
        channel_name: str,
        category: str,
        required_rate_plan: str = '',
    ) -> List[Dict[str, Any]]:
        normalized_channel = cls._normalize_channel(channel_name)
        normalized_category = cls._normalize_category(category)
        wanted_rate_plan = str(required_rate_plan or '').strip()
        rows = cls._load_rows()
        out = [
            row for row in rows
            if str(row.get('channel_name') or '') == normalized_channel
            and str(row.get('category') or '') == normalized_category
            and str(row.get('status') or '') == 'active'
            and str(row.get('external_room_type_id') or '').strip()
            and str(row.get('external_rate_plan_id') or '').strip()
        ]
        if wanted_rate_plan:
            out = [row for row in out if str(row.get('external_rate_plan_id') or '') == wanted_rate_plan]
        return out

    @classmethod
    def assert_channel_mapping_complete_for_rows(
        cls,
        *,
        channel_name: str,
        calendar_rows: List[Dict[str, Any]],
        required_rate_plan: str = '',
    ) -> None:
        missing: List[str] = []
        for row in (calendar_rows or []):
            category = cls._normalize_category(row.get('category'))
            matches = cls.resolve_rate_mappings_for_channel_category(
                channel_name=channel_name,
                category=category,
                required_rate_plan=required_rate_plan,
            )
            if not matches:
                label = next((item['label'] for item in cls._internal_categories() if item['key'] == category), category)
                missing.append(label)
        if missing:
            raise ValueError(f"Mapeamento de categorias incompleto para canal {cls._normalize_channel(channel_name)}: {', '.join(sorted(set(missing)))}.")
