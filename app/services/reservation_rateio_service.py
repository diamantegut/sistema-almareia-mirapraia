import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List

from app.services.cashier_service import file_lock
from app.services.logger_service import LoggerService
from app.services.system_config_manager import RESERVATION_DAILY_SPLITS_FILE


class ReservationRateioService:
    FILE_PATH = RESERVATION_DAILY_SPLITS_FILE

    @staticmethod
    def _parse_date(value: Any) -> datetime:
        text = str(value or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(text)

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        text = str(value or '0').strip().replace('R$', '').replace(' ', '')
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        return Decimal(text).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def _load_all(cls) -> List[Dict[str, Any]]:
        try:
            with open(cls.FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @classmethod
    def _save_all(cls, payload: List[Dict[str, Any]]) -> None:
        with open(cls.FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    @classmethod
    def get_by_reservation(cls, reservation_id: str) -> List[Dict[str, Any]]:
        rows = cls._load_all()
        rid = str(reservation_id)
        selected = [row for row in rows if str(row.get('reservation_id')) == rid]
        selected.sort(key=lambda item: item.get('daily_date') or '')
        return selected

    @classmethod
    def generate(
        cls,
        reservation_id: str,
        total_package: Any,
        checkin: Any,
        checkout: Any,
        user: str = 'Sistema',
        trigger: str = 'reservation_confirmed',
        force: bool = False,
    ) -> Dict[str, Any]:
        rid = str(reservation_id).strip()
        if not rid:
            raise ValueError('reservation_id inválido')
        checkin_dt = cls._parse_date(checkin)
        checkout_dt = cls._parse_date(checkout)
        nights = (checkout_dt.date() - checkin_dt.date()).days
        if nights <= 0:
            raise ValueError('Período inválido para rateio')
        package_total = cls._to_decimal(total_package)
        if package_total < Decimal('0'):
            raise ValueError('Total do pacote inválido')
        with file_lock(cls.FILE_PATH):
            all_rows = cls._load_all()
            existing = [row for row in all_rows if str(row.get('reservation_id')) == rid]
            if existing and not force:
                return {
                    'reservation_id': rid,
                    'nights': nights,
                    'total_package': float(package_total),
                    'rows': existing,
                    'created': False,
                }
            all_rows = [row for row in all_rows if str(row.get('reservation_id')) != rid]
            total_cents = int((package_total * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            base_cents = total_cents // nights
            remainder = total_cents - (base_cents * nights)
            created_at = datetime.now().isoformat()
            rows: List[Dict[str, Any]] = []
            for idx in range(nights):
                current_date = (checkin_dt + timedelta(days=idx)).date().isoformat()
                cents = base_cents + (remainder if idx == nights - 1 else 0)
                daily_value = Decimal(cents) / Decimal(100)
                rows.append({
                    'reservation_id': rid,
                    'daily_date': current_date,
                    'daily_value': float(daily_value),
                    'created_at': created_at,
                    'nights': nights,
                    'package_total': float(package_total),
                    'trigger': trigger,
                    'user': user,
                })
            all_rows.extend(rows)
            cls._save_all(all_rows)
        LoggerService.log_acao(
            acao='Gerou rateio de diária',
            entidade='Reservas',
            detalhes={
                'reservation_id': rid,
                'nights': nights,
                'package_total': float(package_total),
                'trigger': trigger,
                'force': force,
            },
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user,
        )
        return {
            'reservation_id': rid,
            'nights': nights,
            'total_package': float(package_total),
            'rows': rows,
            'created': True,
        }
