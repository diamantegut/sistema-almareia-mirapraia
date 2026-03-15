from flask import render_template, request, jsonify, redirect, url_for, session, flash, current_app, send_from_directory, Response
import os
import json
import traceback
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

from app.blueprints.hr import hr_bp
from app.services.time_tracking_service import (
    load_time_tracking_for_user,
    save_time_tracking_for_user,
    perform_time_tracking_action,
    get_user_by_qr_token,
    ensure_qr_token,
    _get_user_target_seconds,
    _format_seconds_hms
)
from app.services.user_service import (
    load_users, save_users, 
    load_ex_employees, save_ex_employees
)
from app.services.logger_service import LoggerService
from app.services.system_config_manager import BASE_DIR
from app.utils.decorators import login_required
from app.services import hr_service
from app.services import rh_service
from app.services.rh_service import (
    create_document, sign_document, 
    get_all_documents, get_user_documents, get_document_by_id
)

# --- Time Tracking / Kiosk Routes ---

@hr_bp.route('/time_tracking/action', methods=['POST'])
@login_required
def time_tracking_action():
    action = request.form.get('action')
    username = session.get('user')
    photo_data = request.form.get('photo_data')
    lat = request.form.get('latitude')
    lon = request.form.get('longitude')
    
    perform_time_tracking_action(username, action, photo_data, lat, lon)
    return redirect(url_for('main.index'))

@hr_bp.route('/kiosk')
def kiosk_mode():
    return render_template('kiosk.html')

@hr_bp.route('/kiosk/scan', methods=['POST'])
def kiosk_scan():
    data = request.get_json()
    token = data.get('token')
    
    username, user = get_user_by_qr_token(token)
    if not username:
        return jsonify({'valid': False, 'message': 'QR Code inválido'})
    
    # Get current status
    today = datetime.now().strftime('%Y-%m-%d')
    tracking_data = load_time_tracking_for_user(username)
    status = 'Não iniciado'
    if isinstance(tracking_data, dict) and 'days' in tracking_data and today in tracking_data['days']:
        status = tracking_data['days'][today]['status']
        
    return jsonify({
        'valid': True,
        'username': username,
        'name': username, 
        'status': status
    })

@hr_bp.route('/kiosk/action', methods=['POST'])
def kiosk_action():
    data = request.get_json()
    token = data.get('token')
    action = data.get('action')
    photo_data = data.get('photo_data')
    lat = data.get('latitude')
    lon = data.get('longitude')
    
    username, user = get_user_by_qr_token(token)
    if not username:
        return jsonify({'success': False, 'message': 'Usuário não identificado'})
        
    try:
        perform_time_tracking_action(username, action, photo_data, lat, lon)
        return jsonify({'success': True})
    except Exception as e:
        print(f"Kiosk Action Error: {e}")
        return jsonify({'success': False, 'message': str(e)})

@hr_bp.route('/admin/generate_qr/<username>', methods=['POST'])
@login_required
def generate_qr_token(username):
    # Check admin
    curr_user = session.get('user')
    users = load_users()
    
    if users.get(curr_user, {}).get('role') != 'admin':
         return "Unauthorized", 403
         
    token = ensure_qr_token(username)
    return jsonify({'success': True, 'token': token})

# --- HR Management Routes ---

@hr_bp.route('/hr/dashboard')
@login_required
def hr_dashboard():
    # Check permissions (Admin or RH)
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    employees = hr_service.get_all_employees()
    return render_template('hr_dashboard.html', employees=employees)

@hr_bp.route('/hr/employee/<username>', methods=['GET', 'POST'])
@login_required
def hr_employee_detail(username):
    # Check permissions
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        # Handle profile update
        hr_service.update_employee_hr_data(username, request.form.to_dict())
        flash('Dados atualizados com sucesso.')
        return redirect(url_for('hr.hr_employee_detail', username=username))
    
    employee = hr_service.get_employee_details(username)
    if not employee:
        # Check if ex-employee? For now just redirect
        flash('Funcionário não encontrado.')
        return redirect(url_for('hr.hr_dashboard'))
        
    documents = hr_service.list_employee_documents(username)
    epis = hr_service.get_employee_epis(username)
    inventory = hr_service.get_inventory()
    
    return render_template('hr_employee_detail.html', employee=employee, documents=documents, epis=epis, inventory=inventory, companies=hr_service.COMPANIES, contract_types=hr_service.CONTRACT_TYPES)

@hr_bp.route('/hr/employee/hire', methods=['GET', 'POST'])
@login_required
def hr_hire_employee():
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Basic
        basic_info = {
            'full_name': request.form.get('full_name'),
            'admission_date': request.form.get('admission_date'),
            'birthday': request.form.get('birthday'),
            'role': request.form.get('role', 'colaborador')
        }
        # HR
        hr_info = {
            'cpf': request.form.get('cpf'),
            'rg': request.form.get('rg'),
            'address': request.form.get('address'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'company': request.form.get('company'),
            'contract_type': request.form.get('contract_type'),
            'shirt_size': request.form.get('shirt_size'),
            'shoe_size': request.form.get('shoe_size'),
            'pants_size': request.form.get('pants_size')
        }
        
        success, msg = hr_service.hire_employee(username, password, basic_info, hr_info)
        if success:
            flash(msg)
            return redirect(url_for('hr.hr_employee_detail', username=username))
        else:
            flash(msg)
            
    return render_template('hr_hire.html', companies=hr_service.COMPANIES, contract_types=hr_service.CONTRACT_TYPES)

@hr_bp.route('/hr/upload/<username>', methods=['POST'])
@login_required
def hr_upload_document(username):
    # Perms
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        return 'Unauthorized', 403
        
    if 'file' not in request.files:
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('hr.hr_employee_detail', username=username))
        
    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.')
        return redirect(url_for('hr.hr_employee_detail', username=username))
        
    if file:
        filename = secure_filename(file.filename)
        hr_service.save_employee_document(username, file, filename, 'general')
        flash('Arquivo enviado com sucesso.')
        
    return redirect(url_for('hr.hr_employee_detail', username=username))

@hr_bp.route('/hr/download/<username>/<filename>')
@login_required
def hr_download_document(username, filename):
    # Perms
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    # Also allow the user themselves? Maybe later.
    
    if not is_admin and not is_rh:
         return 'Unauthorized', 403
         
    directory = os.path.join(current_app.root_path, 'static', 'uploads', 'hr', username)
    return send_from_directory(directory, filename)

@hr_bp.route('/hr/epis', methods=['GET', 'POST'])
@login_required
def hr_epis():
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    if request.method == 'POST':
        # Add new EPI Type
        name = request.form.get('name')
        epi_type = request.form.get('type')
        stock = request.form.get('stock')
        validity = request.form.get('validity')
        hr_service.add_epi_item(name, epi_type, stock, validity)
        flash('EPI adicionado ao catálogo.')
        
    inventory = hr_service.get_inventory()
    return render_template('hr_epis.html', inventory=inventory)

@hr_bp.route('/hr/epis/assign', methods=['POST'])
@login_required
def hr_assign_epi():
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    username = request.form.get('username')
    epi_id = request.form.get('epi_id')
    quantity = int(request.form.get('quantity', 1))
    
    success, msg = hr_service.assign_epi(username, epi_id, quantity)
    flash(msg)
    
    # Redirect back to where? Employee detail or EPI page?
    referer = request.headers.get("Referer")
    if referer:
        return redirect(referer)
    return redirect(url_for('hr.hr_epis'))

@hr_bp.route('/rh/dismiss/<username>', methods=['GET', 'POST'])
@login_required
def rh_dismiss_employee(username):
    # Allow Admin AND RH users
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    users = load_users()
    if username not in users:
        flash('Usuário não encontrado.')
        return redirect(url_for('admin.admin_users'))

    if request.method == 'POST':
        reason = request.form.get('reason')
        dismissal_date = request.form.get('dismissal_date')
        observations = request.form.get('observations')
        
        ex_employees = load_ex_employees()
        
        user_data = users[username]
        user_data['username'] = username
        user_data['dismissal_info'] = {
            'reason': reason,
            'date': dismissal_date,
            'observations': observations,
            'dismissed_by': session.get('user')
        }
        
        ex_employees.append(user_data)
        save_ex_employees(ex_employees)
        
        del users[username]
        save_users(users)
        
        LoggerService.log_acao(
            acao='Demitir Funcionário',
            entidade='Recursos Humanos',
            detalhes={
                'username': username,
                'reason': reason,
                'date': dismissal_date,
                'observations': observations
            },
            departamento_id='Recursos Humanos',
            colaborador_id=session.get('user', 'Sistema')
        )
        
        flash(f'Funcionário {username} demitido com sucesso.')
        return redirect(url_for('hr.rh_ex_employees'))
        
    return render_template('dismiss_employee.html', user=users[username], username=username)

@hr_bp.route('/rh/ex_employees')
@login_required
def rh_ex_employees():
    # Allow Admin AND RH users
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    ex_employees = load_ex_employees()
    return render_template('ex_employees.html', ex_employees=ex_employees, is_admin=is_admin)

@hr_bp.route('/rh/ex_employees/delete/<username>', methods=['POST'])
@login_required
def rh_delete_ex_employee(username):
    # ONLY ADMIN can delete permanently
    if session.get('role') != 'admin':
        flash('Acesso restrito à Diretoria.')
        return redirect(url_for('hr.rh_ex_employees'))
        
    ex_employees = load_ex_employees()
    new_list = [ex for ex in ex_employees if ex.get('username') != username]
    
    if len(new_list) < len(ex_employees):
        save_ex_employees(new_list)
        
        # LOG: Ex-Employee Deleted
        LoggerService.log_acao(
            acao=f"Excluiu registro de ex-funcionário {username}",
            entidade="RH",
            detalhes={'username': username},
            nivel_severidade='CRÍTICO'
        )
        
        flash(f'Ex-funcionário {username} excluído definitivamente.')
    else:
        flash('Usuário não encontrado.')
        
    return redirect(url_for('hr.rh_ex_employees'))

@hr_bp.route('/rh/timesheet', methods=['GET'])
@login_required
def rh_timesheet():
    if session.get('role') != 'admin' and session.get('department') != 'rh':
        flash('Acesso restrito.')
        # Assuming service_page uses 'rh' ID for HR page
        return redirect(url_for('main.service_page', service_id='rh'))
        
    users_dict = load_users()
    users_list = []
    for uname, udata in users_dict.items():
        users_list.append({
            'username': uname,
            'full_name': udata.get('full_name', uname)
        })
    users_list.sort(key=lambda x: x['full_name'])
    
    selected_user = request.args.get('username')
    month_str = request.args.get('month') # YYYY-MM
    
    if not month_str:
        month_str = datetime.now().strftime('%Y-%m')
        
    report_data = []
    total_worked = 0
    total_target = 0
    balance_seconds = 0
    bank_total_seconds = 0
    
    selected_user_name = ""
    selected_month_display = ""
    
    if selected_user:
        if selected_user in users_dict:
            selected_user_name = users_dict[selected_user].get('full_name', selected_user)
        else:
            selected_user_name = selected_user
            
        try:
            year, month = map(int, month_str.split('-'))
            start_date = datetime(year, month, 1)
            # Last day of month
            if month == 12:
                end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1) - timedelta(days=1)
            
            selected_month_display = start_date.strftime('%B/%Y')
            
            tt_data = load_time_tracking_for_user(selected_user)
            days_data = tt_data.get('days', {}) if isinstance(tt_data, dict) else {}
            
            # Iterate all days in month
            curr = start_date
            while curr <= end_date:
                day_str = curr.strftime('%Y-%m-%d')
                day_record = days_data.get(day_str, {})
                
                # Get target (from record or calc)
                target_sec = day_record.get('target_seconds')
                is_day_off = day_record.get('is_day_off')
                
                if target_sec is None:
                    target_sec, _, is_day_off = _get_user_target_seconds(selected_user, curr)
                
                worked_sec = day_record.get('accumulated_seconds', 0)
                status = day_record.get('status', 'Não iniciado')
                
                # If day is in future, target should be 0 unless it's today or past?
                # Usually target counts for past days. For today, it counts. Future days ignore.
                if curr.date() > datetime.now().date():
                    daily_balance = 0
                    target_sec = 0 # Don't count target for future
                else:
                    daily_balance = worked_sec - target_sec
                
                # Events for start/end
                events = day_record.get('events', [])
                first_start = ""
                last_end = ""
                if events:
                    starts = [e['time'] for e in events if e['type'] == 'start']
                    ends = [e['time'] for e in events if e['type'] == 'end']
                    if starts:
                        try:
                            first_start = datetime.fromisoformat(starts[0]).strftime('%H:%M')
                        except: pass
                    if ends:
                        try:
                            last_end = datetime.fromisoformat(ends[-1]).strftime('%H:%M')
                        except: pass
                    elif status == 'Trabalhando':
                        last_end = "..."
                
                report_data.append({
                    'date_formatted': curr.strftime('%d/%m/%Y'),
                    'weekday_name': ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'][curr.weekday()],
                    'status': status,
                    'first_start': first_start,
                    'last_end': last_end,
                    'worked_hms': _format_seconds_hms(worked_sec),
                    'target_hms': _format_seconds_hms(target_sec),
                    'balance_seconds': daily_balance,
                    'balance_hms': _format_seconds_hms(daily_balance),
                    'is_day_off': is_day_off
                })
                
                total_worked += worked_sec
                total_target += target_sec
                balance_seconds += daily_balance
                
                curr += timedelta(days=1)
                
            # Bank Total (All time)
            for d_str, d_rec in days_data.items():
                if d_rec.get('status') == 'Finalizado':
                    w = d_rec.get('accumulated_seconds', 0)
                    t = d_rec.get('target_seconds', 0)
                    if t is None: # fallback
                         try:
                             dt = datetime.strptime(d_str, '%Y-%m-%d')
                             t, _, _ = _get_user_target_seconds(selected_user, dt)
                         except: t=0
                    bank_total_seconds += (w - t)
                    
        except ValueError:
            pass
            
    return render_template('rh_timesheet.html',
                           users=users_list,
                           selected_user=selected_user,
                           selected_month=month_str,
                           report_data=report_data,
                           selected_user_name=selected_user_name,
                           selected_month_display=selected_month_display,
                           total_worked=_format_seconds_hms(total_worked),
                           total_target=_format_seconds_hms(total_target),
                           total_balance=_format_seconds_hms(balance_seconds),
                           balance_seconds=balance_seconds,
                           bank_total=_format_seconds_hms(bank_total_seconds),
                           bank_seconds=bank_total_seconds)

@hr_bp.route('/rh/documents', methods=['GET', 'POST'])
@login_required
def rh_documents():
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    user = session.get('user')
    
    users = load_users()
    
    if request.method == 'POST':
        if not is_rh:
             flash('Apenas RH pode enviar documentos.')
             return redirect(url_for('hr.rh_documents'))
             
        title = request.form.get('title')
        assigned_to = request.form.get('assigned_to')
        file = request.files.get('file')
        
        if file and file.filename.lower().endswith('.pdf'):
            filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
            upload_folder = os.path.join(BASE_DIR, 'static', 'uploads', 'rh_documents')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            file.save(os.path.join(upload_folder, filename))
            
            create_document(title, filename, user, assigned_to)
            flash('Documento enviado com sucesso.')
            return redirect(url_for('hr.rh_documents'))
        else:
            flash('Erro: Envie um arquivo PDF válido.')
            
    if is_rh:
        documents = get_all_documents()
    else:
        documents = get_user_documents(user)
        
    return render_template('rh_documents.html', documents=documents, is_rh=is_rh, users=users.keys())

@hr_bp.route('/rh/document/<doc_id>', methods=['GET'])
@login_required
def rh_view_document(doc_id):
    doc = get_document_by_id(doc_id)
    if not doc:
        flash('Documento não encontrado.')
        return redirect(url_for('hr.rh_documents'))
        
    user = session.get('user')
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    
    if doc['assigned_to'] != user and not is_rh and not is_admin:
        flash('Acesso negado.')
        return redirect(url_for('hr.rh_documents'))
        
    return render_template('rh_view_document.html', doc=doc)

@hr_bp.route('/rh/document/<doc_id>/sign', methods=['POST'])
@login_required
def rh_sign_document(doc_id):
    data = request.get_json()
    signature_data = data.get('signature')
    
    if not signature_data:
        return jsonify({'success': False, 'message': 'Assinatura vazia.'})
        
    success, message = sign_document(doc_id, signature_data, session.get('user'))
    return jsonify({'success': success, 'message': message})
from app.services import assinafy_service

@hr_bp.route('/api/assinafy/register-signer', methods=['POST'])
@login_required
def api_register_signer():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Usuário não autenticado.'})
    
    users = load_users()
    user_data = users.get(session['user'])
    
    if not user_data:
        return jsonify({'success': False, 'error': 'Dados do usuário não encontrados.'})
    
    # Get required fields
    full_name = user_data.get('full_name') or session['user']
    email = user_data.get('email')
    phone = user_data.get('phone')
    
    if not email:
        return jsonify({'success': False, 'error': 'E-mail não cadastrado para este usuário. Entre em contato com o RH.'})
        
    # Call Assinafy Service
    result = assinafy_service.create_signer(full_name, email, phone)
    
    if "error" in result:
        return jsonify({'success': False, 'error': result["error"]})
        
    return jsonify({'success': True, 'data': result})
