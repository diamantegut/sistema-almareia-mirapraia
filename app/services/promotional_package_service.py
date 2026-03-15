import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.period_selector_service import PeriodSelectorService
from app.services.revenue_management_service import RevenueManagementService
from app.services.system_config_manager import PROMOTIONAL_PACKAGES_FILE, PROMOTIONAL_PACKAGES_LOGS_FILE


class PromotionalPackageService:
    PRICE_TYPES = {'package_fixed', 'percent_discount', 'daily_fixed'}
    STATUS_TYPES = {'active', 'inactive'}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or '').strip().lower()

    @classmethod
    def _normalize_categories(cls, categories: List[Any]) -> List[str]:
        out: List[str] = []
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
    def _load_packages(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(PROMOTIONAL_PACKAGES_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_packages(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(PROMOTIONAL_PACKAGES_FILE):
            cls._save_json(PROMOTIONAL_PACKAGES_FILE, rows)

    @classmethod
    def _load_logs(cls) -> List[Dict[str, Any]]:
        data = cls._load_json(PROMOTIONAL_PACKAGES_LOGS_FILE, [])
        return data if isinstance(data, list) else []

    @classmethod
    def _save_logs(cls, rows: List[Dict[str, Any]]) -> None:
        with file_lock(PROMOTIONAL_PACKAGES_LOGS_FILE):
            cls._save_json(PROMOTIONAL_PACKAGES_LOGS_FILE, rows)

    @classmethod
    def _validate_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get('name') or '').strip()
        if len(name) < 3:
            raise ValueError('Nome do pacote obrigatório')
        description = str(payload.get('description') or '').strip()
        categories = cls._normalize_categories(payload.get('categories') or [])
        if not categories:
            raise ValueError('Selecione ao menos uma categoria')
        price_type = cls._normalize_text(payload.get('price_type'))
        if price_type not in cls.PRICE_TYPES:
            raise ValueError('Tipo de preço inválido')
        try:
            special_price = float(payload.get('special_price') or 0)
        except Exception:
            special_price = 0.0
        if special_price <= 0:
            raise ValueError('Preço especial deve ser maior que zero')
        status = cls._normalize_text(payload.get('status') or 'active')
        if status not in cls.STATUS_TYPES:
            status = 'inactive'
        sale_period = PeriodSelectorService.parse_payload(payload.get('sale_period') or {})
        stay_period = PeriodSelectorService.parse_payload(payload.get('stay_period') or {})
        if not sale_period.get('dates'):
            raise ValueError('Período de venda inválido')
        if not stay_period.get('dates'):
            raise ValueError('Período de hospedagem inválido')
        return {
            'name': name,
            'description': description,
            'categories': categories,
            'price_type': price_type,
            'special_price': round(float(special_price), 2),
            'required_for_sale': bool(payload.get('required_for_sale')),
            'status': status,
            'sale_period': {
                'start_date': sale_period['start_date'],
                'end_date': sale_period['end_date'],
                'weekdays': sale_period['weekdays'],
            },
            'stay_period': {
                'start_date': stay_period['start_date'],
                'end_date': stay_period['end_date'],
                'weekdays': stay_period['weekdays'],
            },
        }

    @classmethod
    def _append_log(cls, action: str, user: str, package_id: str, before: Any, after: Any) -> None:
        log_row = {
            'timestamp': cls._now_iso(),
            'user': user,
            'action': action,
            'package_id': package_id,
            'before': before,
            'after': after,
        }
        logs = cls._load_logs()
        logs.append(log_row)
        cls._save_logs(logs)
        LoggerService.log_acao(
            acao='Pacote promocional atualizado',
            entidade='Revenue Management',
            detalhes=log_row,
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )

    @classmethod
    def list_packages(cls, status: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = cls._load_packages()
        status_norm = cls._normalize_text(status) if status else ''
        out = []
        for row in rows:
            if status_norm and cls._normalize_text(row.get('status')) != status_norm:
                continue
            out.append(row)
        out.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
        return out

    @classmethod
    def create_package(cls, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
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
        rows = cls._load_packages()
        rows.append(row)
        cls._save_packages(rows)
        cls._append_log('create', user, row['id'], None, row)
        return row

    @classmethod
    def update_package(cls, package_id: str, payload: Dict[str, Any], user: str) -> Dict[str, Any]:
        pid = str(package_id or '').strip()
        if not pid:
            raise ValueError('Pacote inválido')
        rows = cls._load_packages()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == pid), None)
        if idx is None:
            raise ValueError('Pacote não encontrado')
        before = rows[idx]
        body = cls._validate_payload(payload or {})
        now = cls._now_iso()
        updated = {
            **before,
            **body,
            'id': pid,
            'updated_at': now,
            'updated_by': user,
        }
        rows[idx] = updated
        cls._save_packages(rows)
        cls._append_log('update', user, pid, before, updated)
        return updated

    @classmethod
    def delete_package(cls, package_id: str, user: str) -> Dict[str, Any]:
        pid = str(package_id or '').strip()
        rows = cls._load_packages()
        idx = next((i for i, item in enumerate(rows) if str(item.get('id')) == pid), None)
        if idx is None:
            raise ValueError('Pacote não encontrado')
        before = rows[idx]
        rows.pop(idx)
        cls._save_packages(rows)
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
    def _category_bucket(cls, category: str) -> str:
        return RevenueManagementService._normalize_category(category)

    @classmethod
    def _fallback_base_total(cls, category: str, nights: int) -> float:
        rules = RevenueManagementService._load_rules()
        bucket = cls._category_bucket(category)
        base_daily = float((rules.get(bucket) or {}).get('base_bar') or 0)
        return round(base_daily * max(nights, 1), 2)

    @classmethod
    def _category_matches(cls, package_categories: List[str], category: str) -> bool:
        wanted = cls._normalize_text(category)
        normalized = {cls._normalize_text(c) for c in package_categories or []}
        return wanted in normalized

    @classmethod
    def _stay_nights(cls, checkin: str, checkout: str) -> List[str]:
        cin = PeriodSelectorService.parse_date(checkin).date()
        cout = PeriodSelectorService.parse_date(checkout).date()
        if cout <= cin:
            raise ValueError('Período de hospedagem inválido')
        out = []
        current = cin
        while current < cout:
            out.append(current.isoformat())
            current += timedelta(days=1)
        return out

    @classmethod
    def _package_total(cls, price_type: str, special_price: float, base_total: float, nights: int) -> float:
        if price_type == 'package_fixed':
            return round(special_price, 2)
        if price_type == 'daily_fixed':
            return round(special_price * max(nights, 1), 2)
        discount = max(0.0, min(100.0, special_price))
        return round(max(0.0, base_total * (1 - (discount / 100.0))), 2)

    @classmethod
    def _eligible_matches(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
        sale_date: Optional[str],
        base_total: Optional[float],
    ) -> Dict[str, Any]:
        nights_rows = cls._stay_nights(checkin, checkout)
        nights = len(nights_rows)
        sale_day = PeriodSelectorService.parse_date(sale_date or datetime.now().strftime('%Y-%m-%d')).date().isoformat()
        normal_total = round(float(base_total), 2) if (base_total is not None and float(base_total) > 0) else cls._fallback_base_total(category, nights)
        matches: List[Dict[str, Any]] = []
        required_context_packages: List[Dict[str, Any]] = []
        for pack in cls.list_packages(status='active'):
            if not cls._category_matches(pack.get('categories') or [], category):
                continue
            sale_period = pack.get('sale_period') or {}
            stay_period = pack.get('stay_period') or {}
            sale_days = set(PeriodSelectorService.expand_dates(sale_period.get('start_date'), sale_period.get('end_date'), sale_period.get('weekdays') or []))
            if sale_day not in sale_days:
                continue
            allowed_stay_days = set(PeriodSelectorService.expand_dates(stay_period.get('start_date'), stay_period.get('end_date'), stay_period.get('weekdays') or []))
            if bool(pack.get('required_for_sale')) and any(day in allowed_stay_days for day in nights_rows):
                required_context_packages.append(pack)
            if not all(day in allowed_stay_days for day in nights_rows):
                continue
            total = cls._package_total(
                price_type=str(pack.get('price_type')),
                special_price=float(pack.get('special_price') or 0),
                base_total=normal_total,
                nights=nights,
            )
            matches.append({
                'package': pack,
                'final_total': total,
                'discount_value': round(normal_total - total, 2),
                'required_for_sale': bool(pack.get('required_for_sale')),
            })
        required_candidates = [item for item in matches if bool(item.get('required_for_sale'))]
        return {
            'normal_total': normal_total,
            'nights': nights,
            'matches': matches,
            'required_candidates': required_candidates,
            'required_context_packages': required_context_packages,
        }

    @classmethod
    def validate_required_package_constraint(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
        sale_date: Optional[str] = None,
        base_total: Optional[float] = None,
    ) -> Dict[str, Any]:
        analysis = cls._eligible_matches(
            category=category,
            checkin=checkin,
            checkout=checkout,
            sale_date=sale_date,
            base_total=base_total,
        )
        if analysis['required_candidates']:
            best_required = sorted(
                analysis['required_candidates'],
                key=lambda item: (item['final_total'], item['package'].get('updated_at') or '')
            )[0]
            return {
                'valid': True,
                'required_for_sale': True,
                'matched_required': True,
                'package': best_required['package'],
                'final_total': best_required['final_total'],
                'normal_total': analysis['normal_total'],
                'nights': analysis['nights'],
            }
        required_packages = analysis.get('required_context_packages') or []
        if required_packages:
            return {
                'valid': False,
                'required_for_sale': True,
                'matched_required': False,
                'message': 'Para este período, é obrigatório contratar pacote promocional.',
                'required_packages': [{'id': p.get('id'), 'name': p.get('name')} for p in required_packages],
                'normal_total': analysis['normal_total'],
                'nights': analysis['nights'],
            }
        return {
            'valid': True,
            'required_for_sale': False,
            'matched_required': False,
            'normal_total': analysis['normal_total'],
            'nights': analysis['nights'],
        }

    @classmethod
    def preview_price(
        cls,
        *,
        category: str,
        checkin: str,
        checkout: str,
        sale_date: Optional[str] = None,
        base_total: Optional[float] = None,
    ) -> Dict[str, Any]:
        analysis = cls._eligible_matches(
            category=category,
            checkin=checkin,
            checkout=checkout,
            sale_date=sale_date,
            base_total=base_total,
        )
        normal_total = analysis['normal_total']
        nights = analysis['nights']
        matches = analysis['matches']
        if not matches:
            return {
                'applied': False,
                'normal_total': normal_total,
                'final_total': normal_total,
                'package': None,
                'nights': nights,
            }
        prioritized = analysis['required_candidates'] if analysis['required_candidates'] else matches
        best = sorted(prioritized, key=lambda item: (item['final_total'], item['package'].get('updated_at') or '' ))[0]
        return {
            'applied': True,
            'normal_total': normal_total,
            'final_total': best['final_total'],
            'discount_value': best['discount_value'],
            'package': {
                'id': best['package'].get('id'),
                'name': best['package'].get('name'),
                'price_type': best['package'].get('price_type'),
                'special_price': best['package'].get('special_price'),
                'required_for_sale': bool(best['package'].get('required_for_sale')),
            },
            'nights': nights,
        }
