import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.revenue_management_service import RevenueManagementService
from app.services.system_config_manager import REVENUE_PROMOTIONS_FILE, REVENUE_PROMOTIONS_LOGS_FILE


class RevenuePromotionService:
    DISCOUNT_TYPES = {'percent', 'daily_fixed', 'closed_rate'}
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
    def _load_promotions(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(REVENUE_PROMOTIONS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_promotions(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(REVENUE_PROMOTIONS_FILE):
            cls._save_json(REVENUE_PROMOTIONS_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(REVENUE_PROMOTIONS_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(REVENUE_PROMOTIONS_LOGS_FILE):
            cls._save_json(REVENUE_PROMOTIONS_LOGS_FILE, rows)

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
    def _append_log(cls, action: str, user: str, promotion_id: str, before: Any, after: Any) -> None:
        row = {
            'timestamp': cls._now_iso(),
            'action': action,
            'user': user,
            'promotion_id': promotion_id,
            'before': before,
            'after': after,
        }
        logs = cls._load_logs()
        logs.append(row)
        cls._save_logs(logs)
        LoggerService.log_acao(
            acao='Atualizou promoção de revenue',
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
            raise ValueError('Nome da promoção obrigatório')
        categories = cls._normalize_categories(payload.get('categories') or [])
        if not categories:
            raise ValueError('Selecione ao menos uma categoria')
        period = PeriodSelectorService.parse_payload(payload.get('period') or {})
        if not period.get('dates'):
            raise ValueError('Período inválido')
        discount_type = cls._normalize_text(payload.get('discount_type'))
        if discount_type not in cls.DISCOUNT_TYPES:
            raise ValueError('Tipo de desconto inválido')
        try:
            discount_value = float(payload.get('discount_value') or 0)
        except Exception:
            discount_value = 0.0
        if discount_value <= 0:
            raise ValueError('Valor do desconto deve ser maior que zero')
        status = cls._normalize_text(payload.get('status') or 'active')
        if status not in cls.STATUS_TYPES:
            status = 'inactive'
        try:
            priority = int(payload.get('priority') or 100)
        except Exception:
            priority = 100
        return {
            'name': name,
            'categories': categories,
            'period': {
                'start_date': period['start_date'],
                'end_date': period['end_date'],
                'weekdays': period['weekdays'],
            },
            'discount_type': discount_type,
            'discount_value': round(float(discount_value), 2),
            'combinable_with_packages': bool(payload.get('combinable_with_packages')),
            'apply_before_dynamic': bool(payload.get('apply_before_dynamic', True)),
            'priority': priority,
            'status': status,
        }

    @classmethod
    def list_promotions(cls, status: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_promotions()
        status_norm = cls._normalize_text(status) if status else ''
        out = []
        for row in rows:
            if status_norm and cls._normalize_text(row.get('status')) != status_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: (int(item.get('priority') or 100), item.get('updated_at') or '' ))
        return out

    @classmethod
    def create_promotion(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
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
        rows = cls._load_promotions()
        rows.append(row)
        cls._save_promotions(rows)
        cls._append_log('create', user, row['id'], None, row)
        return row

    @classmethod
    def update_promotion(cls, promotion_id: str, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        pid = str(promotion_id or '').strip()
        rows = cls._load_promotions()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == pid), None)
        if idx is None:
            raise ValueError('Promoção não encontrada')
        before = rows[idx]
        body = cls._validate_payload(payload or {})
        updated = {
            **before,
            **body,
            'id': pid,
            'updated_at': cls._now_iso(),
            'updated_by': user,
        }
        rows[idx] = updated
        cls._save_promotions(rows)
        cls._append_log('update', user, pid, before, updated)
        return updated

    @classmethod
    def delete_promotion(cls, promotion_id: str, user: str) -> Dict[str, Any]:
        pid = str(promotion_id or '').strip()
        rows = cls._load_promotions()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == pid), None)
        if idx is None:
            raise ValueError('Promoção não encontrada')
        before = rows[idx]
        rows.pop(idx)
        cls._save_promotions(rows)
        cls._append_log('delete', user, pid, before, None)
        return {'deleted': True, 'id': pid}

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
    def _nights(cls, checkin: str, checkout: str) -> int:
        cin = PeriodSelectorService.parse_date(checkin).date()
        cout = PeriodSelectorService.parse_date(checkout).date()
        return max((cout - cin).days, 1)

    @classmethod
    def _category_limits(cls, category: str) -> Dict[str, float]:
        rules = RevenueManagementService._load_rules()
        bucket = RevenueManagementService._normalize_category(category)
        row = rules.get(bucket) or {}
        return {
            'min_bar': float(row.get('min_bar') or 0),
            'max_bar': float(row.get('max_bar') or 999999),
            'base_bar': float(row.get('base_bar') or 0),
        }

    @classmethod
    def preview_price(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
        base_total: float,
        package_applied: bool = False,
    ) -> Dict[str, Any]:
        nights = cls._nights(checkin, checkout)
        base_total_value = round(float(base_total or 0), 2)
        if base_total_value <= 0:
            limits = cls._category_limits(category)
            base_total_value = round(limits['base_bar'] * nights, 2)
        stay_dates = set(PeriodSelectorService.expand_dates(checkin, checkout, []))
        category_norm = cls._normalize_text(category)
        candidates = []
        for row in cls.list_promotions(status='active'):
            rule_categories = {cls._normalize_text(c) for c in row.get('categories') or []}
            if category_norm not in rule_categories:
                continue
            if package_applied and not bool(row.get('combinable_with_packages')):
                continue
            period = row.get('period') or {}
            promo_dates = set(PeriodSelectorService.expand_dates(period.get('start_date'), period.get('end_date'), period.get('weekdays') or []))
            if not any(d in promo_dates for d in stay_dates):
                continue
            candidates.append(row)
        if not candidates:
            return {'applied': False, 'final_total': base_total_value, 'base_total': base_total_value, 'promotion': None}
        chosen = sorted(candidates, key=lambda item: (int(item.get('priority') or 100), item.get('updated_at') or ''))[0]
        discount_type = str(chosen.get('discount_type') or '')
        discount_value = float(chosen.get('discount_value') or 0)
        if discount_type == 'percent':
            final_total = base_total_value * (1 - (max(0.0, min(100.0, discount_value)) / 100.0))
        else:
            final_total = discount_value * nights
        limits = cls._category_limits(category)
        per_night = final_total / max(nights, 1)
        per_night = max(limits['min_bar'], min(limits['max_bar'], per_night))
        clamped_total = round(per_night * nights, 2)
        return {
            'applied': True,
            'base_total': base_total_value,
            'final_total': clamped_total,
            'discount_value': round(base_total_value - clamped_total, 2),
            'promotion': {
                'id': chosen.get('id'),
                'name': chosen.get('name'),
                'priority': chosen.get('priority'),
                'discount_type': chosen.get('discount_type'),
                'discount_value': chosen.get('discount_value'),
                'combinable_with_packages': bool(chosen.get('combinable_with_packages')),
                'apply_before_dynamic': bool(chosen.get('apply_before_dynamic', True)),
            },
            'limits': limits,
        }
