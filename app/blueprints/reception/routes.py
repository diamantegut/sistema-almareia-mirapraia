import json
import uuid
import os
import re
import random
import traceback
import subprocess
import shutil
import csv
import io
from datetime import datetime, timedelta
from typing import Optional
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app, send_file

from . import reception_bp
from app.utils.decorators import login_required
from app.services.data_service import (
    load_room_charges, save_room_charges, load_menu_items, load_products, 
    save_stock_entry, load_cashier_sessions, save_cashier_sessions, 
    load_payment_methods, load_room_occupancy, save_room_occupancy,
    load_cleaning_status, save_cleaning_status, load_checklist_items, save_checklist_items,
    add_inspection_log, normalize_text, format_room_number, normalize_room_simple,
    ARCHIVED_ORDERS_FILE, load_table_orders, save_table_orders,
    load_audit_logs, save_audit_logs
)
from app.services.system_config_manager import RESERVATIONS_DIR
from app.services.printer_manager import load_printers, load_printer_settings, save_printer_settings
from app.services.printing_service import process_and_print_pending_bills, print_individual_bills_thermal, print_cashier_ticket, print_cashier_ticket_async, preview_individual_bill_text
from app.services.logger_service import log_system_action, LoggerService
from app.utils.logger import log_action
from app.services.transfer_service import return_charge_to_restaurant, TableOccupiedError, TransferError
from app.services.cashier_service import CashierService
from app.services.fiscal_pool_service import FiscalPoolService
from app.services import waiting_list_service
from app.services.reservation_service import ReservationService
from app.services.reception_unified_repository import ReceptionUnifiedRepository
from app.services import checklist_service
from app.services.revenue_management_service import RevenueManagementService
from app.services.finance_dashboard_service import FinanceDashboardService
from app.services.inventory_restriction_service import InventoryRestrictionService
from app.services.arrival_departure_restriction_service import ArrivalDepartureRestrictionService
from app.services.channel_inventory_control_service import ChannelInventoryControlService
from app.services.inventory_protection_service import InventoryProtectionService
from app.services.promotional_package_service import PromotionalPackageService
from app.services.stay_restriction_service import StayRestrictionService
from app.services.revenue_promotion_service import RevenuePromotionService
from app.services.weekday_base_rate_service import WeekdayBaseRateService
from app.services.tariff_priority_engine_service import TariffPriorityEngineService
from app.services.ota_booking_rm_service import OTABookingRMService
from app.services.channel_manager_service import ChannelManagerService
from app.services.channel_category_mapping_service import ChannelCategoryMappingService
from app.services.channel_tariff_service import ChannelTariffService
from app.services.channel_inventory_planner_service import ChannelInventoryPlannerService
from app.services.channel_restriction_service import ChannelRestrictionService
from app.services.channel_rule_priority_engine_service import ChannelRulePriorityEngineService
from app.services.channel_sync_log_service import ChannelSyncLogService
from app.services.channel_commercial_audit_service import ChannelCommercialAuditService
from app.services.channel_commission_service import ChannelCommissionService
from app.services.channel_manager_dashboard_service import ChannelManagerDashboardService
from app.utils.validators import (
    validate_required, validate_phone, validate_cpf, validate_email, 
    sanitize_input, validate_date, validate_room_number
)
from app.models.database import db
from app.models.models import (
    SatisfactionSurvey,
    SatisfactionSurveyQuestion,
    SatisfactionSurveyResponse,
    SatisfactionSurveyInvite,
)
from sqlalchemy import func

# --- Helpers ---

def verify_reception_integrity():
    """Checks if critical data files and services are available."""
    try:
        # 1. Check Data Files Loading
        load_room_occupancy()
        load_cleaning_status()
        load_room_charges()
        load_table_orders()
        
        # 2. Check Session Context
        if not session.get('user'):
            return False, "Sessão de usuário inválida."
            
        return True, "Sistema íntegro."
    except Exception as e:
        return False, f"Falha na integridade de dados: {str(e)}"

def parse_br_currency(val):
    if not val: return 0.0
    if isinstance(val, (float, int)): return float(val)
    val = str(val).strip()
    val = val.replace('R$', '').replace(' ', '')
    if ',' in val:
        val_clean = val.replace('.', '').replace(',', '.')
        try:
            return float(val_clean)
        except ValueError:
            return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0

def _waiting_list_access_allowed():
    user_dept = session.get('department')
    user_role = session.get('role')
    return user_role == 'admin' or user_role == 'gerente' or user_dept == 'Recepção' or user_dept == 'Restaurante'

def _generate_unique_invite_ref(survey_id):
    for _ in range(20):
        ref = uuid.uuid4().hex[:12].upper()
        exists = SatisfactionSurveyInvite.query.filter_by(survey_id=survey_id, ref=ref).first()
        if not exists:
            return ref
    return uuid.uuid4().hex[:16].upper()


def _normalize_occupancy_map(occupancy):
    normalized = {}
    if not isinstance(occupancy, dict):
        return normalized
    for room_key, room_data in occupancy.items():
        room_id = format_room_number(room_key)
        if not room_id:
            continue
        if isinstance(room_data, dict):
            payload = dict(room_data)
            if payload.get('room_number'):
                payload['room_number'] = format_room_number(payload.get('room_number'))
        else:
            payload = room_data
        normalized[room_id] = payload
    return normalized

def _auto_invite_waiting_list_entry(entry, actor='system', trigger='status_update'):
    if not isinstance(entry, dict):
        return None
    if not bool(entry.get('consent_survey')):
        return None
    status_norm = waiting_list_service.get_public_status_view(entry.get('status')).get('code')
    if status_norm not in {'sentado', 'desistiu', 'cancelado_pela_equipe', 'nao_compareceu', 'expirado'}:
        return None
    survey = SatisfactionSurvey.query.filter_by(audience='restaurant', is_active=True).order_by(SatisfactionSurvey.updated_at.desc()).first()
    if not survey:
        return None
    for row in entry.get('survey_invites', []) or []:
        if isinstance(row, dict) and row.get('survey_id') == survey.id:
            return None
    ref = _generate_unique_invite_ref(survey.id)
    inv = SatisfactionSurveyInvite(
        survey_id=survey.id,
        waiting_list_id=entry.get('id'),
        ref=ref,
        sent_at=datetime.now(),
        delivery_status='enviada'
    )
    db.session.add(inv)
    db.session.commit()
    invite_url = url_for('guest.satisfaction_survey_by_slug', slug=survey.public_slug, _external=False) + f"?ref={ref}"
    waiting_list_service.register_survey_invite(
        entry_id=entry.get('id'),
        survey_id=survey.id,
        ref=ref,
        invited_by=actor,
        invite_url=invite_url,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'trigger': trigger}
    )
    return {
        'survey_id': survey.id,
        'ref': ref,
        'invite_url': invite_url,
        'trigger': trigger
    }

# --- Routes ---

@reception_bp.route('/reception')
@login_required
def reception_dashboard():
    # Permission Check
    user_role = session.get('role')
    role_norm = normalize_text(str(user_role or ''))
    
    user_dept = session.get('department')
    dept_norm = normalize_text(str(user_dept or ''))
    
    user_perms = session.get('permissions') or []
    has_reception_permission = isinstance(user_perms, (list, tuple, set)) and any(normalize_text(str(p)) == 'recepcao' for p in user_perms)

    if role_norm not in ['admin', 'gerente', 'recepcao', 'supervisor'] and dept_norm != 'recepcao' and not has_reception_permission:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    return render_template('reception_dashboard.html')


@reception_bp.route('/reception/revenue-management')
@login_required
def reception_revenue_management():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and 'recepcao' not in [normalize_text(str(p)) for p in user_perms]:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    return render_template('reception_revenue_management.html')


@reception_bp.route('/api/reception/revenue-management/simulate')
@login_required
def api_reception_revenue_simulate():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    mode = str(request.args.get('mode', 'basic')).strip().lower()
    advanced_mode = mode == 'advanced'
    payload = RevenueManagementService.simulate_projection(start_date=start_date, days=days, advanced_mode=advanced_mode)
    LoggerService.log_acao(
        acao='Simulação Revenue',
        entidade='Revenue Management',
        detalhes={'start_date': start_date, 'days': days, 'mode': mode},
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/rules', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_rules():
    if request.method == 'GET':
        return jsonify(RevenueManagementService._load_rules())
    payload = request.json or {}
    rules = RevenueManagementService.save_rules(payload, user=session.get('user') or 'Sistema')
    return jsonify({'success': True, 'rules': rules})


@reception_bp.route('/api/reception/revenue-management/weekday-base-rates', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_weekday_base_rates():
    if request.method == 'GET':
        return jsonify(WeekdayBaseRateService.get_rates())
    payload = request.json or {}
    saved = WeekdayBaseRateService.save_rates(payload, user=session.get('user') or 'Sistema')
    return jsonify({'success': True, 'rates': saved})


@reception_bp.route('/api/reception/revenue-management/advanced-config', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_advanced_config():
    if request.method == 'GET':
        return jsonify(RevenueManagementService._load_advanced_config())
    payload = request.json or {}
    config = RevenueManagementService.save_advanced_config(payload, user=session.get('user') or 'Sistema')
    return jsonify({'success': True, 'config': config})


@reception_bp.route('/api/reception/revenue-management/events', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_reception_revenue_events():
    if request.method == 'GET':
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        city = request.args.get('city')
        impact = request.args.get('impact')
        rows = RevenueManagementService.list_events(start_date=start_date, end_date=end_date, city=city, impact=impact)
        return jsonify({'items': rows, 'count': len(rows)})
    if request.method == 'DELETE':
        payload = request.json or {}
        event_id = payload.get('id')
        try:
            result = RevenueManagementService.delete_event(event_id, user=session.get('user') or 'Sistema')
            return jsonify({'success': True, 'result': result})
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    payload = request.json or {}
    try:
        saved = RevenueManagementService.save_event(payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'event': saved})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/inventory-protection', methods=['GET', 'POST'])
@login_required
def api_reception_inventory_protection():
    if request.method == 'GET':
        rows = InventoryProtectionService.list_rules(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            category=request.args.get('category'),
        )
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = InventoryProtectionService.apply_rule(
            category=payload.get('category'),
            protected_rooms=payload.get('protected_rooms'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            status=payload.get('status'),
            user=session.get('user') or 'Sistema',
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/inventory-protection/logs')
@login_required
def api_reception_inventory_protection_logs():
    rows = InventoryProtectionService.list_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        category=request.args.get('category'),
        user=request.args.get('user'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/simulator', methods=['POST'])
@login_required
def api_reception_revenue_simulator():
    payload = request.json or {}
    try:
        result = RevenueManagementService.revenue_scenario_simulator(
            expected_occupancy_pct=float(payload.get('expected_occupancy_pct') or 0),
            average_rate_current=float(payload.get('average_rate_current') or 0),
            average_rate_suggested=float(payload.get('average_rate_suggested') or 0),
            average_stay_nights=int(payload.get('average_stay_nights') or 1),
            horizon_days=int(payload.get('horizon_days') or 30),
        )
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/active-rules-panel')
@login_required
def api_reception_active_rules_panel():
    category = request.args.get('category') or 'mar'
    channel = request.args.get('channel') or 'Recepção'
    start_date = request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.args.get('end_date') or start_date
    apply_dynamic = str(request.args.get('apply_dynamic') or 'true').lower() in ('1', 'true', 'yes')
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'items': [], 'count': 0, 'error': 'Período inválido'}), 400
    if end < start:
        start, end = end, start
    items = []
    day = start
    while day <= end:
        checkin = day.isoformat()
        checkout = (day + timedelta(days=1)).isoformat()
        result = TariffPriorityEngineService.evaluate(
            category=category,
            channel=channel,
            checkin=checkin,
            checkout=checkout,
            sale_date=datetime.now().strftime('%Y-%m-%d'),
            apply_dynamic=apply_dynamic,
        )
        pricing = result.get('pricing') or {}
        rules = result.get('rules_applied') or []
        by_rule = {str(rule.get('rule')): rule for rule in rules if isinstance(rule, dict)}
        active_effects = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get('rule') or '')
            if not name:
                continue
            if str(rule.get('result')) == 'blocked':
                active_effects.append(name)
                continue
            details = rule.get('details')
            if isinstance(details, dict) and details.get('applied'):
                active_effects.append(name)
            elif name in ('weekday_base_rate', 'dynamic_revenue'):
                active_effects.append(name)
        items.append({
            'date': checkin,
            'category': category,
            'channel': channel,
            'sellable': bool(result.get('sellable')),
            'message': str(result.get('message') or ''),
            'final_total': float(pricing.get('final_total') or 0),
            'tariff_base': float(pricing.get('base_weekday_total') or 0),
            'package': (pricing.get('package') or {}),
            'promotion': (pricing.get('promotion') or {}),
            'dynamic': (pricing.get('dynamic') or {}),
            'cta_ctd': by_rule.get('cta_ctd'),
            'blackout': by_rule.get('blackout'),
            'stop_sell': by_rule.get('channel_closed'),
            'inventory': by_rule.get('inventory_closed'),
            'active_effects': active_effects,
            'rules_applied': rules,
        })
        day = day + timedelta(days=1)
    return jsonify({'items': items, 'count': len(items)})


@reception_bp.route('/api/reception/revenue-management/occupancy-forecast')
@login_required
def api_reception_occupancy_forecast():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    category = request.args.get('category')
    payload = RevenueManagementService.occupancy_forecast(start_date=start_date, days=days, category=category)
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/pickup-analysis')
@login_required
def api_reception_pickup_analysis():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    category = request.args.get('category')
    payload = RevenueManagementService.pickup_analysis(start_date=start_date, days=days, category=category)
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/reservation-curve')
@login_required
def api_reception_reservation_curve():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    category = request.args.get('category')
    payload = RevenueManagementService.reservation_curve(start_date=start_date, days=days, category=category)
    LoggerService.log_acao(
        acao='Consulta curva de reserva',
        entidade='Revenue Management',
        detalhes={'start_date': start_date, 'days': days, 'category': category},
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/pipeline-verification')
@login_required
def api_reception_pipeline_verification():
    payload = RevenueManagementService.pricing_pipeline_verification()
    LoggerService.log_acao(
        acao='Consulta ordem de pipeline Revenue',
        entidade='Revenue Management',
        detalhes=payload,
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/alerts')
@login_required
def api_reception_revenue_alerts():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    category = request.args.get('category')
    payload = RevenueManagementService.revenue_alerts(start_date=start_date, days=days, category=category)
    LoggerService.log_acao(
        acao='Consulta alertas Revenue',
        entidade='Revenue Management',
        detalhes={'start_date': start_date, 'days': days, 'category': category},
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/channel-performance')
@login_required
def api_reception_revenue_channel_performance():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', start_date)
    category = request.args.get('category')
    payload = RevenueManagementService.channel_performance_report(start_date=start_date, end_date=end_date, category=category)
    LoggerService.log_acao(
        acao='Consulta desempenho por canal',
        entidade='Revenue Management',
        detalhes={'start_date': start_date, 'end_date': end_date, 'category': category},
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/channel-manager/dashboard')
@login_required
def api_reception_channel_manager_dashboard():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    start_date = request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.args.get('end_date') or start_date
    category = request.args.get('category')
    if category and str(category).strip().lower() in ('', 'all', 'all_booking_categories'):
        category = None
    payload = ChannelManagerDashboardService.build_dashboard(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )
    LoggerService.log_acao(
        acao='Consulta dashboard Channel Manager',
        entidade='Revenue Management',
        detalhes={'start_date': start_date, 'end_date': end_date, 'category': category},
        nivel_severidade='INFO',
        departamento_id='Recepção',
        colaborador_id=session.get('user'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/category-strategies', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_category_strategies():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    if request.method == 'GET':
        LoggerService.log_acao(
            acao='Consulta estratégias por categoria',
            entidade='Revenue Management',
            detalhes={},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user'),
        )
        return jsonify(RevenueManagementService.get_category_strategies())
    payload = request.json or {}
    result = RevenueManagementService.save_category_strategies(payload=payload, user=session.get('user') or 'Sistema')
    return jsonify({'success': True, 'strategies': result})


@reception_bp.route('/api/reception/revenue-management/booking-commercial', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_booking_commercial():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'success': False, 'error': 'Acesso restrito.'}), 403
    if request.method == 'GET':
        payload = RevenueManagementService.get_booking_commercial_config()
        return jsonify(payload)
    payload = request.json or {}
    reason = str(payload.get('motivo') or '').strip()
    try:
        saved = RevenueManagementService.save_booking_commercial_config(
            payload=payload,
            user=session.get('user') or 'Sistema',
            reason=reason,
        )
        return jsonify({'success': True, 'config': saved})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/booking-commercial/calculate')
@login_required
def api_reception_revenue_booking_commercial_calculate():
    tarifa_direta = request.args.get('tarifa_direta', type=float)
    tarifa_liquida = request.args.get('tarifa_liquida_desejada', type=float)
    category = request.args.get('category') or 'mar'
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    result = RevenueManagementService.calculate_booking_ota_pricing(
        tarifa_direta=float(tarifa_direta or 0.0),
        tarifa_liquida_desejada=tarifa_liquida,
        category=category,
        date_str=date_str,
    )
    return jsonify({'success': True, 'result': result})


@reception_bp.route('/api/reception/revenue-management/booking-commercial/logs')
@login_required
def api_reception_revenue_booking_commercial_logs():
    rows = RevenueManagementService.list_booking_commission_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        user=request.args.get('user'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/calendar-direct-vs-ota')
@login_required
def api_reception_revenue_calendar_direct_vs_ota():
    category = request.args.get('category') or 'mar'
    start_date = request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.args.get('end_date') or start_date
    weekdays_raw = request.args.get('weekdays') or ''
    weekdays = [item.strip().lower() for item in str(weekdays_raw).split(',') if item.strip()]
    payload = RevenueManagementService.calendar_direct_vs_ota(
        category=category,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays,
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/booking-channel-status', methods=['POST'])
@login_required
def api_reception_revenue_booking_channel_status():
    payload = request.json or {}
    try:
        result = RevenueManagementService.update_booking_channel_sale_status(
            category=payload.get('category') or 'mar',
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            weekdays=payload.get('weekdays') or [],
            status=payload.get('status') or 'inactive',
            reason=str(payload.get('motivo') or '').strip(),
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/integration')
@login_required
def api_reception_ota_booking_integration():
    integration_id = request.args.get('integration_id')
    payload = OTABookingRMService.get_integration_module_status(
        integration_id=integration_id,
        user=session.get('user') or 'Sistema',
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/ota-booking/commercial-rules', methods=['GET', 'POST'])
@login_required
def api_reception_ota_booking_commercial_rules():
    if request.method == 'GET':
        return jsonify(OTABookingRMService.get_commercial_rules())
    payload = request.json or {}
    reason = str(payload.get('motivo') or payload.get('reason') or '').strip()
    try:
        saved = OTABookingRMService.save_commercial_rules(
            payload=payload,
            user=session.get('user') or 'Sistema',
            reason=reason,
        )
        return jsonify({'success': True, 'config': saved})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-rates', methods=['POST'])
@login_required
def api_reception_ota_booking_send_rates():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_rates(
            integration_id=integration_id,
            category=payload.get('category') or 'all_booking_categories',
            rate_plan_id_booking=str(payload.get('rate_plan_id_booking') or '').strip(),
            start_date=payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            end_date=payload.get('end_date') or payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            weekdays=payload.get('weekdays') or [],
            user=session.get('user') or 'Sistema',
            mode=str(payload.get('mode') or 'manual').strip().lower(),
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/rates/process-pending', methods=['POST'])
@login_required
def api_reception_ota_booking_process_pending_rates():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.process_pending_rate_distributions(
            integration_id=integration_id,
            user=session.get('user') or 'Sistema',
            limit=int(payload.get('limit') or 100),
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/rates/reprocess', methods=['POST'])
@login_required
def api_reception_ota_booking_reprocess_failed_rates():
    payload = request.json or {}
    result = OTABookingRMService.reprocess_failed_rate_distributions(
        queue_ids=payload.get('queue_ids') or [],
        user=session.get('user') or 'Sistema',
    )
    return jsonify({'success': True, 'result': result})


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/rates/pending')
@login_required
def api_reception_ota_booking_pending_rates():
    rows = OTABookingRMService.list_pending_rate_distributions(
        status=request.args.get('status'),
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-availability', methods=['POST'])
@login_required
def api_reception_ota_booking_send_availability():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_availability(
            integration_id=integration_id,
            payload={
                'start_date': payload.get('start_date'),
                'end_date': payload.get('end_date'),
                'category': payload.get('category'),
                'rooms_available': payload.get('rooms_available'),
                'dates': payload.get('dates') or [],
                'property_id': payload.get('property_id'),
            },
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-open-close', methods=['POST'])
@login_required
def api_reception_ota_booking_send_open_close():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_open_close(
            integration_id=integration_id,
            category=payload.get('category') or 'mar',
            rate_plan_id_booking=str(payload.get('rate_plan_id_booking') or '').strip(),
            start_date=payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            end_date=payload.get('end_date') or payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            weekdays=payload.get('weekdays') or [],
            status=payload.get('status') or 'inactive',
            reason=str(payload.get('motivo') or payload.get('reason') or '').strip(),
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-min-stay', methods=['POST'])
@login_required
def api_reception_ota_booking_send_min_stay():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_min_stay(
            integration_id=integration_id,
            payload={
                'category': payload.get('category'),
                'start_date': payload.get('start_date'),
                'end_date': payload.get('end_date'),
                'weekdays': payload.get('weekdays') or [],
                'min_stay_nights': payload.get('min_stay_nights'),
                'reason': payload.get('reason') or payload.get('motivo'),
            },
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-cta-ctd', methods=['POST'])
@login_required
def api_reception_ota_booking_send_cta_ctd():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_cta_ctd(
            integration_id=integration_id,
            payload={
                'category': payload.get('category'),
                'start_date': payload.get('start_date'),
                'end_date': payload.get('end_date'),
                'weekdays': payload.get('weekdays') or [],
                'cta': bool(payload.get('cta')) or str(payload.get('type') or '').strip().lower() == 'cta',
                'ctd': bool(payload.get('ctd')) or str(payload.get('type') or '').strip().lower() == 'ctd',
                'active': str(payload.get('status') or payload.get('active') or 'active').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo'),
                'reason': payload.get('reason') or payload.get('motivo'),
            },
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/send-stop-sell', methods=['POST'])
@login_required
def api_reception_ota_booking_send_stop_sell():
    payload = request.json or {}
    try:
        integration_id = OTABookingRMService.resolve_integration_id(payload.get('integration_id'))
        result = OTABookingRMService.send_stop_sell(
            integration_id=integration_id,
            category=payload.get('category') or 'mar',
            start_date=payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            end_date=payload.get('end_date') or payload.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            weekdays=payload.get('weekdays') or [],
            reason=str(payload.get('motivo') or payload.get('reason') or '').strip(),
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': bool(result.get('success')), 'result': result}), (200 if result.get('success') else 502)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/commercial-restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_ota_booking_commercial_restrictions():
    if request.method == 'GET':
        items = OTABookingRMService.list_commercial_audit(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
        )
        return jsonify({'items': items, 'count': len(items)})
    payload = request.json or {}
    try:
        result = OTABookingRMService.apply_commercial_restriction(
            category=str(payload.get('category') or 'mar'),
            start_date=str(payload.get('start_date') or datetime.now().strftime('%Y-%m-%d')),
            end_date=str(payload.get('end_date') or payload.get('start_date') or datetime.now().strftime('%Y-%m-%d')),
            weekdays=payload.get('weekdays') or [],
            rule_type=str(payload.get('rule_type') or ''),
            active=str(payload.get('status') or payload.get('active') or 'active').strip().lower() in ('1', 'true', 'yes', 'sim', 'active', 'ativo'),
            value=payload.get('value'),
            reason=str(payload.get('motivo') or payload.get('reason') or ''),
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/category-mapping', methods=['GET', 'POST'])
@login_required
def api_reception_ota_booking_category_mapping():
    if request.method == 'GET':
        return jsonify(OTABookingRMService.list_category_mappings())
    payload = request.json or {}
    reason = str(payload.get('motivo') or payload.get('reason') or '').strip()
    try:
        result = OTABookingRMService.save_category_mappings(
            payload=payload,
            user=session.get('user') or 'Sistema',
            reason=reason,
        )
        return jsonify({'success': True, 'mapping': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/ota-booking/distribution/logs')
@login_required
def api_reception_ota_booking_distribution_logs():
    success_arg = request.args.get('success')
    success_filter: Optional[bool] = None
    if success_arg is not None and str(success_arg).strip() != '':
        success_filter = str(success_arg).strip().lower() in ('1', 'true', 'yes', 'sim')
    rows = OTABookingRMService.list_distribution_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        distribution_type=request.args.get('distribution_type'),
        success=success_filter,
        status=request.args.get('status'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/ota-booking/sync-logs')
@login_required
def api_reception_ota_booking_sync_logs():
    rows = OTABookingRMService.list_sync_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        status=request.args.get('status'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/ota-booking/commercial-audit')
@login_required
def api_reception_ota_booking_commercial_audit():
    rows = OTABookingRMService.list_commercial_audit(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/ota-booking/audit')
@login_required
def api_reception_ota_booking_audit():
    payload = OTABookingRMService.build_audit_snapshot(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/channel-manager/channels', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_channels():
    if request.method == 'GET':
        items = ChannelManagerService.list_channels()
        return jsonify({'items': items, 'count': len(items)})
    payload = request.json or {}
    try:
        result = ChannelManagerService.save_channels(
            items=payload.get('items') or [],
            user=session.get('user') or 'Sistema',
            reason=str(payload.get('motivo') or payload.get('reason') or '').strip(),
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/channels/logs')
@login_required
def api_reception_channel_manager_channel_logs():
    items = ChannelManagerService.list_channel_logs(limit=request.args.get('limit', 200, type=int))
    return jsonify({'items': items, 'count': len(items)})


@reception_bp.route('/api/reception/revenue-management/channel-manager/mappings', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_mappings():
    if request.method == 'GET':
        payload = ChannelCategoryMappingService.list_mappings(channel_name=request.args.get('channel_name'))
        return jsonify(payload)
    body = request.json or {}
    try:
        payload = ChannelCategoryMappingService.save_mappings(
            payload=body,
            user=session.get('user') or 'Sistema',
            reason=str(body.get('motivo') or body.get('reason') or '').strip(),
        )
        return jsonify({'success': True, 'result': payload})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/tariffs', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_tariffs():
    if request.method == 'GET':
        payload = ChannelTariffService.get_tariff_rules()
        return jsonify(payload)
    body = request.json or {}
    try:
        payload = ChannelTariffService.save_tariff_rules(
            payload=body,
            user=session.get('user') or 'Sistema',
            reason=str(body.get('motivo') or body.get('reason') or '').strip(),
        )
        return jsonify({'success': True, 'result': payload})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/tariffs/calculate')
@login_required
def api_reception_channel_manager_tariffs_calculate():
    channel_name = request.args.get('channel_name') or 'Booking.com'
    category = request.args.get('category') or 'mar'
    start_date = request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.args.get('end_date') or start_date
    weekdays_raw = request.args.get('weekdays') or ''
    weekdays = [item.strip().lower() for item in str(weekdays_raw).split(',') if item.strip()]
    payload = ChannelTariffService.calculate_tariffs(
        channel_name=channel_name,
        category=category,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays,
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/channel-manager/inventory', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_inventory():
    if request.method == 'GET':
        weekdays_raw = request.args.get('weekdays') or ''
        weekdays = [item.strip().lower() for item in str(weekdays_raw).split(',') if item.strip()]
        payload = ChannelInventoryPlannerService.build_snapshot(
            category=request.args.get('category') or 'mar',
            start_date=request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            end_date=request.args.get('end_date') or request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            weekdays=weekdays,
        )
        return jsonify(payload)
    body = request.json or {}
    try:
        payload = ChannelInventoryPlannerService.apply_inventory_plan(
            payload=body,
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': True, 'result': payload})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/inventory/audit')
@login_required
def api_reception_channel_manager_inventory_audit():
    rows = ChannelInventoryPlannerService.list_audit_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        category=request.args.get('category'),
        channel=request.args.get('channel'),
        user=request.args.get('user'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/channel-manager/restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_restrictions():
    if request.method == 'GET':
        rows = ChannelRestrictionService.list_restrictions(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            category=request.args.get('category'),
            channel=request.args.get('channel'),
            restriction_type=request.args.get('restriction_type'),
            status=request.args.get('status'),
        )
        return jsonify({'items': rows, 'count': len(rows)})
    body = request.json or {}
    try:
        result = ChannelRestrictionService.apply_restriction(
            category=body.get('category') or 'mar',
            channel=body.get('channel') or 'Booking.com',
            restriction_type=body.get('restriction_type') or 'stop_sell',
            start_date=body.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            end_date=body.get('end_date') or body.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            weekdays=body.get('weekdays') or [],
            status=body.get('status') or 'active',
            value=body.get('value'),
            reason=str(body.get('motivo') or body.get('reason') or '').strip(),
            user=session.get('user') or 'Sistema',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/restrictions/audit')
@login_required
def api_reception_channel_manager_restrictions_audit():
    rows = ChannelRestrictionService.list_audit_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        category=request.args.get('category'),
        channel=request.args.get('channel'),
        user=request.args.get('user'),
        restriction_type=request.args.get('restriction_type'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/channel-manager/rules/priority/evaluate')
@login_required
def api_reception_channel_manager_rules_priority_evaluate():
    checkin = request.args.get('checkin') or datetime.now().strftime('%Y-%m-%d')
    checkout = request.args.get('checkout')
    if not checkout:
        checkout = (PeriodSelectorService.parse_date(checkin).date().fromordinal(
            PeriodSelectorService.parse_date(checkin).date().toordinal() + 1
        )).isoformat()
    result = ChannelRulePriorityEngineService.evaluate(
        category=request.args.get('category') or 'mar',
        channel=request.args.get('channel') or 'Booking.com',
        checkin=checkin,
        checkout=checkout,
        sale_date=request.args.get('sale_date') or datetime.now().strftime('%Y-%m-%d'),
        package_selected=request.args.get('package_selected'),
        apply_dynamic=str(request.args.get('apply_dynamic') or 'true').strip().lower() in ('1', 'true', 'yes', 'sim'),
    )
    return jsonify(result)


@reception_bp.route('/api/reception/revenue-management/channel-manager/calendar')
@login_required
def api_reception_channel_manager_calendar():
    channel = request.args.get('channel') or 'Booking.com'
    category_filter = request.args.get('category') or 'all_booking_categories'
    rule_type_filter = str(request.args.get('rule_type') or '').strip().lower()
    start_date = request.args.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = request.args.get('end_date') or start_date
    weekdays_raw = request.args.get('weekdays') or ''
    weekdays = [item.strip().lower() for item in str(weekdays_raw).split(',') if item.strip()]
    categories = ['areia', 'mar_familia', 'mar', 'alma_banheira', 'alma', 'alma_diamante'] if category_filter == 'all_booking_categories' else [category_filter]
    start_dt = PeriodSelectorService.parse_date(start_date).date()
    end_dt = PeriodSelectorService.parse_date(end_date).date()
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    days = max(1, (end_dt - start_dt).days + 1)
    sim = RevenueManagementService.simulate_projection(start_date=start_dt.isoformat(), days=days, advanced_mode=True)
    sim_map = {
        (str(row.get('date') or ''), str(row.get('category') or '')): float(row.get('current_bar') or row.get('base_bar') or 0.0)
        for row in (sim.get('rows') or [])
        if isinstance(row, dict)
    }
    rows = []
    current = start_dt
    while current <= end_dt:
        day_iso = current.isoformat()
        if weekdays:
            weekday_code = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][current.weekday()]
            if weekday_code not in weekdays:
                current = current.fromordinal(current.toordinal() + 1)
                continue
        next_day = current.fromordinal(current.toordinal() + 1).isoformat()
        for category in categories:
            direct = sim_map.get((day_iso, RevenueManagementService._booking_category_bucket(category)), 0.0)
            tariff_payload = ChannelTariffService.calculate_tariffs(
                channel_name=channel,
                category=category,
                start_date=day_iso,
                end_date=day_iso,
                weekdays=[],
            )
            tariff_row = (tariff_payload.get('rows') or [{}])[0]
            inv_payload = ChannelInventoryPlannerService.build_snapshot(
                category=category,
                start_date=day_iso,
                end_date=day_iso,
                weekdays=[],
            )
            inv_day = (inv_payload.get('rows') or [{}])[0]
            channels = inv_day.get('channels') if isinstance(inv_day, dict) else []
            channel_row = next((item for item in (channels or []) if str(item.get('channel') or '') == str(channel)), {})
            day_rules = ChannelRestrictionService.resolve_day_rules(category=category, channel=channel, day=day_iso)
            engine = ChannelRulePriorityEngineService.evaluate(
                category=category,
                channel=channel,
                checkin=day_iso,
                checkout=next_day,
                sale_date=day_iso,
                package_selected=None,
                apply_dynamic=True,
            )
            labels = day_rules.get('labels') or []
            if rule_type_filter and rule_type_filter not in [str(item).strip().lower() for item in labels]:
                if rule_type_filter not in str((engine.get('rules_applied') or [{}])[-1].get('rule') if engine.get('rules_applied') else '').lower():
                    continue
            rows.append({
                'date': day_iso,
                'category': category,
                'channel': channel,
                'tarifa_direta': round(float(tariff_row.get('tarifa_direta') or direct), 2),
                'tarifa_canal': round(float((engine.get('pricing') or {}).get('tarifa_final_calculada') or tariff_row.get('tarifa_canal') or 0.0), 2),
                'disponibilidade': int(channel_row.get('available_for_sale') or 0),
                'status_aberto': bool(engine.get('sellable')),
                'restricoes_ativas': labels,
                'promocao_ativa': day_rules.get('promocao_especifica') or '',
                'pacote_ativo': day_rules.get('pacote_obrigatorio') or '',
                'motivo_indisponibilidade': engine.get('message') or '',
                'rules_applied': engine.get('rules_applied') or [],
            })
        current = current.fromordinal(current.toordinal() + 1)
    return jsonify({
        'channel': channel,
        'category': category_filter,
        'start_date': start_dt.isoformat(),
        'end_date': end_dt.isoformat(),
        'weekdays': weekdays,
        'rule_type': rule_type_filter or None,
        'rows': rows,
        'count': len(rows),
    })


@reception_bp.route('/api/reception/revenue-management/channel-manager/calendar/actions', methods=['POST'])
@login_required
def api_reception_channel_manager_calendar_actions():
    body = request.json or {}
    action = str(body.get('action') or '').strip().lower()
    category = body.get('category') or 'mar'
    channel = body.get('channel') or 'Booking.com'
    start_date = body.get('start_date') or datetime.now().strftime('%Y-%m-%d')
    end_date = body.get('end_date') or start_date
    weekdays = body.get('weekdays') or []
    reason = str(body.get('motivo') or body.get('reason') or '').strip()
    user = session.get('user') or 'Sistema'
    try:
        if action == 'editar_tarifa':
            current = ChannelTariffService.get_tariff_rules()
            channels = current.get('channels') if isinstance(current, dict) else []
            selected = next((item for item in (channels or []) if str(item.get('channel_name') or '') == str(channel)), None) or {'channel_name': channel}
            manual = dict(selected.get('manual_tariff_by_category') or {})
            manual[str(category)] = float(body.get('tarifa_manual') or 0.0)
            payload = {
                'channels': [{
                    'channel_name': channel,
                    'tariff_mode': 'usar_tarifa_manual_canal',
                    'manual_tariff_by_category': manual,
                }]
            }
            result = ChannelTariffService.save_tariff_rules(payload=payload, user=user, reason=reason)
            return jsonify({'success': True, 'result': result})
        if action in ('abrir_venda', 'fechar_venda'):
            result = ChannelInventoryControlService.apply_channel_restriction(
                category=category,
                channel=channel,
                start_date=start_date,
                end_date=end_date,
                status='inactive' if action == 'abrir_venda' else 'active',
                user=user,
                reason=reason,
                weekdays=weekdays,
                origin='channel_manager_calendar',
            )
            ChannelRestrictionService.apply_restriction(
                category=category,
                channel=channel,
                restriction_type='aberto_fechado',
                start_date=start_date,
                end_date=end_date,
                weekdays=weekdays,
                status='active',
                value='open' if action == 'abrir_venda' else 'closed',
                reason=reason,
                user=user,
            )
            return jsonify({'success': True, 'result': result})
        mapping = {
            'aplicar_cta': ('cta', True),
            'aplicar_ctd': ('ctd', True),
            'aplicar_min_stay': ('min_stay', int(body.get('value') or 1)),
            'aplicar_promocao': ('promocao_especifica', str(body.get('value') or '')),
            'aplicar_pacote': ('pacote_obrigatorio', str(body.get('value') or '')),
            'aplicar_stop_sell': ('stop_sell', True),
        }
        if action not in mapping:
            return jsonify({'success': False, 'error': 'Ação inválida.'}), 400
        restriction_type, value = mapping[action]
        result = ChannelRestrictionService.apply_restriction(
            category=category,
            channel=channel,
            restriction_type=restriction_type,
            start_date=start_date,
            end_date=end_date,
            weekdays=weekdays,
            status='active',
            value=value,
            reason=reason,
            user=user,
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/sync-logs', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_sync_logs():
    if request.method == 'POST':
        body = request.json or {}
        try:
            row = ChannelSyncLogService.append_log(
                channel=body.get('channel') or 'Booking.com',
                sync_type=body.get('sync_type') or 'tarifa',
                category=body.get('category') or '',
                start_date=body.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
                end_date=body.get('end_date') or body.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
                payload_sent=body.get('payload_sent') or {},
                response_received=body.get('response_received') or {},
                status=body.get('status') or 'sucesso',
                attempts=int(body.get('attempts') or 1),
                error_message=body.get('error_message') or '',
                user=session.get('user') or 'Sistema',
            )
            return jsonify({'success': True, 'result': row})
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    channel = request.args.get('channel')
    sync_type = request.args.get('sync_type')
    status = request.args.get('status')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    internal_rows = ChannelSyncLogService.list_logs(
        start_date=start_date,
        end_date=end_date,
        channel=channel,
        sync_type=sync_type,
        status=status,
    )
    ota_rows_raw = OTABookingRMService.list_sync_logs(
        start_date=start_date,
        end_date=end_date,
        status=status,
    )
    type_map = {
        'envio_tarifas': 'tarifa',
        'envio_disponibilidade': 'disponibilidade',
        'open_close': 'open_close',
        'cta_ctd': 'cta',
        'min_stay': 'min_stay',
        'stop_sell': 'open_close',
        'autenticacao': 'autenticacao',
        'pacote': 'pacote',
    }
    ota_rows = []
    for item in (ota_rows_raw or []):
        mapped_type = type_map.get(str(item.get('type') or item.get('distribution_type') or '').strip().lower(), 'tarifa')
        if sync_type and str(sync_type).strip().lower() != mapped_type:
            continue
        channel_name = str(item.get('channel') or 'Booking.com')
        if channel and str(channel).strip().lower() != channel_name.strip().lower():
            continue
        ota_rows.append({
            'id': item.get('id'),
            'timestamp': item.get('timestamp'),
            'user': item.get('user') or 'Sistema',
            'channel': channel_name,
            'sync_type': mapped_type,
            'category': item.get('category') or '',
            'period': item.get('period') or {},
            'payload_sent': item.get('payload') or {},
            'response_received': item.get('response') or item.get('response_preview') or {},
            'status': str(item.get('status') or '').strip().lower() or ('sucesso' if str(item.get('error_message') or '').strip() == '' else 'erro'),
            'attempts': int(item.get('attempts') or 1),
            'error_message': item.get('error_message') or '',
        })
    rows = list(internal_rows) + ota_rows
    rows.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/channel-manager/commercial-audit')
@login_required
def api_reception_channel_manager_commercial_audit():
    rows = ChannelCommercialAuditService.list_consolidated(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        event_type=request.args.get('event_type'),
        channel=request.args.get('channel'),
        category=request.args.get('category'),
        user=request.args.get('user'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/channel-manager/commissions', methods=['GET', 'POST'])
@login_required
def api_reception_channel_manager_commissions():
    if request.method == 'GET':
        return jsonify(ChannelCommissionService.get_commission_rules())
    body = request.json or {}
    try:
        result = ChannelCommissionService.save_commission_rules(
            payload=body,
            user=session.get('user') or 'Sistema',
            reason=str(body.get('motivo') or body.get('reason') or '').strip(),
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-management/channel-manager/commissions/calculate')
@login_required
def api_reception_channel_manager_commissions_calculate():
    result = ChannelCommissionService.calculate_channel_tariff(
        channel_name=request.args.get('channel_name') or 'Booking.com',
        category=request.args.get('category') or 'mar',
        day_iso=request.args.get('date') or datetime.now().strftime('%Y-%m-%d'),
        direct_tariff=float(request.args.get('tarifa_direta') or 0.0),
    )
    return jsonify(result)


@reception_bp.route('/api/reception/revenue-management/channel-manager/commissions/audit')
@login_required
def api_reception_channel_manager_commissions_audit():
    rows = ChannelCommissionService.list_audit_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        channel=request.args.get('channel'),
        user=request.args.get('user'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-management/auto-demand-adjustment')
@login_required
def api_reception_auto_demand_adjustment():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    days = request.args.get('days', 30, type=int)
    category = request.args.get('category')
    revpar_target = request.args.get('revpar_target', type=float)
    payload = RevenueManagementService.auto_demand_tariff_adjustment(
        start_date=start_date,
        days=days,
        category=category,
        revpar_target=revpar_target,
    )
    return jsonify(payload)


@reception_bp.route('/api/reception/revenue-management/apply', methods=['POST'])
@login_required
def api_reception_revenue_apply():
    payload = request.json or {}
    items = payload.get('items') or []
    justification = str(payload.get('justification') or '').strip()
    origin = str(payload.get('origin') or 'suggestion').strip().lower()
    result = RevenueManagementService.apply_suggestions(
        payload_rows=items,
        justification=justification,
        user=session.get('user') or 'Sistema',
        origin=origin,
    )
    return jsonify({'success': True, 'result': result})


@reception_bp.route('/api/reception/revenue-management/reset-default', methods=['POST'])
@login_required
def api_reception_revenue_reset_default():
    payload = request.json or {}
    items = payload.get('items') or []
    justification = str(payload.get('justification') or '').strip()
    result = RevenueManagementService.reset_to_default(
        payload_rows=items,
        justification=justification,
        user=session.get('user') or 'Sistema',
    )
    return jsonify({'success': True, 'result': result})


@reception_bp.route('/api/reception/revenue-management/audit-report')
@login_required
def api_reception_revenue_audit_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user_filter = request.args.get('user')
    report = RevenueManagementService.get_audit_report(start_date, end_date, user_filter)
    return jsonify({'items': report, 'count': len(report)})


@reception_bp.route('/reception/revenue-packages')
@login_required
def reception_revenue_packages():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and 'recepcao' not in [normalize_text(str(p)) for p in user_perms]:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_revenue_packages.html', categories=categories, today_iso=today_iso)


@reception_bp.route('/api/reception/revenue-packages', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_packages():
    if request.method == 'GET':
        status = request.args.get('status')
        rows = PromotionalPackageService.list_packages(status=status)
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        created = PromotionalPackageService.create_package(payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': created})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-packages/<package_id>', methods=['PUT', 'DELETE'])
@login_required
def api_reception_revenue_package_item(package_id):
    try:
        if request.method == 'DELETE':
            result = PromotionalPackageService.delete_package(package_id=package_id, user=session.get('user') or 'Sistema')
            return jsonify({'success': True, 'result': result})
        payload = request.json or {}
        updated = PromotionalPackageService.update_package(package_id=package_id, payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-packages/logs')
@login_required
def api_reception_revenue_packages_logs():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user = request.args.get('user')
    rows = PromotionalPackageService.list_logs(start_date=start_date, end_date=end_date, user=user)
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-packages/preview-price')
@login_required
def api_reception_revenue_packages_preview_price():
    category = request.args.get('category')
    checkin = request.args.get('checkin')
    checkout = request.args.get('checkout')
    base_total = request.args.get('base_total', type=float)
    if not category or not checkin or not checkout:
        return jsonify({'applied': False, 'normal_total': 0.0, 'final_total': 0.0, 'package': None, 'nights': 0})
    preview = PromotionalPackageService.preview_price(
        category=category,
        checkin=checkin,
        checkout=checkout,
        sale_date=datetime.now().strftime('%Y-%m-%d'),
        base_total=base_total,
    )
    return jsonify(preview)


@reception_bp.route('/reception/stay-restrictions')
@login_required
def reception_stay_restrictions():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and 'recepcao' not in [normalize_text(str(p)) for p in user_perms]:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    packages = PromotionalPackageService.list_packages()
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_stay_restrictions.html', categories=categories, packages=packages, today_iso=today_iso)


@reception_bp.route('/api/reception/stay-restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_stay_restrictions():
    if request.method == 'GET':
        status = request.args.get('status')
        rows = StayRestrictionService.list_rules(status=status)
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        created = StayRestrictionService.create_rule(payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': created})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/stay-restrictions/<rule_id>', methods=['PUT', 'DELETE'])
@login_required
def api_reception_stay_restriction_item(rule_id):
    try:
        if request.method == 'DELETE':
            result = StayRestrictionService.delete_rule(rule_id=rule_id, user=session.get('user') or 'Sistema')
            return jsonify({'success': True, 'result': result})
        payload = request.json or {}
        updated = StayRestrictionService.update_rule(rule_id=rule_id, payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/stay-restrictions/logs')
@login_required
def api_reception_stay_restrictions_logs():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user = request.args.get('user')
    rows = StayRestrictionService.list_logs(start_date=start_date, end_date=end_date, user=user)
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/reception/revenue-promotions')
@login_required
def reception_revenue_promotions():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and 'recepcao' not in [normalize_text(str(p)) for p in user_perms]:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_revenue_promotions.html', categories=categories, today_iso=today_iso)


@reception_bp.route('/api/reception/revenue-promotions', methods=['GET', 'POST'])
@login_required
def api_reception_revenue_promotions():
    if request.method == 'GET':
        status = request.args.get('status')
        rows = RevenuePromotionService.list_promotions(status=status)
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        created = RevenuePromotionService.create_promotion(payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': created})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-promotions/<promotion_id>', methods=['PUT', 'DELETE'])
@login_required
def api_reception_revenue_promotion_item(promotion_id):
    try:
        if request.method == 'DELETE':
            result = RevenuePromotionService.delete_promotion(promotion_id=promotion_id, user=session.get('user') or 'Sistema')
            return jsonify({'success': True, 'result': result})
        payload = request.json or {}
        updated = RevenuePromotionService.update_promotion(promotion_id=promotion_id, payload=payload, user=session.get('user') or 'Sistema')
        return jsonify({'success': True, 'item': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/revenue-promotions/logs')
@login_required
def api_reception_revenue_promotions_logs():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user = request.args.get('user')
    rows = RevenuePromotionService.list_logs(start_date=start_date, end_date=end_date, user=user)
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/revenue-promotions/preview-price')
@login_required
def api_reception_revenue_promotions_preview_price():
    category = request.args.get('category')
    checkin = request.args.get('checkin')
    checkout = request.args.get('checkout')
    base_total = request.args.get('base_total', type=float)
    package_applied = str(request.args.get('package_applied') or '').lower() in ('1', 'true', 'yes')
    if not category or not checkin or not checkout:
        return jsonify({'applied': False, 'base_total': 0.0, 'final_total': 0.0, 'promotion': None})
    preview = RevenuePromotionService.preview_price(
        category=category,
        checkin=checkin,
        checkout=checkout,
        base_total=base_total or 0.0,
        package_applied=package_applied,
    )
    return jsonify(preview)


@reception_bp.route('/api/reception/tariff-engine/preview')
@login_required
def api_reception_tariff_engine_preview():
    category = request.args.get('category')
    channel = request.args.get('channel') or 'Recepção'
    checkin = request.args.get('checkin')
    checkout = request.args.get('checkout')
    apply_dynamic = str(request.args.get('apply_dynamic') or 'false').lower() in ('1', 'true', 'yes')
    if not category or not checkin or not checkout:
        return jsonify({'sellable': False, 'message': 'Dados insuficientes para cálculo.'}), 400
    result = TariffPriorityEngineService.evaluate(
        category=category,
        channel=channel,
        checkin=checkin,
        checkout=checkout,
        sale_date=datetime.now().strftime('%Y-%m-%d'),
        apply_dynamic=apply_dynamic,
    )
    return jsonify(result)


@reception_bp.route('/api/reception/reservations/<reservation_id>/timeline')
@login_required
def api_reception_reservation_timeline(reservation_id):
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        return jsonify({'error': 'Acesso negado'}), 403

    return jsonify(FinanceDashboardService.get_reservation_timeline(reservation_id))


@reception_bp.route('/reception/inventory-restrictions')
@login_required
def reception_inventory_restrictions():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_inventory_restrictions.html', categories=categories, today_iso=today_iso)


@reception_bp.route('/api/reception/inventory-restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_inventory_restrictions():
    if request.method == 'GET':
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        category = request.args.get('category')
        rows = InventoryRestrictionService.list_restrictions(start_date=start_date, end_date=end_date, category=category)
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = InventoryRestrictionService.apply_restriction(
            category=payload.get('category'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            status=payload.get('status'),
            user=session.get('user') or 'Sistema',
            reason=str(payload.get('reason') or '').strip(),
            weekdays=payload.get('weekdays') or [],
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/inventory-restrictions/logs')
@login_required
def api_reception_inventory_restrictions_logs():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    user = request.args.get('user')
    rows = InventoryRestrictionService.list_logs(start_date=start_date, end_date=end_date, user=user, category=category)
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/reception/arrival-departure-restrictions')
@login_required
def reception_arrival_departure_restrictions():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_arrival_departure_restrictions.html', categories=categories, today_iso=today_iso)


@reception_bp.route('/api/reception/arrival-departure-restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_arrival_departure_restrictions():
    if request.method == 'GET':
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        category = request.args.get('category')
        restriction_type = request.args.get('restriction_type')
        status = request.args.get('status')
        rows = ArrivalDepartureRestrictionService.list_restrictions(
            start_date=start_date,
            end_date=end_date,
            category=category,
            restriction_type=restriction_type,
            status=status,
        )
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = ArrivalDepartureRestrictionService.apply_restriction(
            restriction_type=payload.get('restriction_type'),
            category=payload.get('category'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            status=payload.get('status'),
            user=session.get('user') or 'Sistema',
            reason=str(payload.get('reason') or '').strip(),
            weekdays=payload.get('weekdays') or [],
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/arrival-departure-restrictions/logs')
@login_required
def api_reception_arrival_departure_restrictions_logs():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category = request.args.get('category')
    restriction_type = request.args.get('restriction_type')
    user = request.args.get('user')
    rows = ArrivalDepartureRestrictionService.list_logs(
        start_date=start_date,
        end_date=end_date,
        user=user,
        category=category,
        restriction_type=restriction_type,
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/reception/channel-inventory-controls')
@login_required
def reception_channel_inventory_controls():
    user_role = normalize_text(str(session.get('role') or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = 'recepcao' in [normalize_text(str(p)) for p in user_perms]
    if user_role not in ['admin', 'gerente', 'recepcao', 'supervisor'] and not has_reception_permission:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    categories = list(ReservationService().get_room_mapping().keys())
    channels = ['Booking.com', 'Expedia', 'Motor de Reservas', 'Recepção', 'Telefone', 'WhatsApp', 'Airbnb']
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('reception_channel_inventory_controls.html', categories=categories, channels=channels, today_iso=today_iso)


@reception_bp.route('/api/reception/channel-restrictions', methods=['GET', 'POST'])
@login_required
def api_reception_channel_restrictions():
    if request.method == 'GET':
        rows = ChannelInventoryControlService.list_channel_restrictions(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            category=request.args.get('category'),
            channel=request.args.get('channel'),
        )
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = ChannelInventoryControlService.apply_channel_restriction(
            category=payload.get('category'),
            channel=payload.get('channel'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            status=payload.get('status'),
            user=session.get('user') or 'Sistema',
            reason=str(payload.get('reason') or payload.get('motivo') or '').strip(),
            weekdays=payload.get('weekdays') or [],
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/channel-restrictions/logs')
@login_required
def api_reception_channel_restrictions_logs():
    rows = ChannelInventoryControlService.list_channel_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        user=request.args.get('user'),
        category=request.args.get('category'),
        channel=request.args.get('channel'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/blackout-dates', methods=['GET', 'POST'])
@login_required
def api_reception_blackout_dates():
    if request.method == 'GET':
        rows = ChannelInventoryControlService.list_blackouts(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            category=request.args.get('category'),
        )
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = ChannelInventoryControlService.apply_blackout(
            category=payload.get('category'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            status=payload.get('status'),
            reason=str(payload.get('reason') or '').strip(),
            user=session.get('user') or 'Sistema',
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/blackout-dates/logs')
@login_required
def api_reception_blackout_dates_logs():
    rows = ChannelInventoryControlService.list_blackout_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        user=request.args.get('user'),
        category=request.args.get('category'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/channel-allotments', methods=['GET', 'POST'])
@login_required
def api_reception_channel_allotments():
    if request.method == 'GET':
        rows = ChannelInventoryControlService.list_allotments(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            category=request.args.get('category'),
            channel=request.args.get('channel'),
        )
        return jsonify({'items': rows, 'count': len(rows)})
    payload = request.json or {}
    try:
        result = ChannelInventoryControlService.apply_allotment(
            category=payload.get('category'),
            channel=payload.get('channel'),
            rooms=payload.get('rooms'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date') or payload.get('start_date'),
            user=session.get('user') or 'Sistema',
            weekdays=payload.get('weekdays') or [],
            origin='manual',
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@reception_bp.route('/api/reception/channel-allotments/logs')
@login_required
def api_reception_channel_allotments_logs():
    rows = ChannelInventoryControlService.list_allotment_logs(
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        user=request.args.get('user'),
        category=request.args.get('category'),
        channel=request.args.get('channel'),
    )
    return jsonify({'items': rows, 'count': len(rows)})


@reception_bp.route('/api/reception/available-categories')
@login_required
def api_reception_available_categories():
    checkin = request.args.get('checkin')
    checkout = request.args.get('checkout')
    channel = request.args.get('channel') or 'Recepção'
    if not checkin or not checkout:
        return jsonify({'available_categories': []})
    service = ReservationService()
    categories = service.available_categories_for_period(checkin, checkout, channel=channel)
    return jsonify({'available_categories': categories, 'count': len(categories)})

@reception_bp.route('/reception/rooms', methods=['GET', 'POST'])
@login_required
def reception_rooms():
    # 1. Integrity Check
    is_valid, msg = verify_reception_integrity()
    if not is_valid:
        flash(f"ERRO CRÍTICO: {msg}", 'error')
        log_action('Integrity Check Failed', f'Reception: {msg}', department='Recepção')
        return redirect(url_for('main.index'))

    # Permission Check
    user_role = session.get('role')
    role_norm = normalize_text(str(user_role or ''))
    
    user_dept = session.get('department')
    dept_norm = normalize_text(str(user_dept or ''))
    
    user_perms = session.get('permissions') or []
    has_reception_permission = isinstance(user_perms, (list, tuple, set)) and any(normalize_text(str(p)) == 'recepcao' for p in user_perms)

    if role_norm not in ['admin', 'gerente', 'recepcao', 'supervisor'] and dept_norm != 'recepcao' and not has_reception_permission:
         flash('Acesso restrito.')
         return redirect(url_for('main.index'))

    occupancy = _normalize_occupancy_map(load_room_occupancy())
    cleaning_status = load_cleaning_status()
    checklist_items = checklist_service.load_checklist_items()
    
    # Pre-allocation integration
    upcoming_checkins = {}
    upcoming_reservations = []
    requested_reservation_id = (request.args.get('reservation_id') or '').strip()
    open_checkin = (request.args.get('open_checkin') or '').strip().lower() in ['1', 'true', 'yes', 'on']
    try:
        res_service = ReservationService()
        upcoming_reservations = res_service.get_upcoming_checkins()
        if requested_reservation_id:
            requested_res = res_service.get_reservation_for_checkin(requested_reservation_id)
            if requested_res:
                already_loaded = any(str(item.get('id')) == str(requested_reservation_id) for item in upcoming_reservations)
                if not already_loaded:
                    upcoming_reservations.append(requested_res)
        for item in upcoming_reservations:
            if item.get('room'):
                upcoming_checkins[str(item['room'])] = item
    except Exception as e:
        print(f"Error loading upcoming checkins: {e}")

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'pay_charge':
            current_user = session.get('user')
            # Find current open reception session
            current_session = CashierService.get_active_session('guest_consumption')
            if not current_session:
                 current_session = CashierService.get_active_session('reception_room_billing')
            
            if not current_session:
                flash('É necessário abrir o caixa de Consumo de Hóspedes antes de receber pagamentos.')
                return redirect(url_for('reception.reception_cashier'))
            
            charge_id = request.form.get('charge_id')
            
            # MULTI-PAYMENT LOGIC
            payment_data_json = request.form.get('payment_data')
            payments = []
            
            if payment_data_json:
                try:
                    payments = json.loads(payment_data_json)
                except json.JSONDecodeError:
                    flash('Erro ao processar dados de pagamento.')
                    return redirect(url_for('reception.reception_rooms'))
            
            if not payments:
                flash('Nenhum pagamento informado.')
                return redirect(url_for('reception.reception_rooms'))

            emit_invoice = session.get('role') == 'admin' and request.form.get('emit_invoice') == 'on'
            
            room_charges = load_room_charges()
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge and charge.get('status') == 'pending':
                payment_methods_list = load_payment_methods()
                
                # Validate Total
                total_paid = sum(float(p.get('amount', 0)) for p in payments)
                charge_total = float(charge['total'])
                
                if abs(total_paid - charge_total) > 0.05: # Tolerance
                     flash(f'Valor pago (R$ {total_paid:.2f}) difere do total da conta (R$ {charge_total:.2f}).')
                     return redirect(url_for('reception.reception_rooms'))

                # Generate Payment Group ID
                payment_group_id = str(uuid.uuid4()) if len(payments) > 1 else None
                total_payment_group_amount = total_paid if payment_group_id else 0
                
                # Prepare Fiscal Payments List
                fiscal_payments = []
                primary_payment_method_id = payments[0].get('id')

                # Process Transactions
                for p in payments:
                    p_amount = float(p.get('amount', 0))
                    p_id = p.get('id')
                    p_name = p.get('name')
                    
                    # Verify name against ID if possible
                    p_method_obj = next((m for m in payment_methods_list if str(m['id']) == str(p_id)), None)
                    if p_method_obj:
                        p_name = p_method_obj['name']
                        is_fiscal = p_method_obj.get('is_fiscal', False)
                    else:
                        is_fiscal = False
                    
                    fiscal_payments.append({
                        'method': p_name,
                        'amount': p_amount,
                        'is_fiscal': is_fiscal
                    })

                    CashierService.add_transaction(
                        cashier_type='guest_consumption',
                        amount=p_amount,
                        description=f"Pagamento Quarto {charge['room_number']} ({p_name})",
                        payment_method=p_name,
                        user=current_user,
                        details={
                            'room_number': charge['room_number'],
                            'emit_invoice': emit_invoice,
                            'category': 'Pagamento de Conta',
                            'payment_group_id': payment_group_id,
                            'total_payment_group_amount': total_payment_group_amount,
                            'payment_details': payments # Store all payments in details too
                        }
                    )

                # Update Charge
                charge['status'] = 'paid'
                charge['payment_method'] = 'Múltiplos' if len(payments) > 1 else fiscal_payments[0]['method']
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['reception_cashier_id'] = current_session['id']
                charge['payment_details'] = payments
                save_room_charges(room_charges)
                
                flash(f"Pagamento de R$ {charge['total']:.2f} recebido com sucesso.")

                # FISCAL POOL INTEGRATION
                try:
                    items_list = charge.get('items', [])
                    if isinstance(items_list, str):
                        try: items_list = json.loads(items_list)
                        except: items_list = []
                    
                    occupancy = load_room_occupancy()
                    guest_name = occupancy.get(str(charge['room_number']), {}).get('guest_name', 'Hóspede')

                    FiscalPoolService.add_to_pool(
                        origin='reception',
                        original_id=charge['id'],
                        total_amount=float(charge['total']),
                        items=items_list,
                        payment_methods=fiscal_payments,
                        user=current_user,
                        customer_info={'room_number': charge['room_number'], 'guest_name': guest_name}
                    )
                except Exception as e:
                    current_app.logger.error(f"Error adding charge to fiscal pool: {e}")

            else:
                flash('Conta não encontrada ou já paga.')
            
            return redirect(url_for('reception.reception_rooms'))
        
        if action == 'add_checklist_item':
            new_item = request.form.get('item_name')
            if new_item:
                # Check for duplicate
                existing = next((i for i in checklist_items if (i.get('name') if isinstance(i, dict) else i) == new_item), None)
                if not existing:
                    checklist_service.add_catalog_item(new_item, 'Recepção', 'un', 'Recepção')
                    flash('Item adicionado ao checklist.')
                else:
                    flash('Item já existe no checklist.')
            return redirect(url_for('reception.reception_rooms'))
            
        if action == 'delete_checklist_item':
            item_id = request.form.get('item_id')
            item_name = request.form.get('item_name')
            
            if item_id:
                checklist_service.remove_catalog_item(item_id)
                flash('Item removido do checklist.')
            elif item_name:
                # Legacy support: find by name
                items = checklist_service.load_checklist_items()
                found = next((i for i in items if i.get('name') == item_name), None)
                if found:
                    checklist_service.remove_catalog_item(found['id'])
                    flash('Item removido do checklist.')

            return redirect(url_for('reception.reception_rooms'))

        if action == 'inspect_room':
            try:
                room_num_raw = sanitize_input(request.form.get('room_number'))
                # Format room number
                room_num = format_room_number(room_num_raw)
                
                result = sanitize_input(request.form.get('inspection_result')) # 'passed' or 'failed'
                observation = sanitize_input(request.form.get('observation'))
                
                if result not in ['passed', 'failed']:
                     flash('Resultado da inspeção inválido.')
                     return redirect(url_for('reception.reception_rooms'))

                # Log the inspection
                log_entry = {
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'room_number': room_num,
                    'user': session.get('user', 'Recepção'),
                    'result': result,
                    'observation': observation,
                }
                add_inspection_log(log_entry)

                if room_num:
                    if str(room_num) not in cleaning_status:
                        cleaning_status[str(room_num)] = {}
                    
                    if result == 'passed':
                        cleaning_status[str(room_num)]['status'] = 'inspected'
                        cleaning_status[str(room_num)]['inspected_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        cleaning_status[str(room_num)]['inspected_by'] = session.get('user', 'Recepção')
                        # Clear any previous rejection info
                        cleaning_status[str(room_num)].pop('rejection_reason', None)
                        flash(f'Quarto {room_num} inspecionado e liberado para uso.')
                    else:
                        # Failed inspection
                        cleaning_status[str(room_num)]['status'] = 'rejected'
                        cleaning_status[str(room_num)]['rejected_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        cleaning_status[str(room_num)]['rejected_by'] = session.get('user', 'Recepção')
                        cleaning_status[str(room_num)]['rejection_reason'] = observation
                        flash(f'Quarto {room_num} reprovado na inspeção. Governança notificada.')
                
                save_cleaning_status(cleaning_status)
            except Exception as e:
                traceback.print_exc()
                flash(f'Erro ao realizar inspeção: {str(e)}')
                
            return redirect(url_for('reception.reception_rooms'))

        if action == 'transfer_guest':
            old_room_raw = sanitize_input(request.form.get('old_room'))
            new_room_raw = sanitize_input(request.form.get('new_room'))
            reason = sanitize_input(request.form.get('reason'))
            
            if not validate_room_number(old_room_raw)[0] or not validate_room_number(new_room_raw)[0]:
                flash('Erro na Transferência: Números de quarto inválidos.')
                return redirect(url_for('reception.reception_rooms'))
                
            if not reason:
                flash('Erro na Transferência: Motivo é obrigatório.')
                return redirect(url_for('reception.reception_rooms'))

            # Format room numbers
            old_room = format_room_number(old_room_raw)
            new_room = format_room_number(new_room_raw)
            
            if not old_room or not new_room:
                flash('Quartos de origem e destino são obrigatórios.')
                return redirect(url_for('reception.reception_rooms'))
                
            if old_room not in occupancy:
                flash(f'Quarto de origem {old_room} não está ocupado.')
                return redirect(url_for('reception.reception_rooms'))
                
            if new_room in occupancy:
                flash(f'Quarto de destino {new_room} já está ocupado.')
                return redirect(url_for('reception.reception_rooms'))
            
            # Transfer Occupancy
            guest_data = occupancy.pop(old_room)
            occupancy[new_room] = guest_data
            save_room_occupancy(occupancy)

            reservation_id = guest_data.get('reservation_id')
            if reservation_id:
                try:
                    ReservationService().save_manual_allocation(
                        reservation_id=reservation_id,
                        room_number=new_room,
                        checkin=guest_data.get('checkin'),
                        checkout=guest_data.get('checkout'),
                        occupancy_data=occupancy
                    )
                except Exception as sync_err:
                    print(f"Erro ao sincronizar alocação da reserva {reservation_id}: {sync_err}")
            
            # Transfer Restaurant Table/Orders
            orders = load_table_orders()
            if str(old_room) in orders:
                order_data = orders.pop(str(old_room))
                order_data['room_number'] = str(new_room)
                orders[str(new_room)] = order_data
                save_table_orders(orders)
            
            # Transfer Pending Charges (Room Charges)
            room_charges = load_room_charges()
            charges_updated = False
            for charge in room_charges:
                if format_room_number(charge.get('room_number')) == old_room and charge.get('status') == 'pending':
                    charge['room_number'] = new_room
                    charges_updated = True
            
            if charges_updated:
                save_room_charges(room_charges)
            
            # Mark old room as dirty
            cleaning_status = load_cleaning_status()
            if not isinstance(cleaning_status, dict):
                cleaning_status = {}
            
            cleaning_status[old_room] = {
                'status': 'dirty',
                'marked_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'last_guest': guest_data.get('guest_name', ''),
                'note': f'Transferência para quarto {new_room}'
            }
            save_cleaning_status(cleaning_status)
            
            log_action('Troca de Quarto', f'Hóspede {guest_data.get("guest_name")} transferido do Quarto {old_room} para {new_room}. Motivo: {reason}', department='Recepção')
            flash(f'Hóspede transferido com sucesso do Quarto {old_room} para {new_room}.')
            return redirect(url_for('reception.reception_rooms'))

        if action == 'edit_guest_name':
            room_num_raw = sanitize_input(request.form.get('room_number'))
            new_name = sanitize_input(request.form.get('new_name'))
            
            if not validate_room_number(room_num_raw)[0]:
                flash('Erro na Edição: Número de quarto inválido.')
                return redirect(url_for('reception.reception_rooms'))
                
            if not validate_required(new_name, "Novo Nome")[0]:
                flash('Erro na Edição: Novo nome é obrigatório.')
                return redirect(url_for('reception.reception_rooms'))
            
            room_num = format_room_number(room_num_raw)
            
            if room_num in occupancy and new_name:
                old_name = occupancy[room_num].get('guest_name')
                occupancy[room_num]['guest_name'] = new_name
                save_room_occupancy(occupancy)
                
                # Sync with Reservation Service
                reservation_id = occupancy[room_num].get('reservation_id')
                if reservation_id:
                    try:
                        rs = ReservationService()
                        if rs.update_guest_details(reservation_id, {'guest_name': new_name}):
                            log_action('Sincronização de Reserva', f'Nome atualizado na reserva {reservation_id}', department='Recepção')
                    except Exception as e:
                        print(f"Erro ao sincronizar reserva: {e}")

                log_action('Edição de Hóspede', f'Nome alterado de "{old_name}" para "{new_name}" no Quarto {room_num}.', department='Recepção')
                flash(f'Nome do hóspede do Quarto {room_num} atualizado com sucesso.')
            else:
                flash('Erro ao atualizar nome do hóspede. Verifique os dados.')
            
            return redirect(url_for('reception.reception_rooms'))

        if action == 'cancel_charge':
            if session.get('role') != 'admin':
                flash('Apenas administradores podem cancelar consumos.')
                return redirect(url_for('reception.reception_rooms'))
                
            charge_id = request.form.get('charge_id')
            reason = request.form.get('cancellation_reason')
            
            room_charges = load_room_charges()
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge:
                old_status = charge.get('status')
                charge['status'] = 'cancelled'
                charge['cancelled_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['cancelled_by'] = session.get('user')
                
                # --- FINANCIAL AUDIT LOG ---
                try:
                    from app.services.financial_audit_service import FinancialAuditService
                    FinancialAuditService.log_event(
                        user=session.get("user"),
                        action=FinancialAuditService.EVENT_CANCEL,
                        entity=f"Room Charge {charge_id}",
                        old_data={'status': old_status},
                        new_data={'status': 'cancelled'},
                        details={'reason': reason, 'charge_total': charge.get('total')}
                    )
                except Exception as e:
                    current_app.logger.error(f"Failed to log cancel charge audit: {e}")
                charge['cancellation_reason'] = reason
                
                save_room_charges(room_charges)
                
                log_action('Cancelamento de Consumo', 
                          f"Consumo {charge_id} (Quarto {charge.get('room_number')}) cancelado. Motivo: {reason}", 
                          department='Recepção')
                flash(f'Consumo cancelado com sucesso.')
            else:
                flash('Consumo não encontrado.')
                
            return redirect(url_for('reception.reception_rooms'))

        if action == 'checkin':
            # Logic moved to /reception/checkin (reception_checkin)
            return redirect(url_for('reception.reception_rooms'))
        
        elif action == 'checkout':
            room_num_raw = sanitize_input(request.form.get('room_number'))
            
            valid_room, msg_room = validate_room_number(room_num_raw)
            if not valid_room:
                flash(f'Erro no Check-out: {msg_room}')
                return redirect(url_for('reception.reception_rooms'))
                
            room_num = format_room_number(room_num_raw)
            
            # Check for pending charges
            room_charges = load_room_charges()
            has_pending = False
            for c in room_charges:
                if format_room_number(c.get('room_number')) == room_num and c.get('status') == 'pending':
                    has_pending = True
                    break
            
            if has_pending:
                flash('Check-out bloqueado: Existem contas pendentes transferidas do restaurante. Regularize no Caixa da Recepção.')
                return redirect(url_for('reception.reception_rooms'))
                
            if room_num in occupancy:
                checked_out_payload = occupancy.get(room_num, {}) or {}
                reservation_id = checked_out_payload.get('reservation_id')
                # Mark as Dirty (Checkout Type) for Governance
                cleaning_status = load_cleaning_status()
                if not isinstance(cleaning_status, dict):
                    cleaning_status = {}
                    
                cleaning_status[room_num] = {
                    'status': 'dirty_checkout',
                    'marked_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'last_guest': occupancy[room_num].get('guest_name', '')
                }
                save_cleaning_status(cleaning_status)

                if reservation_id:
                    try:
                        rs = ReservationService()
                        rs.update_reservation_status(reservation_id, 'Checked-out')
                        rs.save_manual_allocation(
                            reservation_id=reservation_id,
                            room_number=room_num,
                            checkin=checked_out_payload.get('checkin'),
                            checkout=datetime.now().strftime('%d/%m/%Y')
                        )
                    except Exception as sync_err:
                        print(f"Erro ao sincronizar check-out da reserva {reservation_id}: {sync_err}")

                del occupancy[room_num]
                save_room_occupancy(occupancy)
                
                # Automatically Close Restaurant Table for the room upon Checkout
                orders = load_table_orders()
                if str(room_num) in orders:
                    # Prevent data loss: Check if order has items or total
                    order_to_close = orders[str(room_num)]
                    if order_to_close.get('items') or order_to_close.get('total', 0) > 0:
                        # Archive to a separate file for recovery
                        try:
                            archive_file = ARCHIVED_ORDERS_FILE
                            archived = {}
                            if os.path.exists(archive_file):
                                with open(archive_file, 'r', encoding='utf-8') as f:
                                    try:
                                        archived = json.load(f)
                                    except: pass
                            
                            archive_id = f"{room_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            archived[archive_id] = order_to_close
                            
                            with open(archive_file, 'w', encoding='utf-8') as f:
                                json.dump(archived, f, indent=4, ensure_ascii=False)
                            current_app.logger.info(f"Archived unclosed order for Room {room_num} to {archive_id}")
                        except Exception as e:
                            current_app.logger.error(f"Error archiving order: {e}")
                    
                    # Close table
                    del orders[str(room_num)]
                    save_table_orders(orders)
                    flash(f'Check-out realizado e Mesa {room_num} fechada/arquivada.')
                else:
                    flash(f'Check-out realizado para Quarto {room_num}.')
            else:
                flash('Quarto não está ocupado.')
                
        return redirect(url_for('reception.reception_rooms'))
    
    # Load Products for "Add Item" modal (Using Menu Items for consistency)
    products = []
    try:
        menu_items = load_menu_items()
        products = [p for p in menu_items if p.get('active', True)]
        products.sort(key=lambda x: x['name'])
    except Exception as e:
        current_app.logger.error(f"Error loading products: {e}")

    # Load and Group Pending Charges for "Ver Consumo" modal
    try:
        room_charges = load_room_charges()
        pending_charges = [c for c in room_charges if isinstance(c, dict) and c.get('status') == 'pending']
        
        grouped_charges = {}
        any_commissionable_charge = False
        has_commissionable_service_fee_charge = False
        for charge in pending_charges:
            room_num = format_room_number(charge.get('room_number'))
            if not room_num:
                continue

            if room_num not in grouped_charges:
                grouped_charges[room_num] = []
            
            items = charge.get('items')
            if not isinstance(items, list):
                items = []
                charge['items'] = items

            # Ensure source is set for display
            if 'source' not in charge:
                has_minibar = any(isinstance(item, dict) and item.get('category') == 'Frigobar' for item in items)
                charge['source'] = 'minibar' if has_minibar else 'restaurant'
                
            grouped_charges[room_num].append(charge)
            
        pending_rooms = list(grouped_charges.keys())
        print(f"[DEBUG reception_rooms] Loaded {len(pending_charges)} pending charges for rooms: {pending_rooms}")

        payment_methods = load_payment_methods()
        payment_methods = [m for m in payment_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]
        
    except Exception as e:
        print(f"[ERROR reception_rooms] Failed to load consumption data: {e}")
        grouped_charges = {}
        pending_rooms = []
        # Don't reset payment_methods here if they were loaded before, 
        # but since we are moving loading outside, we need to handle it separately.
        # We will load payment methods independently.
        pass

    # Load Payment Methods independently to ensure they are available even if charge loading fails
    reception_payment_methods = []
    reservation_payment_methods = []
    try:
        all_methods = load_payment_methods()
        # Filter for Reception (Close Account)
        reception_payment_methods = [m for m in all_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]
        # Filter for Reservations (Receber Reserva)
        reservation_payment_methods = [
            m for m in all_methods
            if any(tag in (m.get('available_in') or []) for tag in ['reservations', 'reservas', 'caixa_reservas'])
        ]
    except Exception as e:
        current_app.logger.error(f"Error loading payment methods: {e}")
        reception_payment_methods = []
        reservation_payment_methods = []

    printers = load_printers()
    printer_settings = load_printer_settings()

    # Load Active Experiences for Launch Modal
    experiences = ExperienceService.get_all_experiences(only_active=True)
    collaborators = ExperienceService.get_unique_collaborators()
    
    room_capacities = ReservationService.ROOM_CAPACITIES
    open_consumption_room = (request.args.get('open_consumption_room') or '').strip()
    room_operational_info = {}
    try:
        rs = ReservationService()
        for room_key, occ in (occupancy or {}).items():
            if not isinstance(occ, dict):
                continue
            rid = occ.get('reservation_id')
            if not rid:
                continue
            details = rs.get_guest_details(rid)
            op = details.get('operational_info') if isinstance(details, dict) else {}
            if not isinstance(op, dict):
                op = {}
            room_operational_info[str(room_key)] = {
                'allergies': op.get('allergies') or '',
                'dietary_restrictions': op.get('dietary_restrictions') or [],
                'breakfast_time_start': op.get('breakfast_time_start') or '',
                'breakfast_time_end': op.get('breakfast_time_end') or '',
                'commemorative_dates': op.get('commemorative_dates') or [],
                'vip_note': op.get('vip_note') or ''
            }
    except Exception as e:
        print(f"Erro ao montar resumo operacional dos quartos: {e}")

    return render_template('reception_rooms.html', 
                           occupancy=occupancy, 
                           cleaning_status=cleaning_status,
                           checklist_items=checklist_items,
                           grouped_charges=grouped_charges,
                           pending_rooms=pending_rooms,
                           payment_methods=reception_payment_methods, # Used by Close Account
                           reservation_payment_methods=reservation_payment_methods, # Used by Receber Reserva
                           products=products,
                           upcoming_checkins=upcoming_checkins,
                           upcoming_reservations=upcoming_reservations,
                           today=datetime.now().strftime('%Y-%m-%d'),
                           printers=printers,
                           printer_settings=printer_settings,
                           experiences=experiences,
                           collaborators=collaborators,
                           room_capacities=room_capacities,
                           room_operational_info=room_operational_info,
                           reservation_status_catalog=ReservationService.RESERVATION_STATUS_CATALOG,
                           operational_status_catalog=ReservationService.OPERATIONAL_STATUS_CATALOG,
                           open_consumption_room=open_consumption_room,
                           open_checkin=open_checkin,
                           requested_reservation_id=requested_reservation_id)

@reception_bp.route('/reception/cashier', methods=['GET', 'POST'])
@login_required
def reception_cashier():
    import app as app_module
    current_user = session.get('user')
    
    # Permission Check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
        flash('Acesso não autorizado ao Caixa da Recepção.')
        return redirect(url_for('main.index'))

    # Find current open session (Specific Type)
    sessions = app_module.load_cashier_sessions()
    current_session = None
    
    # Prioritize guest_consumption
    for s in sessions:
        if s.get('status') == 'open' and s.get('type') == 'guest_consumption':
            current_session = s
            break
            
    # Fallback to reception_room_billing
    if not current_session:
        for s in sessions:
            if s.get('status') == 'open' and s.get('type') == 'reception_room_billing':
                current_session = s
                break
    
    # Load printer configuration for report
    printers = app_module.load_printers()
    printer_settings = app_module.load_printer_settings()
            
    # Load pending room charges
    try:
        room_charges = app_module.load_room_charges()
    except Exception as e:
        print(f"[ERROR] Failed to load room charges: {e}")
        room_charges = []

    pending_charges = [c for c in room_charges if c.get('status') == 'pending']
    
    # Group charges by room
    room_occupancy = app_module.load_room_occupancy()
    grouped_charges = {}
    
    for charge in pending_charges:
        # Determine source if missing
        if 'source' not in charge:
            has_minibar = any(item.get('category') == 'Frigobar' for item in charge.get('items', []))
            charge['source'] = 'minibar' if has_minibar else 'restaurant'

        room_num = str(charge.get('room_number'))
        if room_num not in grouped_charges:
            grouped_charges[room_num] = {
                'room_number': room_num,
                'guest_name': room_occupancy.get(room_num, {}).get('guest_name', 'Desconhecido'),
                'charges': [],
                'total_debt': 0.0
            }
        
        grouped_charges[room_num]['charges'].append(charge)
        grouped_charges[room_num]['total_debt'] += float(charge.get('total', 0.0))
    
    # Sort grouped charges by room number
    sorted_rooms = sorted(grouped_charges.values(), key=lambda x: int(x['room_number']) if x['room_number'].isdigit() else 999)

    payment_methods = app_module.load_payment_methods()
    # Filter for reception availability
    payment_methods = [m for m in payment_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]

    if request.method == 'POST':
        action = request.form.get('action')
        print(f"DEBUG: POST action={action}, form={request.form}")
        
        if action == 'open_cashier':
            if current_session:
                flash(f'Já existe um Caixa Recepção Restaurante aberto (Usuário: {current_session.get("user")}).')
            else:
                try:
                    initial_balance = parse_br_currency(request.form.get('opening_balance', '0'))
                except ValueError:
                    initial_balance = 0.0
                
                try:
                    CashierService.open_session(
                        cashier_type='guest_consumption',
                        user=current_user,
                        opening_balance=initial_balance
                    )
                    log_action('Caixa Aberto', f'Caixa Recepção Restaurante aberto por {current_user} com R$ {initial_balance:.2f}', department='Recepção')
                    flash('Caixa da Recepção aberto com sucesso.')
                except ValueError as e:
                    flash(str(e))
                
                return redirect(url_for('reception.reception_cashier'))
                
        elif action == 'close_cashier':
            if not current_session:
                flash('Não há caixa aberto para fechar.')
            else:
                try:
                    raw_cash = request.form.get('closing_cash')
                    raw_non_cash = request.form.get('closing_non_cash')
                    closing_cash = parse_br_currency(raw_cash) if raw_cash else None
                    closing_non_cash = parse_br_currency(raw_non_cash) if raw_non_cash else None
                    user_closing_balance = None
                    if closing_cash is not None or closing_non_cash is not None:
                        user_closing_balance = (closing_cash or 0.0) + (closing_non_cash or 0.0)
                except ValueError:
                    closing_cash = None
                    closing_non_cash = None
                    user_closing_balance = None
                
                try:
                    closed_session = CashierService.close_session(
                        session_id=current_session['id'],
                        user=current_user,
                        closing_balance=user_closing_balance,
                        closing_cash=closing_cash,
                        closing_non_cash=closing_non_cash
                    )
                    
                    log_action('Caixa Fechado', f'Caixa Recepção Restaurante fechado por {current_user} com saldo final R$ {closed_session["closing_balance"]:.2f}', department='Recepção')
                    
                    log_system_action(
                        action='close_cashier',
                        details={
                            'session_id': closed_session['id'],
                            'closing_balance': closed_session['closing_balance'],
                            'difference': closed_session.get('difference', 0.0),
                            'opened_at': closed_session.get('opened_at'),
                            'closed_at': closed_session.get('closed_at'),
                            'department': 'Recepção'
                        },
                        user=current_user,
                        category='Caixa'
                    )

                    flash('Caixa fechado com sucesso.')
                except Exception as e:
                    flash(f'Erro ao fechar caixa: {e}')
                
                return redirect(url_for('reception.reception_cashier'))

        elif action == 'pay_charge':
            if not current_session:
                flash('É necessário abrir o Caixa Recepção Restaurante antes de receber pagamentos.')
                return redirect(url_for('reception.reception_cashier'))

            charge_id = request.form.get('charge_id')
            payment_data_json = request.form.get('payment_data')
            emit_invoice = False 
            
            charge = next((c for c in room_charges if c['id'] == charge_id), None)
            
            if charge and charge.get('status') == 'pending':
                charge_total = float(charge.get('total', 0))
                if abs(charge_total) < 0.01:
                    charge['status'] = 'paid'
                    charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                    charge['reception_cashier_id'] = current_session['id']
                    charge['payment_method'] = 'Isento/Zerado'
                    
                    save_room_charges(room_charges)
                    log_action('Conta Zerada Fechada', f'Quarto {charge["room_number"]}: R$ 0.00 fechado.', department='Recepção')
                    flash(f"Conta do Quarto {charge['room_number']} (R$ 0.00) fechada com sucesso.")
                    
                    if request.form.get('redirect_to') == 'reception_rooms':
                        return redirect(url_for('reception.reception_rooms'))
                    return redirect(url_for('reception.reception_cashier'))

                payments_to_process = []
                
                if payment_data_json:
                    try:
                        payments_list = json.loads(payment_data_json)
                        for p in payments_list:
                            payments_to_process.append({
                                'method_id': p.get('id'),
                                'method_name': p.get('name'),
                                'amount': float(p.get('amount', 0))
                            })
                    except Exception as e:
                        print(f"Error processing payment data: {e}")
                        flash('Erro ao processar dados de pagamento.')
                        return redirect(url_for('reception.reception_cashier'))
                else:
                    method_id = request.form.get('payment_method')
                    if method_id:
                        method_name = next((m['name'] for m in payment_methods if m['id'] == method_id), method_id)
                        payments_to_process.append({
                            'method_id': method_id,
                            'method_name': method_name,
                            'amount': float(charge['total'])
                        })
                
                if not payments_to_process:
                    flash('Nenhum pagamento informado.')
                    if request.form.get('redirect_to') == 'reception_rooms':
                        return redirect(url_for('reception.reception_rooms'))
                    return redirect(url_for('reception.reception_cashier'))

                charge['status'] = 'paid'
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                charge['reception_cashier_id'] = current_session['id']
                
                if len(payments_to_process) > 1:
                    charge['payment_method'] = 'Múltiplos'
                    charge['payment_details'] = payments_to_process
                else:
                    charge['payment_method'] = payments_to_process[0]['method_id']
                
                save_room_charges(room_charges)
                
                log_action('Início Pagamento', f'Iniciando processamento de pagamento para Quarto {charge["room_number"]}. Total: R$ {charge["total"]}', department='Recepção')

                payment_group_id = str(uuid.uuid4()) if len(payments_to_process) > 1 else None
                total_payment_group_amount = sum(float(p['amount']) for p in payments_to_process) if payment_group_id else 0

                for payment in payments_to_process:
                    details = {}
                    if payment_group_id:
                        details['payment_group_id'] = payment_group_id
                        details['total_payment_group_amount'] = total_payment_group_amount
                        details['payment_method_code'] = payment['method_name']

                    transaction = {
                        'id': f"TRANS_{datetime.now().strftime('%Y%m%d%H%M%S')}_{int(payment['amount']*100)}",
                        'type': 'in',
                        'category': 'Pagamento de Conta',
                        'description': f"Pagamento Quarto {charge['room_number']} ({payment['method_name']})",
                        'amount': payment['amount'],
                        'payment_method': payment['method_name'],
                        'emit_invoice': emit_invoice,
                        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                        'time': datetime.now().strftime('%H:%M'),
                        'waiter': charge.get('waiter'),
                        'waiter_breakdown': charge.get('waiter_breakdown'),
                        'service_fee_removed': charge.get('service_fee_removed', False),
                        'related_charge_id': charge['id'],
                        'details': details
                    }
                    current_session['transactions'].append(transaction)
                    log_action('Transação Parcial', f'Pagamento parcial: R$ {payment["amount"]:.2f} via {payment["method_name"]}', department='Recepção')
                
                save_cashier_sessions(sessions)
                
                try:
                    all_payment_methods = load_payment_methods()
                    pm_map = {m['id']: m for m in all_payment_methods}

                    items_list = charge.get('items', [])
                    if isinstance(items_list, str):
                        try: items_list = json.loads(items_list)
                        except: items_list = []
                    
                    occupancy = load_room_occupancy()
                    guest_name = occupancy.get(str(charge['room_number']), {}).get('guest_name', 'Hóspede')

                    fiscal_payments = []
                    for p in payments_to_process:
                        # Determine is_fiscal
                        pm_id = p.get('method_id')
                        # If method_id not available (passed from name?), try to find by name
                        pm_obj = pm_map.get(pm_id)
                        if not pm_obj:
                             # Fallback lookup by name
                             pm_obj = next((m for m in all_payment_methods if m['name'] == p['method_name']), None)
                        
                        is_fiscal = pm_obj.get('is_fiscal', False) if pm_obj else False

                        fiscal_payments.append({
                            'method': p['method_name'],
                            'amount': p['amount'],
                            'is_fiscal': is_fiscal
                        })

                    FiscalPoolService.add_to_pool(
                        origin='reception_charge',
                        original_id=f"CHARGE_{charge['id']}",
                        total_amount=float(charge['total']),
                        items=items_list,
                        payment_methods=fiscal_payments,
                        user=current_user,
                        customer_info={'room_number': charge['room_number'], 'guest_name': guest_name}
                    )
                    log_action('Sincronização Fiscal', f'Conta {charge["id"]} enviada para pool fiscal.', department='Recepção')
                except Exception as e:
                    print(f"Error adding charge to fiscal pool: {e}")
                    # Use a simpler logging mechanism if LoggerService is not available or too complex to import
                    print(f"CRITICAL: Fiscal Pool Error: {e}")
                    log_action('Erro Fiscal', f'Falha ao enviar conta {charge["id"]} para pool fiscal: {e}', department='Recepção')

                log_action('Pagamento Concluído', f'Quarto {charge["room_number"]}: R$ {charge["total"]:.2f} via {charge["payment_method"]}', department='Recepção')
                flash(f"Pagamento de R$ {charge['total']:.2f} recebido com sucesso.")
            else:
                flash('Conta não encontrada ou já paga.')
            
            redirect_to = request.form.get('redirect_to')
            if redirect_to == 'reception_rooms':
                return redirect(url_for('reception.reception_rooms'))
                
            return redirect(url_for('reception.reception_cashier'))

        elif action == 'add_transaction':
            if not current_session:
                flash('É necessário abrir o caixa da recepção antes de realizar movimentações.')
                return redirect(url_for('reception.reception_cashier'))
                
            trans_type = request.form.get('type', '').strip().lower()
            description = request.form.get('description')
            try:
                amount = parse_br_currency(request.form.get('amount', '0'))
            except ValueError:
                amount = 0.0
            
            if amount > 0 and description:
                try:
                    if trans_type == 'transfer':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                        target_cashier = request.form.get('target_cashier')
                        source_type = current_session.get('type', 'reception')
                        
                        CashierService.transfer_funds(
                            source_type=source_type,
                            target_type=target_cashier,
                            amount=amount,
                            description=description,
                            user=current_user
                        )
                        
                        try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
                                    target_printer = p
                                    break
                            if not target_printer and printers_config:
                                target_printer = printers_config[0]
                            
                            if target_printer:
                                print_cashier_ticket_async(target_printer, 'TRANSFERENCIA', amount, session.get('user', 'Sistema'), f"{description} -> {target_cashier}")
                        except Exception as e:
                            print(f"Error printing cashier ticket: {e}")

                        log_action('Transferência Caixa', f'Recepção -> {target_cashier}: R$ {amount:.2f}', department='Recepção')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Transferência realizada com sucesso.'})
                        flash('Transferência realizada com sucesso.')
                    
                    elif trans_type == 'deposit':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                        CashierService.add_transaction(
                            cashier_type=current_session.get('type', 'guest_consumption'),
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='in',
                            is_withdrawal=False,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                        log_action('Transação Caixa', f'Recepção Restaurante: Suprimento de R$ {amount:.2f} - {description}', department='Recepção')
                        
                        try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
                                    target_printer = p
                                    break
                            if not target_printer and printers_config:
                                target_printer = printers_config[0]
                            
                            if target_printer:
                                print_cashier_ticket_async(target_printer, 'SUPRIMENTO', amount, session.get('user', 'Sistema'), description)
                        except Exception as e:
                            print(f"Error printing cashier ticket: {e}")

                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Suprimento registrado com sucesso.'})

                        flash('Suprimento registrado com sucesso.')
                        
                    elif trans_type == 'withdrawal':
                         # Idempotency Check
                         idempotency_key = request.form.get('idempotency_key')
                         if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_cashier'))

                         CashierService.add_transaction(
                            cashier_type=current_session.get('type', 'guest_consumption'),
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='out',
                            is_withdrawal=True,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                         log_action('Transação Caixa', f'Recepção Restaurante: Sangria de R$ {amount:.2f} - {description}', department='Recepção')
                         
                         try:
                            printers_config = load_printers()
                            target_printer = None
                            for p in printers_config:
                                if 'recepcao' in p.get('name', '').lower() or 'reception' in p.get('name', '').lower():
                                    target_printer = p
                                    break
                            if not target_printer and printers_config:
                                target_printer = printers_config[0]
                            
                            if target_printer:
                                print_cashier_ticket_async(target_printer, 'SANGRIA', amount, session.get('user', 'Sistema'), description)
                         except Exception as e:
                            print(f"Error printing cashier ticket: {e}")

                         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Sangria registrada com sucesso.'})
                         flash('Sangria registrada com sucesso.')

                except ValueError as e:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})
                    flash(f'Erro: {str(e)}')
                except Exception as e:
                    current_app.logger.error(f"Transaction Error: {e}")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': f'Erro inesperado: {str(e)}'})
                    flash(f'Erro inesperado: {str(e)}')
            else:
                msg = 'Valor inválido ou descrição ausente.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': msg})
                flash(msg)
            
            return redirect(url_for('reception.reception_cashier'))

    # Calculate totals for display
    total_in = 0
    total_out = 0
    balance = 0
    current_totals = {}
    total_balance = 0.0

    if current_session:
        total_in = sum(t['amount'] for t in current_session['transactions'] if t['type'] in ['in', 'sale', 'deposit'])
        total_out = sum(t['amount'] for t in current_session['transactions'] if t['type'] in ['out', 'withdrawal'])
        
        initial_balance = current_session.get('initial_balance', current_session.get('opening_balance', 0.0))
        balance = initial_balance + total_in - total_out
        
        for t in current_session['transactions']:
            if t['type'] in ['in', 'sale', 'deposit']:
                method = t.get('payment_method', 'Outros')
                current_totals[method] = current_totals.get(method, 0.0) + t['amount']
        
        if 'opening_balance' not in current_session:
            current_session['opening_balance'] = initial_balance

        # Calculate Total Balance
        total_balance = current_session.get('opening_balance', 0.0)
        for t in current_session.get('transactions', []):
            if t['type'] in ['in', 'sale', 'deposit']:
                total_balance += float(t['amount'])
            elif t['type'] in ['out', 'withdrawal']:
                total_balance -= float(t['amount'])

    products = []
    try:
        menu_items = load_menu_items()
        products = [p for p in menu_items if p.get('active', True)]
        products.sort(key=lambda x: x['name'])
    except Exception as e:
        current_app.logger.error(f"Error loading menu items: {e}")

    printer_settings = load_printer_settings()
    printers = load_printers()
    
    displayed_transactions = []
    has_more = False
    current_page = 1
    
    if current_session:
        try:
            current_page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
        except ValueError:
            current_page = 1
            per_page = 20

        displayed_transactions, has_more = CashierService.get_paginated_transactions(current_session.get('id'), page=current_page, per_page=per_page)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
            return jsonify({
                'transactions': displayed_transactions,
                'has_more': has_more,
                'current_page': current_page
            })

    return render_template('reception_cashier.html', 
                         cashier=current_session, 
                         displayed_transactions=displayed_transactions,
                         has_more=has_more,
                         current_page=current_page,
                         pending_charges=pending_charges,
                         grouped_charges=sorted_rooms,
                         payment_methods=payment_methods,
                         products=products,
                         printers=printers,
                         printer_settings=printer_settings,
                         total_balance=total_balance,
                         current_totals=current_totals)

@reception_bp.route('/api/reception/calculate_reservation_update', methods=['POST'])
@login_required
def api_calculate_reservation_update():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        new_room = data.get('new_room')
        new_checkin = data.get('new_checkin')
        new_checkout = data.get('new_checkout')
        
        service = ReservationService()
        
        # Now the service handles all logic including collision check
        calculation = service.calculate_reservation_update(res_id, new_room, new_checkin, new_checkout)
            
        return jsonify({'success': True, 'data': calculation})
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/experiences/launch', methods=['POST'])
@login_required
def launch_experience():
    try:
        data = {
            'experience_id': request.form.get('experience_id'),
            'room_number': request.form.get('room_number'),
            'guest_name': request.form.get('guest_name'),
            'collaborator_name': request.form.get('collaborator_name'),
            'scheduled_date': request.form.get('scheduled_date'),
            'notes': request.form.get('notes')
        }
        
        if ExperienceService.launch_experience(data):
            return jsonify({'success': True, 'message': 'Experiência lançada com sucesso!'})
        return jsonify({'success': False, 'message': 'Erro ao lançar experiência.'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/reception/experiences/report', methods=['GET'])
@login_required
def get_launched_experiences_report():
    try:
        filters = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'collaborator': request.args.get('collaborator'),
            'supplier': request.args.get('supplier')
        }
        
        report = ExperienceService.get_launched_experiences(filters)
        return jsonify({'success': True, 'data': report})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/reception/experiences/launch/<launch_id>/toggle_paid', methods=['POST'])
@login_required
def toggle_experience_commission_paid(launch_id):
    try:
        new_status = ExperienceService.toggle_commission_paid(launch_id)
        if new_status is None:
             return jsonify({'success': False, 'message': 'Lançamento não encontrado'}), 404
        return jsonify({'success': True, 'paid': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/api/reception/move_reservation', methods=['POST'])
@login_required
def api_move_reservation():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        new_room = data.get('new_room')
        
        # Optional date overrides from Drag & Drop
        new_checkin = data.get('checkin')
        new_checkout = data.get('checkout')
        
        price_adj = data.get('price_adjustment') # dict {type, amount}
        
        if not res_id or not new_room:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        service = ReservationService()
        occupancy = load_room_occupancy()
        
        service.save_manual_allocation(
            reservation_id=res_id,
            room_number=new_room,
            checkin=new_checkin,
            checkout=new_checkout,
            price_adjustment=price_adj,
            occupancy_data=occupancy
        )
        active_room = None
        for room_key, occ in (occupancy or {}).items():
            if str((occ or {}).get('reservation_id') or '') == str(res_id):
                active_room = str(room_key)
                break
        if active_room:
            active_payload = occupancy.pop(active_room)
            active_payload['reservation_id'] = str(res_id)
            active_payload['checkin'] = new_checkin or active_payload.get('checkin')
            active_payload['checkout'] = new_checkout or active_payload.get('checkout')
            occupancy[str(new_room)] = active_payload
            save_room_occupancy(occupancy)
        
        return jsonify({'success': True})
    except ValueError as e:
         return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/resize_reservation', methods=['POST'])
@login_required
def api_resize_reservation():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        checkin = data.get('checkin')
        checkout = data.get('checkout')
        room_number = data.get('room_number')
        price_adj = data.get('price_adjustment')
        
        if not res_id or not checkin or not checkout:
             return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
             
        service = ReservationService()
        occupancy = load_room_occupancy()
        
        service.save_manual_allocation(
            reservation_id=res_id,
            room_number=room_number,
            checkin=checkin,
            checkout=checkout,
            price_adjustment=price_adj,
            occupancy_data=occupancy
        )
        for room_key, occ in (occupancy or {}).items():
            if str((occ or {}).get('reservation_id') or '') == str(res_id):
                occ['checkin'] = checkin
                occ['checkout'] = checkout
                break
        save_room_occupancy(occupancy)
        return jsonify({'success': True})
    except ValueError as e:
         return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/upload_reservations', methods=['POST'])
@login_required
def api_upload_reservations():
    try:
        file = request.files.get('file')
        if not file or not file.filename:
             return jsonify({'success': False, 'error': 'Arquivo inválido'}), 400
             
        filename = file.filename.lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.csv')):
             return jsonify({'success': False, 'error': 'Formato não suportado. Use Excel (.xlsx) ou CSV.'}), 400
        
        target_dir = RESERVATIONS_DIR
        os.makedirs(target_dir, exist_ok=True)
        
        # Save directly (Legacy behavior) OR implement import flow?
        # The user requested "Import Button" -> "Preview" -> "Confirm".
        # This endpoint seems to be the one I should use for the PREVIEW step or keep as legacy direct upload.
        # Given the new requirements, I will repurpose this or add new ones.
        # Let's keep this as "Legacy Direct Upload" if needed, but the new UI will use new endpoints.
        
        save_path = os.path.join(target_dir, f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file.save(save_path)
        
        return jsonify({'success': True, 'message': 'Arquivo carregado com sucesso.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/import_preview', methods=['POST'])
@login_required
def api_import_preview():
    try:
        file = request.files.get('file')
        if not file or not file.filename:
             return jsonify({'success': False, 'error': 'Arquivo inválido'}), 400
             
        filename = file.filename.lower()
        if not filename.endswith('.xlsx'):
             return jsonify({'success': False, 'error': 'Formato não suportado. Use Excel (.xlsx).'}), 400
        
        # Save to temp
        temp_dir = os.path.join(current_app.instance_path, 'temp_imports')
        os.makedirs(temp_dir, exist_ok=True)
        
        temp_filename = f"temp_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        temp_path = os.path.join(temp_dir, temp_filename)
        file.save(temp_path)
        
        service = ReservationService()
        result = service.preview_import(temp_path)
        
        if not result['success']:
            os.remove(temp_path)
            return jsonify(result), 400
            
        return jsonify({
            'success': True,
            'report': result['report'],
            'token': temp_filename # Pass back token for confirmation
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/import_confirm', methods=['POST'])
@login_required
def api_import_confirm():
    try:
        data = request.json
        token = data.get('token')
        if not token:
            return jsonify({'success': False, 'error': 'Token de importação inválido.'}), 400
            
        temp_dir = os.path.join(current_app.instance_path, 'temp_imports')
        temp_path = os.path.join(temp_dir, token)
        
        if not os.path.exists(temp_path):
            return jsonify({'success': False, 'error': 'Arquivo de importação expirou ou não existe.'}), 404
            
        service = ReservationService()
        result = service.process_import_confirm(temp_path, token)
        
        if result.get('success'):
            # Cleanup temp file
            try:
                os.remove(temp_path)
            except:
                pass
            
            log_action('Importação Reservas', f"Importação concluída. Importados: {result['summary']['imported']}, Conflitos: {result['summary']['conflicts']}", department='Recepção')
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/reservations/sync-engine', methods=['POST'])
@login_required
def api_sync_engine_reservation():
    try:
        payload = request.json or {}
        service = ReservationService()
        result = service.upsert_external_reservation(payload)
        log_action(
            'Sincronização Motor Reservas',
            f"Reserva externa sincronizada ({result.get('action')}) id={result.get('reservation_id')}",
            department='Recepção'
        )
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/unallocated_reservations')
@login_required
def api_unallocated_reservations():
    try:
        service = ReservationService()
        filters = {
            'date': request.args.get('date'),
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'category': request.args.get('category'),
            'guest_name': request.args.get('guest_name')
        }
        # Clean empty filters
        filters = {k: v for k, v in filters.items() if v}
        
        results = service.get_unallocated_reservations(filters)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/unallocated_reservations/delete', methods=['POST'])
@login_required
def api_delete_unallocated_reservation():
    try:
        data = request.json
        index = data.get('index')
        if index is None:
            return jsonify({'success': False, 'error': 'Índice obrigatório.'}), 400
            
        service = ReservationService()
        if service.delete_unallocated_reservation(int(index)):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Falha ao remover item.'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/create_manual_reservation', methods=['POST'])
@login_required
def api_create_manual_reservation():
    try:
        data = request.json
        if not data.get('guest_name') or not data.get('checkin') or not data.get('checkout'):
             return jsonify({'success': False, 'error': 'Dados obrigatórios faltando.'}), 400
             
        # Parse Dates (handle both formats)
        checkin_str = data.get('checkin')
        checkout_str = data.get('checkout')
        
        try:
            cin = datetime.strptime(checkin_str, '%d/%m/%Y').date()
            cout = datetime.strptime(checkout_str, '%d/%m/%Y').date()
        except ValueError:
            try:
                cin = datetime.strptime(checkin_str, '%Y-%m-%d').date()
                cout = datetime.strptime(checkout_str, '%Y-%m-%d').date()
                # Normalize data to DD/MM/YYYY for consistency
                data['checkin'] = cin.strftime('%d/%m/%Y')
                data['checkout'] = cout.strftime('%d/%m/%Y')
            except ValueError:
                return jsonify({'success': False, 'error': 'Formato de data inválido. Use DD/MM/AAAA.'}), 400

        # Block past check-in dates for manual creations
        today = datetime.now().date()
        if cin < today:
            return jsonify({'success': False, 'error': 'Check-in não pode ser anterior a hoje.'}), 400
        
        tariff_engine = None
        if data.get('category') and data.get('checkin') and data.get('checkout'):
            try:
                tariff_engine = TariffPriorityEngineService.evaluate(
                    category=data.get('category'),
                    channel=data.get('channel') or 'Recepção',
                    checkin=data.get('checkin'),
                    checkout=data.get('checkout'),
                    sale_date=datetime.now().strftime('%Y-%m-%d'),
                    apply_dynamic=False,
                )
            except Exception:
                tariff_engine = None
            if tariff_engine and not tariff_engine.get('sellable'):
                return jsonify({'success': False, 'error': tariff_engine.get('message') or 'Período indisponível para venda.'}), 200
            if tariff_engine and tariff_engine.get('pricing'):
                final_total = float((tariff_engine.get('pricing') or {}).get('final_total') or 0.0)
                if final_total > 0:
                    data['amount'] = f"{final_total:.2f}"
                    data['total_value'] = data['amount']
                package_preview = ((tariff_engine.get('pricing') or {}).get('package') or {})
                promotion_preview = ((tariff_engine.get('pricing') or {}).get('promotion') or {})
                if package_preview.get('applied'):
                    data['pricing_package_id'] = (package_preview.get('package') or {}).get('id')
                    data['pricing_package_name'] = (package_preview.get('package') or {}).get('name')
                if promotion_preview.get('applied'):
                    data['pricing_promotion_id'] = (promotion_preview.get('promotion') or {}).get('id')
                    data['pricing_promotion_name'] = (promotion_preview.get('promotion') or {}).get('name')
                if package_preview.get('applied') and promotion_preview.get('applied'):
                    data['pricing_source'] = 'package+promotion'
                elif package_preview.get('applied'):
                    data['pricing_source'] = 'package'
                elif promotion_preview.get('applied'):
                    data['pricing_source'] = 'promotion'
                else:
                    data['pricing_source'] = 'weekday_base'

        # Payment Validation
        try:
            paid_amount = float(data.get('paid_amount', 0))
        except (ValueError, TypeError):
            paid_amount = 0.0
            
        print(f"DEBUG: api_create_manual_reservation paid_amount={paid_amount}")
            
        total_value = parse_br_currency(data.get('total_value', data.get('amount', 0)))
        payment_method_id = data.get('payment_method')
        
        if paid_amount > 0:
            if paid_amount > total_value + 0.01: # Small tolerance
                return jsonify({'success': False, 'error': 'Valor pago não pode ser maior que o total.'}), 400
            
            if not payment_method_id:
                return jsonify({'success': False, 'error': 'Forma de pagamento obrigatória para valores pagos.'}), 400
                
            # Check Cashier Session
            current_session = CashierService.get_active_session('reservation_cashier')
            if not current_session:
                 return jsonify({'success': False, 'error': 'Caixa de Reservas fechado. Abra o caixa para registrar o pagamento.'}), 400

        room_number = str(data.get('room_number') or '').strip()
        service = ReservationService()
        occupancy = load_room_occupancy()
        
        if room_number:
            try:
                service.check_collision('new', room_number, data.get('checkin'), data.get('checkout'), occupancy_data=occupancy)
            except ValueError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
        else:
            req_category = (data.get('category') or '').strip()
            if req_category:
                if tariff_engine and not tariff_engine.get('sellable'):
                    return jsonify({'success': False, 'error': tariff_engine.get('message') or 'Período indisponível para venda.'}), 200
                if not InventoryRestrictionService.is_open_for_period(req_category, data.get('checkin'), data.get('checkout')):
                    return jsonify({'success': False, 'error': f'Categoria "{req_category}" fechada para venda no período informado.'}), 200
                if not service.has_availability_for_category(
                    req_category,
                    data.get('checkin'),
                    data.get('checkout'),
                    channel=data.get('channel') or 'Recepção',
                ):
                    alts = service.available_categories_for_period(
                        data.get('checkin'),
                        data.get('checkout'),
                        exclude_category=req_category,
                        channel=data.get('channel') or 'Recepção',
                    )
                    if alts:
                        bullet = "\n".join([f" - {c}" for c in alts])
                        msg = f'Indisponível na categoria "{req_category}" para o período {data.get("checkin")}–{data.get("checkout")}. Disponível nas categorias:\n{bullet}'
                        return jsonify({'success': False, 'error': msg, 'available_categories': alts}), 200
                    return jsonify({'success': False, 'error': f'Não há disponibilidade para o período {data.get("checkin")}–{data.get("checkout")} em nenhuma categoria.'}), 200
        
        # Create Reservation
        creation_data = data.copy()
        # Ensure paid_amount is 0 for initial creation to avoid double counting by add_payment later
        creation_data['paid_amount'] = '0.00'
        new_res = service.create_manual_reservation(creation_data)
        
        # Process Payment if applicable
        # print(f"DEBUG: Processing Payment? paid_amount={paid_amount}")
        if paid_amount > 0:
            try:
                # Get Payment Method Name
                payment_methods = load_payment_methods()
                method_name = next((m['name'] for m in payment_methods if str(m['id']) == str(payment_method_id)), 'Desconhecido')
                
                # Add to Cashier
                CashierService.add_transaction(
                    cashier_type='reservation_cashier',
                    amount=paid_amount,
                    description=f"Pagamento Inicial Reserva #{new_res['id']} - {data.get('guest_name')}",
                    payment_method=method_name,
                    user=session.get('user'),
                    transaction_type='sale',
                    is_withdrawal=False
                )
                
                # Add to Reservation Payments
                service.add_payment(new_res['id'], paid_amount, {
                    'method': method_name,
                    'method_id': payment_method_id,
                    'user': session.get('user'),
                    'notes': 'Pagamento no ato da reserva'
                })
                
                log_action('Pagamento Reserva', f"Recebido R$ {paid_amount:.2f} ({method_name}) para Reserva #{new_res['id']}", department='Recepção')
                
            except Exception as e:
                # Log error but don't fail reservation creation (critical data already saved)
                current_app.logger.error(f"Erro ao processar pagamento reserva {new_res['id']}: {str(e)}")
                # print(f"DEBUG: Payment Error: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # Trigger pre-allocation immediately?
        service.auto_pre_allocate(window_hours=48)
        
        if room_number:
            occupancy = load_room_occupancy()
            try:
                service.save_manual_allocation(
                    reservation_id=new_res['id'],
                    room_number=room_number,
                    checkin=data.get('checkin'),
                    checkout=data.get('checkout'),
                    occupancy_data=occupancy
                )
            except ValueError as e:
                 return jsonify({'success': False, 'error': f"Reserva criada, mas falha na alocação: {str(e)}"}), 400
        
        return jsonify({
            'success': True,
            'reservation': new_res,
            'pricing': tariff_engine,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/auto_pre_allocate', methods=['POST'])
@login_required
def api_run_pre_allocation():
    try:
        service = ReservationService()
        actions = service.auto_pre_allocate(window_hours=24)
        return jsonify({'success': True, 'actions': actions})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/reservations/search')
@login_required
def api_search_reservations():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': True, 'results': []})
    
    if len(query) < 3:
        return jsonify({'success': False, 'error': 'Digite pelo menos 3 caracteres.'}), 400

    try:
        service = ReservationService()
        results = service.search_reservations(query)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/reservations')
@login_required
def reception_reservations():
    from datetime import timedelta
    service = ReservationService()
    
    start_date_str = request.args.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            start_date = datetime.now()
    else:
        start_date = datetime.now()
        
    # Reset time to midnight
    start_date = datetime(start_date.year, start_date.month, start_date.day)
    
    num_days = 31
    
    occupancy = _normalize_occupancy_map(load_room_occupancy())
    reservations = service.get_february_reservations()
    
    grid = service.get_occupancy_grid(occupancy, start_date, num_days)
    grid = service.allocate_reservations(grid, reservations, start_date, num_days)
    segments = service.get_gantt_segments(grid, start_date, num_days)
    
    days = []
    today_date = datetime.now().date()
    curr = start_date
    for i in range(num_days):
        days.append({
            'day': curr.day,
            'weekday': curr.strftime('%a'),
            'is_weekend': curr.weekday() >= 5,
            'is_today': curr.date() == today_date,
            'iso_date': curr.strftime('%Y-%m-%d')
        })
        curr += timedelta(days=1)
        
    mapping = service.get_room_mapping()
    reference_day = start_date.strftime('%Y-%m-%d')
    closed_categories_reference = InventoryRestrictionService.closed_categories_for_day(reference_day)
    grouped_rooms = []
    for cat, rooms in mapping.items():
        grouped_rooms.append({
            'category': cat,
            'rooms': rooms,
            'closed_for_sale': cat in closed_categories_reference
        })

    occupied_room_numbers = set()
    for room_key, room_data in (occupancy or {}).items():
        if not room_data:
            continue
        room_str = str(room_key).strip()
        if not room_str:
            continue
        occupied_room_numbers.add(room_str)
        if room_str.isdigit():
            occupied_room_numbers.add(room_str.zfill(2))
    heatmap_payload = RevenueManagementService.reservations_calendar_heatmap(
        start_date=start_date.strftime('%Y-%m-%d'),
        days=num_days,
    )
    heatmap_index = {str(item.get('date')): item for item in (heatmap_payload.get('rows') or []) if isinstance(item, dict)}
    heatmap_rows = []
    for day in days:
        item = heatmap_index.get(day.get('iso_date'))
        if not isinstance(item, dict):
            item = {
                'date': day.get('iso_date'),
                'occupancy_current_pct': 0.0,
                'occupancy_projected_pct': 0.0,
                'average_rate': 0.0,
                'heat_level': 'low',
                'heat_color': 'green',
            }
        heatmap_rows.append(item)
        
    return render_template('reception_reservations.html',
                          start_date=start_date,
                          days=days,
                          grouped_rooms=grouped_rooms,
                          segments=segments,
                          grid=grid,
                          heatmap_rows=heatmap_rows,
                          occupied_room_numbers=sorted(occupied_room_numbers),
                          today_iso=today_date.strftime('%Y-%m-%d'),
                          today_br=today_date.strftime('%d/%m/%Y'),
                          closed_categories_reference=closed_categories_reference,
                          reservation_status_catalog=ReservationService.RESERVATION_STATUS_CATALOG,
                          operational_status_catalog=ReservationService.OPERATIONAL_STATUS_CATALOG,
                          year=start_date.year,
                          month=start_date.month)

@reception_bp.route('/reception/surveys', methods=['GET', 'POST'])
@login_required
def reception_surveys():
    # Permission check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    try:
        db.create_all()
    except Exception:
        pass

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            title = request.form.get('title', '').strip()
            audience = request.form.get('audience', 'hotel').strip()
            is_active = bool(request.form.get('is_active'))
            if not title:
                flash('Título é obrigatório.', 'danger')
                return redirect(url_for('reception.reception_surveys'))
            # Gera slug público único
            base_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:24] or 'survey'
            slug = base_slug
            suffix = 1
            while SatisfactionSurvey.query.filter_by(public_slug=slug).first() is not None:
                suffix += 1
                slug = f"{base_slug}-{suffix}"
                if len(slug) > 40:
                    slug = f"survey-{uuid.uuid4().hex[:8]}"
                    break
            survey = SatisfactionSurvey(
                title=title,
                audience=audience if audience in ['hotel', 'restaurant', 'colaboradores', 'candidatos'] else 'hotel',
                is_active=is_active,
                public_slug=slug
            )
            db.session.add(survey)
            db.session.commit()
            flash('Pesquisa criada com sucesso.', 'success')
            return redirect(url_for('reception.reception_surveys'))
        elif action == 'invite_waiting_list_segment':
            survey_id = request.form.get('survey_id', '').strip()
            selected_survey = SatisfactionSurvey.query.filter_by(id=survey_id, audience='restaurant').first()
            if not selected_survey:
                flash('Pesquisa de restaurante não encontrada.', 'warning')
                return redirect(url_for('reception.reception_surveys'))
            seg_filters = {
                'country_code': request.form.get('queue_country', '').strip(),
                'status': request.form.get('queue_status', '').strip(),
                'name': request.form.get('queue_name', '').strip(),
                'phone': request.form.get('queue_phone', '').strip(),
                'start_date': request.form.get('queue_start_date', '').strip(),
                'end_date': request.form.get('queue_end_date', '').strip(),
                'wait_min': request.form.get('queue_wait_min', '').strip(),
                'wait_max': request.form.get('queue_wait_max', '').strip(),
                'party_size': request.form.get('queue_party_size', '').strip(),
                'table_id': request.form.get('queue_table_id', '').strip(),
                'source': request.form.get('queue_source', '').strip(),
                'consent_mode': request.form.get('queue_consent_mode', '').strip(),
                'served_only': '1',
                'survey_status': request.form.get('queue_survey_status', '').strip(),
            }
            require_consent_survey = bool(request.form.get('queue_require_consent_survey'))
            require_consent_marketing = bool(request.form.get('queue_require_consent_marketing'))
            only_final = bool(request.form.get('queue_only_final'))
            rows = waiting_list_service.get_queue_history_filtered(filters=seg_filters, limit=3000)
            final_statuses = {'sentado', 'desistiu', 'cancelado_pela_equipe', 'nao_compareceu', 'expirado'}
            candidates = []
            for row in rows:
                status_norm = waiting_list_service.get_public_status_view(row.get('status')).get('code')
                if only_final and status_norm not in final_statuses:
                    continue
                if require_consent_survey and not bool(row.get('consent_survey')):
                    continue
                if require_consent_marketing and not bool(row.get('consent_marketing')):
                    continue
                already_sent = False
                for sent in row.get('survey_invites', []) or []:
                    if isinstance(sent, dict) and sent.get('survey_id') == selected_survey.id:
                        already_sent = True
                        break
                if already_sent:
                    continue
                candidates.append(row)
            sent_count = 0
            fail_count = 0
            for row in candidates:
                try:
                    ref = _generate_unique_invite_ref(selected_survey.id)
                    inv = SatisfactionSurveyInvite(
                        survey_id=selected_survey.id,
                        waiting_list_id=row.get('id'),
                        ref=ref,
                        sent_at=datetime.now(),
                        delivery_status='enviada'
                    )
                    db.session.add(inv)
                    db.session.flush()
                    invite_url = url_for('guest.satisfaction_survey_by_slug', slug=selected_survey.public_slug, _external=False) + f"?ref={ref}"
                    waiting_list_service.register_survey_invite(
                        entry_id=row.get('id'),
                        survey_id=selected_survey.id,
                        ref=ref,
                        invited_by=session.get('user'),
                        invite_url=invite_url,
                        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'trigger': 'segment_campaign'}
                    )
                    sent_count += 1
                except Exception as exc:
                    fail_count += 1
                    waiting_list_service.mark_survey_failed(
                        entry_id=row.get('id'),
                        error_message=str(exc),
                        user=session.get('user'),
                        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'trigger': 'segment_campaign'}
                    )
            db.session.commit()
            if fail_count > 0:
                flash(f'Convites gerados para {sent_count} contato(s) e {fail_count} falha(s).', 'warning')
            else:
                flash(f'Convites gerados para {sent_count} contato(s) da fila virtual.', 'success')
            return redirect(url_for('reception.reception_surveys'))
        elif action == 'register_waiting_list_marketing_campaign':
            campaign_key = request.form.get('campaign_key', '').strip() or f"campanha_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            seg_filters = {
                'country_code': request.form.get('queue_country', '').strip(),
                'status': request.form.get('queue_status', '').strip(),
                'name': request.form.get('queue_name', '').strip(),
                'phone': request.form.get('queue_phone', '').strip(),
                'start_date': request.form.get('queue_start_date', '').strip(),
                'end_date': request.form.get('queue_end_date', '').strip(),
                'wait_min': request.form.get('queue_wait_min', '').strip(),
                'wait_max': request.form.get('queue_wait_max', '').strip(),
                'party_size': request.form.get('queue_party_size', '').strip(),
                'table_id': request.form.get('queue_table_id', '').strip(),
                'source': request.form.get('queue_source', '').strip(),
                'consent_mode': request.form.get('queue_consent_mode', '').strip(),
                'survey_status': request.form.get('queue_survey_status', '').strip(),
            }
            rows = waiting_list_service.get_queue_history_filtered(filters=seg_filters, limit=3000)
            status_targets = {'sentado', 'desistiu', 'cancelado_pela_equipe'}
            marked = 0
            for row in rows:
                status_norm = waiting_list_service.get_public_status_view(row.get('status')).get('code')
                if status_norm not in status_targets:
                    continue
                if not bool(row.get('consent_marketing')):
                    continue
                updated = waiting_list_service.register_marketing_campaign_target(
                    entry_id=row.get('id'),
                    campaign_key=campaign_key,
                    user=session.get('user'),
                    channel='whatsapp',
                    action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'trigger': 'marketing_campaign'}
                )
                if updated:
                    marked += 1
            flash(f'{marked} contato(s) da fila foram marcados para campanha futura "{campaign_key}".', 'success')
            return redirect(url_for('reception.reception_surveys'))
        elif action == 'delete':
            survey_id = request.form.get('survey_id')
            s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
            if s:
                # Remover dependências
                SatisfactionSurveyInvite.query.filter_by(survey_id=s.id).delete()
                SatisfactionSurveyResponse.query.filter_by(survey_id=s.id).delete()
                SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).delete()
                db.session.delete(s)
                db.session.commit()
                flash('Pesquisa removida.', 'success')
            else:
                flash('Pesquisa não encontrada.', 'warning')
            return redirect(url_for('reception.reception_surveys'))

    segment_filters = {
        'country_code': request.args.get('queue_country', '').strip(),
        'status': request.args.get('queue_status', '').strip(),
        'name': request.args.get('queue_name', '').strip(),
        'phone': request.args.get('queue_phone', '').strip(),
        'start_date': request.args.get('queue_start_date', '').strip(),
        'end_date': request.args.get('queue_end_date', '').strip(),
        'wait_min': request.args.get('queue_wait_min', '').strip(),
        'wait_max': request.args.get('queue_wait_max', '').strip(),
        'party_size': request.args.get('queue_party_size', '').strip(),
        'table_id': request.args.get('queue_table_id', '').strip(),
        'source': request.args.get('queue_source', '').strip() or 'fila_virtual',
        'consent_mode': request.args.get('queue_consent_mode', '').strip(),
        'survey_status': request.args.get('queue_survey_status', '').strip(),
    }
    require_consent_survey = request.args.get('queue_require_consent_survey', '1').strip() != '0'
    require_consent_marketing = request.args.get('queue_require_consent_marketing', '').strip() == '1'
    only_final = request.args.get('queue_only_final', '1').strip() != '0'
    queue_candidates_all = waiting_list_service.get_queue_history_filtered(filters=segment_filters, limit=3000)
    final_statuses = {'sentado', 'desistiu', 'cancelado_pela_equipe', 'nao_compareceu', 'expirado'}
    queue_candidates = []
    country_stats = {}
    status_stats = {}
    for row in queue_candidates_all:
        status_norm = waiting_list_service.get_public_status_view(row.get('status')).get('code')
        if only_final and status_norm not in final_statuses:
            continue
        if require_consent_survey and not bool(row.get('consent_survey')):
            continue
        if require_consent_marketing and not bool(row.get('consent_marketing')):
            continue
        queue_candidates.append(row)
        cc = str(row.get('country_code') or 'N/A')
        country_stats[cc] = country_stats.get(cc, 0) + 1
        status_stats[status_norm] = status_stats.get(status_norm, 0) + 1

    restaurant_surveys = SatisfactionSurvey.query.filter_by(audience='restaurant').order_by(SatisfactionSurvey.updated_at.desc()).all()

    # Estatísticas por público
    stats_by_audience = {
        'hotel': {'sent': 0, 'responded': 0},
        'restaurant': {'sent': 0, 'responded': 0},
        'colaboradores': {'sent': 0, 'responded': 0},
        'candidatos': {'sent': 0, 'responded': 0},
    }
    # Agregados (counts) por audience
    surveys = SatisfactionSurvey.query.order_by(SatisfactionSurvey.created_at.desc()).all()
    survey_ids = [s.id for s in surveys]
    if survey_ids:
        # invites
        inv_counts = dict(
            db.session.query(SatisfactionSurveyInvite.survey_id, func.count('*'))
            .filter(SatisfactionSurveyInvite.survey_id.in_(survey_ids))
            .group_by(SatisfactionSurveyInvite.survey_id)
            .all()
        )
        # responses
        resp_counts = dict(
            db.session.query(SatisfactionSurveyResponse.survey_id, func.count('*'))
            .filter(SatisfactionSurveyResponse.survey_id.in_(survey_ids))
            .group_by(SatisfactionSurveyResponse.survey_id)
            .all()
        )
        # questions
        q_counts = dict(
            db.session.query(SatisfactionSurveyQuestion.survey_id, func.count('*'))
            .filter(SatisfactionSurveyQuestion.survey_id.in_(survey_ids))
            .group_by(SatisfactionSurveyQuestion.survey_id)
            .all()
        )
    else:
        inv_counts, resp_counts, q_counts = {}, {}, {}

    items = []
    for s in surveys:
        audience = s.audience or 'hotel'
        if audience not in stats_by_audience:
            audience = 'hotel'
        stats_by_audience[audience]['sent'] += inv_counts.get(s.id, 0)
        stats_by_audience[audience]['responded'] += resp_counts.get(s.id, 0)
        public_url = url_for('guest.satisfaction_survey', _external=False)
        items.append({
            'survey': s,
            'questions_count': q_counts.get(s.id, 0),
            'invites_count': inv_counts.get(s.id, 0),
            'responses_count': resp_counts.get(s.id, 0),
            'public_url': public_url,
        })

    return render_template('reception_surveys.html',
                           stats_by_audience=stats_by_audience,
                           items=items,
                           restaurant_surveys=restaurant_surveys,
                           queue_candidates=queue_candidates[:30],
                           queue_candidates_count=len(queue_candidates),
                           queue_country_stats=country_stats,
                           queue_status_stats=status_stats,
                           queue_segment_filters=segment_filters,
                           queue_require_consent_survey=require_consent_survey,
                           queue_require_consent_marketing=require_consent_marketing,
                           queue_only_final=only_final)

@reception_bp.route('/reception/surveys/<survey_id>/edit', methods=['GET', 'POST'])
@login_required
def reception_survey_edit(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        flash('Pesquisa não encontrada.', 'warning')
        return redirect(url_for('reception.reception_surveys'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        audience = request.form.get('audience', 'hotel').strip()
        is_active = bool(request.form.get('is_active'))
        intro_text = request.form.get('intro_text') or ''
        thank_you_text = request.form.get('thank_you_text') or ''
        if title:
            s.title = title
        s.audience = audience if audience in ['hotel', 'restaurant', 'colaboradores', 'candidatos'] else 'hotel'
        s.is_active = is_active
        s.intro_text = intro_text
        s.thank_you_text = thank_you_text
        s.updated_at = datetime.now()
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(url_for('reception.reception_survey_edit', survey_id=survey_id))
    inv_count = db.session.query(func.count('*')).select_from(SatisfactionSurveyInvite).filter_by(survey_id=s.id).scalar()
    resp_count = db.session.query(func.count('*')).select_from(SatisfactionSurveyResponse).filter_by(survey_id=s.id).scalar()
    q_count = db.session.query(func.count('*')).select_from(SatisfactionSurveyQuestion).filter_by(survey_id=s.id).scalar()
    public_url = url_for('guest.satisfaction_survey_by_slug', slug=s.public_slug, _external=False)
    return render_template('reception_survey_edit.html',
                           survey=s,
                           questions_count=q_count,
                           invites_count=inv_count,
                           responses_count=resp_count,
                           public_url=public_url)

@reception_bp.route('/reception/surveys/<survey_id>/questions', methods=['GET', 'POST'])
@login_required
def reception_survey_questions(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        flash('Pesquisa não encontrada.', 'warning')
        return redirect(url_for('reception.reception_surveys'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_question':
            text = request.form.get('question_text', '').strip()
            qtype = request.form.get('question_type', 'rating_0_10').strip()
            required = bool(request.form.get('required'))
            options_raw = request.form.get('options_raw', '').strip()
            options_json = None
            if options_raw:
                lines = [l.strip() for l in options_raw.splitlines() if l.strip()]
                if lines:
                    options_json = json.dumps(lines, ensure_ascii=False)
            max_pos = db.session.query(func.max(SatisfactionSurveyQuestion.position)).filter_by(survey_id=s.id).scalar() or 0
            q = SatisfactionSurveyQuestion(
                survey_id=s.id,
                position=max_pos + 1,
                question_text=text or 'Pergunta',
                question_type=qtype if qtype else 'rating_0_10',
                required=required,
                options_json=options_json
            )
            db.session.add(q)
            db.session.commit()
            flash('Pergunta adicionada.', 'success')
            return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
        elif action == 'update_question':
            qid = request.form.get('question_id')
            q = SatisfactionSurveyQuestion.query.filter_by(id=qid, survey_id=s.id).first()
            if not q:
                flash('Pergunta não encontrada.', 'warning')
                return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
            text = request.form.get('question_text', '').strip()
            qtype = request.form.get('question_type', '').strip()
            required = bool(request.form.get('required'))
            options_raw = request.form.get('options_raw', '').strip()
            if text:
                q.question_text = text
            if qtype:
                q.question_type = qtype
            q.required = required
            if options_raw:
                lines = [l.strip() for l in options_raw.splitlines() if l.strip()]
                if lines:
                    q.options_json = json.dumps(lines, ensure_ascii=False)
                else:
                    q.options_json = None
            elif q.question_type != 'multiple_choice':
                q.options_json = None
            db.session.commit()
            flash('Pergunta atualizada.', 'success')
            return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
        elif action == 'delete_question':
            qid = request.form.get('question_id')
            q = SatisfactionSurveyQuestion.query.filter_by(id=qid, survey_id=s.id).first()
            if q:
                db.session.delete(q)
                db.session.commit()
                # Renumerar posições após remoção
                qs_all = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
                for idx, item in enumerate(qs_all, start=1):
                    item.position = idx
                db.session.commit()
                flash('Pergunta removida.', 'success')
            else:
                flash('Pergunta não encontrada.', 'warning')
            return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
        elif action in ['move_up', 'move_down']:
            qid = request.form.get('question_id')
            q = SatisfactionSurveyQuestion.query.filter_by(id=qid, survey_id=s.id).first()
            if not q:
                flash('Pergunta não encontrada.', 'warning')
                return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
            # Buscar todas ordenadas
            qs_all = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
            # Criar mapa id->index
            idx_map = {item.id: i for i, item in enumerate(qs_all)}
            i = idx_map.get(q.id, None)
            if i is None:
                return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
            if action == 'move_up' and i > 0:
                qs_all[i].position, qs_all[i-1].position = qs_all[i-1].position, qs_all[i].position
            elif action == 'move_down' and i < len(qs_all) - 1:
                qs_all[i].position, qs_all[i+1].position = qs_all[i+1].position, qs_all[i].position
            db.session.commit()
            # Normalizar posições 1..N
            qs_all_sorted = sorted(qs_all, key=lambda x: x.position)
            for idx, item in enumerate(qs_all_sorted, start=1):
                item.position = idx
            db.session.commit()
            return redirect(url_for('reception.reception_survey_questions', survey_id=survey_id))
    qs = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
    for q in qs:
        lines = []
        if q.options_json:
            try:
                data = json.loads(q.options_json)
                if isinstance(data, list):
                    lines = [str(x) for x in data]
                else:
                    lines = [str(data)]
            except Exception:
                lines = [q.options_json]
        q.options_lines = "\n".join(lines)
    return render_template('reception_survey_edit.html',
                           survey=s,
                           questions=qs,
                           questions_count=len(qs),
                           invites_count=db.session.query(func.count('*')).select_from(SatisfactionSurveyInvite).filter_by(survey_id=s.id).scalar(),
                           responses_count=db.session.query(func.count('*')).select_from(SatisfactionSurveyResponse).filter_by(survey_id=s.id).scalar(),
                           public_url=url_for('guest.satisfaction_survey_by_slug', slug=s.public_slug, _external=False))

@reception_bp.route('/reception/surveys/<survey_id>/dashboard')
@login_required
def reception_survey_dashboard(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        flash('Pesquisa não encontrada.', 'warning')
        return redirect(url_for('reception.reception_surveys'))
    qs = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
    rating_qid = None
    for q in qs:
        if str(q.question_type).startswith('rating'):
            rating_qid = q.id
            break
    resps = SatisfactionSurveyResponse.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyResponse.submitted_at.desc()).all()
    scores = []
    recent = []
    for r in resps[:10]:
        cat = None
        sc = None
        try:
            ans = json.loads(r.answers_json)
        except:
            ans = {}
        if rating_qid:
            key = f"q_{rating_qid}"
            try:
                sc = float(ans.get(key)) if key in ans else None
            except:
                sc = None
            if sc is not None:
                scores.append(sc)
                if sc >= 9:
                    cat = 'promotor'
                elif sc >= 7:
                    cat = 'neutro'
                else:
                    cat = 'detrator'
        recent.append({
            'id': r.id,
            'submitted_at': r.submitted_at,
            'ref': None,
            'short_id': r.id.split('-')[0] if r.id else '',
            'score': sc,
            'category': cat,
            'notes': ''
        })
    total_responses = len(resps)
    has_rating = rating_qid is not None
    avg_score = sum(scores) / len(scores) if scores else None
    promoters = len([x for x in scores if x is not None and x >= 9])
    passives = len([x for x in scores if x is not None and 7 <= x < 9])
    detractors = len([x for x in scores if x is not None and x < 7])
    nps = None
    if total_responses and has_rating:
        nps = int(((promoters - detractors) / total_responses) * 100)
    # Range selector
    range_mode = request.args.get('range', 'week')
    labels = []
    counts = []
    today = datetime.now().date()
    if range_mode == 'week':
        for i in range(6, -1, -1):
            d = today.fromordinal(today.toordinal() - i)
            labels.append(d.strftime('%d/%m'))
            c = 0
            for r in resps:
                if r.submitted_at and r.submitted_at.date() == d:
                    c += 1
            counts.append(c)
    elif range_mode == 'month':
        for i in range(29, -1, -1):
            d = today.fromordinal(today.toordinal() - i)
            labels.append(d.strftime('%d/%m'))
            c = 0
            for r in resps:
                if r.submitted_at and r.submitted_at.date() == d:
                    c += 1
            counts.append(c)
    elif range_mode == 'semester':
        # Últimos 6 meses, por mês
        cur = datetime(today.year, today.month, 1)
        months = []
        for i in range(5, -1, -1):
            y = (cur.year if cur.month - i > 0 else cur.year - 1)
            m = (cur.month - i) if (cur.month - i) > 0 else (12 + (cur.month - i))
            months.append((y, m))
        for y, m in months:
            labels.append(f"{m:02d}/{y%100:02d}")
            c = 0
            for r in resps:
                if r.submitted_at and r.submitted_at.year == y and r.submitted_at.month == m:
                    c += 1
            counts.append(c)
    elif range_mode == 'year':
        # Últimos 12 meses, por mês
        cur = datetime(today.year, today.month, 1)
        months = []
        for i in range(11, -1, -1):
            y = (cur.year if cur.month - i > 0 else cur.year - 1)
            m = (cur.month - i) if (cur.month - i) > 0 else (12 + (cur.month - i))
            months.append((y, m))
        for y, m in months:
            labels.append(f"{m:02d}/{y%100:02d}")
            c = 0
            for r in resps:
                if r.submitted_at and r.submitted_at.year == y and r.submitted_at.month == m:
                    c += 1
            counts.append(c)
    else:
        range_mode = 'week'
        for i in range(6, -1, -1):
            d = today.fromordinal(today.toordinal() - i)
            labels.append(d.strftime('%d/%m'))
            c = 0
            for r in resps:
                if r.submitted_at and r.submitted_at.date() == d:
                    c += 1
            counts.append(c)
    # Para o gráfico de média, usamos a média global como linha de referência
    chart_avgs = []
    for _ in labels:
        chart_avgs.append(avg_score if avg_score is not None else 0)
    return render_template('satisfaction_survey_dashboard.html',
                           survey=s,
                           range_mode=range_mode,
                           total_responses=total_responses,
                           has_rating=has_rating,
                           avg_score=avg_score,
                           nps=nps,
                           promoters=promoters,
                           passives=passives,
                           detractors=detractors,
                           recent=recent,
                           chart_labels=labels,
                           chart_counts=counts,
                           chart_avgs=chart_avgs,
                           google_review_url=None,
                           tripadvisor_review_url=None)

@reception_bp.route('/reception/surveys/<survey_id>/export')
@login_required
def reception_survey_export(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        flash('Pesquisa não encontrada.', 'warning')
        return redirect(url_for('reception.reception_surveys'))
    range_mode = request.args.get('range', 'week')
    today = datetime.now().date()
    days = None
    if range_mode == 'week':
        days = 6
    elif range_mode == 'month':
        days = 29
    elif range_mode == 'semester':
        days = 180
    elif range_mode == 'year':
        days = 365
    if days is not None:
        start_date = today - timedelta(days=days)
        start_dt = datetime.combine(start_date, datetime.min.time())
        resps = SatisfactionSurveyResponse.query.filter_by(survey_id=s.id).filter(
            SatisfactionSurveyResponse.submitted_at >= start_dt
        ).order_by(SatisfactionSurveyResponse.submitted_at.desc()).all()
    else:
        resps = SatisfactionSurveyResponse.query.filter_by(survey_id=s.id).order_by(
            SatisfactionSurveyResponse.submitted_at.desc()
        ).all()
    qs = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
    header = ['id', 'submitted_at', 'ref', 'ip', 'user_agent']
    for q in qs:
        header.append(f"Q{q.position} - {q.question_text[:40]}")
    header.extend(['score', 'category'])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    rating_qid = None
    for q in qs:
        if str(q.question_type).startswith('rating'):
            rating_qid = q.id
            break
    resp_ids = [r.id for r in resps]
    invite_map = {}
    if resp_ids:
        invites = SatisfactionSurveyInvite.query.filter(
            SatisfactionSurveyInvite.survey_id == s.id,
            SatisfactionSurveyInvite.used_response_id.in_(resp_ids)
        ).all()
        for inv in invites:
            rid = getattr(inv, 'used_response_id', None)
            if rid:
                invite_map[rid] = inv.ref
    for r in resps:
        try:
            ans = json.loads(r.answers_json)
        except:
            ans = {}
        meta = {}
        if getattr(r, 'meta_json', None):
            try:
                meta = json.loads(r.meta_json)
            except Exception:
                meta = {}
        ip = meta.get('ip', '')
        ua = meta.get('user_agent', '')
        if ua:
            ua = ua[:120]
        ref = invite_map.get(r.id, '')
        row = [r.id, r.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if r.submitted_at else '', ref, ip, ua]
        for q in qs:
            key = f"q_{q.id}"
            row.append(ans.get(key, ''))
        score = None
        cat = None
        if rating_qid:
            key = f"q_{rating_qid}"
            try:
                score = float(ans.get(key)) if key in ans else None
            except:
                score = None
            if score is not None:
                if score >= 9:
                    cat = 'promotor'
                elif score >= 7:
                    cat = 'neutro'
                else:
                    cat = 'detrator'
        row.append(score if score is not None else '')
        row.append(cat or '')
        writer.writerow(row)
    data = output.getvalue().encode('utf-8-sig')
    buffer = io.BytesIO(data)
    buffer.seek(0)
    filename = f"pesquisa_{survey_id}_{range_mode}.csv"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='text/csv')

@reception_bp.route('/reception/surveys/<survey_id>/responses/<response_id>')
@login_required
def reception_survey_response_detail(survey_id, response_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        flash('Pesquisa não encontrada.', 'warning')
        return redirect(url_for('reception.reception_surveys'))
    r = SatisfactionSurveyResponse.query.filter_by(id=response_id, survey_id=s.id).first()
    if not r:
        flash('Resposta não encontrada.', 'warning')
        return redirect(url_for('reception.reception_survey_dashboard', survey_id=survey_id))
    qs = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).order_by(SatisfactionSurveyQuestion.position).all()
    try:
        ans = json.loads(r.answers_json)
    except Exception:
        ans = {}
    meta_raw = {}
    if getattr(r, 'meta_json', None):
        try:
            meta_raw = json.loads(r.meta_json)
        except Exception:
            meta_raw = {}
    meta = {
        'ip': meta_raw.get('ip', ''),
        'user_agent': meta_raw.get('user_agent', '')
    }
    rating_qid = None
    for q in qs:
        if str(q.question_type).startswith('rating'):
            rating_qid = q.id
            break
    score = None
    category = None
    if rating_qid:
        key = f"q_{rating_qid}"
        try:
            score = float(ans.get(key)) if key in ans else None
        except Exception:
            score = None
        if score is not None:
            if score >= 9:
                category = 'promotor'
            elif score >= 7:
                category = 'neutro'
            else:
                category = 'detrator'
    answers = []
    for q in qs:
        key = f"q_{q.id}"
        answers.append({
            'position': q.position,
            'question': q.question_text,
            'answer': ans.get(key, ''),
            'type': q.question_type
        })
    ref = None
    inv = SatisfactionSurveyInvite.query.filter_by(survey_id=s.id, used_response_id=response_id).first()
    if inv:
        ref = inv.ref
    return render_template('reception_survey_response_detail.html',
                           survey=s,
                           response=r,
                           answers=answers,
                           meta=meta,
                           score=score,
                           category=category,
                           ref=ref)

@reception_bp.route('/reception/surveys/<survey_id>/invite/new', methods=['POST'])
@login_required
def reception_survey_invite_new(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        return jsonify({'ok': False, 'error': 'Acesso restrito.'}), 403
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        return jsonify({'ok': False, 'error': 'Pesquisa não encontrada.'}), 404
    ref = request.json.get('ref') if request.is_json else None
    if not ref:
        chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        ref = ''.join(random.choice(chars) for _ in range(8))
    # Garantir unicidade por pesquisa
    exists = SatisfactionSurveyInvite.query.filter_by(survey_id=s.id, ref=ref).first()
    if exists:
        return jsonify({'ok': False, 'error': 'Ref em uso.'}), 400
    inv = SatisfactionSurveyInvite(survey_id=s.id, ref=ref)
    db.session.add(inv)
    db.session.commit()
    base_url = url_for('guest.satisfaction_survey_by_slug', slug=s.public_slug, _external=False)
    link = f"{base_url}?ref={ref}"
    return jsonify({'ok': True, 'ref': ref, 'link': link})

@reception_bp.route('/reception/surveys/<survey_id>/questions/reorder', methods=['POST'])
@login_required
def reception_survey_questions_reorder(survey_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        return jsonify({'ok': False, 'error': 'Acesso restrito.'}), 403
    s = SatisfactionSurvey.query.filter_by(id=survey_id).first()
    if not s:
        return jsonify({'ok': False, 'error': 'Pesquisa não encontrada.'}), 404
    if not request.is_json:
        return jsonify({'ok': False, 'error': 'JSON obrigatório.'}), 400
    data = request.get_json(silent=True) or {}
    order = data.get('order')
    if not isinstance(order, list):
        return jsonify({'ok': False, 'error': 'Formato inválido.'}), 400
    qs_all = SatisfactionSurveyQuestion.query.filter_by(survey_id=s.id).all()
    id_map = {str(q.id): q for q in qs_all}
    used = set()
    pos = 1
    for qid in order:
        q = id_map.get(str(qid))
        if not q:
            continue
        q.position = pos
        pos += 1
        used.add(q.id)
    # Qualquer pergunta não incluída fica no final, mantendo ordem atual
    for q in qs_all:
        if q.id not in used:
            q.position = pos
            pos += 1
    db.session.commit()
    return jsonify({'ok': True})
@reception_bp.route('/reception/print_pending_bills', methods=['POST'])
@login_required
def print_reception_pending_bills():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
        return jsonify({'success': False, 'message': 'Acesso não autorizado.'}), 403

    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400
            
        printer_id = sanitize_input(data.get('printer_id'))
        save_default = bool(data.get('save_default', False))
        room_filter = sanitize_input(data.get('room_number'))
        
        if not printer_id:
            return jsonify({'success': False, 'message': 'Nenhuma impressora selecionada.'}), 400

        if save_default:
            settings = load_printer_settings()
            settings['default_reception_report_printer_id'] = printer_id
            save_printer_settings(settings)
            
        printers = load_printers()
        printer_name = next((p['name'] for p in printers if p['id'] == printer_id), None)
        
        if not printer_name:
             return jsonify({'success': False, 'message': 'Impressora não encontrada no sistema.'}), 404
        
        room_charges = load_room_charges()
        if not isinstance(room_charges, list):
            room_charges = []
            
        pending_charges = []
        for c in room_charges:
             if isinstance(c, dict) and c.get('status') == 'pending':
                 pending_charges.append(c)
        
        if room_filter:
            pending_charges = [c for c in pending_charges if str(c.get('room_number')) == str(room_filter)]
            
        room_occupancy = load_room_occupancy()
        
        formatted_bills = []
        
        for charge in pending_charges:
            room_num = str(charge.get('room_number'))
            guest_name = room_occupancy.get(room_num, {}).get('guest_name', 'Desconhecido')
            
            products = []
            for item in charge.get('items', []):
                products.append({
                    "name": item.get('name', 'Item'),
                    "qty": float(item.get('qty', 1)),
                    "unit_price": float(item.get('price', 0)),
                    "subtotal": float(item.get('total', 0))
                })
            
            service_fee = float(charge.get('service_fee', 0))
            if service_fee > 0:
                products.append({
                    "name": "Taxa de Serviço (10%)",
                    "qty": 1.0,
                    "unit_price": service_fee,
                    "subtotal": service_fee
                })
            
            formatted_bills.append({
                "origin": {
                    "client": guest_name,
                    "table": f"Quarto {room_num}",
                    "order_id": charge.get('id', 'N/A')
                },
                "products": products
            })
            
        if not formatted_bills:
            return jsonify({'success': False, 'message': 'Não há contas pendentes para imprimir.'})

        result = process_and_print_pending_bills(formatted_bills, printer_name)
        
        if result['errors']:
             return jsonify({'success': False, 'message': f"Erros na impressão: {', '.join(result['errors'])}"}), 500
             
        return jsonify({
            'success': True, 
            'message': f'Relatório enviado para {printer_name}. {result["summary"]["total_bills_count"]} contas processadas.'
        })

    except Exception as e:
        print(f"Error printing reception report: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Erro interno: {str(e)}"}), 500

@reception_bp.route('/api/reception/return_to_restaurant', methods=['POST'])
@login_required
def api_reception_return_to_restaurant():
    user_role = session.get('role')
    user_dept = session.get('department')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente', 'supervisor'] and user_dept != 'Recepção' and 'recepcao' not in user_perms:
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Dados inválidos'}), 400

        charge_id = sanitize_input(data.get('charge_id'))
        target_table_id = sanitize_input(data.get('target_table_id')) 
        user_name = session.get('user', 'Unknown')
        
        if not charge_id:
            return jsonify({'success': False, 'error': 'ID da cobrança não fornecido'})

        success, message = return_charge_to_restaurant(charge_id, user_name, target_table_id=target_table_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
            
    except TableOccupiedError as e:
        return jsonify({
            'success': False, 
            'error': str(e),
            'error_code': 'TABLE_OCCUPIED',
            'free_tables': e.free_tables
        }), 409
    except TransferError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error returning charge to restaurant: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/pay_charge/<charge_id>', methods=['POST'])
@login_required
def reception_pay_charge(charge_id):
    try:
        data = request.json
        payments = data.get('payments', [])
        room_num = data.get('room_num')
        
        if not payments:
            return jsonify({'success': False, 'message': 'Nenhum pagamento informado.'})

        room_charges = load_room_charges()
        charge = next((c for c in room_charges if c['id'] == charge_id), None)
        
        if not charge:
            return jsonify({'success': False, 'message': 'Conta não encontrada.'})
            
        if charge.get('status') == 'paid':
             return jsonify({'success': False, 'message': 'Conta já paga.'})

        # Load session
        sessions = load_cashier_sessions()
        
        # Debug Logging for Session Verification
        open_sessions = [s for s in sessions if s.get('status') == 'open']
        current_app.logger.info(f"Payment Verification: Found {len(open_sessions)} open sessions. Types: {[s.get('type') for s in open_sessions]}")

        # Check for any valid reception session type
        # Valid types: 'reception' (legacy), 'guest_consumption', 'reception_room_billing'
        valid_types = ['reception', 'guest_consumption', 'reception_room_billing']
        
        current_session = next((s for s in reversed(sessions) 
                                if s['status'] == 'open' and s.get('type') in valid_types), None)
        
        if not current_session:
             current_app.logger.warning("Payment Verification Failed: No open reception cashier session found.")
             return jsonify({'success': False, 'message': 'Caixa da recepção fechado. Abra o caixa para receber pagamentos.'})

        current_app.logger.info(f"Payment Verification Success: Using session {current_session.get('id')} of type {current_session.get('type')}")

        # Calculate total paid
        total_paid = sum(float(p['amount']) for p in payments)
        charge_total = float(charge.get('total', 0))
        
        # Register transactions
        user = session.get('user', 'Sistema')
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
        payment_methods_list = load_payment_methods()
        
        payment_group_id = str(uuid.uuid4()) if len(payments) > 1 else None
        total_payment_group_amount = total_paid if payment_group_id else 0
        
        for p in payments:
            method_id = str(p.get('method'))
            method_name = next((m['name'] for m in payment_methods_list if str(m['id']) == method_id), 'Desconhecido')
            
            details = {}
            if payment_group_id:
                details['payment_group_id'] = payment_group_id
                details['total_payment_group_amount'] = total_payment_group_amount
                details['payment_method_code'] = method_name
            
            transaction = {
                'id': f"PAY_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}",
                'type': 'in',
                'category': 'Pagamento Item',
                'description': f"Pagamento Item Quarto {room_num} ({method_name})",
                'amount': float(p['amount']),
                'payment_method': method_name,
                'timestamp': timestamp,
                'user': user,
                'related_charge_id': charge_id,
                'details': details
            }
            current_session['transactions'].append(transaction)
            
        save_cashier_sessions(sessions)
        
        # Update charge
        charge['status'] = 'paid'
        charge['paid_at'] = timestamp
        charge['reception_cashier_id'] = current_session['id']
        # Persist the payments in a standard field
        try:
            normalized_payments = []
            for p in payments:
                normalized_payments.append({
                    'method': str(p.get('method')),
                    'amount': float(p.get('amount', 0))
                })
            charge['payments'] = normalized_payments
        except Exception:
            charge['payments'] = payments
        
        save_room_charges(room_charges)
        
        log_action('Pagamento Item', f'Quarto {room_num}: R$ {total_paid:.2f} pago.', department='Recepção')
        
        return jsonify({'success': True})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})

@reception_bp.route('/reception/charge/edit', methods=['POST'])
@login_required
def reception_edit_charge():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    source_page = request.form.get('source_page')

    def _redirect_after_edit():
        if source_page == 'reception_rooms':
            return redirect(url_for('reception.reception_rooms'))
        return redirect(url_for('reception.reception_cashier'))

    if user_role not in ['admin', 'gerente', 'supervisor'] and 'recepcao' not in user_perms:
        flash('Acesso não autorizado para editar contas.')
        return _redirect_after_edit()

    charge_id = sanitize_input(request.form.get('charge_id'))
    new_date = sanitize_input(request.form.get('new_date'))
    new_status = sanitize_input(request.form.get('new_status'))
    new_notes = sanitize_input(request.form.get('new_notes'))
    justification = sanitize_input(request.form.get('justification'))
    
    if not justification:
        flash('Justificativa é obrigatória para edição de contas.')
        return _redirect_after_edit()

    items_to_add_json = request.form.get('items_to_add', '[]')
    items_to_remove_json = request.form.get('items_to_remove', '[]')
    removal_justifications_json = request.form.get('removal_justifications', '{}')
    
    try:
        items_to_add = json.loads(items_to_add_json)
        items_to_remove = json.loads(items_to_remove_json)
        removal_justifications = json.loads(removal_justifications_json)
        
        # Validate structure of items to add
        if not isinstance(items_to_add, list): raise ValueError("Items to add must be a list")
        if not isinstance(items_to_remove, list): raise ValueError("Items to remove must be a list")
        
        for item in items_to_add:
            if 'id' not in item or 'qty' not in item:
                 raise ValueError("Invalid item structure in added items")
                 
    except (json.JSONDecodeError, ValueError) as e:
        flash(f'Erro ao processar itens da conta: {str(e)}')
        return _redirect_after_edit()

    room_charges = load_room_charges()
    charge = next((c for c in room_charges if c['id'] == charge_id), None)
    
    if not charge:
        flash('Conta não encontrada.')
        return _redirect_after_edit()
        
    old_status = charge.get('status')
    original_total = float(charge.get('total', 0))
        
    changes = []
    
    if new_date and new_date != charge.get('date'):
        changes.append(f"Data: {charge.get('date')} -> {new_date}")
        charge['date'] = new_date
        
    if new_status and new_status != charge.get('status'):
        changes.append(f"Status: {charge.get('status')} -> {new_status}")
        charge['status'] = new_status
        
    if new_notes != charge.get('notes', ''):
        changes.append(f"Obs: {charge.get('notes', '')} -> {new_notes}")
        charge['notes'] = new_notes

    try:
        menu_items = load_menu_items()
        products_insumos = load_products() 
    except Exception as e:
        current_app.logger.error(f"Error loading data for edit charge: {e}")
        menu_items = []
        products_insumos = []

    insumo_map = {str(i['id']): i for i in products_insumos}
    
    if items_to_remove:
        current_items = charge.get('items', [])
        kept_items = []
        removed_list = charge.get('removed_items', [])

        for idx, item in enumerate(current_items):
            item_id = item.get('id')
            item_idx_key = f"__idx_{idx}"
            should_remove = item_id in items_to_remove or item_idx_key in items_to_remove
            if should_remove:
                item_name = item.get('name')
                qty_removed = float(item.get('qty', 1))
                
                product_def = next((p for p in menu_items if p['name'] == item_name), None)
                
                if product_def and product_def.get('recipe'):
                    try:
                        for ingred in product_def['recipe']:
                            ing_id = str(ingred['ingredient_id'])
                            ing_qty = float(ingred['qty'])
                            total_refund = ing_qty * qty_removed
                            
                            insumo_data = insumo_map.get(ing_id)
                            
                            if insumo_data:
                                entry_data = {
                                    'id': f"REFUND_{charge.get('table_id', 'REC')}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ing_id}",
                                    'user': session.get('user', 'Sistema'),
                                    'product': insumo_data['name'],
                                    'supplier': f"ESTORNO: Recp {charge.get('room_number')}",
                                    'qty': total_refund, 
                                    'price': insumo_data.get('price', 0),
                                    'invoice': f"Edição Conta: {item_name}",
                                    'date': datetime.now().strftime('%d/%m/%Y'),
                                    'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                                }
                                save_stock_entry(entry_data)
                    except Exception as e:
                        print(f"Stock refund error (Reception): {e}")
                
                justification_text = (
                    removal_justifications.get(item_id) or
                    removal_justifications.get(item_idx_key) or
                    'Sem justificativa'
                )
                changes.append(f"Item Removido: {item_name} (x{qty_removed}) - Justificativa: {justification_text}")
                
                # Store for reversibility
                removed_item_entry = item.copy()
                removed_item_entry.update({
                    'removed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'removed_by': session.get('user', 'Sistema'),
                    'removal_justification': justification_text
                })
                removed_list.append(removed_item_entry)
            else:
                kept_items.append(item)
        
        charge['items'] = kept_items
        charge['removed_items'] = removed_list

    if items_to_add:
        for new_item in items_to_add:
            prod_id = new_item.get('id')
            try:
                qty = float(new_item.get('qty', 1))
            except ValueError:
                qty = 1.0
                
            product_def = next((p for p in menu_items if str(p['id']) == str(prod_id)), None)
            
            if product_def:
                if product_def.get('recipe'):
                    try:
                        for ingred in product_def['recipe']:
                            ing_id = str(ingred['ingredient_id'])
                            ing_qty = float(ingred['qty'])
                            total_needed = ing_qty * qty
                            
                            insumo_data = insumo_map.get(ing_id)
                            
                            if insumo_data:
                                entry_data = {
                                    'id': f"SALE_REC_{charge.get('room_number')}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ing_id}",
                                    'user': session.get('user', 'Sistema'),
                                    'product': insumo_data['name'],
                                    'supplier': f"VENDA: Recp {charge.get('room_number')}",
                                    'qty': -total_needed, 
                                    'price': insumo_data.get('price', 0),
                                    'invoice': f"Edição Conta",
                                    'date': datetime.now().strftime('%d/%m/%Y'),
                                    'entry_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                                }
                                save_stock_entry(entry_data)
                    except Exception as e:
                        print(f"Stock deduction error (Reception): {e}")

                item_entry = {
                    'id': str(uuid.uuid4()),
                    'name': product_def['name'],
                    'qty': qty,
                    'price': float(product_def['price']),
                    'category': product_def.get('category', 'Outros'),
                    'source': 'reception_edit',
                    'added_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'added_by': session.get('user')
                }
                charge.get('items', []).append(item_entry)
                changes.append(f"Item Adicionado: {product_def['name']} (x{qty})")

    if 'items' not in charge:
        charge['items'] = []
        
    taxable_total = 0.0
    total_items = 0.0
    
    for item in charge['items']:
        item_price = float(item.get('price', 0))
        item_qty = float(item.get('qty', 1))
        
        comps_price = sum(float(c.get('price', 0)) for c in item.get('complements', []))
        
        line_total = item_qty * (item_price + comps_price)
        total_items += line_total
        
        if not item.get('service_fee_exempt', False):
            taxable_total += line_total

    service_fee_removed = request.form.get('remove_service_fee') == 'on'
    
    if service_fee_removed != charge.get('service_fee_removed', False):
        if service_fee_removed:
            changes.append("Comissão de 10% removida")
        else:
            changes.append("Comissão de 10% restaurada")
        charge['service_fee_removed'] = service_fee_removed

    if service_fee_removed:
        service_fee = 0.0
    else:
        service_fee = taxable_total * 0.10
        
    grand_total = total_items + service_fee
    
    current_total = float(charge.get('total', 0))
    if abs(grand_total - current_total) > 0.01:
        changes.append(f"Recálculo Total: {current_total:.2f} -> {grand_total:.2f}")
        charge['total'] = grand_total
        charge['service_fee'] = service_fee

    if changes:
        # --- FINANCIAL AUDIT LOG ---
        try:
            from app.services.financial_audit_service import FinancialAuditService
            FinancialAuditService.log_event(
                user=session.get("user"),
                action='EDICAO_CONTA',
                entity=f"Room Charge {charge_id}",
                old_data={'total': current_total, 'status': old_status},
                new_data={'total': grand_total, 'status': new_status},
                details={'changes': changes, 'justification': justification}
            )
        except Exception as e:
            current_app.logger.error(f"Failed to log edit charge audit: {e}")

        audit_entry = {
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'user': session.get('user'),
            'changes': changes,
            'justification': justification
        }
        
        sessions = load_cashier_sessions()
        
        cashier_id = charge.get('reception_cashier_id')
        paying_session = next((s for s in sessions if s['id'] == cashier_id), None)
        
        current_reception_cashier = next((s for s in reversed(sessions) 
                                        if s['status'] == 'open' and s.get('type') == 'reception'), None)

        if old_status == 'paid':
            if paying_session and paying_session['status'] == 'open':
                transaction_found = False
                for t in paying_session['transactions']:
                    if t['type'] == 'in' and f"Quarto {charge.get('room_number')}" in t['description'] and abs(t['amount'] - original_total) < 0.01:
                        if new_status == 'paid':
                            t['amount'] = grand_total
                            t['description'] = t['description'] + " (Editada)"
                            changes.append(f"Transação atualizada de R$ {original_total:.2f} para R$ {grand_total:.2f}")
                        elif new_status == 'pending':
                            paying_session['transactions'].remove(t)
                            changes.append(f"Pagamento de R$ {original_total:.2f} estornado (removido do caixa aberto)")
                        transaction_found = True
                        break
                
                if not transaction_found and new_status == 'pending':
                     changes.append("AVISO: Transação original não encontrada para estorno automático.")

            else:
                if current_reception_cashier:
                    if new_status == 'pending':
                        reversal_trans = {
                            'id': f"REV_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                            'type': 'out', 
                            'category': 'Estorno/Correção',
                            'description': f"Estorno Ref. Quarto {charge.get('room_number')} (Edição de Conta)",
                            'amount': original_total,
                            'payment_method': 'Outros', 
                            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                            'time': datetime.now().strftime('%H:%M')
                        }
                        current_reception_cashier['transactions'].append(reversal_trans)
                        changes.append(f"Estorno de R$ {original_total:.2f} lançado no caixa atual para reabertura.")
                        
                        charge.pop('reception_cashier_id', None)
                        charge.pop('paid_at', None)

                    elif new_status == 'paid' and abs(grand_total - original_total) > 0.01:
                        diff = grand_total - original_total
                        
                        if diff > 0:
                            adj_trans = {
                                'id': f"ADJ_IN_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                'type': 'in',
                                'category': 'Ajuste de Conta',
                                'description': f"Ajuste Adicional Quarto {charge.get('room_number')}",
                                'amount': diff,
                                'payment_method': 'Outros', 
                                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                                'time': datetime.now().strftime('%H:%M')
                            }
                            current_reception_cashier['transactions'].append(adj_trans)
                            changes.append(f"Diferença de R$ {diff:.2f} lançada como entrada no caixa atual.")
                        else:
                            adj_trans = {
                                'id': f"ADJ_OUT_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                                'type': 'out',
                                'category': 'Devolução/Ajuste',
                                'description': f"Devolução Diferença Quarto {charge.get('room_number')}",
                                'amount': abs(diff),
                                'payment_method': 'Outros',
                                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                                'time': datetime.now().strftime('%H:%M')
                            }
                            current_reception_cashier['transactions'].append(adj_trans)
                            changes.append(f"Diferença de R$ {abs(diff):.2f} lançada como saída (devolução) no caixa atual.")
                else:
                    if new_status == 'pending' or (new_status == 'paid' and abs(grand_total - original_total) > 0.01):
                        changes.append("AVISO CRÍTICO: Ajuste financeiro necessário mas nenhum caixa de recepção está aberto. O saldo financeiro pode estar inconsistente.")

        elif old_status != 'paid' and new_status == 'paid':
             if current_reception_cashier:
                payment_trans = {
                    'id': f"MANUAL_PAY_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'type': 'in',
                    'category': 'Recebimento Manual',
                    'description': f"Recebimento Manual Ref. Quarto {charge.get('room_number')} (Edição)",
                    'amount': grand_total,
                    'payment_method': 'Outros',
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'time': datetime.now().strftime('%H:%M'),
                    'waiter': charge.get('waiter'),
                    'waiter_breakdown': charge.get('waiter_breakdown'),
                    'service_fee_removed': charge.get('service_fee_removed', False)
                }
                current_reception_cashier['transactions'].append(payment_trans)
                
                charge['reception_cashier_id'] = current_reception_cashier['id']
                charge['paid_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                
                changes.append(f"Pagamento Manual de R$ {grand_total:.2f} registrado no caixa atual.")
             else:
                changes.append("AVISO: Pagamento não registrado financeiramente pois não há caixa aberto.")

        save_cashier_sessions(sessions)

        if 'audit_log' not in charge:
            charge['audit_log'] = []
        charge['audit_log'].append(audit_entry)
        
        save_room_charges(room_charges)
        log_action('Edição de Conta', f"Conta {charge_id} editada: {', '.join(changes)}")
        flash('Conta atualizada com sucesso.')
    else:
        flash('Nenhuma alteração realizada.')

    return _redirect_after_edit()

@reception_bp.route('/api/reception/cashier/summary')
@login_required
def api_cashier_summary():
    try:
        cashier_type = request.args.get('type', 'reservation_cashier')
        
        # Security check: Ensure user has access to this cashier type
        # For now, rely on @login_required, but could add role checks
        
        active_session = CashierService.get_active_session(cashier_type)
        if not active_session:
             return jsonify({'success': False, 'error': 'Caixa fechado'}), 404
             
        summary = CashierService.get_session_summary(active_session)
        
        # Add total_balance alias for frontend compatibility
        summary['total_balance'] = summary.get('current_balance', 0.0)
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

import logging

@reception_bp.route('/reception/reservations-cashier', methods=['GET', 'POST'])
@login_required
def reception_reservations_cashier():
    logging.warning(f"DEBUG: Entering reception_reservations_cashier method={request.method}")
    if 'user' not in session: return redirect(url_for('auth.login'))

    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'reservas' not in user_perms and 'principal' not in user_perms:
        flash('Acesso não autorizado ao Caixa de Reservas.')
        return redirect(url_for('main.index'))

    current_user = session.get('user')
    
    # Use Service to get session
    current_session = CashierService.get_active_session('reservation_cashier')
            
    payment_methods = load_payment_methods()
    payment_methods = [m for m in payment_methods if 'caixa_reservas' in m.get('available_in', []) or 'reservas' in m.get('available_in', []) or 'reservations' in m.get('available_in', [])]

    if request.method == 'POST':
        action = request.form.get('action')
        logging.warning(f"DEBUG: RESERVATIONS POST action={action}, form={request.form}")
        
        if action == 'open_cashier':
            try:
                initial_balance = float(request.form.get('opening_balance', 0))
            except ValueError:
                initial_balance = 0.0
            
            try:
                CashierService.open_session('reservation_cashier', current_user, initial_balance)
                log_action('Caixa Aberto', f'Caixa Reservas aberto por {current_user} com R$ {initial_balance:.2f}', department='Recepção')
                flash('Caixa de Reservas aberto com sucesso.')
            except ValueError as e:
                flash(str(e))
            except Exception as e:
                flash(f'Erro ao abrir caixa: {str(e)}')
            
            return redirect(url_for('reception.reception_reservations_cashier'))
                
        elif action == 'close_cashier':
            if not current_session:
                flash('Não há caixa de reservas aberto para fechar.')
            else:
                try:
                    raw_cash = request.form.get('closing_cash')
                    raw_non_cash = request.form.get('closing_non_cash')
                    try:
                        closing_cash = parse_br_currency(raw_cash) if raw_cash else None
                    except Exception:
                        closing_cash = None
                    try:
                        closing_non_cash = parse_br_currency(raw_non_cash) if raw_non_cash else None
                    except Exception:
                        closing_non_cash = None
                    closing_balance = None
                    if closing_cash is not None or closing_non_cash is not None:
                        closing_balance = (closing_cash or 0.0) + (closing_non_cash or 0.0)
                    
                    CashierService.close_session(
                        session_id=current_session['id'],
                        user=current_user,
                        closing_balance=closing_balance,
                        closing_cash=closing_cash,
                        closing_non_cash=closing_non_cash
                    )
                    log_action('Caixa Fechado', f'Caixa Reservas fechado por {current_user}', department='Recepção')
                    flash('Caixa de Reservas fechado com sucesso.')
                except Exception as e:
                    flash(f'Erro ao fechar caixa: {str(e)}')
                    
                return redirect(url_for('reception.reception_reservations_cashier'))

        elif action == 'add_transaction':
            if not current_session:
                flash('É necessário abrir o caixa de reservas antes de realizar movimentações.')
                return redirect(url_for('reception.reception_reservations_cashier'))
                
            trans_type = request.form.get('type') 
            description = request.form.get('description')
            try:
                amount = float(request.form.get('amount', 0))
            except ValueError:
                amount = 0.0
            
            if amount > 0 and description:
                try:
                    if trans_type == 'transfer':
                        target_cashier = request.form.get('target_cashier')
                        CashierService.transfer_funds(
                            source_type='reservation_cashier',
                            target_type=target_cashier,
                            amount=amount,
                            description=description,
                            user=current_user
                        )
                        flash('Transferência realizada com sucesso.')
                        log_action('Transferência Caixa', f'Reservas -> {target_cashier}: R$ {amount:.2f}', department='Recepção')

                    elif trans_type == 'sale':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_reservations_cashier'))

                        payment_list_json = request.form.get('payment_list_json')
                        
                        if payment_list_json:
                            # Multi-payment logic
                            try:
                                payment_list = json.loads(payment_list_json)
                                logging.warning(f"DEBUG: Payment List received: {payment_list}")
                                if not payment_list:
                                    raise ValueError("Lista de pagamentos vazia.")
                                
                                # Validate total
                                total_payments = sum(float(p.get('amount', 0)) for p in payment_list)
                                logging.warning(f"DEBUG: Total payments: {total_payments}, Expected: {amount}")
                                if abs(total_payments - amount) > 0.05: # 5 cent tolerance
                                    raise ValueError(f"Soma dos pagamentos (R$ {total_payments:.2f}) difere do valor total (R$ {amount:.2f})")
                                
                                group_id = str(uuid.uuid4())
                                
                                for p in payment_list:
                                    p_amount = float(p.get('amount', 0))
                                    p_method_id = p.get('id')
                                    p_method_name = p.get('name', 'Desconhecido')
                                    
                                    # Ensure method name is correct if ID is provided
                                    if p_method_id:
                                        found_name = next((m['name'] for m in payment_methods if m['id'] == p_method_id), None)
                                        if found_name:
                                            p_method_name = found_name
                                        else:
                                            logging.warning(f"DEBUG: Payment method ID {p_method_id} not found in {payment_methods}")

                                    CashierService.add_transaction(
                                        cashier_type='reservation_cashier',
                                        amount=p_amount,
                                        description=description,
                                        payment_method=p_method_name,
                                        user=current_user,
                                        transaction_type='sale',
                                        is_withdrawal=False,
                                        payment_group_id=group_id,
                                        details={'idempotency_key': idempotency_key} if idempotency_key else None
                                    )
                                    logging.warning(f"DEBUG: Added transaction for {p_method_name}: {p_amount}")
                                    
                                log_action('Transação Caixa', f'Reservas: Recebimento Múltiplo de R$ {amount:.2f} - {description}', department='Recepção')
                                
                                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                    return jsonify({'success': True, 'message': 'Recebimento múltiplo registrado com sucesso.'})

                                flash('Recebimento múltiplo registrado com sucesso.')

                            except json.JSONDecodeError:
                                logging.warning("DEBUG: JSON Decode Error")
                                flash('Erro ao processar lista de pagamentos.')
                            except ValueError as ve:
                                logging.warning(f"DEBUG: Value Error: {ve}")
                                flash(f'Erro de validação: {str(ve)}')
                        
                        else:
                            # Single payment logic (Legacy/Default)
                            method_id = request.form.get('payment_method')
                            method_name = next((m['name'] for m in payment_methods if m['id'] == method_id), method_id)
                            
                            CashierService.add_transaction(
                                cashier_type='reservation_cashier',
                                amount=amount,
                                description=description,
                                payment_method=method_name,
                                user=current_user,
                                transaction_type='sale',
                                is_withdrawal=False,
                                details={'idempotency_key': idempotency_key} if idempotency_key else None
                            )
                            log_action('Transação Caixa', f'Reservas: Recebimento de R$ {amount:.2f} - {description}', department='Recepção')
                            
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                return jsonify({'success': True, 'message': 'Recebimento registrado com sucesso.'})

                            flash('Recebimento registrado com sucesso.')

                    elif trans_type == 'deposit':
                        # Idempotency Check
                        idempotency_key = request.form.get('idempotency_key')
                        if idempotency_key and current_session:
                            for t in current_session.get('transactions', []):
                                if t.get('details', {}).get('idempotency_key') == idempotency_key:
                                    current_app.logger.warning(f"Duplicate transaction attempt detected. Key: {idempotency_key}")
                                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                                        return jsonify({'success': True, 'message': 'Transação já processada anteriormente.'})
                                    flash('Transação já processada anteriormente.')
                                    return redirect(url_for('reception.reception_reservations_cashier'))

                        CashierService.add_transaction(
                            cashier_type='reservation_cashier',
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='deposit',
                            is_withdrawal=False,
                            details={'idempotency_key': idempotency_key} if idempotency_key else None
                        )
                        log_action('Transação Caixa', f'Reservas: Suprimento de R$ {amount:.2f} - {description}', department='Recepção')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Suprimento registrado com sucesso.'})

                        flash('Suprimento registrado com sucesso.')
                        
                    elif trans_type == 'withdrawal':
                        CashierService.add_transaction(
                            cashier_type='reservation_cashier',
                            amount=amount,
                            description=description,
                            payment_method='Dinheiro',
                            user=current_user,
                            transaction_type='withdrawal',
                            is_withdrawal=True
                        )
                        log_system_action('Transação Caixa', f'Reservas: Sangria de R$ {amount:.2f} - {description}')
                        
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return jsonify({'success': True, 'message': 'Sangria registrada com sucesso.'})

                        flash('Sangria registrada com sucesso.')
                
                except ValueError as e:
                    flash(f'Erro: {str(e)}')
                except Exception as e:
                    flash(f'Erro inesperado: {str(e)}')
            else:
                flash('Valor inválido ou descrição ausente.')
            
            return redirect(url_for('reception.reception_reservations_cashier'))

    total_in = 0
    total_out = 0
    balance = 0
    current_totals = {}

    if current_session:
        total_in = sum(t['amount'] for t in current_session['transactions'] if t.get('type') in ['in', 'sale', 'deposit', 'suprimento'])
        total_out = sum(t['amount'] for t in current_session['transactions'] if t.get('type') in ['out', 'withdrawal', 'sangria'])
        
        initial_balance = float(current_session.get('initial_balance') or current_session.get('opening_balance') or 0.0)
        balance = initial_balance + total_in - total_out
        
        for t in current_session['transactions']:
            if t.get('type') in ['in', 'sale', 'deposit', 'suprimento']:
                method = t.get('payment_method', 'Outros')
                current_totals[method] = current_totals.get(method, 0.0) + float(t.get('amount', 0))
        
        if 'opening_balance' not in current_session:
            current_session['opening_balance'] = initial_balance

    # Pagination
    try:
        current_page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
    except ValueError:
        current_page = 1
        per_page = 20

    displayed_transactions = []
    has_more = False
    
    if current_session:
        displayed_transactions, has_more = CashierService.get_paginated_transactions(current_session.get('id'), page=current_page, per_page=per_page)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
            return jsonify({
                'transactions': displayed_transactions,
                'has_more': has_more,
                'current_page': current_page
            })

    return render_template('reception_reservations_cashier.html', 
                         cashier=current_session, 
                         displayed_transactions=displayed_transactions,
                         has_more=has_more,
                         current_page=current_page,
                         payment_methods=payment_methods,
                         total_in=total_in,
                         total_out=total_out,
                         balance=balance,
                         total_balance=balance,
                         current_totals=current_totals)

@reception_bp.route('/reception/waiting-list')
@login_required
def reception_waiting_list():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))

    filters = {
        'start_date': request.args.get('start_date', '').strip(),
        'end_date': request.args.get('end_date', '').strip(),
        'status': request.args.get('status', '').strip(),
        'phone': request.args.get('phone', '').strip(),
        'name': request.args.get('name', '').strip(),
        'party_size': request.args.get('party_size', '').strip(),
        'collaborator': request.args.get('collaborator', '').strip(),
        'table_id': request.args.get('table_id', '').strip(),
        'country_code': request.args.get('country_code', '').strip(),
        'wait_min': request.args.get('wait_min', '').strip(),
        'wait_max': request.args.get('wait_max', '').strip(),
        'consent_mode': request.args.get('consent_mode', '').strip(),
    }

    queue = waiting_list_service.get_waiting_list()
    settings = waiting_list_service.get_settings()
    metrics = waiting_list_service.get_queue_metrics()
    queue_events = waiting_list_service.get_queue_events(limit=200)
    queue_history = waiting_list_service.get_queue_history_filtered(filters=filters, limit=2000)
    seated_customers = waiting_list_service.get_seated_customers(limit=40)
    available_tables = waiting_list_service.list_available_tables()
    table_catalog = waiting_list_service.get_table_status_catalog()
    countries = waiting_list_service.get_supported_countries()
    
    now = datetime.now()
    smart_reference = waiting_list_service.get_capacity_aware_queue_reference(
        target_capacity=settings.get('smart_call_target_capacity', 4),
        limit=max(50, len(queue) + 20)
    )
    smart_reference_map = {row.get('entry_id'): row for row in smart_reference}
    for pos, item in enumerate(queue, start=1):
        entry_time = datetime.fromisoformat(item['entry_time'])
        item['position'] = pos
        item['wait_minutes'] = int((now - entry_time).total_seconds() / 60)
        item['entry_time_fmt'] = entry_time.strftime('%H:%M:%S')
        item['phone_clean'] = re.sub(r'\D', '', item['phone'])

        party_size = item.get('party_size')
        try:
            party_size_int = int(party_size)
        except (TypeError, ValueError):
            party_size_int = None

        if party_size_int == 1:
            party_label = "1 pessoa"
        elif party_size_int and party_size_int > 1:
            party_label = f"{party_size_int} pessoas"
        else:
            party_label = "seu grupo"

        item['call_message'] = (
            f"Olá {item.get('name', '')}! Aqui é do Mirapraia. "
            f"Sua mesa já está pronta para {party_label}. "
            f"Vamos te esperar por até {int(settings.get('call_presence_sla_minutes', settings.get('call_response_timeout_minutes', 15)))} minutos. "
            "Por favor, venham até a recepção. Até já!"
        )

        phone_wa = item.get('phone_wa')
        if not phone_wa:
            digits = re.sub(r'\D', '', item['phone'])
            phone_wa = digits
        item['wa_phone'] = phone_wa
        item['current_table_id'] = str(item.get('current_table_id') or '')
        item['internal_notes'] = item.get('internal_notes') or ''
        call_timeout = item.get('call_timeout_minutes')
        try:
            item['call_timeout_minutes'] = int(call_timeout)
        except Exception:
            item['call_timeout_minutes'] = int(settings.get('call_presence_sla_minutes', settings.get('call_response_timeout_minutes', 15)))
        call_expires_at = item.get('call_expires_at')
        item['call_expires_at'] = call_expires_at
        item['call_remaining_minutes'] = None
        item['call_sla_expired'] = False
        exp_dt = None
        try:
            exp_dt = datetime.fromisoformat(call_expires_at) if call_expires_at else None
        except Exception:
            exp_dt = None
        if exp_dt and item.get('status') == 'chamado':
            diff = int((exp_dt - now).total_seconds() / 60)
            item['call_remaining_minutes'] = diff
            item['call_sla_expired'] = diff < 0
        recurring = waiting_list_service.get_recurring_summary(item.get('phone_wa'), current_entry_id=item.get('id'), limit=3)
        item['is_recurring'] = bool(recurring.get('is_recurring'))
        item['visit_number'] = recurring.get('visit_number') or item.get('visit_number') or 1
        item['recent_visits'] = recurring.get('recent_visits') or []
        smart = smart_reference_map.get(item.get('id')) or {}
        item['smart_reference_position'] = smart.get('reference_position')
        item['smart_fit_gap'] = smart.get('fit_gap')

    for item in seated_customers:
        entry_time_raw = item.get('seated_at') or item.get('last_updated') or item.get('entry_time')
        try:
            seated_dt = datetime.fromisoformat(entry_time_raw)
            item['seated_time_fmt'] = seated_dt.strftime('%H:%M')
            item['seated_minutes'] = int((now - seated_dt).total_seconds() / 60)
        except Exception:
            item['seated_time_fmt'] = '--:--'
            item['seated_minutes'] = 0

    queue_public_url = str(settings.get('public_queue_url') or '').strip()
    if not queue_public_url:
        queue_public_url = request.url_root.rstrip('/') + url_for('restaurant.public_waiting_list')

    return render_template(
        'waiting_list_admin.html',
        queue=queue,
        settings=settings,
        metrics=metrics,
        queue_public_url=queue_public_url,
        queue_events=queue_events,
        queue_history=queue_history,
        seated_customers=seated_customers,
        available_tables=available_tables,
        table_catalog=table_catalog,
        countries=countries,
        history_filters=filters
    )

@reception_bp.route('/reception/waiting-list/manual-entry', methods=['POST'])
@login_required
def reception_waiting_list_manual_entry():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))

    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    party_size = request.form.get('party_size', '').strip()
    country_code = request.form.get('country_code', 'BR').strip() or 'BR'
    country_dial_code = request.form.get('country_dial_code', '').strip()
    consent_marketing = bool(request.form.get('consent_marketing'))
    consent_survey = bool(request.form.get('consent_survey'))

    if not name or not phone or not party_size:
        flash('Preencha nome, telefone e quantidade de pessoas.')
        return redirect(url_for('reception.reception_waiting_list'))

    result, error = waiting_list_service.add_customer(
        name=name,
        phone=phone,
        party_size=party_size,
        country_code=country_code,
        country_dial_code=country_dial_code,
        consent_marketing=consent_marketing,
        consent_survey=consent_survey,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method},
        created_by=session.get('user', 'recepcao'),
        source='recepcao_manual',
        force_queue_end=True
    )
    if error:
        flash(error)
        return redirect(url_for('reception.reception_waiting_list'))

    try:
        LoggerService.log_acao(
            acao='Fila Espera - Entrada Manual',
            entidade='Fila de Espera',
            detalhes={
                'entry_id': result.get('entry', {}).get('id'),
                'name': result.get('entry', {}).get('name'),
                'party_size': result.get('entry', {}).get('party_size'),
                'country_code': result.get('entry', {}).get('country_code')
            },
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass

    flash(f"Cliente adicionado na fila manualmente. Posição atual: {result.get('position', '-')}.")
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/update/<id>/<status>')
@login_required
def update_queue_status(id, status):
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    reason = request.args.get('reason')
    user = session.get('user')
    status_norm = str(status or '').strip().lower()
    updated = waiting_list_service.update_customer_status(
        id,
        status_norm,
        reason=reason,
        user=user,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    if not updated:
        flash('Não foi possível atualizar o status.')
        return redirect(url_for('reception.reception_waiting_list'))
    _auto_invite_waiting_list_entry(updated, actor=user, trigger='status_update')
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Status Atualizado',
            entidade='Fila de Espera',
            detalhes={'entry_id': id, 'status': status_norm, 'reason': reason},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=user
        )
    except Exception:
        pass
    flash(f'Status atualizado para {status}.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/settings', methods=['POST'])
@login_required
def update_queue_settings():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))

    avg_wait = int(request.form.get('avg_wait', 15))
    max_size = int(request.form.get('max_size', 50))
    cutoff_hour = int(request.form.get('cutoff_hour', 20))
    max_party_size = int(request.form.get('max_party_size', 20))
    duplicate_block_minutes = int(request.form.get('duplicate_block_minutes', 5))
    call_response_timeout_minutes = int(request.form.get('call_response_timeout_minutes', 15))
    call_presence_sla_minutes = int(request.form.get('call_presence_sla_minutes', call_response_timeout_minutes))
    call_timeout_action = request.form.get('call_timeout_action', 'manual').strip().lower()
    smart_call_enabled = bool(request.form.get('smart_call_enabled'))
    smart_call_target_capacity = int(request.form.get('smart_call_target_capacity', 4))
    house_rules = request.form.get('house_rules', '')
    public_queue_url = request.form.get('public_queue_url', '').strip()
    whatsapp_token = request.form.get('whatsapp_token', '').strip()
    whatsapp_phone_id = request.form.get('whatsapp_phone_id', '').strip()
    
    settings_update = {
        'average_wait_per_party': avg_wait,
        'max_queue_size': max_size,
        'cutoff_hour': cutoff_hour,
        'max_party_size': max_party_size,
        'duplicate_block_minutes': duplicate_block_minutes,
        'call_response_timeout_minutes': call_response_timeout_minutes,
        'call_presence_sla_minutes': call_presence_sla_minutes,
        'call_timeout_action': call_timeout_action,
        'smart_call_enabled': smart_call_enabled,
        'smart_call_target_capacity': smart_call_target_capacity,
        'house_rules': house_rules,
        'public_queue_url': public_queue_url,
        'updated_by': session.get('user')
    }
    
    if whatsapp_token:
        settings_update['whatsapp_api_token'] = whatsapp_token
    if whatsapp_phone_id:
        settings_update['whatsapp_phone_id'] = whatsapp_phone_id
        
    waiting_list_service.update_settings(settings_update)
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Configurações Atualizadas',
            entidade='Fila de Espera',
            detalhes={'settings': {k: v for k, v in settings_update.items() if k != 'whatsapp_api_token'}},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass
    flash('Configurações atualizadas.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/process-call-sla', methods=['POST'])
@login_required
def process_call_sla_timeout():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    affected = waiting_list_service.process_call_sla_expired_entries(user=session.get('user'), trigger='manual')
    flash(f'{affected} cliente(s) marcado(s) como não compareceu por SLA expirado.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/export')
@login_required
def export_waiting_list_history():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    export_format = (request.args.get('format') or 'csv').strip().lower()
    filters = {
        'start_date': request.args.get('start_date', '').strip(),
        'end_date': request.args.get('end_date', '').strip(),
        'status': request.args.get('status', '').strip(),
        'phone': request.args.get('phone', '').strip(),
        'name': request.args.get('name', '').strip(),
        'party_size': request.args.get('party_size', '').strip(),
        'collaborator': request.args.get('collaborator', '').strip(),
        'table_id': request.args.get('table_id', '').strip(),
        'country_code': request.args.get('country_code', '').strip(),
        'wait_min': request.args.get('wait_min', '').strip(),
        'wait_max': request.args.get('wait_max', '').strip(),
        'consent_mode': request.args.get('consent_mode', '').strip(),
    }
    rows = waiting_list_service.get_queue_history_filtered(filters=filters, limit=3000)
    export_rows = []
    for row in rows:
        export_rows.append({
            'id': row.get('id'),
            'data_visita': str(row.get('entry_time') or '')[:19].replace('T', ' '),
            'nome': row.get('name'),
            'telefone': row.get('phone_normalized') or row.get('phone') or row.get('phone_raw'),
            'pais': row.get('country_code'),
            'pessoas': row.get('party_size'),
            'status_final': row.get('status'),
            'tempo_espera_ate_chamada_min': row.get('wait_to_called_minutes'),
            'tempo_chamado_ate_sentado_min': row.get('called_to_seated_minutes'),
            'tempo_total_fluxo_min': row.get('total_to_finish_minutes'),
            'mesa_atual': row.get('current_table_id') or '',
            'mesas_usadas': ', '.join([str(x.get('table_id')) for x in (row.get('table_history') or []) if isinstance(x, dict) and x.get('table_id')]),
            'consentiu_pesquisa': 'sim' if bool(row.get('consent_survey')) else 'nao',
            'consentiu_marketing': 'sim' if bool(row.get('consent_marketing')) else 'nao',
            'survey_status': row.get('survey_status') or ('enviada' if row.get('received_survey') else 'nao_enviada'),
            'origem': row.get('source') or 'fila_virtual',
            'colaborador': row.get('updated_by') or row.get('created_by') or '',
        })
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if export_format == 'xlsx':
        import pandas as pd
        buffer = io.BytesIO()
        pd.DataFrame(export_rows).to_excel(buffer, index=False, sheet_name='fila_historico')
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'fila_historico_{ts}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    output = io.StringIO()
    fieldnames = list(export_rows[0].keys()) if export_rows else [
        'id', 'data_visita', 'nome', 'telefone', 'pais', 'pessoas', 'status_final',
        'tempo_espera_ate_chamada_min', 'tempo_chamado_ate_sentado_min', 'tempo_total_fluxo_min',
        'mesa_atual', 'mesas_usadas', 'consentiu_pesquisa', 'consentiu_marketing', 'survey_status',
        'origem', 'colaborador'
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in export_rows:
        writer.writerow(row)
    csv_buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    csv_buffer.seek(0)
    return send_file(
        csv_buffer,
        as_attachment=True,
        download_name=f'fila_historico_{ts}.csv',
        mimetype='text/csv'
    )

@reception_bp.route('/reception/waiting-list/toggle')
@login_required
def toggle_queue_status():
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    settings = waiting_list_service.get_settings()
    new_status = not settings['is_open']
    waiting_list_service.update_settings({'is_open': new_status, 'updated_by': session.get('user')})
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Abertura Alterada',
            entidade='Fila de Espera',
            detalhes={'is_open': new_status},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass
    flash(f"Fila {'aberta' if new_status else 'fechada'}.")
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/api/queue/log-notification', methods=['POST'])
@login_required
def log_queue_notification():
    if not _waiting_list_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito'}), 403
    data = request.json
    customer_id = data.get('id')
    if customer_id:
        waiting_list_service.log_notification(
            customer_id,
            'whatsapp_call',
            user=session.get('user'),
            action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
        )
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@reception_bp.route('/api/queue/send-notification', methods=['POST'])
@login_required
def send_queue_notification():
    if not _waiting_list_access_allowed():
        return jsonify({'success': False, 'error': 'Acesso restrito'}), 403
    data = request.json
    customer_id = data.get('id')
    if not customer_id:
        return jsonify({'success': False, 'message': 'ID required'}), 400
    
    success, message = waiting_list_service.send_notification(
        customer_id,
        message_type="table_ready",
        user=session.get('user'),
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    
    return jsonify({
        'success': success,
        'message': message,
        'code': 'sent' if success else 'error'
    })

@reception_bp.route('/reception/waiting-list/seat/<id>', methods=['POST'])
@login_required
def seat_queue_customer(id):
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    table_id = request.form.get('table_id', '').strip()
    reason = request.form.get('reason', '').strip() or 'Cliente sentado'
    updated, error = waiting_list_service.seat_customer(
        id,
        table_id=table_id,
        user=session.get('user'),
        reason=reason,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    if error:
        flash(error)
        return redirect(url_for('reception.reception_waiting_list'))
    _auto_invite_waiting_list_entry(updated, actor=session.get('user'), trigger='seat_customer')
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Cliente Sentado',
            entidade='Fila de Espera',
            detalhes={'entry_id': id, 'table_id': table_id, 'status': updated.get('status')},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass
    flash(f"Cliente sentado na mesa {table_id}.")
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/table/change/<id>', methods=['POST'])
@login_required
def change_queue_customer_table(id):
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    new_table_id = request.form.get('new_table_id', '').strip()
    reason = request.form.get('reason', '').strip() or 'Troca de mesa'
    updated, error = waiting_list_service.change_customer_table(
        id,
        new_table_id=new_table_id,
        user=session.get('user'),
        reason=reason,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    if error:
        flash(error)
        return redirect(url_for('reception.reception_waiting_list'))
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Troca de Mesa',
            entidade='Fila de Espera',
            detalhes={'entry_id': id, 'new_table_id': new_table_id, 'current_table_id': updated.get('current_table_id')},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass
    flash(f"Mesa alterada para {new_table_id}.")
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/call/<id>', methods=['POST'])
@login_required
def call_queue_customer(id):
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    channel = request.form.get('channel', 'whatsapp').strip() or 'whatsapp'
    timeout_minutes = request.form.get('timeout_minutes', '')
    reason = request.form.get('reason', '').strip() or 'Cliente chamado'
    resend = bool(request.form.get('resend'))
    updated, error = waiting_list_service.call_customer(
        customer_id=id,
        user=session.get('user'),
        channel=channel,
        timeout_minutes=timeout_minutes,
        reason=reason,
        resend=resend,
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    if error:
        flash(error)
        return redirect(url_for('reception.reception_waiting_list'))
    try:
        LoggerService.log_acao(
            acao='Fila Espera - Cliente Chamado',
            entidade='Fila de Espera',
            detalhes={'entry_id': id, 'channel': channel, 'timeout_minutes': timeout_minutes, 'resend': resend},
            nivel_severidade='INFO',
            departamento_id='Recepção',
            colaborador_id=session.get('user')
        )
    except Exception:
        pass
    flash('Cliente chamado com sucesso.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/waiting-list/notes/<id>', methods=['POST'])
@login_required
def update_queue_customer_notes(id):
    if not _waiting_list_access_allowed():
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    notes = request.form.get('internal_notes', '')
    updated = waiting_list_service.update_customer_notes(
        id,
        notes,
        user=session.get('user'),
        action_origin={'ip': request.remote_addr, 'endpoint': request.path, 'method': request.method}
    )
    if not updated:
        flash('Não foi possível atualizar observações.')
        return redirect(url_for('reception.reception_waiting_list'))
    flash('Observações atualizadas.')
    return redirect(url_for('reception.reception_waiting_list'))

@reception_bp.route('/reception/room_consumption_report/<room_num>')
@reception_bp.route('/reception/room_consumption_report/<room_num>/')
@login_required
def get_room_consumption_report(room_num):
    try:
        # Permission Check
        user_role = session.get('role')
        user_perms = session.get('permissions', [])
        if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms and 'principal' not in user_perms:
            return "Acesso não autorizado", 403

        room_charges = load_room_charges()
        room_occupancy = load_room_occupancy()
        
        # Get guest info
        room_num_str = str(room_num)
        
        target_room_norm = normalize_room_simple(room_num_str)

        
        # Guest info lookup
        guest_info = {}
        # Try exact match, formatted, and normalized
        keys_to_try = [room_num_str]
        if room_num_str.isdigit():
            keys_to_try.append(f"{int(room_num_str):02d}")
        keys_to_try.append(target_room_norm)
        
        for key in keys_to_try:
             if key in room_occupancy:
                 guest_info = room_occupancy[key]
                 break
        
        guest_name = guest_info.get('guest_name', 'Hóspede não identificado')
        
        # Filter charges
        if not isinstance(room_charges, list):
            room_charges = []
            
        target_charges = []
        for c in room_charges:
            if not isinstance(c, dict):
                continue
            
            c_room = c.get('room_number')
            c_room_norm = normalize_room_simple(c_room)
            
            # Match by normalized room number
            if c.get('status') == 'pending' and c_room_norm == target_room_norm:
                target_charges.append(c)
        
        processed_charges = []
        total_amount = 0.0
        
        for charge in target_charges:
            date_raw = charge.get('date', '')
            time_str = charge.get('time', '')
            date = date_raw
            if isinstance(date_raw, str):
                try:
                    dt = datetime.strptime(date_raw, '%d/%m/%Y %H:%M')
                    date = dt.strftime('%d/%m/%Y')
                    if not time_str:
                        time_str = dt.strftime('%H:%M')
                except:
                    pass
            
            # If time is missing, try to parse from created_at if available
            if not time_str and 'created_at' in charge:
                try:
                    dt = datetime.strptime(charge['created_at'], '%d/%m/%Y %H:%M')
                    time_str = dt.strftime('%H:%M')
                except:
                    pass
            
            items_list = charge.get('items')
            if isinstance(items_list, str):
                try:
                    items_list = json.loads(items_list)
                except:
                    items_list = []
            elif items_list is None:
                items_list = []

            source = charge.get('source')
            if not source:
                charge_type = charge.get('type')
                if charge_type == 'minibar':
                    source = 'minibar'
                else:
                    has_minibar = any(
                        (isinstance(item, dict) and (item.get('category') == 'Frigobar' or item.get('source') == 'minibar'))
                        for item in (items_list or [])
                    )
                    source = 'minibar' if has_minibar else 'restaurant'
            
            charge_items = []
            charge_subtotal = 0.0
            taxable_total = 0.0
            
            # Debug: Trace item processing
            print(f"DEBUG: Processing charge {charge.get('id')} items. Count: {len(items_list)}")
                
            for item in items_list:
                try:
                    if not isinstance(item, dict):
                        print(f"DEBUG: Skipping non-dict item: {item}")
                        continue
                        
                    qty = float(item.get('qty', 1) or 1)
                    if qty.is_integer():
                        qty = int(qty)
                    base_price = float(item.get('price', 0) or 0)
                    
                    item_name = item.get('name', 'Item sem nome')
                    print(f"DEBUG: Processing item: {item_name}, qty: {qty}, price: {base_price}")

                    complements_total = 0.0
                    complements = item.get('complements') or []
                    if isinstance(complements, str):
                        try:
                            complements = json.loads(complements)
                        except:
                            complements = []
                    if isinstance(complements, list):
                        for c in complements:
                            if isinstance(c, dict):
                                try:
                                    complements_total += float(c.get('price', 0) or 0)
                                except:
                                    pass

                    accompaniments_total = 0.0
                    accompaniments = item.get('accompaniments') or []
                    if isinstance(accompaniments, str):
                        try:
                            accompaniments = json.loads(accompaniments)
                        except:
                            accompaniments = []
                    if isinstance(accompaniments, list):
                        for a in accompaniments:
                            if isinstance(a, dict):
                                try:
                                    accompaniments_total += float(a.get('price', 0) or 0)
                                except:
                                    pass

                    unit_price = base_price + complements_total + accompaniments_total
                    item_total = qty * unit_price
                    
                    charge_items.append({
                        'name': item.get('name', 'Item sem nome'),
                        'qty': qty,
                        'unit_price': unit_price,
                        'total': item_total
                    })
                    charge_subtotal += item_total
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += item_total
                except (ValueError, TypeError) as e:
                    print(f"Error processing item in room report: {e}")
                    continue
            
            if charge_items:
                service_fee = charge.get('service_fee')
                try:
                    service_fee = float(service_fee) if service_fee is not None else None
                except:
                    service_fee = None
                if service_fee is None:
                    service_fee = taxable_total * 0.10
                
                stored_total = charge.get('total')
                charge_total = charge_subtotal + service_fee
                if stored_total is not None:
                    try:
                        stored_total_f = float(stored_total)
                    except:
                        stored_total_f = None
                    if stored_total_f is not None:
                        if abs(stored_total_f - charge_total) <= 0.05:
                            charge_total = stored_total_f
                        elif abs(stored_total_f - charge_subtotal) <= 0.05:
                            charge_total = charge_subtotal + service_fee
                        else:
                            charge_total = stored_total_f

                processed_charges.append({
                    'id': charge.get('id'),
                    'date': date,
                    'time': time_str,
                    'source': source,
                    'line_items': charge_items,
                    'service_fee': service_fee,
                    'total': charge_total
                })
                total_amount += charge_total
        
        # Sort charges by date/time
        def sort_key(c):
            try:
                d = datetime.strptime(c['date'], '%d/%m/%Y')
                # Try to add time if available
                if c['time']:
                    try:
                        t = datetime.strptime(c['time'], '%H:%M').time()
                        d = datetime.combine(d.date(), t)
                    except: pass
                return d
            except:
                return datetime.min

        processed_charges.sort(key=sort_key)
        
        # total_amount already accumulated to include service fee consistently
        
        return render_template('consumption_report.html',
                            room_number=room_num_str,
                            guest_name=guest_name,
                            generation_date=datetime.now().strftime('%d/%m/%Y %H:%M'),
                            charges=processed_charges,
                            total_amount=total_amount)
    except Exception as e:
        traceback.print_exc()
        return f"Erro ao gerar relatório: {str(e)}", 500

@reception_bp.route('/debug/report_calc/<room_num>')
def debug_report_calc_route(room_num):
    try:
        room_charges = load_room_charges()
        # Normalize room number (handle 02 vs 2)
        target_charges = []
        for c in room_charges:
            r = str(c.get('room_number'))
            if r == str(room_num) or r == f"{int(room_num):02d}" or r == str(int(room_num)):
                if c.get('status') == 'pending':
                    target_charges.append(c)
        
        details = []
        total_amount = 0.0
        
        for charge in target_charges:
            charge_items = charge.get('items', [])
            if isinstance(charge_items, str):
                charge_items = json.loads(charge_items)
            
            charge_subtotal = 0.0
            taxable_total = 0.0
            source = charge.get('source', 'restaurant')
            
            item_details = []
            for item in charge_items:
                try:
                    p = float(item.get('price', 0))
                    q = float(item.get('qty', 1))
                    val = p * q
                    charge_subtotal += val
                    
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += val
                    item_details.append({'name': item.get('name'), 'val': val, 'apply_fee': apply_fee})
                except: pass

            service_fee = charge.get('service_fee')
            stored_total = charge.get('total')
            
            # Logic simulation
            final_total = 0.0
            method = "unknown"
            
            if stored_total is not None:
                final_total = float(stored_total)
                method = "stored_total"
            else:
                try:
                    sf = float(service_fee) if service_fee is not None else (taxable_total * 0.10)
                except:
                    sf = taxable_total * 0.10
                final_total = charge_subtotal + sf
                method = "calculated"
            
            total_amount += final_total
            details.append({
                'id': charge.get('id'),
                'stored_total': stored_total,
                'service_fee': service_fee,
                'subtotal': charge_subtotal,
                'taxable': taxable_total,
                'final_total': final_total,
                'method': method
            })
            
        return jsonify({
            'room': room_num,
            'count': len(target_charges),
            'total_amount': total_amount,
            'details': details
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@reception_bp.route('/reception/close_account/<room_num>', methods=['POST'])
@login_required
def reception_close_account(room_num):
    # Permission Check
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        return jsonify({'success': False, 'error': 'Permissão negada'}), 403

    try:
        data = request.get_json()
        print_receipt = data.get('print_receipt', False)
        
        # Multi-payment support
        payments_payload = data.get('payments', [])
        legacy_payment_method = data.get('payment_method')
        
        # If no detailed payments provided, fallback to legacy single method
        if not payments_payload and legacy_payment_method:
             # We don't know the total yet, so we'll construct it after loading charges
             pass
        elif not payments_payload and not legacy_payment_method:
            return jsonify({'success': False, 'error': 'Forma de pagamento é obrigatória'}), 400
        
        occupancy = load_room_occupancy()
        room_num = str(room_num)
        
        # Validation: Room must be occupied
        if room_num not in occupancy:
            return jsonify({'success': False, 'error': 'Quarto não está ocupado'}), 400
            
        guest_name = occupancy[room_num].get('guest_name', 'Hóspede')
        
        # Validation: Open Cashier Session
        user = session.get('user', 'Sistema')
        
        # Use CashierService to find active session
        current_session = CashierService.get_active_session('guest_consumption')
        if not current_session:
             # Fallback to check legacy type or auto-open if needed? 
             # For now strict check as per legacy behavior
             current_session = CashierService.get_active_session('reception_room_billing')

        if not current_session:
             return jsonify({'success': False, 'error': 'Nenhum caixa de Consumo de Hóspedes aberto.'}), 400
        
        room_charges = load_room_charges()
        pending_charges = [c for c in room_charges if str(c.get('room_number')) == room_num and c.get('status') == 'pending']
        
        if not pending_charges:
            return jsonify({'success': False, 'error': 'Não há consumo pendente para este quarto'}), 400
            
        # Calculate total pending
        total_pending = sum(float(c.get('total', 0)) for c in pending_charges)
        
        # Prepare Payment List
        payment_methods_list = load_payment_methods()
        pm_map = {m['id']: m for m in payment_methods_list}
        
        final_payments = []
        
        if payments_payload:
            # Validate total match
            total_paid = sum(float(p['amount']) for p in payments_payload)
            if abs(total_paid - total_pending) > 0.05: # 5 cents tolerance
                 # If overpaid, it might be a tip or error. For now, we accept if it covers the total.
                 # But strictly, close_account usually means exact match.
                 # Let's enforce coverage but allow slight difference due to rounding.
                 if total_paid < total_pending - 0.05:
                     return jsonify({'success': False, 'error': f'Valor pago (R$ {total_paid:.2f}) é menor que o total (R$ {total_pending:.2f})'}), 400
            
            for p in payments_payload:
                mid = p['method_id']
                amt = float(p['amount'])
                if amt <= 0: continue
                m_obj = pm_map.get(mid)
                m_name = m_obj['name'] if m_obj else mid
                is_fiscal = m_obj.get('is_fiscal', False) if m_obj else False
                final_payments.append({
                    'id': mid,
                    'name': m_name,
                    'amount': amt,
                    'is_fiscal': is_fiscal,
                    'remaining': amt # For distribution
                })
        else:
            # Legacy Single Method
            mid = legacy_payment_method
            m_obj = pm_map.get(mid)
            m_name = m_obj['name'] if m_obj else mid
            is_fiscal = m_obj.get('is_fiscal', False) if m_obj else False
            final_payments.append({
                'id': mid,
                'name': m_name,
                'amount': total_pending,
                'is_fiscal': is_fiscal,
                'remaining': total_pending
            })

        # Calculate total and prepare receipt data
        total_amount = 0.0
        processed_charges = []
        now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        # Aggregate waiter breakdown
        from collections import defaultdict
        aggregated_waiter_breakdown = defaultdict(float)
        has_commissionable_service_fee_charge = False
        
        # Distribution Logic
        # We need to distribute payments to charges to ensure Fiscal Pool gets correct info per charge
        
        for charge in pending_charges:
            charge_total = float(charge.get('total', 0))
            
            # Determine which payments cover this charge
            charge_payments = []
            amount_needed = charge_total
            
            for fp in final_payments:
                if amount_needed <= 0.001: break
                if fp['remaining'] > 0:
                    take = min(amount_needed, fp['remaining'])
                    fp['remaining'] -= take
                    amount_needed -= take
                    charge_payments.append({
                        'method': fp['name'],
                        'amount': take,
                        'is_fiscal': fp['is_fiscal']
                    })
            
            # Update Status
            charge['status'] = 'paid'
            charge['paid_at'] = now_str
            charge['closed_by'] = user
            
            # Store payment details
            if not charge_payments:
                charge['payment_method'] = 'Isento' if charge_total == 0 else 'Desconhecido'
            elif len(charge_payments) == 1:
                charge['payment_method'] = charge_payments[0]['method'] # Store Name
            else:
                # Store the one with highest amount as primary, but mark as split
                primary = max(charge_payments, key=lambda x: x['amount'])
                charge['payment_method'] = primary['method']
                charge['payment_details'] = charge_payments # New field
                
            charge['notes'] = charge.get('notes', '') + f" [Baixa Total por {user} em {now_str}]"
            
            # Prepare data for receipt
            date = charge.get('date', '')
            time_str = charge.get('time', '')
            source = charge.get('source')
            if not source:
                has_minibar = any(item.get('category') == 'Frigobar' for item in (charge.get('items') or []))
                source = 'minibar' if has_minibar else 'Restaurante'
            
            if not time_str and 'created_at' in charge:
                try:
                    dt = datetime.strptime(charge['created_at'], '%d/%m/%Y %H:%M')
                    time_str = dt.strftime('%H:%M')
                except: pass
                
            items_list = charge.get('items')
            if isinstance(items_list, str):
                try: items_list = json.loads(items_list)
                except: items_list = []
            elif items_list is None:
                items_list = []

            # Add to Fiscal Pool (Individual Emission per Charge)
            try:
                # Use the distributed payments for this charge
                fiscal_payments = charge_payments
                
                FiscalPoolService.add_to_pool(
                    origin='reception_charge',
                    original_id=f"CHARGE_{charge['id']}",
                    total_amount=float(charge.get('total', 0)),
                    items=items_list,
                    payment_methods=fiscal_payments,
                    user=user,
                    customer_info={'room_number': room_num, 'guest_name': guest_name}
                )
            except Exception as e:
                print(f"Error adding charge {charge['id']} to fiscal pool: {e}")
                
            charge_items = []
            charge_subtotal = 0.0
            taxable_total = 0.0
            
            for item in items_list:
                try:
                    if not isinstance(item, dict): continue
                    qty = int(item.get('qty', 1))
                    unit_price = float(item.get('price', 0))
                    item_total = qty * unit_price
                    
                    charge_items.append({
                        'name': item.get('name', 'Item sem nome'),
                        'qty': qty,
                        'unit_price': unit_price,
                        'total': item_total
                    })
                    charge_subtotal += item_total
                    apply_fee = not bool(item.get('service_fee_exempt', False)) and source != 'minibar' and item.get('category') != 'Frigobar'
                    if apply_fee:
                        taxable_total += item_total
                except: continue
                
            if charge_items:
                service_fee = charge.get('service_fee')
                try:
                    service_fee = float(service_fee) if service_fee is not None else None
                except:
                    service_fee = None
                
                # Check if service fee was explicitly removed
                is_fee_removed = charge.get('service_fee_removed', False)
                
                if service_fee is None:
                    if is_fee_removed:
                        service_fee = 0.0
                    else:
                        service_fee = taxable_total * 0.10
                        
                charge_total = charge_subtotal + service_fee
                processed_charges.append({
                    'id': charge.get('id'),
                    'date': date,
                    'time': time_str,
                    'source': source,
                    'line_items': charge_items,
                    'service_fee': service_fee,
                    'total': charge_total
                })
                total_amount += charge_total
                
                if not is_fee_removed and source != 'minibar' and service_fee > 0:
                    has_commissionable_service_fee_charge = True
                
                # Waiter Commission Aggregation
                # Only add commission if service fee was NOT removed e não for Minibar
                if not is_fee_removed and source != 'minibar':
                    any_commissionable_charge = True
                    wb = charge.get('waiter_breakdown')
                    if wb and isinstance(wb, dict):
                        for w, amt in wb.items():
                            try:
                                aggregated_waiter_breakdown[w] += float(amt)
                            except: pass
                    elif charge.get('waiter'):
                        # Fallback para cobranças legadas: usa o total da cobrança como base de comissão
                        try:
                            w_name = charge.get('waiter')
                            base_amount = charge_total
                            if base_amount > 0:
                                aggregated_waiter_breakdown[w_name] += base_amount
                        except: pass
                    else:
                        # Lançamentos com taxa de serviço ativos feitos pela recepção (sem garçom)
                        # são atribuídos ao grupo "Recepção" na base de comissão.
                        try:
                            base_amount = charge_total
                            if base_amount > 0 and service_fee > 0:
                                aggregated_waiter_breakdown['Recepção'] += base_amount
                        except: pass

        save_room_charges(room_charges)
        
        # Log Transaction to Cashier Session (One per payment method)
        if total_amount > 0:
            base_transaction_details = {
                'room_number': room_num, 
                'guest_name': guest_name, 
                'category': 'Baixa de Conta'
            }
            
            # Add service fee info if relevant (boolean flag is safe to copy)
            if not has_commissionable_service_fee_charge:
                base_transaction_details['service_fee_removed'] = True
            
            # Prepare for waiter breakdown distribution
            remaining_breakdown = dict(aggregated_waiter_breakdown) if aggregated_waiter_breakdown else {}
            
            # Filter valid payments first to know which is last
            valid_payments = [p for p in final_payments if p['amount'] > 0]
            
            # Log each payment separately
            for i, payment in enumerate(valid_payments):
                p_amount = payment['amount']
                
                current_details = base_transaction_details.copy()
                
                # Distribute waiter breakdown proportionally
                if aggregated_waiter_breakdown:
                    is_last = (i == len(valid_payments) - 1)
                    
                    if is_last:
                         current_details['waiter_breakdown'] = remaining_breakdown
                    else:
                        ratio = p_amount / total_amount if total_amount > 0 else 0
                        scaled_breakdown = {}
                        for w, full_amt in aggregated_waiter_breakdown.items():
                             share = round(full_amt * ratio, 2)
                             scaled_breakdown[w] = share
                             if w in remaining_breakdown:
                                 remaining_breakdown[w] = round(remaining_breakdown[w] - share, 2)
                        current_details['waiter_breakdown'] = scaled_breakdown

                CashierService.add_transaction(
                    cashier_type='guest_consumption',
                    amount=float(p_amount),
                    description=f"Fechamento Conta Quarto {room_num} - {guest_name}",
                    payment_method=payment['name'],
                    user=user,
                    details=current_details
                )
        
        log_action('Baixa de Conta', f'Conta do Quarto {room_num} fechada por {user}. Total: R$ {total_amount:.2f}', department='Recepção')
        
        receipt_html = None
        if print_receipt:
            # Sort charges
            def sort_key(c):
                try:
                    d = datetime.strptime(c['date'], '%d/%m/%Y')
                    if c['time']:
                        try:
                            t = datetime.strptime(c['time'], '%H:%M').time()
                            d = datetime.combine(d.date(), t)
                        except: pass
                    return d
                except: return datetime.min
            
            processed_charges.sort(key=sort_key)
            
            receipt_html = render_template('consumption_report.html',
                                room_number=room_num,
                                guest_name=guest_name,
                                generation_date=now_str,
                                charges=processed_charges,
                                total_amount=total_amount)

        # --- FISCAL POOL INTEGRATION REMOVED ---
        # Logic moved to individual charge loop to prevent grouping
        # ---------------------------------------

        return jsonify({'success': True, 'receipt_html': receipt_html})
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@reception_bp.route('/admin/consumption/cancel', methods=['POST'])
@login_required
def cancel_consumption():
    try:
        user_role = session.get('role')
        user_perms = session.get('permissions', [])
        
        # Allow Admin, Manager, Supervisor OR anyone with 'recepcao' permission
        if user_role not in ['admin', 'gerente', 'supervisor'] and 'recepcao' not in user_perms:
            return jsonify({'success': False, 'message': 'Acesso negado. Permissão insuficiente.'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400

        charge_id = data.get('charge_id')
        justification = data.get('justification')
        
        if not charge_id or not justification:
            return jsonify({'success': False, 'message': 'ID do consumo e justificativa são obrigatórios.'}), 400
            
        room_charges = load_room_charges()
        charge = next((c for c in room_charges if c.get('id') == charge_id), None)
        
        if not charge:
            return jsonify({'success': False, 'message': 'Consumo não encontrado.'}), 404
            
        if charge.get('status') == 'canceled':
            return jsonify({'success': False, 'message': 'Este consumo já foi cancelado.'}), 400
            
        # Update Status
        old_status = charge.get('status')
        charge['status'] = 'canceled'
        charge['canceled_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        charge['canceled_by'] = session.get('user')
        charge['cancellation_reason'] = justification
        
        save_room_charges(room_charges)
        
        # Audit Log
        logs = load_audit_logs()
        logs.append({
            'id': f"AUDIT_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}",
            'action': 'cancel_consumption',
            'target_id': charge_id,
            'target_details': {
                'room': charge.get('room_number'),
                'total': charge.get('total'),
                'date': charge.get('date'),
                'old_status': old_status
            },
            'user': session.get('user'),
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'justification': justification
        })
        save_audit_logs(logs)
        
        # Structured Logging (DB)
        LoggerService.log_acao(
            acao='Cancelar Consumo',
            entidade='Consumo',
            detalhes={
                'charge_id': charge_id,
                'room_number': charge.get('room_number'),
                'total': charge.get('total'),
                'old_status': old_status,
                'justification': justification
            },
            nivel_severidade='ALERTA',
            departamento_id='Recepção',
            colaborador_id=session.get('user', 'Sistema')
        )
        
        return jsonify({'success': True, 'message': 'Consumo cancelado com sucesso.'})
        
    except Exception as e:
        print(f"Error cancelling consumption: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/api/guest/details', defaults={'reservation_id': None})
@reception_bp.route('/api/guest/details/<path:reservation_id>')
@login_required
def api_guest_details(reservation_id):
    try:
        reservation_id = reservation_id or request.args.get('reservation_id')
        reservation_id = sanitize_input(reservation_id)
        if not reservation_id:
            return jsonify({'success': False, 'error': 'ID da reserva não informado'}), 400

        service = ReservationService()
        
        # 1. Get Basic Info
        res = service.get_reservation_by_id(reservation_id)
        if not res:
            res = {}
        else:
            res = service.merge_overrides_into_reservation(reservation_id, res)

        # 2. Get Extended Info
        details = service.get_guest_details(reservation_id)
        
        return jsonify({
            'success': True,
            'data': {
                'guest': details,
                'reservation': res,
                'unified': service.build_unified_reservation_record(reservation_id)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/update', methods=['POST'])
@login_required
def api_guest_update():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        if not res_id:
            return jsonify({'success': False, 'error': 'ID da reserva necessário'}), 400
            
        service = ReservationService()
        service.update_guest_details(res_id, data)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/search')
@login_required
def api_guest_search():
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': True, 'results': []})
        
        from app.services.guest_manager import guest_manager
        results = guest_manager.search_guests(query)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/add_companion', methods=['POST'])
@login_required
def api_guest_add_companion():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        companion = data.get('companion')
        
        if not res_id or not companion:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        service = ReservationService()
        details = service.get_guest_details(res_id)
        
        if 'companions' not in details:
            details['companions'] = []
            
        # Add ID if not present
        if 'id' not in companion:
            import uuid
            companion['id'] = str(uuid.uuid4())
            
        # Timestamp and Audit
        companion['created_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        companion['created_by'] = session.get('user')
            
        details['companions'].append(companion)
        service.update_guest_details(res_id, {'companions': details['companions']})
        
        return jsonify({'success': True, 'companion': companion})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/remove_companion', methods=['POST'])
@login_required
def api_guest_remove_companion():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        comp_id = data.get('companion_id')
        
        if not res_id or not comp_id:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        service = ReservationService()
        details = service.get_guest_details(res_id)
        
        if 'companions' in details:
            details['companions'] = [c for c in details['companions'] if str(c.get('id')) != str(comp_id)]
            service.update_guest_details(res_id, {'companions': details['companions']})
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/update_reservation_financials', methods=['POST'])
@login_required
def api_update_reservation_financials():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        if not res_id:
            return jsonify({'success': False, 'error': 'ID da reserva necessário'}), 400
        # Normalize numeric strings
        for k in ['amount', 'paid_amount', 'to_receive']:
            if k in data and isinstance(data.get(k), (int, float)):
                data[k] = f"{float(data[k]):.2f}"
        service = ReservationService()
        if data.get('status') not in (None, ''):
            service.update_reservation_status(res_id, data.get('status'))
        fin = service.update_financial_overrides(res_id, data)
        occupancy = load_room_occupancy() or {}
        cleaning = load_cleaning_status() or {}
        sync_changes = service.sync_operational_state_for_reservation(
            reservation_id=res_id,
            reservation_status=data.get('status'),
            occupancy_data=occupancy,
            cleaning_status=cleaning
        )
        if sync_changes.get('occupancy_changed'):
            save_room_occupancy(occupancy)
        if sync_changes.get('cleaning_changed'):
            save_cleaning_status(cleaning)
        # Return merged details
        res = service.get_reservation_by_id(res_id) or {}
        res = service.merge_overrides_into_reservation(res_id, res)
        return jsonify({'success': True, 'financial': fin, 'reservation': res, 'sync': sync_changes})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/reservation/status', methods=['POST'])
@login_required
def api_update_reservation_status_sync():
    try:
        data = request.json or {}
        reservation_id = data.get('reservation_id')
        new_status = data.get('status')
        if not reservation_id or not new_status:
            return jsonify({'success': False, 'error': 'reservation_id e status são obrigatórios'}), 400
        service = ReservationService()
        service.update_reservation_status(reservation_id, new_status)
        occupancy = load_room_occupancy() or {}
        cleaning = load_cleaning_status() or {}
        sync_changes = service.sync_operational_state_for_reservation(
            reservation_id=reservation_id,
            reservation_status=new_status,
            occupancy_data=occupancy,
            cleaning_status=cleaning
        )
        if sync_changes.get('occupancy_changed'):
            save_room_occupancy(occupancy)
        if sync_changes.get('cleaning_changed'):
            save_cleaning_status(cleaning)
        unified = service.build_unified_reservation_record(
            reservation_id=reservation_id,
            occupancy_data=occupancy,
            cleaning_status=cleaning
        )
        return jsonify({'success': True, 'sync': sync_changes, 'unified': unified})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@reception_bp.route('/api/reception/unified/sync_reservation', methods=['POST'])
@login_required
def api_unified_sync_reservation():
    try:
        data = request.json or {}
        reservation_id = data.get('reservation_id')
        if not reservation_id:
            return jsonify({'success': False, 'error': 'reservation_id é obrigatório'}), 400
        repo = ReceptionUnifiedRepository()
        result = repo.sync_from_legacy_reservation(reservation_id)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@reception_bp.route('/api/reception/unified/sync_all', methods=['POST'])
@login_required
def api_unified_sync_all():
    try:
        data = request.json or {}
        max_items = int(data.get('max_items') or 0)
        repo = ReceptionUnifiedRepository()
        result = repo.sync_all_from_legacy(max_items=max_items)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/upload_document', methods=['POST'])
@login_required
def api_guest_upload_document():
    try:
        res_id = request.form.get('reservation_id')
        file = request.files.get('document_photo')
        
        if not res_id or not file:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        filename = f"doc_{res_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        target_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'documents')
        os.makedirs(target_dir, exist_ok=True)
        
        path = os.path.join(target_dir, filename)
        file.save(path)
        final_filename = filename
        try:
            from PIL import Image, ImageOps
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)
            max_size = (1280, 1280)
            img.thumbnail(max_size)
            if img.mode in ('RGBA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = bg
            out_name = os.path.splitext(filename)[0] + '.jpg'
            out_path = os.path.join(target_dir, out_name)
            img.save(out_path, format='JPEG', quality=80, optimize=True, progressive=True)
            try:
                if os.path.exists(path) and path != out_path:
                    os.remove(path)
            except:
                pass
            final_filename = out_name
        except Exception:
            final_filename = filename
        
        # Update details with path (support up to 3 documents per reservation)
        service = ReservationService()
        details = service.get_guest_details(res_id)
        if 'personal_info' not in details:
            details['personal_info'] = {}
        pi = details['personal_info']
        photos = pi.get('document_photos')
        if not isinstance(photos, list):
            photos = []
            legacy = pi.get('document_photo_path')
            if legacy:
                photos.append(legacy)
        photos.append(final_filename)
        # keep only last 4
        photos = photos[-4:]
        pi['document_photos'] = photos
        # keep legacy key pointing to the latest for backward compatibility
        pi['document_photo_path'] = photos[-1] if photos else final_filename
        service.update_guest_details(res_id, {'personal_info': pi})
        
        return jsonify({'success': True, 'filename': final_filename, 'count': len(photos)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/guest/upload_signature', methods=['POST'])
@login_required
def api_guest_upload_signature():
    try:
        res_id = request.form.get('reservation_id')
        file = request.files.get('signature')
        if not res_id or not file:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
        target_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'signatures')
        os.makedirs(target_dir, exist_ok=True)
        filename = f"sign_{res_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        path = os.path.join(target_dir, filename)
        file.save(path)
        service = ReservationService()
        details = service.get_guest_details(res_id)
        if 'personal_info' not in details:
            details['personal_info'] = {}
        details['personal_info']['signature_path'] = filename
        service.update_guest_details(res_id, {'personal_info': details['personal_info']})
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/fnrh/<reservation_id>')
@login_required
def reception_fnrh(reservation_id):
    try:
        service = ReservationService()
        res = service.get_reservation_by_id(reservation_id) or {}
        details = service.get_guest_details(reservation_id) or {}
        return render_template('fnrh.html', reservation=res, details=details, reservation_id=reservation_id)
    except Exception as e:
        return f"Erro: {str(e)}", 500

@reception_bp.route('/api/utils/cep')
@login_required
def api_utils_cep():
    try:
        cep = request.args.get('cep', '').strip()
        import re
        cep_digits = re.sub(r'\D', '', cep or '')
        if len(cep_digits) != 8:
            return jsonify({'success': False, 'error': 'CEP inválido'}), 200
        import requests
        url = f'https://viacep.com.br/ws/{cep_digits}/json/'
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('erro'):
            return jsonify({'success': False, 'error': 'CEP não encontrado'}), 200
        logradouro = (data.get('logradouro') or '').strip()
        bairro = (data.get('bairro') or '').strip()
        localidade = (data.get('localidade') or '').strip()
        uf = (data.get('uf') or '').strip()
        address = ', '.join([p for p in [logradouro, bairro] if p])
        municipality = ' - '.join([p for p in [localidade, uf] if p])
        return jsonify({'success': True, 'address': address, 'municipality': municipality})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/utils/cpf')
@login_required
def api_utils_cpf():
    try:
        cpf = request.args.get('cpf', '').strip()
        import re, os
        cpf_digits = re.sub(r'\D', '', cpf or '')
        if len(cpf_digits) != 11:
            return jsonify({'success': False, 'error': 'CPF inválido'}), 200
        # Allow configuration via environment or system_config.json
        try:
            from app.services.system_config_manager import get_config_value
        except Exception:
            get_config_value = None
        ab_base = os.environ.get('APIBRASIL_CPF_BASE') or (get_config_value('apibrasil_cpf_base') if get_config_value else None)
        ab_token = os.environ.get('APIBRASIL_TOKEN') or (get_config_value('apibrasil_token') if get_config_value else None)
        base = os.environ.get('CPF_API_BASE') or (get_config_value('cpf_api_base') if get_config_value else None)
        token = os.environ.get('CPF_API_TOKEN') or (get_config_value('cpf_api_token') if get_config_value else None)
        use_base = None
        use_token = None
        if ab_base and ab_token:
            use_base = ab_base
            use_token = ab_token
        elif base and token:
            use_base = base
            use_token = token
        if not use_base or not use_token:
            return jsonify({'success': False, 'error': 'API de CPF não configurada'}), 200
        import requests
        headers = {'Authorization': f'Bearer {use_token}'}
        # Generic pattern: base may require path/params; we try fallback query param
        url = use_base
        if '{cpf}' in url:
            url = url.replace('{cpf}', cpf_digits)
            r = requests.get(url, headers=headers, timeout=7)
        else:
            r = requests.get(url, headers=headers, params={'cpf': cpf_digits}, timeout=7)
        data = {}
        try:
            data = r.json()
        except Exception:
            return jsonify({'success': False, 'error': 'Resposta inválida da API de CPF'}), 200
        # Best-effort extraction
        name = data.get('nome') or data.get('name') or data.get('full_name')
        birth = data.get('nascimento') or data.get('birthdate') or data.get('data_nascimento')
        address = None
        # Try common address structures
        endereco = data.get('endereco') or data.get('address') or {}
        if isinstance(endereco, dict):
            log = endereco.get('logradouro') or endereco.get('street')
            num = endereco.get('numero') or endereco.get('number')
            bai = endereco.get('bairro') or endereco.get('neighborhood')
            cid = endereco.get('cidade') or endereco.get('city')
            uf = endereco.get('uf') or endereco.get('state') or endereco.get('estado')
            parts = [p for p in [log, num if num else None, bai] if p]
            if parts:
                address = ', '.join([str(x) for x in parts])
        elif isinstance(endereco, str):
            address = endereco
        municipality = None
        if isinstance(endereco, dict):
            cid = endereco.get('cidade') or endereco.get('city')
            uf = endereco.get('uf') or endereco.get('state') or endereco.get('estado')
            if cid or uf:
                municipality = ' - '.join([p for p in [cid, uf] if p])
        return jsonify({'success': True, 'name': name, 'birthdate': birth, 'address': address, 'municipality': municipality})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/api/reception/generate_pre_checkin', methods=['POST'])
@login_required
def api_generate_pre_checkin():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        guest_name = data.get('guest_name')
        send_wa = data.get('send_whatsapp')
        
        # Generate Link (Placeholder)
        # In a real app, this would generate a unique token
        token = f"{res_id}" # Simple for now
        # Check if 'public' blueprint exists, otherwise use absolute string
        try:
            link = url_for('public.pre_checkin', token=token, _external=True)
        except:
            link = f"http://{request.host}/pre-checkin/{token}"
        
        wa_result = None
        if send_wa:
            # Send WA logic
            pass
            
        return jsonify({'success': True, 'link': link, 'whatsapp_result': wa_result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/print_individual_bills', methods=['POST'])
@login_required
def print_individual_bills_route():
    try:
        data = request.get_json()
        room_num = data.get('room_number')
        guest_name = data.get('guest_name', 'Hóspede')
        printer_id = data.get('printer_id')
        selected_ids = data.get('selected_charge_ids', [])
        
        if not room_num or not printer_id:
            return jsonify({'success': False, 'message': 'Dados incompletos'}), 400
            
        room_charges = load_room_charges()
        
        # Filter selected charges
        charges_to_print = []
        total_amount = 0.0
        
        for c in room_charges:
            if c.get('id') in selected_ids:
                charges_to_print.append(c)
                total_amount += float(c.get('total', 0))
        
        if not charges_to_print:
            return jsonify({'success': False, 'message': 'Nenhuma conta encontrada'}), 404
            
        success, error = print_individual_bills_thermal(printer_id, room_num, guest_name, charges_to_print, total_amount)
        
        if success:
            return jsonify({'success': True, 'message': 'Enviado para impressão.'})
        else:
            return jsonify({'success': False, 'message': f'Erro na impressão: {error}'})
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@reception_bp.route('/reception/preview_individual_bills', methods=['POST'])
@login_required
def preview_individual_bills_route():
    try:
        data = request.get_json()
        room_num = data.get('room_number')
        guest_name = data.get('guest_name', 'Hóspede')
        selected_ids = data.get('selected_charge_ids', [])
        
        if not room_num:
            return jsonify({'success': False, 'message': 'Dados incompletos'}), 400
            
        room_charges = load_room_charges()
        
        # Filter selected charges
        charges_to_print = []
        total_amount = 0.0
        
        for c in room_charges:
            if c.get('id') in selected_ids:
                charges_to_print.append(c)
                total_amount += float(c.get('total', 0))
        
        if not charges_to_print:
            return jsonify({'success': False, 'message': 'Nenhuma conta encontrada'}), 404
            
        preview_text = preview_individual_bill_text(room_num, guest_name, charges_to_print, total_amount)
        
        return jsonify({'success': True, 'preview_text': preview_text})
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- Experience Management Routes ---

from app.services.experience_service import ExperienceService

@reception_bp.route('/reception/experiences')
@login_required
def reception_experiences():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    if user_role not in ['admin', 'gerente'] and 'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    experiences = ExperienceService.get_all_experiences()
    # Sort by created_at desc
    experiences.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return render_template('reception_experiences.html', experiences=experiences)

@reception_bp.route('/reception/experiences/create', methods=['POST'])
@login_required
def create_experience():
    try:
        # Process files
        files = request.files.getlist('images')
        saved_images = ExperienceService.process_images(files)
        
        # Process video
        video_file = request.files.get('video')
        saved_video = ExperienceService.process_video(video_file)
        
        data = {
            'type': request.form.get('type'),
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'duration': request.form.get('duration'),
            'min_people': request.form.get('min_people', 1),
            'max_people': request.form.get('max_people', 1),
            'price': request.form.get('price'),
            'images': saved_images,
            'video': saved_video,
            # Internal Info
            'active': request.form.get('is_active') == 'on',
            'supplier_name': request.form.get('supplier_name'),
            'supplier_phone': request.form.get('supplier_phone'),
            'supplier_price': request.form.get('supplier_price'),
            'guest_price': request.form.get('guest_price'),
            'expected_commission': request.form.get('expected_commission'),
            'sales_commission': request.form.get('sales_commission'),
            'hotel_commission': request.form.get('hotel_commission')
        }
        
        if ExperienceService.create_experience(data):
            flash('Experiência criada com sucesso!', 'success')
        else:
            flash('Erro ao criar experiência.', 'error')
            
    except Exception as e:
        print(f"Error creating experience: {e}")
        flash(f'Erro: {str(e)}', 'error')
        
    return redirect(url_for('reception.reception_experiences'))

@reception_bp.route('/reception/experiences/<exp_id>/update', methods=['POST'])
@login_required
def update_experience(exp_id):
    try:
        current_exp = ExperienceService.get_experience_by_id(exp_id)
        if not current_exp:
            flash('Experiência não encontrada.', 'error')
            return redirect(url_for('reception.reception_experiences'))
            
        # Process new files
        files = request.files.getlist('images')
        new_images = ExperienceService.process_images(files)
        
        # Process new video (replace if provided)
        video_file = request.files.get('video')
        new_video = ExperienceService.process_video(video_file)
        
        # Combine images
        final_images = current_exp.get('images', []) + new_images
        
        # Determine video (new or existing)
        # If new video uploaded, replace. Else keep old.
        # If user wants to delete video, that's a separate action not handled here yet (simple CRUD)
        final_video = new_video if new_video else current_exp.get('video')
        
        data = {
            'type': request.form.get('type'),
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'duration': request.form.get('duration'),
            'min_people': request.form.get('min_people'),
            'max_people': request.form.get('max_people'),
            'price': request.form.get('price'),
            'images': final_images,
            'video': final_video,
            # Internal Info
            'active': request.form.get('is_active') == 'on',
            'supplier_name': request.form.get('supplier_name'),
            'supplier_phone': request.form.get('supplier_phone'),
            'supplier_price': request.form.get('supplier_price'),
            'guest_price': request.form.get('guest_price'),
            'expected_commission': request.form.get('expected_commission'),
            'sales_commission': request.form.get('sales_commission'),
            'hotel_commission': request.form.get('hotel_commission')
        }
        
        if ExperienceService.update_experience(exp_id, data):
            flash('Experiência atualizada.', 'success')
        else:
            flash('Erro ao atualizar.', 'error')
            
    except Exception as e:
        print(f"Error updating experience: {e}")
        flash(f'Erro: {str(e)}', 'error')
        
    return redirect(url_for('reception.reception_experiences'))

@reception_bp.route('/reception/experiences/<exp_id>/toggle', methods=['POST'])
@login_required
def toggle_experience(exp_id):
    try:
        new_state = ExperienceService.toggle_active(exp_id)
        if new_state is not None:
            return jsonify({'success': True, 'active': new_state})
        return jsonify({'success': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/experiences/<exp_id>/delete', methods=['POST'])
@login_required
def delete_experience(exp_id):
    try:
        if ExperienceService.delete_experience(exp_id):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/guest/experiences')
def guest_experiences_menu():
    # Public route (or requiring token if we implemented strict guest auth)
    # For now public as requested ("Menu Digital")
    experiences = ExperienceService.get_all_experiences(only_active=True)
    
    # Group by type?
    grouped = {}
    for e in experiences:
        t = e.get('type', 'Outros')
        if t not in grouped: grouped[t] = []
        grouped[t].append(e)
        
    return render_template('guest_experiences_menu.html', grouped_experiences=grouped)


@reception_bp.route('/reception/reservation/<reservation_id>/debt')
@login_required
def reception_reservation_debt(reservation_id):
    try:
        service = ReservationService()
        res = service.get_reservation_by_id(reservation_id)
        if not res:
            return jsonify({'success': False, 'error': 'Reserva não encontrada'}), 404
            
        def parse_val(val):
            if isinstance(val, (int, float)):
                return float(val)
            try:
                # Handle R$ 1.000,00 -> 1000.00
                if ',' in str(val):
                    clean = str(val).replace('R$', '').replace('.', '').replace(',', '.').strip()
                else:
                    clean = str(val).replace('R$', '').strip()
                return float(clean)
            except:
                return 0.0

        total = parse_val(res.get('amount', 0))
        paid = parse_val(res.get('paid_amount', 0))

        if str(res.get('source_type', '')).lower() != 'manual':
            all_payments = service.get_reservation_payments()
            sidecar_payments = all_payments.get(str(reservation_id), [])
            sidecar_total = 0.0
            for p in sidecar_payments:
                sidecar_total += parse_val((p or {}).get('amount', 0))
            paid += sidecar_total

        remaining = max(0.0, total - paid)
        
        return jsonify({
            'success': True,
            'total': total,
            'paid': paid,
            'remaining': remaining
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@reception_bp.route('/reception/reservation/pay', methods=['POST'])
@login_required
def reception_reservation_pay():
    try:
        data = request.json
        res_id = data.get('reservation_id')
        amount = float(data.get('amount', 0))
        payment_method_id = data.get('payment_method_id')
        payment_method_name = data.get('payment_method_name')
        origin = data.get('origin', 'reservations') # 'reservations' or 'checkin'
        
        if not res_id or amount <= 0 or not payment_method_id:
             return jsonify({'success': False, 'error': 'Dados inválidos.'}), 400
             
        # Check Cashier Session
        current_session = CashierService.get_active_session('reservation_cashier')
        if not current_session:
             return jsonify({'success': False, 'error': 'Caixa de Reservas fechado. Abra o caixa para registrar o pagamento.'}), 400

        service = ReservationService()
        res = service.get_reservation_by_id(res_id)
        if not res:
             return jsonify({'success': False, 'error': 'Reserva não encontrada.'}), 404

        payment_methods = load_payment_methods()
        method_obj = next((m for m in payment_methods if str(m.get('id')) == str(payment_method_id)), None)
        if not method_obj:
            return jsonify({'success': False, 'error': 'Forma de pagamento inválida.'}), 400
        available_in = method_obj.get('available_in') or []
        if not any(tag in available_in for tag in ['reservations', 'reservas', 'caixa_reservas']):
            return jsonify({'success': False, 'error': 'Forma de pagamento não habilitada para Reservas.'}), 400
        payment_method_name = method_obj.get('name') or payment_method_name or 'Desconhecido'

        def parse_val(val):
            if isinstance(val, (int, float)):
                return float(val)
            try:
                if ',' in str(val):
                    clean = str(val).replace('R$', '').replace('.', '').replace(',', '.').strip()
                else:
                    clean = str(val).replace('R$', '').strip()
                return float(clean)
            except Exception:
                return 0.0

        total = parse_val(res.get('amount', 0))
        paid = parse_val(res.get('paid_amount', 0))
        if str(res.get('source_type', '')).lower() != 'manual':
            sidecar = service.get_reservation_payments().get(str(res_id), [])
            paid += sum(parse_val((p or {}).get('amount', 0)) for p in sidecar)
        remaining_before = max(0.0, total - paid)
        if amount > remaining_before + 0.05:
            return jsonify({'success': False, 'error': f'Valor informado excede o saldo pendente (R$ {remaining_before:.2f}).'}), 400
        
        # Determine description based on origin
        desc_prefix = "Pagamento Reserva"
        if origin == 'checkin':
            desc_prefix = "Pagamento Check-in"
            
        # Add to Cashier
        CashierService.add_transaction(
            cashier_type='reservation_cashier',
            amount=amount,
            description=f"{desc_prefix} #{res_id} - {res.get('guest_name')}",
            payment_method=payment_method_name,
            user=session.get('user'),
            transaction_type='sale',
            is_withdrawal=False,
            details={
                'reservation_id': str(res_id),
                'origin': origin,
                'category': 'Pagamento de Reserva',
                'tag': 'reservas',
                'guest_name': res.get('guest_name', ''),
                'remaining_before': remaining_before
            }
        )
        
        # Add to Reservation Payments
        service.add_payment(res_id, amount, {
            'method': payment_method_name,
            'method_id': payment_method_id,
            'user': session.get('user'),
            'notes': f'Pagamento via Recepção ({origin})'
        })

        try:
            FiscalPoolService.add_to_pool(
                origin='reservations',
                original_id=f"RESERVATION_PAY_{res_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                total_amount=amount,
                items=[
                    {
                        'name': f"Reserva #{res_id} - Complemento no Check-in",
                        'qty': 1,
                        'price': amount,
                        'total': amount,
                        'is_service': True,
                        'service_code': '0901'
                    }
                ],
                payment_methods=[
                    {
                        'method': payment_method_name,
                        'amount': amount,
                        'is_fiscal': True,
                        'fiscal_cnpj': method_obj.get('fiscal_cnpj')
                    }
                ],
                user=session.get('user'),
                customer_info={
                    'name': res.get('guest_name', 'Hóspede'),
                    'cpf_cnpj': res.get('doc_id') or res.get('cpf') or '',
                    'reservation_id': str(res_id),
                    'origin': origin
                },
                notes=f"Recebimento de reserva na recepção ({origin})"
            )
        except Exception as fiscal_error:
            current_app.logger.error(f"Erro ao enviar pagamento de reserva ao pool fiscal: {fiscal_error}")
        
        log_action('Pagamento Reserva', f"Recebido R$ {amount:.2f} ({payment_method_name}) para Reserva #{res_id} (Origem: {origin})", department='Recepção')
        
        remaining_after = max(0.0, remaining_before - amount)
        return jsonify({'success': True, 'remaining': remaining_after})
    except Exception as e:
        current_app.logger.error(f"Erro pagamento reserva: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@reception_bp.route('/reception/checkin', methods=['POST'])
@login_required
def reception_checkin():
    """
    Dedicated route for handling guest check-in.
    Refactored from reception_rooms to improve maintainability.
    """
    # Permission Check (Same as reception_rooms)
    user_role = session.get('role')
    role_norm = normalize_text(str(user_role or ''))
    user_dept = session.get('department')
    dept_norm = normalize_text(str(user_dept or ''))
    user_perms = session.get('permissions') or []
    has_reception_permission = isinstance(user_perms, (list, tuple, set)) and any(normalize_text(str(p)) == 'recepcao' for p in user_perms)

    if role_norm not in ['admin', 'gerente', 'recepcao', 'supervisor'] and dept_norm != 'recepcao' and not has_reception_permission:
         flash('Acesso restrito.')
         return redirect(url_for('main.index'))

    occupancy = load_room_occupancy()
    
    # Pre-allocation integration (needed for reservation linking logic)
    upcoming_checkins = {}
    try:
        res_service = ReservationService()
        upcoming_list = res_service.get_upcoming_checkins()
        for item in upcoming_list:
            upcoming_checkins[item['room']] = item
    except Exception as e:
        print(f"Error loading upcoming checkins: {e}")

    # 1. Sanitization & Input Extraction
    room_num_raw = sanitize_input(request.form.get('room_number'))
    guest_name = sanitize_input(request.form.get('guest_name'))
    doc_id = sanitize_input(request.form.get('doc_id'))
    email = sanitize_input(request.form.get('email'))
    phone = sanitize_input(request.form.get('phone'))
    checkin_date = sanitize_input(request.form.get('checkin_date'))
    checkout_date = sanitize_input(request.form.get('checkout_date'))
    num_adults_raw = request.form.get('num_adults', 1)

    # 2. Validation
    valid_room, msg_room = validate_room_number(room_num_raw)
    if not valid_room:
        log_action('Validation Error', f"Checkin - Invalid Room: {room_num_raw} - {msg_room}", department='Recepção')
        flash(f'Erro no Check-in: {msg_room}')
        return redirect(url_for('reception.reception_rooms'))
    
    valid_name, msg_name = validate_required(guest_name, "Nome do Hóspede")
    if not valid_name:
        log_action('Validation Error', f"Checkin - Invalid Name: {msg_name}", department='Recepção')
        flash(f'Erro no Check-in: {msg_name}')
        return redirect(url_for('reception.reception_rooms'))

    # Optional Validations
    if doc_id:
        # Simple check: if it looks like CPF (11 digits), validate it. Otherwise assume passport/RG.
        digits = re.sub(r'\D', '', doc_id)
        if len(digits) == 11:
            valid_cpf, msg_cpf = validate_cpf(doc_id)
            if not valid_cpf:
                log_action('Validation Error', f"Checkin - Invalid CPF: {doc_id} - {msg_cpf}", department='Recepção')
                flash(f'Erro no Check-in: {msg_cpf}')
                return redirect(url_for('reception.reception_rooms'))

    if email:
        valid_email, msg_email = validate_email(email)
        if not valid_email:
            log_action('Validation Error', f"Checkin - Invalid Email: {email} - {msg_email}", department='Recepção')
            flash(f'Erro no Check-in: {msg_email}')
            return redirect(url_for('reception.reception_rooms'))

    if phone:
        valid_phone, msg_phone = validate_phone(phone)
        if not valid_phone:
            log_action('Validation Error', f"Checkin - Invalid Phone: {phone} - {msg_phone}", department='Recepção')
            flash(f'Erro no Check-in: {msg_phone}')
            return redirect(url_for('reception.reception_rooms'))

    valid_in, msg_in = validate_date(checkin_date, '%Y-%m-%d')
    valid_out, msg_out = validate_date(checkout_date, '%Y-%m-%d')
    if not (valid_in and valid_out):
        log_action('Validation Error', f"Checkin - Invalid Dates: {checkin_date}/{checkout_date} - {msg_in or msg_out}", department='Recepção')
        flash(f'Erro no Check-in: {msg_in or msg_out}')
        return redirect(url_for('reception.reception_rooms'))

    try:
        num_adults = int(num_adults_raw)
        if num_adults < 1: raise ValueError
    except ValueError:
        flash('Erro no Check-in: Número de adultos inválido.')
        return redirect(url_for('reception.reception_rooms'))

    # Format room number
    room_num = format_room_number(room_num_raw)
    
    # Validation: Capacity Check
    room_capacities = ReservationService.ROOM_CAPACITIES
    if str(room_num) in room_capacities:
        max_capacity = room_capacities[str(room_num)]
        if num_adults > max_capacity:
            log_action('Checkin Blocked', f"Capacity exceeded for room {room_num}: {num_adults} > {max_capacity}", department='Recepção')
            flash(f'Erro: Quarto {room_num} comporta no máximo {max_capacity} adultos.')
            return redirect(url_for('reception.reception_rooms'))
    
    # Validation: Check if room is already occupied
    if str(room_num) in occupancy:
        current_guest = occupancy[str(room_num)].get('guest_name', 'Hóspede Desconhecido')
        # Allow update ONLY if guest name matches exactly (Edit Check-in scenario)
        # Otherwise, block to prevent overwrite
        if current_guest.lower() != guest_name.lower():
            log_action('Checkin Blocked', f"Attempt to overwrite occupied room {room_num} ({current_guest}) with {guest_name}", department='Recepção')
            flash(f'Erro: Quarto {room_num} já está ocupado por {current_guest}. Realize o check-out ou verifique o número do quarto.')
            return redirect(url_for('reception.reception_rooms'))
        else:
            # It's an update for the same guest
            log_action('Checkin Update', f"Updating info for {guest_name} in room {room_num}", department='Recepção')
    
    # Logic continues
    if room_num and guest_name:
        # Convert dates to DD/MM/YYYY for storage/display
        try:
            if checkin_date:
                checkin_date = datetime.strptime(checkin_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            if checkout_date:
                checkout_date = datetime.strptime(checkout_date, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass # Already validated above, but safety net

        # 3. Update Reservation Status (if linked) or Create Walk-in
        reservation_id = request.form.get('reservation_id')
        res_service = ReservationService()

        # Heuristic: Try to find reservation if not provided but matches upcoming
        if not reservation_id:
            g_name = normalize_text(guest_name)
            
            # Strategy 1: Match by Room (High Confidence)
            if room_num in upcoming_checkins:
                upcoming = upcoming_checkins[room_num]
                u_name = normalize_text(upcoming.get('guest_name', ''))
                # Allow partial match if room matches
                if u_name and g_name and (u_name in g_name or g_name in u_name):
                    reservation_id = upcoming.get('id')

            # Strategy 2: Match by Name (Medium Confidence) - Only if Strategy 1 failed
            if not reservation_id:
                for item in upcoming_list:
                    u_name = normalize_text(item.get('guest_name', ''))
                    if u_name and g_name and u_name == g_name:
                        reservation_id = item.get('id')
                        log_action('Checkin Link', f"Linked reservation {reservation_id} by name match '{guest_name}' (allocated room: {item.get('room')})", department='Recepção')
                        break

        # Collect Personal Info for Guest Details
        personal_info = {
            'name': guest_name,
            'doc_id': doc_id,
            'email': email,
            'phone': phone,
            'address': request.form.get('address'),
            'city': request.form.get('city'),
            'state': request.form.get('state'),
            'zip': request.form.get('zipcode'),
            'nationality': request.form.get('nationality'),
            'profession': request.form.get('profession'),
            'gender': request.form.get('gender'),
            'birth_date': request.form.get('birth_date')
        }

        if reservation_id:
            try:
                # Update status
                res_service.update_reservation_status(reservation_id, 'Checked-in')
                log_action('Reservation Updated', f"Reservation {reservation_id} status set to Checked-in", department='Recepção')
                
                # Update Guest Details
                res_service.update_guest_details(reservation_id, {'personal_info': personal_info})
            except Exception as e:
                print(f"Error updating reservation status/details: {e}")
        else:
            # Create Walk-in / Manual Reservation to store details
            try:
                new_res_data = {
                    'guest_name': guest_name,
                    'checkin': checkin_date, # DD/MM/YYYY
                    'checkout': checkout_date, # DD/MM/YYYY
                    'status': 'Checked-in',
                    'category': 'Walk-in',
                    'channel': 'Balcão',
                    'amount': '0.00', # Pricing not handled in this modal yet
                    'paid_amount': '0.00',
                    'to_receive': '0.00'
                }
                new_res = res_service.create_manual_reservation(new_res_data)
                reservation_id = new_res.get('id')
                
                # Update Guest Details for the new reservation
                res_service.update_guest_details(reservation_id, {'personal_info': personal_info})
                
                # Also save manual allocation
                res_service.save_manual_allocation(reservation_id, room_num, checkin_date, checkout_date)
                
                log_action('Walk-in Created', f"Created walk-in reservation {reservation_id} for {guest_name}", department='Recepção')
            except Exception as e:
                print(f"Error creating walk-in reservation: {e}")

        occupancy[room_num] = {
            'guest_name': guest_name,
            'checkin': checkin_date,
            'checkout': checkout_date,
            'num_adults': num_adults,
            'checked_in_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'reservation_id': reservation_id # Link stored
        }
        save_room_occupancy(occupancy)
        
        # Automatically open restaurant table for the room
        orders = load_table_orders()
        if str(room_num) not in orders:
            orders[str(room_num)] = {
                'items': [], 
                'total': 0, 
                'status': 'open', 
                'opened_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'num_adults': num_adults,
                'customer_type': 'hospede',
                'room_number': str(room_num)
            }
            save_table_orders(orders)
            log_action('Check-in', f'Check-in Quarto {room_num} - {guest_name}', department='Recepção')
            flash(f'Check-in realizado e Mesa {room_num} aberta automaticamente.')
        else:
            # Update existing order details if needed
            orders[str(room_num)]['num_adults'] = num_adults
            orders[str(room_num)]['room_number'] = str(room_num) # ensure link
            save_table_orders(orders)
            log_action('Check-in (Update)', f'Check-in (Atualização) Quarto {room_num} - {guest_name}', department='Recepção')
            flash(f'Check-in realizado para Quarto {room_num}.')
            
    return redirect(url_for('reception.reception_rooms'))
