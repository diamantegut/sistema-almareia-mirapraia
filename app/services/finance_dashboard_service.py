import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.services.cashier_service import CashierService
from app.services.data_service import load_cashier_sessions
from app.services.ledger_service import LedgerService
from app.services.logger_service import LoggerService
from app.services.reservation_service import ReservationService
from app.services.system_config_manager import PAYMENT_METHODS_FILE


class FinanceDashboardService:
    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace('R$', '').replace(' ', '')
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_date(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or '').strip().lower()

    @staticmethod
    def _get_day_bounds(date_str: str) -> Tuple[datetime, datetime]:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return (
            dt.replace(hour=0, minute=0, second=0, microsecond=0),
            dt.replace(hour=23, minute=59, second=59, microsecond=999999),
        )

    @staticmethod
    def _load_payment_methods_raw() -> List[Dict[str, Any]]:
        try:
            with open(PAYMENT_METHODS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def ensure_payment_methods_classification(user: str = 'Sistema') -> Dict[str, Any]:
        methods = FinanceDashboardService._load_payment_methods_raw()
        changed = False
        fixed = 0
        for method in methods:
            if not isinstance(method, dict):
                continue
            if 'is_fiscal' not in method or not isinstance(method.get('is_fiscal'), bool):
                method['is_fiscal'] = False
                changed = True
                fixed += 1
        if changed:
            with open(PAYMENT_METHODS_FILE, 'w', encoding='utf-8') as f:
                json.dump(methods, f, indent=2, ensure_ascii=False)
            LoggerService.log_acao(
                acao='Classificação de métodos de pagamento',
                entidade='Financeiro',
                detalhes={'corrigidos': fixed},
                nivel_severidade='WARNING',
                departamento_id='Financeiro',
                colaborador_id=user,
            )
        return {'updated': changed, 'fixed': fixed}

    @staticmethod
    def get_payment_methods_index() -> Dict[str, Dict[str, Any]]:
        methods = FinanceDashboardService._load_payment_methods_raw()
        index: Dict[str, Dict[str, Any]] = {}
        for method in methods:
            if not isinstance(method, dict):
                continue
            name = str(method.get('name') or '').strip()
            if not name:
                continue
            key = FinanceDashboardService._normalize_text(name)
            index[key] = {
                'is_fiscal': bool(method.get('is_fiscal', False)),
                'id': method.get('id'),
                'name': name,
            }
        return index

    @staticmethod
    def _is_fiscal_payment(method_name: Any, payment_index: Dict[str, Dict[str, Any]]) -> bool:
        key = FinanceDashboardService._normalize_text(method_name)
        if key in payment_index:
            return bool(payment_index[key].get('is_fiscal', False))
        return False

    @staticmethod
    def get_ledger_data(start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        all_tx = LedgerService.get_transactions()
        filtered = []
        for tx in all_tx:
            try:
                tx_dt = datetime.fromisoformat(str(tx.get('timestamp')))
            except Exception:
                continue
            if start_date <= tx_dt <= end_date:
                filtered.append(tx)
        return filtered

    @staticmethod
    def _extract_reservation_id_from_reference(reference: Any) -> Optional[str]:
        text = str(reference or '')
        patterns = [
            r'reserva(?:\s*#|\s*id[:=\s#]+)([a-zA-Z0-9-]{6,})',
            r'reservation[_\s-]*id[:=\s#]+([a-zA-Z0-9-]{6,})',
            r'ref(?:er[eê]ncia)?[:=\s#]+([a-zA-Z0-9-]{6,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return str(match.group(1))
        return None

    @staticmethod
    def _extract_room_from_reference(reference: Any) -> Optional[str]:
        text = str(reference or '')
        match = re.search(r'quarto\s*#?\s*(\d{1,3})', text, re.IGNORECASE)
        if match:
            return match.group(1).zfill(2)
        return None

    @staticmethod
    def _tx_matches_reservation(tx: Dict[str, Any], reservation_id: str, room_number: Optional[str]) -> bool:
        rid = str(reservation_id)
        reference = str(tx.get('reference') or '')
        if rid and rid in reference:
            return True
        extracted = FinanceDashboardService._extract_reservation_id_from_reference(reference)
        if extracted and extracted == rid:
            return True
        if room_number:
            ref_room = FinanceDashboardService._extract_room_from_reference(reference)
            if ref_room and ref_room == str(room_number).zfill(2):
                return True
            dest = FinanceDashboardService._normalize_text(tx.get('dest_box'))
            source = FinanceDashboardService._normalize_text(tx.get('source_box'))
            room_token = f'quarto {str(room_number).zfill(2)}'
            if room_token in dest or room_token in source:
                return True
        return False

    @staticmethod
    def _reservation_total(reservation: Dict[str, Any]) -> float:
        candidates = [
            reservation.get('amount'),
            reservation.get('total_value'),
            reservation.get('total'),
            reservation.get('valor_total'),
        ]
        for value in candidates:
            if value is None:
                continue
            return FinanceDashboardService._to_float(value, 0.0)
        return 0.0

    @staticmethod
    def _reservation_period(reservation: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
        checkin = FinanceDashboardService._parse_date(reservation.get('checkin'))
        checkout = FinanceDashboardService._parse_date(reservation.get('checkout'))
        return checkin, checkout

    @staticmethod
    def _classify_timeline_event(tx: Dict[str, Any], is_fiscal: bool) -> Dict[str, Any]:
        op_type = FinanceDashboardService._normalize_text(tx.get('operation_type')).upper()
        reference = FinanceDashboardService._normalize_text(tx.get('reference'))
        source = FinanceDashboardService._normalize_text(tx.get('source_box'))
        dest = FinanceDashboardService._normalize_text(tx.get('dest_box'))
        event_type = 'movimento'
        label = 'Movimento Financeiro'
        if op_type == 'REVERSAL' or 'estorno' in reference:
            event_type = 'ajuste_estorno'
            label = 'Ajuste/Estorno'
        elif 'cancelamento' in reference:
            event_type = 'ajuste_estorno'
            label = 'Cancelamento'
        elif 'desconto' in reference or 'cortesia' in reference:
            event_type = 'desconto_cortesia'
            label = 'Desconto/Cortesia'
        elif 'restaurante' in source and ('quarto' in dest or 'hospedagem' in dest or 'quarto' in reference):
            event_type = 'consumo_transferido'
            label = 'Consumo Restaurante -> Quarto'
        elif 'hospedagem' in reference or 'diaria' in reference or 'diária' in reference:
            event_type = 'lancamento_hospedagem'
            label = 'Lançamento de Hospedagem'
        elif source == 'externo' or dest in ('recepção', 'caixa de reservas', 'caixa consumo de hóspedes'):
            event_type = 'pagamento'
            label = 'Pagamento Recebido'
        return {
            'event_type': event_type,
            'label': label,
            'is_fiscal': bool(is_fiscal),
        }

    @staticmethod
    def get_reservation_timeline(reservation_id: str) -> Dict[str, Any]:
        reservation_service = ReservationService()
        reservation = reservation_service.get_reservation_by_id(reservation_id) or {}
        room_number = reservation.get('room')
        payment_index = FinanceDashboardService.get_payment_methods_index()
        tx_all = LedgerService.get_transactions()
        timeline: List[Dict[str, Any]] = []
        for tx in tx_all:
            if not isinstance(tx, dict):
                continue
            if not FinanceDashboardService._tx_matches_reservation(tx, reservation_id, room_number):
                continue
            is_fiscal = FinanceDashboardService._is_fiscal_payment(tx.get('payment_method'), payment_index)
            classified = FinanceDashboardService._classify_timeline_event(tx, is_fiscal)
            timeline.append({
                'id': tx.get('id'),
                'timestamp': tx.get('timestamp'),
                'operation_type': tx.get('operation_type'),
                'payment_method': tx.get('payment_method'),
                'source_box': tx.get('source_box'),
                'dest_box': tx.get('dest_box'),
                'reference': tx.get('reference'),
                'value': FinanceDashboardService._to_float(tx.get('value')),
                'event_type': classified['event_type'],
                'label': classified['label'],
                'is_fiscal': classified['is_fiscal'],
            })
        timeline.sort(key=lambda item: item.get('timestamp') or '')
        created_at = reservation.get('created_at')
        if created_at:
            created_dt = FinanceDashboardService._parse_date(created_at)
            timeline.insert(0, {
                'id': f'CREATED_{reservation_id}',
                'timestamp': created_dt.isoformat() if created_dt else str(created_at),
                'operation_type': 'RESERVATION_CREATED',
                'payment_method': None,
                'source_box': 'RESERVATION_SERVICE',
                'dest_box': 'RESERVATION_SERVICE',
                'reference': f'Reserva {reservation_id}',
                'value': 0.0,
                'event_type': 'criacao_reserva',
                'label': 'Criação da Reserva',
                'is_fiscal': False,
            })
        total_pago = 0.0
        total_lancado = 0.0
        for item in timeline:
            value = FinanceDashboardService._to_float(item.get('value'))
            if item.get('event_type') == 'pagamento':
                total_pago += value
            elif item.get('event_type') in ('lancamento_hospedagem', 'consumo_transferido'):
                total_lancado += value
            elif item.get('event_type') == 'desconto_cortesia':
                total_lancado -= abs(value)
        total_reserva = FinanceDashboardService._reservation_total(reservation)
        if total_reserva <= 0:
            total_reserva = max(total_lancado, 0.0)
        saldo_pendente = max(total_reserva - total_pago, 0.0)
        if total_reserva > 0 and saldo_pendente <= 0.01 and timeline:
            timeline.append({
                'id': f'CLOSE_{reservation_id}',
                'timestamp': timeline[-1].get('timestamp'),
                'operation_type': 'RESERVATION_CLOSED',
                'payment_method': None,
                'source_box': 'FINANCE',
                'dest_box': 'FINANCE',
                'reference': f'Fechamento Reserva {reservation_id}',
                'value': 0.0,
                'event_type': 'fechamento_final',
                'label': 'Fechamento Final',
                'is_fiscal': False,
            })
        return {
            'reservation_id': reservation_id,
            'reservation': reservation,
            'total_reserva': round(total_reserva, 2),
            'total_pago': round(total_pago, 2),
            'saldo_pendente': round(saldo_pendente, 2),
            'timeline': timeline,
        }

    @staticmethod
    def get_reservation_financials(
        start_date_str: str,
        end_date_str: str,
        checkout_today: bool = False,
        min_balance: float = 0.0,
        fiscal_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return []
        payment_index = FinanceDashboardService.get_payment_methods_index()
        reservation_service = ReservationService()
        reservations = reservation_service.get_february_reservations()
        period_tx = FinanceDashboardService.get_ledger_data(start_date, end_date)
        today = datetime.now().date()
        results: List[Dict[str, Any]] = []
        for reservation in reservations:
            if not isinstance(reservation, dict):
                continue
            reservation_id = str(reservation.get('id') or '').strip()
            if not reservation_id:
                continue
            room_number = reservation.get('room')
            related = [tx for tx in period_tx if FinanceDashboardService._tx_matches_reservation(tx, reservation_id, room_number)]
            total_paid = 0.0
            fiscal_paid = 0.0
            non_fiscal_paid = 0.0
            has_manual = False
            has_adjustments = False
            last_activity = None
            for tx in related:
                value = FinanceDashboardService._to_float(tx.get('value'))
                is_fiscal = FinanceDashboardService._is_fiscal_payment(tx.get('payment_method'), payment_index)
                classified = FinanceDashboardService._classify_timeline_event(tx, is_fiscal)
                if classified['event_type'] == 'pagamento':
                    total_paid += value
                    if is_fiscal:
                        fiscal_paid += value
                    else:
                        non_fiscal_paid += value
                    if 'manual' in FinanceDashboardService._normalize_text(tx.get('reference')):
                        has_manual = True
                if classified['event_type'] in ('ajuste_estorno', 'desconto_cortesia'):
                    has_adjustments = True
                tx_ts = tx.get('timestamp')
                if not last_activity or (tx_ts and tx_ts > last_activity):
                    last_activity = tx_ts
            total_previsto = FinanceDashboardService._reservation_total(reservation)
            saldo = max(total_previsto - total_paid, 0.0)
            checkin, checkout = FinanceDashboardService._reservation_period(reservation)
            if checkout_today and (not checkout or checkout.date() != today):
                continue
            if saldo <= float(min_balance or 0):
                continue
            if fiscal_filter == 'fiscal' and fiscal_paid <= 0:
                continue
            if fiscal_filter == 'nao_fiscal' and non_fiscal_paid <= 0:
                continue
            results.append({
                'reservation_id': reservation_id,
                'reservation_ref': reservation_id,
                'guest_name': reservation.get('guest_name'),
                'period_start': checkin.strftime('%Y-%m-%d') if checkin else None,
                'period_end': checkout.strftime('%Y-%m-%d') if checkout else None,
                'origin': reservation.get('channel') or reservation.get('origin') or 'direta',
                'total_previsto': round(total_previsto, 2),
                'total_pago': round(total_paid, 2),
                'saldo_pendente': round(saldo, 2),
                'total_paid': round(total_paid, 2),
                'transaction_count': len(related),
                'last_activity': last_activity,
                'status': 'Pendente' if saldo > 0.01 else 'Quitada',
                'fiscal_paid': round(fiscal_paid, 2),
                'non_fiscal_paid': round(non_fiscal_paid, 2),
                'has_manual': has_manual,
                'has_adjustments': has_adjustments,
            })
        results.sort(key=lambda item: (item.get('saldo_pendente', 0), item.get('period_end') or ''), reverse=True)
        return results

    @staticmethod
    def get_daily_summary(date_str: str) -> Dict[str, Any]:
        start_of_day, end_of_day = FinanceDashboardService._get_day_bounds(date_str)
        payment_index = FinanceDashboardService.get_payment_methods_index()
        transactions = FinanceDashboardService.get_ledger_data(start_of_day, end_of_day)
        accommodation_revenue = 0.0
        restaurant_to_room = 0.0
        receipts_by_cashier: Dict[str, float] = {}
        fiscal_total = 0.0
        non_fiscal_total = 0.0
        manual_total = 0.0
        adjustments_total = 0.0
        for tx in transactions:
            value = FinanceDashboardService._to_float(tx.get('value'))
            source = FinanceDashboardService._normalize_text(tx.get('source_box'))
            dest = FinanceDashboardService._normalize_text(tx.get('dest_box'))
            is_fiscal = FinanceDashboardService._is_fiscal_payment(tx.get('payment_method'), payment_index)
            classified = FinanceDashboardService._classify_timeline_event(tx, is_fiscal)
            if classified['event_type'] in ('lancamento_hospedagem', 'consumo_transferido'):
                accommodation_revenue += value
            if classified['event_type'] == 'consumo_transferido':
                restaurant_to_room += value
            if source == 'externo' and dest:
                receipts_by_cashier[tx.get('dest_box')] = receipts_by_cashier.get(tx.get('dest_box'), 0.0) + value
                if is_fiscal:
                    fiscal_total += value
                else:
                    non_fiscal_total += value
                if 'manual' in FinanceDashboardService._normalize_text(tx.get('reference')):
                    manual_total += value
            if classified['event_type'] in ('ajuste_estorno', 'desconto_cortesia'):
                adjustments_total += value
        reservation_service = ReservationService()
        reservations = reservation_service.get_february_reservations()
        target_day = start_of_day.date()
        occupied_rooms = set()
        for reservation in reservations:
            if not isinstance(reservation, dict):
                continue
            status = FinanceDashboardService._normalize_text(reservation.get('status'))
            if 'cancel' in status:
                continue
            checkin, checkout = FinanceDashboardService._reservation_period(reservation)
            if not checkin or not checkout:
                continue
            if checkin.date() <= target_day < checkout.date():
                room = str(reservation.get('room') or '').zfill(2) if reservation.get('room') else None
                if room:
                    occupied_rooms.add(room)
        total_rooms = len(getattr(ReservationService, 'ROOM_CAPACITIES', {})) or 20
        sold_rooms = len(occupied_rooms)
        occupancy_rate = (sold_rooms / total_rooms * 100.0) if total_rooms > 0 else 0.0
        adr = (accommodation_revenue / sold_rooms) if sold_rooms > 0 else 0.0
        revpar = (accommodation_revenue / total_rooms) if total_rooms > 0 else 0.0
        reservation_financials = FinanceDashboardService.get_reservation_financials(
            start_of_day.strftime('%Y-%m-%d'),
            end_of_day.strftime('%Y-%m-%d'),
        )
        pending_receivables = sum(item.get('saldo_pendente', 0.0) for item in reservation_financials)
        return {
            'accommodation_revenue': round(accommodation_revenue, 2),
            'restaurant_to_room': round(restaurant_to_room, 2),
            'receipts_by_cashier': {k: round(v, 2) for k, v in receipts_by_cashier.items()},
            'receipts_reception': round(receipts_by_cashier.get('Caixa Consumo de Hóspedes', 0.0), 2),
            'pending_receivables': round(pending_receivables, 2),
            'occupancy_rate': round(occupancy_rate, 2),
            'adr': round(adr, 2),
            'revpar': round(revpar, 2),
            'occupied_rooms': sold_rooms,
            'total_rooms': total_rooms,
            'fiscal_total': round(fiscal_total, 2),
            'non_fiscal_total': round(non_fiscal_total, 2),
            'manual_total': round(manual_total, 2),
            'adjustments_total': round(adjustments_total, 2),
            'kpi_tooltips': {
                'occupancy': 'Ocupação = quartos ocupados / quartos disponíveis',
                'adr': 'ADR = receita de hospedagem / quartos vendidos',
                'revpar': 'RevPAR = receita de hospedagem / quartos disponíveis',
            },
        }

    @staticmethod
    def get_cashier_conference(date_str: str, cashier_id: str = 'Caixa Consumo de Hóspedes') -> Dict[str, Any]:
        start_of_day, end_of_day = FinanceDashboardService._get_day_bounds(date_str)
        opening_cutoff = start_of_day - timedelta(microseconds=1)
        opening_balance = LedgerService.rebuild_balance(cashier_id, opening_cutoff.isoformat())
        day_tx = FinanceDashboardService.get_ledger_data(start_of_day, end_of_day)
        entries = 0.0
        exits = 0.0
        transfers_in = 0.0
        transfers_out = 0.0
        for tx in day_tx:
            value = FinanceDashboardService._to_float(tx.get('value'))
            source = str(tx.get('source_box') or '')
            dest = str(tx.get('dest_box') or '')
            source_norm = FinanceDashboardService._normalize_text(source)
            dest_norm = FinanceDashboardService._normalize_text(dest)
            if dest == cashier_id:
                if source_norm != 'externo':
                    transfers_in += value
                else:
                    entries += value
            elif source == cashier_id:
                if dest_norm != 'externo':
                    transfers_out += value
                else:
                    exits += value
        expected_balance = opening_balance + entries + transfers_in - exits - transfers_out
        sessions = load_cashier_sessions()
        reported_balance = None
        day_ref = start_of_day.strftime('%d/%m/%Y')
        for session in sessions:
            if session.get('status') != 'closed':
                continue
            closed_at = str(session.get('closed_at') or '')
            if not closed_at.startswith(day_ref):
                continue
            c_type = str(session.get('type') or '')
            mapped = CashierService.TYPES.get(c_type, c_type)
            if mapped == cashier_id:
                reported_balance = FinanceDashboardService._to_float(session.get('closing_cash'), None)
        if reported_balance is None:
            reported_balance = 0.0
        return {
            'opening_balance': round(opening_balance, 2),
            'entries': round(entries, 2),
            'exits': round(exits, 2),
            'transfers_in': round(transfers_in, 2),
            'transfers_out': round(transfers_out, 2),
            'expected_balance': round(expected_balance, 2),
            'reported_balance': round(reported_balance, 2),
            'difference': round(reported_balance - expected_balance, 2),
        }

    @staticmethod
    def get_payment_methods_summary(
        start_date_str: str,
        end_date_str: str,
        fiscal_filter: Optional[str] = None,
        non_fiscal_limit: float = 500.0,
    ) -> Dict[str, Any]:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return {'methods': []}
        payment_index = FinanceDashboardService.get_payment_methods_index()
        tx = FinanceDashboardService.get_ledger_data(start_date, end_date)
        methods: Dict[str, Dict[str, Any]] = {}
        total = 0.0
        fiscal_total = 0.0
        non_fiscal_total = 0.0
        manual_total = 0.0
        adjustment_total = 0.0
        violations: List[Dict[str, Any]] = []
        for item in tx:
            source = FinanceDashboardService._normalize_text(item.get('source_box'))
            if source != 'externo':
                continue
            method_name = str(item.get('payment_method') or 'Não informado')
            value = FinanceDashboardService._to_float(item.get('value'))
            if value <= 0:
                continue
            is_fiscal = FinanceDashboardService._is_fiscal_payment(method_name, payment_index)
            if fiscal_filter == 'fiscal' and not is_fiscal:
                continue
            if fiscal_filter == 'nao_fiscal' and is_fiscal:
                continue
            ref = FinanceDashboardService._normalize_text(item.get('reference'))
            is_manual = 'manual' in ref
            is_adjust = 'ajuste' in ref or 'estorno' in ref or 'cancelamento' in ref
            if method_name not in methods:
                methods[method_name] = {
                    'method': method_name,
                    'total': 0.0,
                    'count': 0,
                    'fiscal': is_fiscal,
                    'manual_total': 0.0,
                    'adjustment_total': 0.0,
                }
            methods[method_name]['total'] += value
            methods[method_name]['count'] += 1
            if is_manual:
                methods[method_name]['manual_total'] += value
                manual_total += value
            if is_adjust:
                methods[method_name]['adjustment_total'] += value
                adjustment_total += value
            if is_fiscal:
                fiscal_total += value
            else:
                non_fiscal_total += value
                justification_ok = any(key in ref for key in ('justificativa', 'motivo', 'obs:', 'observacao'))
                if value > float(non_fiscal_limit) and not justification_ok:
                    violations.append({
                        'transaction_id': item.get('id'),
                        'timestamp': item.get('timestamp'),
                        'value': round(value, 2),
                        'payment_method': method_name,
                        'reference': item.get('reference'),
                    })
            total += value
        ordered = []
        for method_data in methods.values():
            method_data['percentage'] = (method_data['total'] / total * 100.0) if total > 0 else 0.0
            ordered.append({
                'method': method_data['method'],
                'total': round(method_data['total'], 2),
                'count': method_data['count'],
                'percentage': round(method_data['percentage'], 2),
                'fiscal': method_data['fiscal'],
                'manual_total': round(method_data['manual_total'], 2),
                'adjustment_total': round(method_data['adjustment_total'], 2),
            })
        ordered.sort(key=lambda x: x['total'], reverse=True)
        return {
            'methods': ordered,
            'totals': {
                'total': round(total, 2),
                'fiscal_total': round(fiscal_total, 2),
                'non_fiscal_total': round(non_fiscal_total, 2),
                'manual_total': round(manual_total, 2),
                'adjustment_total': round(adjustment_total, 2),
            },
            'non_fiscal_limit': float(non_fiscal_limit),
            'non_fiscal_violations': violations,
        }

    @staticmethod
    def get_audit_events(
        start_date_str: str,
        end_date_str: str,
        user_filter: Optional[str] = None,
        cashier_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return []
        tx = FinanceDashboardService.get_ledger_data(start_date, end_date)
        events = []
        for item in tx:
            op_type = FinanceDashboardService._normalize_text(item.get('operation_type')).upper()
            ref = FinanceDashboardService._normalize_text(item.get('reference'))
            source = str(item.get('source_box') or '')
            dest = str(item.get('dest_box') or '')
            if user_filter and FinanceDashboardService._normalize_text(item.get('user')) != FinanceDashboardService._normalize_text(user_filter):
                continue
            if cashier_filter and cashier_filter not in (source, dest):
                continue
            is_event = (
                op_type == 'REVERSAL'
                or 'estorno' in ref
                or 'ajuste' in ref
                or 'cancelamento' in ref
                or (source.lower() != 'externo' and dest.lower() != 'externo')
            )
            if not is_event:
                continue
            events.append({
                'id': item.get('id'),
                'timestamp': item.get('timestamp'),
                'user': item.get('user'),
                'operation_type': item.get('operation_type'),
                'source_box': source,
                'dest_box': dest,
                'payment_method': item.get('payment_method'),
                'value': round(FinanceDashboardService._to_float(item.get('value')), 2),
                'reference': item.get('reference'),
            })
        events.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        return events

    @staticmethod
    def get_day_closure_report(date_str: str, non_fiscal_limit: float = 500.0) -> Dict[str, Any]:
        start_of_day, end_of_day = FinanceDashboardService._get_day_bounds(date_str)
        day_tx = FinanceDashboardService.get_ledger_data(start_of_day, end_of_day)
        payment_summary = FinanceDashboardService.get_payment_methods_summary(
            start_of_day.strftime('%Y-%m-%d'),
            end_of_day.strftime('%Y-%m-%d'),
            non_fiscal_limit=non_fiscal_limit,
        )
        total_received_by_cashier: Dict[str, float] = {}
        transfers: List[Dict[str, Any]] = []
        reversals: List[Dict[str, Any]] = []
        missing_reference: List[Dict[str, Any]] = []
        for tx in day_tx:
            source = str(tx.get('source_box') or '')
            dest = str(tx.get('dest_box') or '')
            value = FinanceDashboardService._to_float(tx.get('value'))
            if FinanceDashboardService._normalize_text(source) == 'externo' and dest:
                total_received_by_cashier[dest] = total_received_by_cashier.get(dest, 0.0) + value
            if FinanceDashboardService._normalize_text(source) != 'externo' and FinanceDashboardService._normalize_text(dest) != 'externo':
                transfers.append({
                    'id': tx.get('id'),
                    'timestamp': tx.get('timestamp'),
                    'source_box': source,
                    'dest_box': dest,
                    'value': round(value, 2),
                    'reference': tx.get('reference'),
                })
            ref = str(tx.get('reference') or '').strip()
            if not ref:
                missing_reference.append({
                    'id': tx.get('id'),
                    'timestamp': tx.get('timestamp'),
                    'source_box': source,
                    'dest_box': dest,
                    'value': round(value, 2),
                })
            op_type = FinanceDashboardService._normalize_text(tx.get('operation_type')).upper()
            ref_norm = FinanceDashboardService._normalize_text(tx.get('reference'))
            if op_type == 'REVERSAL' or 'estorno' in ref_norm or 'cancelamento' in ref_norm:
                reversals.append({
                    'id': tx.get('id'),
                    'timestamp': tx.get('timestamp'),
                    'user': tx.get('user'),
                    'operation_type': tx.get('operation_type'),
                    'value': round(value, 2),
                    'reference': tx.get('reference'),
                })
        sessions = load_cashier_sessions()
        day_prefix = start_of_day.strftime('%d/%m/%Y')
        differences = []
        for session in sessions:
            closed_at = str(session.get('closed_at') or '')
            if session.get('status') == 'closed' and closed_at.startswith(day_prefix):
                diff = FinanceDashboardService._to_float(session.get('difference'))
                if abs(diff) > 0.01:
                    differences.append({
                        'session_id': session.get('id'),
                        'type': session.get('type'),
                        'closed_at': closed_at,
                        'difference': round(diff, 2),
                        'approved': bool(session.get('difference_approved')),
                    })
        open_sessions = []
        for s_type in ('restaurant', 'restaurant_service', 'guest_consumption', 'reception_room_billing', 'reservation_cashier'):
            active = CashierService.get_active_session(s_type)
            if active:
                open_sessions.append({
                    'session_id': active.get('id'),
                    'type': active.get('type'),
                    'opened_at': active.get('opened_at'),
                })
        all_cashiers_closed = len(open_sessions) == 0
        validations = {
            'all_cashiers_closed': all_cashiers_closed,
            'has_cashier_difference': len(differences) > 0,
            'has_missing_reference': len(missing_reference) > 0,
            'open_sessions': open_sessions,
            'difference_count': len(differences),
            'missing_reference_count': len(missing_reference),
        }
        LoggerService.log_acao(
            acao='Consulta Fechamento do Dia',
            entidade='Dashboard Financeiro',
            detalhes={
                'date': date_str,
                'all_cashiers_closed': all_cashiers_closed,
                'difference_count': len(differences),
                'missing_reference_count': len(missing_reference),
            },
            nivel_severidade='INFO',
            departamento_id='Financeiro',
        )
        return {
            'date': date_str,
            'total_received_by_cashier': {k: round(v, 2) for k, v in total_received_by_cashier.items()},
            'payment_summary': payment_summary,
            'fiscal_vs_non_fiscal': payment_summary.get('totals', {}),
            'transfers_between_cashiers': transfers,
            'reversals_and_cancellations': reversals,
            'validations': validations,
            'cashier_differences': differences,
            'missing_reference_transactions': missing_reference,
        }
