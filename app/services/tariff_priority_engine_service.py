from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.arrival_departure_restriction_service import ArrivalDepartureRestrictionService
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.inventory_protection_service import InventoryProtectionService
from app.services.period_selector_service import PeriodSelectorService
from app.services.promotional_package_service import PromotionalPackageService
from app.services.revenue_management_service import RevenueManagementService
from app.services.revenue_promotion_service import RevenuePromotionService
from app.services.stay_restriction_service import StayRestrictionService
from app.services.weekday_base_rate_service import WeekdayBaseRateService


class TariffPriorityEngineService:
    @classmethod
    def _stay_dates(cls, checkin: str, checkout: str) -> List[str]:
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
    def _dynamic_factor(cls, category: str, day: str) -> Dict[str, Any]:
        simulation = RevenueManagementService.simulate_projection(start_date=day, days=1, advanced_mode=True)
        bucket = RevenueManagementService._normalize_category(category)
        row = next((item for item in (simulation.get('rows') or []) if str(item.get('category')) == bucket), None)
        if not row:
            return {'factor': 1.0, 'details': {'mode': 'advanced', 'reason': 'sem linha de simulação'}}
        current = float(row.get('current_bar') or 0)
        suggested = float(row.get('suggested_bar') or 0)
        if current <= 0:
            return {'factor': 1.0, 'details': {'mode': 'advanced', 'reason': str(row.get('reason') or '')}}
        factor = max(0.5, min(2.0, suggested / current))
        return {'factor': factor, 'details': {'mode': 'advanced', 'reason': str(row.get('reason') or '')}}

    @classmethod
    def evaluate(
        cls,
        *,
        category: str,
        channel: str = 'Recepção',
        checkin: str,
        checkout: str,
        sale_date: Optional[str] = None,
        apply_dynamic: bool = True,
    ) -> Dict[str, Any]:
        sale_day = PeriodSelectorService.parse_date(sale_date or datetime.now().strftime('%Y-%m-%d')).date().isoformat()
        dates = cls._stay_dates(checkin, checkout)
        nights = len(dates)
        rules_trace: List[Dict[str, Any]] = []

        if not InventoryRestrictionService.is_open_for_period(category, checkin, checkout):
            rules_trace.append({'priority': 1, 'rule': 'inventory_closed', 'applied': True, 'result': 'blocked'})
            return {
                'sellable': False,
                'message': f'Categoria "{category}" fechada para venda no período informado.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 1, 'rule': 'inventory_closed', 'applied': False, 'result': 'passed'})

        allotment_validation = ChannelInventoryControlService.validate_allotment_availability(
            category=category,
            channel=channel,
            checkin=checkin,
            checkout=checkout,
        )
        if not allotment_validation.get('valid'):
            rules_trace.append({'priority': 2, 'rule': 'allotment', 'applied': True, 'result': 'blocked', 'details': allotment_validation})
            return {
                'sellable': False,
                'message': allotment_validation.get('message') or 'Allotment indisponível para o canal.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 2, 'rule': 'allotment', 'applied': True, 'result': 'passed', 'details': allotment_validation})

        protection_validation = InventoryProtectionService.validate_sale(
            category=category,
            checkin=checkin,
            checkout=checkout,
        )
        if not protection_validation.get('valid'):
            rules_trace.append({'priority': 3, 'rule': 'inventory_protection', 'applied': True, 'result': 'blocked', 'details': protection_validation})
            return {
                'sellable': False,
                'message': protection_validation.get('message') or 'Proteção de inventário ativa no período.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 3, 'rule': 'inventory_protection', 'applied': True, 'result': 'passed', 'details': protection_validation})

        if ChannelInventoryControlService.is_blackout_for_period(category=category, checkin=checkin, checkout=checkout):
            rules_trace.append({'priority': 4, 'rule': 'blackout', 'applied': True, 'result': 'blocked'})
            return {
                'sellable': False,
                'message': 'Categoria bloqueada por blackout no período informado.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 4, 'rule': 'blackout', 'applied': False, 'result': 'passed'})

        if not ChannelInventoryControlService.is_channel_open_for_period(category=category, channel=channel, checkin=checkin, checkout=checkout):
            rules_trace.append({'priority': 5, 'rule': 'channel_closed', 'applied': True, 'result': 'blocked'})
            return {
                'sellable': False,
                'message': f'Canal {channel} fechado para venda no período informado.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 5, 'rule': 'channel_closed', 'applied': False, 'result': 'passed'})

        arrival_departure_validation = ArrivalDepartureRestrictionService.validate_period(
            category=category,
            checkin=checkin,
            checkout=checkout,
        )
        if not arrival_departure_validation.get('valid'):
            rules_trace.append({'priority': 6, 'rule': 'cta_ctd', 'applied': True, 'result': 'blocked', 'details': arrival_departure_validation})
            return {
                'sellable': False,
                'message': arrival_departure_validation.get('message') or 'Período bloqueado por restrição CTA/CTD.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 6, 'rule': 'cta_ctd', 'applied': True, 'result': 'passed', 'details': arrival_departure_validation})

        stay_validation = StayRestrictionService.validate_stay(
            category=category,
            checkin=checkin,
            checkout=checkout,
            package_id=None,
        )
        if not stay_validation.get('valid'):
            rules_trace.append({'priority': 7, 'rule': 'min_nights', 'applied': True, 'result': 'blocked', 'details': stay_validation})
            return {
                'sellable': False,
                'message': stay_validation.get('message') or 'Período inválido para estadia.',
                'rules_applied': rules_trace,
                'nights': nights,
            }
        rules_trace.append({'priority': 7, 'rule': 'min_nights', 'applied': True, 'result': 'passed', 'details': stay_validation})

        bucket = RevenueManagementService._normalize_category(category)
        rules = RevenueManagementService._load_rules()
        fallback_daily = float((rules.get(bucket) or {}).get('base_bar') or 0.0)
        weekday_base_total = WeekdayBaseRateService.base_total_for_period(category=bucket, dates=dates, fallback_daily=fallback_daily)

        package_constraint = PromotionalPackageService.validate_required_package_constraint(
            category=category,
            checkin=checkin,
            checkout=checkout,
            sale_date=sale_day,
            base_total=weekday_base_total,
        )
        if not package_constraint.get('valid'):
            rules_trace.append({'priority': 8, 'rule': 'required_package', 'applied': True, 'result': 'blocked', 'details': package_constraint})
            return {
                'sellable': False,
                'message': package_constraint.get('message') or 'Pacote obrigatório para este período.',
                'rules_applied': rules_trace,
                'nights': nights,
            }

        package_preview = PromotionalPackageService.preview_price(
            category=category,
            checkin=checkin,
            checkout=checkout,
            sale_date=sale_day,
            base_total=weekday_base_total,
        )
        price_after_package = float(package_preview.get('final_total') or weekday_base_total)
        rules_trace.append({'priority': 8, 'rule': 'package', 'applied': bool(package_preview.get('applied')), 'result': 'passed', 'details': package_preview})

        promo_preview = RevenuePromotionService.preview_price(
            category=category,
            checkin=checkin,
            checkout=checkout,
            base_total=price_after_package,
            package_applied=bool(package_preview.get('applied')),
        )
        promo_apply_before_dynamic = bool((promo_preview.get('promotion') or {}).get('apply_before_dynamic', True))
        rules_trace.append({
            'priority': 9,
            'rule': 'promotion',
            'applied': bool(promo_preview.get('applied')),
            'result': 'passed',
            'details': {**promo_preview, 'apply_before_dynamic': promo_apply_before_dynamic},
        })

        price_before_dynamic = float(promo_preview.get('final_total')) if (promo_preview.get('applied') and promo_apply_before_dynamic) else price_after_package
        rules_trace.append({
            'priority': 10,
            'rule': 'weekday_base_rate',
            'applied': True,
            'result': 'passed',
            'details': {
                'dates': dates,
                'base_total_weekday': round(weekday_base_total, 2),
                'source_total_before_dynamic': round(price_before_dynamic, 2),
            },
        })

        final_total = float(price_before_dynamic)
        dynamic_details = {'factor': 1.0, 'details': {'mode': 'disabled'}}
        if apply_dynamic and dates:
            dynamic_details = cls._dynamic_factor(category=bucket, day=dates[0])
            final_total = round(final_total * float(dynamic_details.get('factor') or 1.0), 2)
        rules_trace.append({'priority': 11, 'rule': 'dynamic_revenue', 'applied': bool(apply_dynamic), 'result': 'passed', 'details': dynamic_details})

        if promo_preview.get('applied') and not promo_apply_before_dynamic:
            final_total = float(RevenuePromotionService.preview_price(
                category=category,
                checkin=checkin,
                checkout=checkout,
                base_total=final_total,
                package_applied=bool(package_preview.get('applied')),
            ).get('final_total') or final_total)

        return {
            'sellable': True,
            'message': '',
            'nights': nights,
            'rules_applied': rules_trace,
            'pricing': {
                'base_weekday_total': round(weekday_base_total, 2),
                'after_package_total': round(price_after_package, 2),
                'after_promotion_total': round(float(promo_preview.get('final_total') or price_after_package), 2),
                'final_total': round(final_total, 2),
                'package': package_preview,
                'promotion': promo_preview,
                'dynamic': dynamic_details,
            },
        }
