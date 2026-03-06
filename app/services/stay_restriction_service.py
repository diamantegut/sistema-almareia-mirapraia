import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.system_config_manager import STAY_RESTRICTIONS_FILE, STAY_RESTRICTIONS_LOGS_FILE


class StayRestrictionService:
    STATUS_TYPES = {'active', 'inactive'}

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or '').strip().lower()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat()

    @classmethod
    def _load_json(cls, path: str, fallback: Any) -> Any:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception:
            return fallback

    @classmethod
    def _save_json(cls, path: str, payload: Any) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    @classmethod
    def _load_rules(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(STAY_RESTRICTIONS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_rules(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(STAY_RESTRICTIONS_FILE):
            cls._save_json(STAY_RESTRICTIONS_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(STAY_RESTRICTIONS_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(STAY_RESTRICTIONS_LOGS_FILE):
            cls._save_json(STAY_RESTRICTIONS_LOGS_FILE, rows)

    @classmethod
    def _normalize_categories(cls, categories: List[Any]) -> List[str]:
        out = []
        seen = set()
        for item in categories or []:
            text = str(item or '').strip()
            if not text:
                continue
            key = cls._normalize_text(text)
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    @classmethod
    def _normalize_package_ids(cls, package_ids: List[Any]) -> List[str]:
        out = []
        seen = set()
        for item in package_ids or []:
            text = str(item or '').strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    @classmethod
    def _append_log(cls, action: str, user: str, rule_id: str, before: Any, after: Any) -> None:
        row = {
            'timestamp': cls._now_iso(),
            'action': action,
            'user': user,
            'rule_id': rule_id,
            'before': before,
            'after': after,
        }
        logs = cls._load_logs()
        logs.append(row)
        cls._save_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou restrição de estadia',
            entidade='Revenue Management',
            detalhes=row,
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )

    @classmethod
    def _validate_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get('name') or '').strip()
        if len(name) < 3:
            raise ValueError('Nome da regra obrigatório')
        categories = cls._normalize_categories(payload.get('categories') or [])
        package_ids = cls._normalize_package_ids(payload.get('package_ids') or [])
        if not categories and not package_ids:
            raise ValueError('Selecione ao menos uma categoria ou pacote')
        period = PeriodSelectorService.parse_payload(payload.get('period') or {})
        if not period.get('dates'):
            raise ValueError('Período inválido')
        try:
            min_nights = int(payload.get('min_nights') or 0)
        except Exception:
            min_nights = 0
        if min_nights < 1:
            raise ValueError('Mínimo de noites deve ser maior que zero')
        max_raw = payload.get('max_nights')
        max_nights = None
        if max_raw not in (None, ''):
            try:
                max_nights = int(max_raw)
            except Exception:
                max_nights = None
            if max_nights is not None and max_nights < min_nights:
                raise ValueError('Máximo de noites deve ser maior ou igual ao mínimo')
        status = cls._normalize_text(payload.get('status') or 'active')
        if status not in cls.STATUS_TYPES:
            status = 'inactive'
        return {
            'name': name,
            'categories': categories,
            'package_ids': package_ids,
            'period': {
                'start_date': period['start_date'],
                'end_date': period['end_date'],
                'weekdays': period['weekdays'],
            },
            'min_nights': min_nights,
            'max_nights': max_nights,
            'status': status,
        }

    @classmethod
    def list_rules(cls, status: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_rules()
        status_norm = cls._normalize_text(status) if status else ''
        out = []
        for row in rows:
            if status_norm and cls._normalize_text(row.get('status')) != status_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
        return out

    @classmethod
    def create_rule(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        body = cls._validate_payload(payload or {})
        now = cls._now_iso()
        row = {
            'id': str(uuid.uuid4()),
            **body,
            'created_at': now,
            'updated_at': now,
            'created_by': user,
            'updated_by': user,
        }
        rows = cls._load_rules()
        rows.append(row)
        cls._save_rules(rows)
        cls._append_log('create', user, row['id'], None, row)
        return row

    @classmethod
    def update_rule(cls, rule_id: str, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        rid = str(rule_id or '').strip()
        rows = cls._load_rules()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == rid), None)
        if idx is None:
            raise ValueError('Regra não encontrada')
        before = rows[idx]
        body = cls._validate_payload(payload or {})
        updated = {
            **before,
            **body,
            'updated_at': cls._now_iso(),
            'updated_by': user,
            'id': rid,
        }
        rows[idx] = updated
        cls._save_rules(rows)
        cls._append_log('update', user, rid, before, updated)
        return updated

    @classmethod
    def delete_rule(cls, rule_id: str, user: str) -> Dict[str, Any]:
        rid = str(rule_id or '').strip()
        rows = cls._load_rules()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == rid), None)
        if idx is None:
            raise ValueError('Regra não encontrada')
        before = rows[idx]
        rows.pop(idx)
        cls._save_rules(rows)
        cls._append_log('delete', user, rid, before, None)
        return {'deleted': True, 'id': rid}

    @classmethod
    def list_logs(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, user: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_logs()
        start = PeriodSelectorService.parse_date(start_date).date() if start_date else None
        end = PeriodSelectorService.parse_date(end_date).date() if end_date else None
        user_norm = cls._normalize_text(user)
        out = []
        for row in rows:
            ts = str(row.get('timestamp') or '')
            row_user = cls._normalize_text(row.get('user'))
            try:
                day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if start and day < start:
                continue
            if end and day > end:
                continue
            if user_norm and user_norm not in row_user:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return out

    @classmethod
    def _stay_nights(cls, checkin: str, checkout: str) -> List[str]:
        cin = PeriodSelectorService.parse_date(checkin).date()
        cout = PeriodSelectorService.parse_date(checkout).date()
        if cout <= cin:
            raise ValueError('Período inválido')
        out = []
        current = cin
        while current < cout:
            out.append(current.isoformat())
            current = current.fromordinal(current.toordinal() + 1)
        return out

    @classmethod
    def validate_stay(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
        package_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        nights_rows = cls._stay_nights(checkin, checkout)
        nights = len(nights_rows)
        category_norm = cls._normalize_text(category)
        package_id_text = str(package_id or '').strip()
        applicable = []
        for row in cls.list_rules(status='active'):
            rule_categories = {cls._normalize_text(c) for c in row.get('categories') or []}
            rule_package_ids = {str(pid) for pid in row.get('package_ids') or []}
            category_match = bool(rule_categories and category_norm in rule_categories)
            package_match = bool(package_id_text and rule_package_ids and package_id_text in rule_package_ids)
            if not category_match and not package_match:
                continue
            period = row.get('period') or {}
            period_days = set(
                PeriodSelectorService.expand_dates(
                    period.get('start_date'),
                    period.get('end_date'),
                    period.get('weekdays') or [],
                )
            )
            if not any(day in period_days for day in nights_rows):
                continue
            applicable.append(row)

        violations = []
        for row in applicable:
            min_nights = int(row.get('min_nights') or 1)
            max_nights = row.get('max_nights')
            if nights < min_nights:
                violations.append({
                    'rule': row,
                    'message': f'Para este período, a estadia mínima é de {min_nights} noites.',
                })
                continue
            if max_nights is not None and nights > int(max_nights):
                violations.append({
                    'rule': row,
                    'message': f'Para este período, a estadia máxima é de {int(max_nights)} noites.',
                })
        if violations:
            selected = sorted(violations, key=lambda item: int(item['rule'].get('min_nights') or 0), reverse=True)[0]
            return {'valid': False, 'message': selected['message'], 'rule': selected['rule'], 'nights': nights}
        return {'valid': True, 'message': '', 'rule': None, 'nights': nights, 'rules_checked': len(applicable)}
