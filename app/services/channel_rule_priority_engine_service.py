from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.channel_commission_service import ChannelCommissionService
from app.services.channel_restriction_service import ChannelRestrictionService
from app.services.channel_tariff_service import ChannelTariffService
from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.period_selector_service import PeriodSelectorService
from app.services.revenue_management_service import RevenueManagementService
from app.services.tariff_priority_engine_service import TariffPriorityEngineService


class ChannelRulePriorityEngineService:
    @classmethod
    def _stay_days(cls, checkin: str, checkout: str) -> List[str]:
        start = PeriodSelectorService.parse_date(checkin).date()
        end = PeriodSelectorService.parse_date(checkout).date()
        if end <= start:
            raise ValueError('Período inválido.')
        out: List[str] = []
        current = start
        while current < end:
            out.append(current.isoformat())
            current = current.fromordinal(current.toordinal() + 1)
        return out

    @classmethod
    def _parse_promotion(cls, promo_code: str) -> Dict[str, Any]:
        text = str(promo_code or '').strip()
        if not text:
            return {'mode': 'none', 'value': 0.0}
        upper = text.upper()
        if upper.endswith('%'):
            try:
                pct = float(upper.replace('%', '').strip())
                return {'mode': 'percent', 'value': max(0.0, min(100.0, pct)) / 100.0}
            except Exception:
                return {'mode': 'code', 'value': text}
        if upper.startswith('PERCENT:'):
            try:
                pct = float(upper.split(':', 1)[1].strip())
                return {'mode': 'percent', 'value': max(0.0, min(100.0, pct)) / 100.0}
            except Exception:
                return {'mode': 'code', 'value': text}
        if upper.startswith('FIXED:'):
            try:
                amount = float(upper.split(':', 1)[1].strip())
                return {'mode': 'fixed', 'value': max(0.0, amount)}
            except Exception:
                return {'mode': 'code', 'value': text}
        return {'mode': 'code', 'value': text}

    @classmethod
    def _tariff_for_day(cls, *, channel_name: str, category: str, day_iso: str) -> Dict[str, Any]:
        payload = ChannelTariffService.calculate_tariffs(
            channel_name=channel_name,
            category=category,
            start_date=day_iso,
            end_date=day_iso,
            weekdays=[],
        )
        row = (payload.get('rows') or [{}])[0]
        return row if isinstance(row, dict) else {}

    @classmethod
    def evaluate(
        cls,
        *,
        category: str,
        channel: str,
        checkin: str,
        checkout: str,
        sale_date: Optional[str] = None,
        package_selected: Optional[str] = None,
        apply_dynamic: bool = True,
    ) -> Dict[str, Any]:
        normalized_category = RevenueManagementService._normalize_booking_category(category)
        bucket = RevenueManagementService._booking_category_bucket(normalized_category)
        stay_days = cls._stay_days(checkin, checkout)
        nights = len(stay_days)
        checkin_day = stay_days[0]
        checkout_day = PeriodSelectorService.parse_date(checkout).date().isoformat()
        sale_day = PeriodSelectorService.parse_date(sale_date or datetime.now().strftime('%Y-%m-%d')).date().isoformat()
        rules_trace: List[Dict[str, Any]] = []

        if ChannelInventoryControlService.is_blackout_for_period(category=bucket, checkin=checkin, checkout=checkout):
            rules_trace.append({'priority': 1, 'rule': 'blackout_total', 'applied': True, 'result': 'blocked'})
            return {'sellable': False, 'message': 'Blackout total ativo no período.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 1, 'rule': 'blackout_total', 'applied': False, 'result': 'passed'})

        first_day_rules = ChannelRestrictionService.resolve_day_rules(category=bucket, channel=channel, day=checkin_day)
        if bool(first_day_rules.get('stop_sell')):
            rules_trace.append({'priority': 2, 'rule': 'stop_sell_canal', 'applied': True, 'result': 'blocked', 'details': first_day_rules})
            return {'sellable': False, 'message': f'Canal {channel} com stop sell ativo.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 2, 'rule': 'stop_sell_canal', 'applied': False, 'result': 'passed'})

        if not InventoryRestrictionService.is_open_for_period(bucket, checkin, checkout):
            rules_trace.append({'priority': 3, 'rule': 'categoria_fechada', 'applied': True, 'result': 'blocked'})
            return {'sellable': False, 'message': 'Categoria fechada para venda no período.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 3, 'rule': 'categoria_fechada', 'applied': False, 'result': 'passed'})

        if bool(first_day_rules.get('cta')):
            rules_trace.append({'priority': 4, 'rule': 'cta', 'applied': True, 'result': 'blocked', 'details': first_day_rules})
            return {'sellable': False, 'message': 'Restrição CTA ativa para a data de check-in.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 4, 'rule': 'cta', 'applied': False, 'result': 'passed'})

        checkout_rules = ChannelRestrictionService.resolve_day_rules(category=bucket, channel=channel, day=checkout_day)
        if bool(checkout_rules.get('ctd')):
            rules_trace.append({'priority': 5, 'rule': 'ctd', 'applied': True, 'result': 'blocked', 'details': checkout_rules})
            return {'sellable': False, 'message': 'Restrição CTD ativa para a data de check-out.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 5, 'rule': 'ctd', 'applied': False, 'result': 'passed'})

        min_stay = max([int(ChannelRestrictionService.resolve_day_rules(category=bucket, channel=channel, day=day).get('min_stay') or 0) for day in stay_days] or [0])
        max_stay = max([int(ChannelRestrictionService.resolve_day_rules(category=bucket, channel=channel, day=day).get('max_stay') or 0) for day in stay_days] or [0])
        if min_stay > 0 and nights < min_stay:
            rules_trace.append({'priority': 6, 'rule': 'min_stay', 'applied': True, 'result': 'blocked', 'details': {'min_stay': min_stay}})
            return {'sellable': False, 'message': f'Estadia mínima de {min_stay} noite(s) ativa.', 'rules_applied': rules_trace, 'nights': nights}
        if max_stay > 0 and nights > max_stay:
            rules_trace.append({'priority': 6, 'rule': 'max_stay', 'applied': True, 'result': 'blocked', 'details': {'max_stay': max_stay}})
            return {'sellable': False, 'message': f'Estadia máxima de {max_stay} noite(s) ativa.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 6, 'rule': 'min_max_stay', 'applied': bool(min_stay or max_stay), 'result': 'passed', 'details': {'min_stay': min_stay, 'max_stay': max_stay}})

        package_required = str(first_day_rules.get('pacote_obrigatorio') or '').strip()
        if package_required and str(package_selected or '').strip().lower() != package_required.lower():
            rules_trace.append({'priority': 7, 'rule': 'pacote_obrigatorio', 'applied': True, 'result': 'blocked', 'details': {'required': package_required}})
            return {'sellable': False, 'message': f'Pacote obrigatório ativo: {package_required}.', 'rules_applied': rules_trace, 'nights': nights}
        rules_trace.append({'priority': 7, 'rule': 'pacote_obrigatorio', 'applied': bool(package_required), 'result': 'passed', 'details': {'required': package_required}})

        day_tariff = cls._tariff_for_day(channel_name=channel, category=bucket, day_iso=checkin_day)
        tarifa_direta = float(day_tariff.get('tarifa_direta') or 0.0)
        tarifa_canal = float(day_tariff.get('tarifa_canal') or tarifa_direta)
        promo_code = str(first_day_rules.get('promocao_especifica') or '').strip()
        promo_parsed = cls._parse_promotion(promo_code)
        if promo_parsed.get('mode') == 'percent':
            tarifa_canal = max(0.0, tarifa_canal * (1.0 - float(promo_parsed.get('value') or 0.0)))
        elif promo_parsed.get('mode') == 'fixed':
            tarifa_canal = max(0.0, tarifa_canal - float(promo_parsed.get('value') or 0.0))
        rules_trace.append({'priority': 8, 'rule': 'promocao_canal', 'applied': bool(promo_code), 'result': 'passed', 'details': {'promotion_code': promo_code, 'parsed': promo_parsed}})

        rules_trace.append({'priority': 9, 'rule': 'tarifa_base_canal', 'applied': True, 'result': 'passed', 'details': day_tariff})

        dynamic_details = {'factor': 1.0, 'details': {'mode': 'disabled'}}
        tariff_after_dynamic = tarifa_canal
        if apply_dynamic:
            dynamic_details = TariffPriorityEngineService._dynamic_factor(category=bucket, day=sale_day)
            tariff_after_dynamic = round(tariff_after_dynamic * float(dynamic_details.get('factor') or 1.0), 2)
        rules_trace.append({'priority': 10, 'rule': 'ajuste_dinamico_rm', 'applied': bool(apply_dynamic), 'result': 'passed', 'details': dynamic_details})

        commission_calc = ChannelCommissionService.calculate_channel_tariff(
            channel_name=channel,
            category=bucket,
            day_iso=checkin_day,
            direct_tariff=tariff_after_dynamic,
        )
        commission_pct = float(commission_calc.get('commission_pct') or 0.0)
        tariff_after_commission_model = float(commission_calc.get('tarifa_canal') or tariff_after_dynamic)
        liquido = float(commission_calc.get('liquido_estimado_hotel') or 0.0)
        if commission_pct <= 0 and float(day_tariff.get('comissao_aplicada_percentual') or 0.0) > 0:
            commission_pct = float(day_tariff.get('comissao_aplicada_percentual') or 0.0)
            liquido = round(tariff_after_dynamic * (1.0 - commission_pct), 2)
            tariff_after_commission_model = tariff_after_dynamic
        rules_trace.append({
            'priority': 11,
            'rule': 'comissao_grossup_ota',
            'applied': True,
            'result': 'passed',
            'details': {
                'commercial_model': commission_calc.get('commercial_model'),
                'commission_pct': commission_pct,
                'commission_value': round(max(0.0, tariff_after_commission_model - liquido), 2),
            },
        })

        return {
            'sellable': True,
            'message': '',
            'nights': nights,
            'rules_applied': rules_trace,
            'restrictions_active': first_day_rules.get('labels') or [],
            'pricing': {
                'tarifa_direta': round(tarifa_direta, 2),
                'tarifa_canal_base': round(float(day_tariff.get('tarifa_canal') or tarifa_canal), 2),
                'tarifa_final_calculada': round(tariff_after_commission_model, 2),
                'liquido_estimado_hotel': round(liquido, 2),
                'comissao_percentual': round(commission_pct, 6),
                'modelo_comercial': commission_calc.get('commercial_model'),
            },
        }
