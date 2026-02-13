from flask import render_template, session, redirect, url_for, request, flash, jsonify, current_app
from . import main_bp
from datetime import datetime
import traceback
import re
import requests
from app.utils.decorators import login_required
from app.services.data_service import (
    load_maintenance_requests, load_payment_methods, save_payment_methods, load_fiscal_settings
)
from app.services.user_service import load_users
from app.services.rh_service import get_user_documents
from app.services.time_tracking_service import (
    load_time_tracking_for_user, 
    _get_user_target_seconds, 
    _format_seconds_hms
)

# Constants
SERVICE_PAGES = [
    {
        'id': 'cozinha',
        'name': 'Cozinha',
        'icon': 'bi bi-egg-fried',
        'actions': []
    },
    {
        'id': 'principal',
        'name': 'Estoque Principal',
        'icon': 'bi bi-box-seam',
        'actions': []
    },
    {
        'id': 'restaurante_mirapraia',
        'name': 'Restaurante Mirapraia',
        'icon': 'bi bi-restaurant',
        'actions': [
            {'name': 'Mesas / Pedidos', 'url': 'restaurant.restaurant_tables', 'icon': 'bi bi-grid-3x3-gap'},
            {'name': 'Fila de Espera', 'url': 'reception.reception_waiting_list', 'icon': 'bi bi-people-fill'},
            {'name': 'Caixa', 'url': 'restaurant.restaurant_cashier', 'icon': 'bi bi-cash-coin'},
            {'name': 'Complementos', 'url': 'restaurant.restaurant_complements', 'icon': 'bi bi-plus-square'},
            {'name': 'Observações', 'url': 'restaurant.restaurant_observations', 'icon': 'bi bi-card-text'}
        ]
    },
    {
        'id': 'recepcao',
        'name': 'Recepção (Quartos)',
        'icon': 'bi bi-bell',
        'actions': [
            {'name': 'Gestão de Quartos', 'url': 'reception.reception_rooms', 'icon': 'bi bi-building'},
            {'name': 'Caixa da Recepção', 'url': 'reception.reception_cashier', 'icon': 'bi bi-cash-coin'},
            {'name': 'Fila de Espera', 'url': 'reception.reception_waiting_list', 'icon': 'bi bi-people-fill'}
        ]
    },
    {
        'id': 'governanca',
        'name': 'Governança',
        'icon': 'bi bi-house-gear',
        'actions': []
    },
    {
        'id': 'conferencias',
        'name': 'Conferências',
        'icon': 'bi bi-clipboard-data',
        'actions': []
    },
    {
        'id': 'financeiro',
        'name': 'Financeiro',
        'icon': 'bi bi-graph-up-arrow',
        'actions': [
            {'name': 'Cálculo de Comissões', 'url': 'finance.finance_commission', 'icon': 'bi bi-calculator'},
            {'name': 'Caixa Restaurante', 'url': 'restaurant.restaurant_cashier', 'icon': 'bi bi-cash-coin'},
            {'name': 'Caixa Recepção', 'url': 'reception.reception_cashier', 'icon': 'bi bi-cash-stack'},
            {'name': 'Relatório de Fechamentos', 'url': 'finance.finance_cashier_reports', 'icon': 'bi bi-bar-chart'},
            {'name': 'Balanços', 'url': 'finance.finance_balances', 'icon': 'bi bi-clipboard-data'},
            {'name': 'Formas de Pagamento', 'url': 'main.payment_methods', 'icon': 'bi bi-credit-card-2-front'},
            {'name': 'Conciliação de Cartões', 'url': 'finance.finance_reconciliation', 'icon': 'bi bi-arrows-shuffle'},
            {'name': 'Ranking de Comissões', 'url': 'finance.commission_ranking', 'icon': 'bi bi-award'},
            {'name': 'Portal Contabilidade', 'url': 'finance.accounting_dashboard', 'icon': 'bi bi-journal-richtext'}
        ]
    },
    {
        'id': 'rh',
        'name': 'Recursos Humanos',
        'icon': 'bi bi-people',
        'actions': [
            {'name': 'Controle de Ponto', 'url': 'hr.rh_timesheet', 'icon': 'bi bi-calendar-check'},
            {'name': 'Documentos', 'url': 'hr.rh_documents', 'icon': 'bi bi-file-earmark-text'},
            {'name': 'Ex-Funcionários', 'url': 'hr.rh_ex_employees', 'icon': 'bi bi-person-x'}
        ]
    }
]

SERVICES = [
    {'name': 'Cardápio Digital', 'url': 'menu.menu_management', 'icon': 'bi bi-book'},
    {'name': 'Mesas / Pedidos', 'url': 'restaurant_tables', 'icon': 'bi bi-grid-3x3-gap'},
    {'name': 'Comandas (Hóspedes)', 'url': 'reception_reservations', 'icon': 'bi bi-receipt'}, # Still in app.py
    {'name': 'Cozinha (KDS)', 'url': 'kitchen.kitchen_kds', 'icon': 'bi bi-tv'},
    {'name': 'Estoque', 'url': 'stock.stock_dashboard', 'icon': 'bi bi-box-seam'},
    {'name': 'Compras', 'url': 'stock.purchasing_dashboard', 'icon': 'bi bi-cart'},
    {'name': 'Manutenção', 'url': 'maintenance_dashboard', 'icon': 'bi bi-tools'},
    {'name': 'RH / Ponto', 'url': 'hr_dashboard', 'icon': 'bi bi-people'},
    {'name': 'Governança', 'url': 'housekeeping_dashboard', 'icon': 'bi bi-house-door'},
    {'name': 'Lavanderia', 'url': 'laundry_management', 'icon': 'bi bi-basket'},
    {'name': 'Fiscal', 'url': 'fiscal_dashboard', 'icon': 'bi bi-file-earmark-text'},
    {'name': 'Relatórios', 'url': 'reports_dashboard', 'icon': 'bi bi-graph-up'},
    {'name': 'Configurações', 'url': 'settings', 'icon': 'bi bi-gear'}
]

@main_bp.route('/')
@login_required
def index():
    try:
        pending_count = 0
        scheduling_count = 0
        
        user_role = session.get('role')
        user_dept = session.get('department')
        
        if user_role in ['gerente', 'admin']:
            requests = load_maintenance_requests()
            
            # Se for gerente de manutenção ou admin, vê pendentes de manutenção
            if user_dept == 'Manutenção' or user_role == 'admin':
                pending_count = sum(1 for r in requests if r.get('status') == 'Pendente')
                
            # Verifica se há solicitações de agendamento
            if user_role == 'admin':
                # Admin vê TODAS as solicitações aguardando agendamento de TODOS os departamentos
                scheduling_count = sum(1 for r in requests if r.get('status') == 'Aguardando Agendamento')
            else:
                # Gerente vê apenas do seu departamento
                scheduling_count = sum(1 for r in requests if r.get('department') == user_dept and r.get('status') == 'Aguardando Agendamento')
            
        # Notificações de Estoques (Segunda=0, Quinta=3)
        stock_notification = None
        weekday = datetime.now().weekday()
        
        if user_role in ['gerente', 'admin']:
            if weekday == 0: # Segunda
                stock_notification = "Lembrete: Requisição de Material deve ser feita hoje (Segunda-feira)!"
            elif weekday == 3: # Quinta
                stock_notification = "Lembrete: Requisição de Material deve ser feita hoje (Quinta-feira)!"

        # Check for stock adjustments (First day of month)
        stock_adjustment_alert = False
        if datetime.now().day == 1 and (session.get('role') == 'admin' or (session.get('role') == 'gerente' and session.get('department') == 'Principal')):
             stock_adjustment_alert = True

        # Time Tracking Logic
        time_tracking_status = 'Não iniciado'
        time_tracking_total = "00:00:00"
        time_tracking_target = "00:00:00"
        time_tracking_overtime = "00:00:00"
        time_tracking_bank = "00:00:00"
        time_tracking_has_overtime = False
        time_tracking_is_day_off = False
        current_session_seconds = 0
        
        if session.get('user'):
            username = session.get('user')
            today = datetime.now().strftime('%Y-%m-%d')
            date_obj = datetime.now()
            
            tt_user_data = load_time_tracking_for_user(username)
            days = tt_user_data.get('days', {}) if isinstance(tt_user_data, dict) else {}
            day_record = days.get(today) if isinstance(days, dict) else None
            
            if isinstance(day_record, dict):
                time_tracking_status = day_record.get('status', 'Não iniciado')
                accumulated = day_record.get('accumulated_seconds', 0)
                
                if time_tracking_status == 'Trabalhando' and day_record.get('last_start_time'):
                    try:
                        start_time = datetime.fromisoformat(day_record['last_start_time'])
                        current_session_seconds = (datetime.now() - start_time).total_seconds()
                    except ValueError:
                        pass
                    
                total_seconds = int(accumulated + current_session_seconds)
                time_tracking_total = _format_seconds_hms(total_seconds)
                
                target_seconds = day_record.get('target_seconds')
                if target_seconds is None:
                    target_seconds, _, is_day_off = _get_user_target_seconds(username, date_obj)
                    time_tracking_is_day_off = is_day_off
                else:
                    time_tracking_is_day_off = bool(day_record.get('is_day_off', False))
                time_tracking_target = _format_seconds_hms(target_seconds)
                
                if time_tracking_is_day_off:
                    overtime_seconds = int(total_seconds)
                else:
                    overtime_seconds = max(0, int(total_seconds) - int(target_seconds or 0))
                time_tracking_has_overtime = overtime_seconds > 0
                time_tracking_overtime = _format_seconds_hms(overtime_seconds)
            
            bank_seconds = 0
            if isinstance(days, dict):
                for day_key, record in days.items():
                    if not isinstance(record, dict):
                        continue
                    if record.get('status') != 'Finalizado':
                        continue
                    worked = record.get('accumulated_seconds', 0)
                    try:
                        worked_seconds = int(float(worked))
                    except (TypeError, ValueError):
                        worked_seconds = 0
                    target = record.get('target_seconds')
                    is_day_off_rec = False
                    if target is None:
                        try:
                            d = datetime.strptime(day_key, '%Y-%m-%d')
                            target, _, is_day_off_rec = _get_user_target_seconds(username, d)
                        except ValueError:
                            target = 0
                    else:
                        is_day_off_rec = bool(record.get('is_day_off', False))

                    try:
                        target_seconds = int(target or 0)
                    except (TypeError, ValueError):
                        target_seconds = 0
                        
                    overtime = max(0, worked_seconds - target_seconds)
                        
                    bank_seconds += overtime
            time_tracking_bank = _format_seconds_hms(bank_seconds)

        # Birthday and Anniversary Logic
        celebrants = []
        try:
            all_users = load_users()
            now_dt = datetime.now()
            current_user = session.get('user')
            
            for u_login, u_data in all_users.items():
                if u_login == current_user:
                    continue 
                
                # Birthday
                dob_str = u_data.get('birthday', '')
                if dob_str:
                    try:
                        dob = datetime.strptime(dob_str, '%Y-%m-%d')
                        if dob.day == now_dt.day and dob.month == now_dt.month:
                            celebrants.append({
                                'type': 'birthday',
                                'name': u_data.get('full_name') or u_login
                            })
                    except ValueError:
                        pass
                
                # Anniversary
                adm_str = u_data.get('admission_date', '')
                if adm_str:
                    try:
                        adm = datetime.strptime(adm_str, '%Y-%m-%d')
                        if adm.day == now_dt.day and adm.month == now_dt.month and adm.year != now_dt.year:
                            years = now_dt.year - adm.year
                            if years > 0:
                                celebrants.append({
                                    'type': 'anniversary',
                                    'name': u_data.get('full_name') or u_login,
                                    'years': years
                                })
                    except ValueError:
                        pass
        except Exception as e:
            print(f"Error checking celebrations: {e}")

        # RH Documents Notification
        rh_docs_pending = 0
        try:
            user_docs = get_user_documents(session.get('user'))
            rh_docs_pending = sum(1 for d in user_docs if d.get('status') == 'pending')
        except:
            pass

        return render_template(
            'index.html',
            celebrants=celebrants,
            services=SERVICE_PAGES,
            pending_maintenance=pending_count,
            scheduling_requests=scheduling_count,
            stock_notification=stock_notification,
            stock_adjustment_alert=stock_adjustment_alert,
            time_tracking_status=time_tracking_status,
            time_tracking_total=time_tracking_total,
            time_tracking_target=time_tracking_target,
            time_tracking_overtime=time_tracking_overtime,
            time_tracking_bank=time_tracking_bank,
            time_tracking_has_overtime=time_tracking_has_overtime,
            time_tracking_is_day_off=time_tracking_is_day_off,
            rh_docs_pending=rh_docs_pending
        )
    except Exception as e:
        err_msg = f"CRITICAL ERROR IN INDEX: {str(e)}\n{traceback.format_exc()}"
        print(err_msg)
        return f"Erro interno no Dashboard: {str(e)}", 500

@main_bp.route('/health')
def health():
    return {'status': 'ok'}

@main_bp.route('/guest')
def guest_welcome():
    return render_template('guest_welcome.html')

import os
from flask import send_from_directory, send_file, current_app
from app.services.system_config_manager import SAEPEARL_TEMPLATE_DIR, SAEPEARL_ASSETS_DIR, PRODUCT_PHOTOS_DIR
from app.services.data_service import load_products, load_stock_entries

# SERVICE_PAGES MOVED TO TOP OF FILE

@main_bp.app_template_filter('abbreviate_unit')
def abbreviate_unit_filter(unit_name):
    if not unit_name: return ""
    mapping = {
        'Kilogramas': 'Kg', 'Kilograma': 'Kg',
        'Quilogramas': 'Kg', 'Quilograma': 'Kg',
        'Gramas': 'g', 'Grama': 'g',
        'Litros': 'L', 'Litro': 'L',
        'Mililitros': 'ml', 'Mililitro': 'ml',
        'Unidade': 'Un', 'Unidades': 'Un',
        'Pacote': 'Pct', 'Pacotes': 'Pct',
        'Caixa': 'Cx', 'Caixas': 'Cx',
        'Metro': 'm', 'Metros': 'm'
    }
    return mapping.get(unit_name, unit_name)

@main_bp.route('/site')
def site():
    index_path = os.path.join(SAEPEARL_TEMPLATE_DIR, 'index.html')
    return send_file(index_path)

@main_bp.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(SAEPEARL_ASSETS_DIR, filename)

@main_bp.route('/service/<service_id>')
@login_required
def service_page(service_id):
    try:
        current_app.logger.info(
            f"Service page access: service_id={service_id}, user={session.get('user')}, role={session.get('role')}, department={session.get('department')}, permissions={session.get('permissions')}"
        )
        service = next((s for s in SERVICE_PAGES if s['id'] == service_id), None)
        if service:
            if service_id == 'recepcao':
                return redirect(url_for('reception.reception_dashboard'))
                
            # Verifica se é gerente DO departamento atual ou ADMIN
            is_manager = False
            user_dept = session.get('department')
            user_role = session.get('role')
            
            # Mapeamento simples de IDs de serviço para nomes de departamento
            dept_map = {
                'cozinha': 'Cozinha',
                'principal': 'Principal',
                'manutencao': 'Manutenção',
                'restaurante_mirapraia': 'Cozinha',
                'governanca': 'Governança',
                'conferencias': 'Governança', 
                'financeiro': 'Principal',
                'rh': 'Principal'
            }
            
            current_service_dept = dept_map.get(service_id)
            
            if user_role == 'admin' or (user_role == 'gerente' and user_dept == current_service_dept) or service_id in session.get('permissions', []):
                is_manager = True
                
            purchase_alerts = []
            if service_id == 'principal' and is_manager:
                products = load_products()
                entries = load_stock_entries()
                
                # Map last purchase date per product
                last_purchases = {}
                for entry in entries:
                    p_name = entry['product']
                    try:
                        entry_date = datetime.strptime(entry['date'], '%d/%m/%Y')
                        if p_name not in last_purchases or entry_date > last_purchases[p_name]:
                            last_purchases[p_name] = entry_date
                    except ValueError:
                        pass
                
                today = datetime.now()
                
                for p in products:
                    freq = p.get('frequency', 'Sem Frequência')
                    if not freq or freq == 'Sem Frequência':
                        continue
                    
                    last_date = last_purchases.get(p['name'])
                    days_diff = 0
                    
                    # Check thresholds
                    is_alert = False
                    threshold_desc = ""
                    
                    if last_date:
                        days_diff = (today - last_date).days
                        last_date_str = last_date.strftime('%d/%m/%Y')
                    else:
                        days_diff = 9999 # Never purchased
                        last_date_str = "Nunca"
                    
                    if freq == 'Semanal' and days_diff > 14:
                        is_alert = True
                        threshold_desc = "> 2 semanas"
                    elif freq == 'Quinzenal' and days_diff > 30:
                        is_alert = True
                        threshold_desc = "> 2 quinzenas"
                    elif freq == 'Mensal' and days_diff > 60:
                        is_alert = True
                        threshold_desc = "> 2 meses"
                    
                    if is_alert:
                        days_display = f"{days_diff} dias" if days_diff != 9999 else "Nunca comprado"
                        purchase_alerts.append({
                            'product': p['name'],
                            'days': days_display,
                            'last_purchase': last_date_str,
                            'threshold': threshold_desc
                        })

            response = render_template('service.html', 
                                   service=service, 
                                   is_manager=is_manager,
                                   purchase_alerts=purchase_alerts)
            current_app.logger.info(
                f"Service page rendered: service_id={service_id}, user={session.get('user')}, role={session.get('role')}"
            )
            return response
        else:
            return "Serviço não encontrado", 404
            
    except Exception as e:
        current_app.logger.exception(f"Erro service page: {e}")
        traceback.print_exc()
        return redirect(url_for('main.index'))

@main_bp.route('/service-click', methods=['POST'])
@login_required
def service_click():
    payload = request.get_json(silent=True) or {}
    service_id = payload.get('service_id')
    current_app.logger.info(
        f"Service card click: service_id={service_id}, user={session.get('user')}, role={session.get('role')}, department={session.get('department')}, ua={request.headers.get('User-Agent')}, ref={request.referrer}"
    )
    return jsonify({'success': True})

@main_bp.route('/service/<service_id>/log')
@login_required
def service_log(service_id):
    dept_map = {
        'cozinha': 'Cozinha',
        'principal': 'Principal',
        'manutencao': 'Manutenção',
        'restaurante_mirapraia': 'Cozinha',
        'governanca': 'Governança',
        'conferencias': 'Governança', 
        'financeiro': 'Principal',
        'rh': 'Principal'
    }
    dept = dept_map.get(service_id, 'Geral')
    return redirect(url_for('admin.department_log_view', department=dept))

@main_bp.route('/api/common/cep/<cep>')
@login_required
def validate_cep(cep):
    """
    Busca informações de CEP usando BrasilAPI com fallback para ViaCEP.
    """
    # Remove non-digits
    clean_cep = ''.join(filter(str.isdigit, cep))
    
    if len(clean_cep) != 8:
        return jsonify({'valid': False, 'message': 'CEP deve ter 8 dígitos.'})
        
    try:
        # 1. Try BrasilAPI (Usually faster and more complete)
        try:
            response = requests.get(f'https://brasilapi.com.br/api/cep/v2/{clean_cep}', timeout=3)
            if response.status_code == 200:
                data = response.json()
                return jsonify({
                    'valid': True,
                    'data': {
                        'zip': clean_cep,
                        'street': data.get('street', ''),
                        'neighborhood': data.get('neighborhood', ''),
                        'city': data.get('city', ''),
                        'state': data.get('state', ''),
                        'service': 'brasilapi'
                    }
                })
        except Exception:
            pass # Fallback
            
        # 2. Fallback to ViaCEP
        response = requests.get(f'https://viacep.com.br/ws/{clean_cep}/json/', timeout=3)
        if response.status_code == 200:
            data = response.json()
            if 'erro' not in data:
                return jsonify({
                    'valid': True,
                    'data': {
                        'zip': clean_cep,
                        'street': data.get('logradouro', ''),
                        'neighborhood': data.get('bairro', ''),
                        'city': data.get('localidade', ''),
                        'state': data.get('uf', ''),
                        'service': 'viacep'
                    }
                })
        
        return jsonify({'valid': False, 'message': 'CEP não encontrado.'})
            
    except Exception as e:
        current_app.logger.error(f"CEP Error: {e}")
        return jsonify({'valid': False, 'message': 'Erro ao consultar CEP.'})
