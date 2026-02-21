from flask import render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app, send_file
import os
import sys
import json
import io
import time
import threading
import subprocess
import pandas as pd
from datetime import datetime
from . import admin_bp
from app.utils.decorators import login_required
from app.services.logger_service import LoggerService
from app.services.system_config_manager import DEPARTMENTS
from app.services.data_service import load_users, save_users, load_ex_employees, normalize_text
from app.services.rh_service import load_reset_requests
from app.services.backup_service import backup_service
from app.services.logging_service import get_logs, export_logs_to_csv
from app.services.monitor_service import check_backup_health, load_system_alerts, get_latest_alerts
from app.services.security_service import load_alerts, load_security_settings, save_security_settings, update_alert_status
from app.services.system_config_manager import get_backup_path

# --- Helpers ---

def _parse_weekly_day_off(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return 6 # Sunday default

# --- Routes ---

@admin_bp.route('/admin/api/backups/config', methods=['POST'])
@login_required
def api_update_backup_config():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    backup_type = data.get('type')
    interval = data.get('interval')
    retention = data.get('retention')
    retention_unit = data.get('retention_unit', 'hours')
    
    if not backup_type:
        return jsonify({'error': 'Missing backup type'}), 400
        
    success, msg = backup_service.update_config(backup_type, interval, retention, retention_unit)
    
    if success:
        LoggerService.log_acao(
            acao=f"Configuração de Backup Atualizada ({backup_type})",
            entidade="Backup",
            detalhes={'type': backup_type, 'interval': interval, 'retention': retention, 'unit': retention_unit},
            nivel_severidade='INFO'
        )
        return jsonify({'success': True, 'message': msg})
    else:
        return jsonify({'success': False, 'error': msg})

@admin_bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    # Allow Admin AND RH users (Department 'Recursos Humanos' or Permission 'rh')
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    users = load_users()
    
    # Define services (Assuming services are passed to template, need to load or define them)
    # Looking at original code, 'services' variable was used in render_template but not defined in the snippet I saw.
    # It might be defined globally or I missed it. I will define a basic list or load from somewhere if possible.
    # Usually services = ['Restaurante', 'Recepção', etc.]
    # For now, I'll check if I can omit it or define a default.
    services = ['Restaurante', 'Recepção', 'Cozinha', 'Governança', 'Manutenção', 'Estoque', 'RH', 'Financeiro']

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'edit':
            username = request.form.get('username')
            if username in users:
                # Rename Logic
                new_username = request.form.get('new_username')
                renamed = False
                if new_username and new_username != username:
                    # Basic Validation
                    if new_username in users:
                        flash(f'Erro: O usuário "{new_username}" já existe.')
                        return redirect(url_for('admin.admin_users'))
                    
                    # Check Ex-Employees
                    try:
                        ex_employees = load_ex_employees()
                        if any(ex.get('username') == new_username for ex in ex_employees):
                            flash(f'Erro: O usuário "{new_username}" é um ex-funcionário.')
                            return redirect(url_for('admin.admin_users'))
                    except:
                        pass
                        
                    # Rename
                    users[new_username] = users.pop(username)
                    old_username = username
                    username = new_username
                    renamed = True
                    
                    # Log Rename
                    LoggerService.log_acao(
                        acao=f"Renomeou usuário {old_username} para {new_username}",
                        entidade="Usuários",
                        detalhes={
                            'old_username': old_username,
                            'new_username': new_username
                        },
                        nivel_severidade='WARNING',
                        departamento_id='RH',
                        colaborador_id=session.get('user', 'Sistema')
                    )
                    
                    flash(f'Usuário renomeado com sucesso.')

                users[username]['password'] = request.form.get('password')
                
                # Role and Department Logic
                new_role = request.form.get('role')
                if is_admin:
                    users[username]['role'] = new_role
                else:
                    new_role = users[username].get('role') # Keep existing if not admin

                if new_role == 'admin':
                     users[username]['department'] = '' # Diretoria has no department
                else:
                    users[username]['department'] = request.form.get('department')
                    
                # Other fields
                users[username]['full_name'] = request.form.get('full_name', '')
                users[username]['admission_date'] = request.form.get('admission_date', '')
                users[username]['birthday'] = request.form.get('birthday', '')
                
                raw_score = request.form.get('score', 0)
                try:
                    score_int = int(raw_score)
                except (TypeError, ValueError):
                    score_int = 0
                users[username]['score'] = score_int
                
                raw_target = request.form.get('daily_target_hours', 8)
                try:
                    target_hours = int(raw_target)
                except (TypeError, ValueError):
                    target_hours = 8
                if target_hours not in (7, 8):
                    target_hours = 8
                users[username]['daily_target_hours'] = target_hours

                users[username]['weekly_day_off'] = _parse_weekly_day_off(
                    request.form.get('weekly_day_off', users[username].get('weekly_day_off', 6))
                )
                
                # Handle Permissions
                permissions = request.form.getlist('permissions')
                users[username]['permissions'] = permissions
                
                save_users(users)
                
                # LOG: User Updated
                LoggerService.log_acao(
                    acao=f"Atualizou usuário {username}",
                    entidade="Usuários",
                    detalhes={
                        'username': username,
                        'department': users[username].get('department'),
                        'role': users[username].get('role'),
                        'updated_fields': ['permissions', 'daily_target_hours', 'weekly_day_off', 'score']
                    },
                    nivel_severidade='INFO'
                )
                
                if not renamed:
                    flash(f'Usuário {username} atualizado com sucesso.')
                
                if renamed:
                     return redirect('/service/rh')
                
        elif action == 'add':
            username = request.form.get('username')
            if username in users:
                flash('Usuário já existe.')
            else:
                # Check if ex-employee
                ex_employees = load_ex_employees()
                is_ex = False
                for ex in ex_employees:
                    if ex.get('username') == username:
                        is_ex = True
                        break
                
                if is_ex:
                    flash('Usuário consta como Ex-Funcionário. Impossível recadastrar.')
                else:
                    role = request.form.get('role', 'colaborador')
                    dept = request.form.get('department')
                    
                    if role == 'admin':
                        dept = '' # Diretoria has no department
                        
                    raw_score = request.form.get('score', 0)
                    try:
                        score_int = int(raw_score)
                    except (TypeError, ValueError):
                        score_int = 0
                    if role != 'admin':
                        if score_int == 5:
                            role = 'gerente'
                        elif score_int == 4:
                            role = 'supervisor'
                    users[username] = {
                        'password': request.form.get('password'),
                        'department': dept,
                        'role': role,
                        'score': score_int,
                        'permissions': request.form.getlist('permissions'),
                        'full_name': request.form.get('full_name', ''),
                        'admission_date': request.form.get('admission_date', ''),
                        'birthday': request.form.get('birthday', '')
                    }
                    raw_target = request.form.get('daily_target_hours', 8)
                    try:
                        target_hours = int(raw_target)
                    except (TypeError, ValueError):
                        target_hours = 8
                    if target_hours not in (7, 8):
                        target_hours = 8
                    users[username]['daily_target_hours'] = target_hours
                    users[username]['weekly_day_off'] = _parse_weekly_day_off(request.form.get('weekly_day_off', 6))
                    save_users(users)
                    
                    # LOG: User Created
                    LoggerService.log_acao(
                        acao=f"Criou novo usuário {username}",
                        entidade="Usuários",
                        detalhes={
                            'username': username,
                            'role': role,
                            'department': dept
                        },
                        nivel_severidade='INFO'
                    )

                    flash(f'Usuário {username} criado com sucesso.')
                
        elif action == 'delete':
            # BLOCKED FOR ACTIVE USERS
            flash('Ação não permitida. Para excluir, o usuário deve ser demitido primeiro.')
        
        return_url = request.form.get('return_url')
        if return_url:
            return redirect(return_url)
        return redirect(url_for('admin.admin_users'))
        
    # Organizar usuários por departamento para exibição
    dept_groups = []
    
    # 0. Diretoria (Sem Departamento)
    diretoria_users = {u: d for u, d in users.items() if d.get('role') == 'admin'}
    if diretoria_users:
        dept_groups.append({'name': 'Diretoria', 'users': diretoria_users})
        
    # 1. Departamentos oficiais na ordem
    for dept in DEPARTMENTS:
        # Case insensitive match. EXCLUDE ADMINS (already in Diretoria)
        group_users = {u: d for u, d in users.items() 
                       if d.get('department') and normalize_text(str(d.get('department'))) == normalize_text(dept) and d.get('role') != 'admin'}
        if group_users:
             dept_groups.append({'name': dept, 'users': group_users})
    
    # 2. Outros / Sem departamento
    dept_names_normalized = [normalize_text(d) for d in DEPARTMENTS]
    other_users = {u: d for u, d in users.items() 
                   if (not d.get('department') or normalize_text(str(d.get('department'))) not in dept_names_normalized) and d.get('role') != 'admin'}
    if other_users:
        dept_groups.append({'name': 'Outros / Sem Departamento', 'users': other_users})

    # Load password requests
    password_requests = load_reset_requests()
    # Filter only pending
    password_requests = [r for r in password_requests if r.get('status') == 'pending']

    return render_template('admin_users.html', 
                           users=users, 
                           dept_groups=dept_groups, 
                           departments=DEPARTMENTS, 
                           services=services, 
                           is_admin=is_admin, 
                           is_rh=is_rh,
                           password_requests=password_requests)

@admin_bp.route('/admin/users/export')
@login_required
def admin_export_users():
    # Permission check
    is_admin = session.get('role') == 'admin'
    is_rh = session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', [])
    
    if not is_admin and not is_rh:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    try:
        users = load_users()
        data_list = []
        
        for username, data in users.items():
            # Calculate status (active if in users.json)
            status = "Ativo"
            
            # Format permissions
            perms = ", ".join(data.get('permissions', []))
            
            # Weekly day off mapping
            days_map = {0: 'Segunda', 1: 'Terça', 2: 'Quarta', 3: 'Quinta', 4: 'Sexta', 5: 'Sábado', 6: 'Domingo'}
            try:
                day_off_val = int(data.get('weekly_day_off', 6))
            except:
                day_off_val = 6
            day_off = days_map.get(day_off_val, 'Domingo')
            
            data_list.append({
                'Login': username,
                'Nome Completo': data.get('full_name', ''),
                'Departamento': data.get('department', ''),
                'Cargo': data.get('role', '').title(),
                'Email': data.get('email', ''),
                'Telefone': data.get('phone', ''),
                'Data Admissão': data.get('admission_date', ''),
                'Aniversário': data.get('birthday', ''),
                'Pontuação': data.get('score', 0),
                'Folga Semanal': day_off,
                'Permissões': perms,
                'Status': status
            })
            
        df = pd.DataFrame(data_list)
        
        # Output to BytesIO
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Colaboradores', index=False)
            
            # Get workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Colaboradores']
            
            # Add header format
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            
            # Apply format to headers
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                
            # Auto-adjust column width (approximate)
            for i, col in enumerate(df.columns):
                # Find max length of column content
                max_len = max(
                    df[col].astype(str).map(len).max(),
                    len(col)
                ) + 2
                worksheet.set_column(i, i, max_len)
                
            # Add AutoFilter
            worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
                
        output.seek(0)
        
        filename = f"colaboradores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        current_app.logger.error(f"Erro ao exportar usuários: {e}")
        flash(f'Erro ao gerar arquivo de exportação: {str(e)}')
        return redirect(url_for('admin.admin_users'))

@admin_bp.route('/admin/restart', methods=['POST'])
@login_required
def admin_restart():
    if session.get('role') != 'admin':
        flash('Acesso restrito à Diretoria.')
        return redirect(url_for('main.index'))
    
    def restart_server():
        time.sleep(1) # Give time for the response to reach the client
        print("Restarting...")
        try:
            with open("restart_debug.log", "a") as f:
                f.write(f"Restarting at {datetime.now()}\n")
            
            # Use current_app to locate main script? Or just sys.argv[0]
            # sys.argv[0] is usually correct for the main entry point
            script = os.path.abspath(sys.argv[0])
            
            # Use a delayed restart mechanism to ensure port 5000 is released
            # We spawn a temporary python process that waits 5 seconds then starts the app
            restart_code = f"""
import time
import subprocess
import sys
import os

print("Waiting for server to shutdown and port to release...")
time.sleep(5)
print("Starting server...")
subprocess.Popen([sys.executable, r"{script}"], creationflags=subprocess.CREATE_NEW_CONSOLE)
"""
            # Start the delayed restarter
            subprocess.Popen([sys.executable, '-c', restart_code], creationflags=subprocess.CREATE_NEW_CONSOLE)
            
            # Kill current process
            os._exit(0)
        except Exception as e:
            with open("restart_debug.log", "a") as f:
                f.write(f"Restart failed: {e}\n")

    flash('Servidor reiniciando... Aguarde alguns instantes.')
    
    # Run restart in a separate thread to allow this request to complete
    threading.Thread(target=restart_server).start()
    
    return redirect(url_for('main.index'))

@admin_bp.route('/department/log')
@login_required
def department_log_view():
    user_dept = session.get('department')
    # Admin can view any department (passed as query param, defaults to 'Geral')
    if session.get('role') == 'admin':
        target_dept = request.args.get('department', 'Geral')
    else:
        target_dept = user_dept
        
    return render_template('department_log.html', department_id=target_dept)

@admin_bp.route('/api/logs/department/<department_id>')
@login_required
def get_department_logs(department_id):
    # Security check: User must be admin, or belong to the department
    user_role = session.get('role')
    user_dept = session.get('department')
    
    # Allow admin to view any. Allow user to view their own.
    if user_role != 'admin' and user_dept != department_id:
        return jsonify({'error': 'Acesso negado'}), 403
        
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        filters = {}
        if request.args.get('start_date'):
            filters['start_date'] = request.args.get('start_date')
        if request.args.get('end_date'):
            filters['end_date'] = request.args.get('end_date')
        if request.args.get('action_type'):
            filters['action_type'] = request.args.get('action_type')
        if request.args.get('user'):
            filters['user'] = request.args.get('user')
            
        result = LoggerService.get_logs(
            department_id=department_id,
            page=page,
            per_page=per_page,
            filters=filters
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/api/admin/trigger_backup', methods=['POST'])
@login_required
def trigger_backup():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Acesso negado. Apenas administradores podem realizar backups.'}), 403
    
    try:
        # Script path - using the one in the project root
        script_path = os.path.join(current_app.root_path, 'backup_system.ps1')
        
        # Verify script exists
        if not os.path.exists(script_path):
             return jsonify({'success': False, 'message': 'Script de backup não encontrado no servidor.'}), 500
        
        # Execute PowerShell script
        result = subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # Success
            LoggerService.log_acao(
                acao="Backup Manual Executado",
                entidade="Sistema",
                detalhes={"status": "success", "output": result.stdout[-200:]}, # Log last 200 chars of output
                nivel_severidade="INFO"
            )
            return jsonify({'success': True, 'message': 'Backup realizado com sucesso!'})
        else:
            # Failure
            error_msg = result.stderr if result.stderr else result.stdout
            LoggerService.log_acao(
                acao="Falha em Backup Manual",
                entidade="Sistema",
                detalhes={"status": "error", "error": error_msg[-200:] if error_msg else "Unknown error"},
                nivel_severidade="CRITICO"
            )
            return jsonify({'success': False, 'message': 'Erro ao executar backup. Verifique os logs.'}), 500
            
    except Exception as e:
        LoggerService.log_acao(
            acao="Erro em Backup Manual",
            entidade="Sistema",
            detalhes={"status": "exception", "error": str(e)},
            nivel_severidade="CRITICO"
        )
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'}), 500

@admin_bp.route('/logs')
@login_required
def view_logs():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    # Handle DEPARTMENTS being a list or a dictionary
    if isinstance(DEPARTMENTS, dict):
        dept_list = list(DEPARTMENTS.keys())
    elif isinstance(DEPARTMENTS, list):
        dept_list = DEPARTMENTS
    else:
        dept_list = [] # Fallback
        
    return render_template('admin_logs.html', today=datetime.now().strftime('%Y-%m-%d'), departments=dept_list)

@admin_bp.route('/api/admin/logs/search')
@login_required
def api_search_logs():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        # Filters
        department_id = request.args.get('department')
        if department_id == 'all': department_id = None
        
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search_query = request.args.get('search')
        severity = request.args.get('severity')
        
        colaborador_id = request.args.get('user')
        
        # Call LoggerService
        result = LoggerService.get_logs(
            departamento_id=department_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
            search_query=search_query,
            colaborador_id=colaborador_id,
            nivel_severidade=severity
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/api/admin/logs/export')
@login_required
def api_export_logs_unified():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        department_id = request.args.get('department')
        if department_id == 'all': department_id = None
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search_query = request.args.get('search')
        severity = request.args.get('severity')
        
        # Fetch all (high limit)
        result = LoggerService.get_logs(
            departamento_id=department_id,
            start_date=start_date,
            end_date=end_date,
            page=1,
            per_page=10000, # Limit export to 10k rows for safety
            search_query=search_query,
            nivel_severidade=severity
        )
        
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Data/Hora', 'Severidade', 'Departamento', 'Usuário', 'Ação', 'Entidade', 'Detalhes'])
        
        for log in result['items']:
            writer.writerow([
                log.get('timestamp'),
                log.get('nivel_severidade'),
                log.get('departamento_id'),
                log.get('colaborador_id'),
                log.get('acao'),
                log.get('entidade'),
                json.dumps(log.get('detalhes', {}), ensure_ascii=False)
            ])
            
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=logs_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/admin/backups')
@login_required
def admin_backups_view():
    if session.get('role') != 'admin':
        return redirect(url_for('main.index'))
    return render_template('admin_backups.html')

@admin_bp.route('/admin/api/backups/list/<backup_type>')
@login_required
def api_list_backups(backup_type):
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    backups = backup_service.list_backups(backup_type)
    return jsonify(backups)

@admin_bp.route('/admin/api/backups/trigger', methods=['POST'])
@login_required
def api_trigger_backup_service():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    backup_type = data.get('type')
    
    if not backup_type:
        return jsonify({'error': 'Missing type'}), 400
        
    success, msg = backup_service.trigger_backup(backup_type)
    
    if success:
        return jsonify({'success': True, 'message': msg})
    else:
        return jsonify({'success': False, 'error': msg})

@admin_bp.route('/admin/api/backups/restore', methods=['POST'])
@login_required
def api_restore_backup():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    backup_type = data.get('type')
    filename = data.get('filename')
    
    if not backup_type or not filename:
        return jsonify({'error': 'Missing data'}), 400
        
    success, msg = backup_service.restore_backup(backup_type, filename)
    
    if success:
        # Log Restore
        LoggerService.log_acao(
            acao=f"Restore de Backup ({backup_type})",
            entidade="Backup",
            detalhes={'filename': filename, 'type': backup_type},
            nivel_severidade='CRITICO'
        )
        return jsonify({'success': True, 'message': msg})
    else:
        return jsonify({'success': False, 'error': msg})

@admin_bp.route('/admin')
@admin_bp.route('/admin/dashboard')
@admin_bp.route('/admin/system/dashboard')
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('main.index'))
    
    # System Stats (Mock or Real)
    system_stats = {
        'cpu_load': 15, # Mock
        'memory_usage': 45, # Mock
        'disk_usage': 60, # Mock
        'uptime': '3d 12h' # Mock
    }
    
    # Backup Health
    backup_health = check_backup_health(get_backup_path('Sistema_Completo'))
    
    # Recent Alerts
    recent_alerts = get_latest_alerts(limit=5)
    
    return render_template('admin_dashboard.html', 
                           stats=system_stats, 
                           backup_health=backup_health, 
                           alerts=recent_alerts)

@admin_bp.route('/admin/security/dashboard')
@login_required
def admin_security_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('main.index'))
        
    alerts = load_alerts()
    # Sort by priority/date
    alerts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    settings = load_security_settings()
    
    return render_template('admin_security_dashboard.html', alerts=alerts, settings=settings)

@admin_bp.route('/admin/security/resolve/<alert_id>', methods=['POST'])
@login_required
def resolve_security_alert(alert_id):
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
        
    success = update_alert_status(alert_id, 'resolved', session.get('user'))
    return jsonify({'success': success})

@admin_bp.route('/admin/security/settings', methods=['POST'])
@login_required
def admin_security_settings():
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
        
    data = request.json
    save_security_settings(data)
    return jsonify({'success': True})

from app.services.printer_manager import load_printers, save_printers, load_printer_settings, save_printer_settings
from app.services.printing_service import test_printer_connection
from app.services.data_service import load_menu_items, save_menu_items
from app.services.fiscal_service import load_fiscal_settings, save_fiscal_settings, FiscalPoolService, get_access_token, get_fiscal_integration, download_xml
from app.services.system_config_manager import get_data_path

@admin_bp.route('/config/printers', methods=['GET', 'POST'])
@login_required
def printers_config():
    if session.get('role') not in ['admin', 'gerente']:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    printers = load_printers()
    printer_settings = load_printer_settings()
    
    # Load menu items for category mapping
    menu_items = load_menu_items()
    categories = set()
    for item in menu_items:
        if item.get('category'):
            categories.add(item['category'])
    
    category_map = []
    # Build map structure: [{name: 'Bebidas', item_count: 10, current_printer_id: '123'}]
    # We need to scan items to see assigned printers
    for cat in sorted(list(categories)):
        cat_items = [i for i in menu_items if i.get('category') == cat]
        count = len(cat_items)
        
        # Determine common printer
        printer_ids = set()
        for i in cat_items:
            if i.get('printer_id'):
                printer_ids.add(i['printer_id'])
        
        current_pid = None
        if len(printer_ids) == 1:
            current_pid = list(printer_ids)[0]
        elif len(printer_ids) > 1:
            current_pid = 'mixed'
            
        category_map.append({
            'name': cat,
            'item_count': count,
            'current_printer_id': current_pid
        })
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            name = request.form.get('name')
            ptype = request.form.get('type') # windows/network
            
            new_printer = {
                'id': str(datetime.now().timestamp()),
                'name': name,
                'type': ptype,
                'status': 'active'
            }
            
            if ptype == 'windows':
                new_printer['windows_name'] = request.form.get('windows_name')
            else:
                new_printer['ip'] = request.form.get('ip')
                new_printer['port'] = request.form.get('port', 9100)
            
            if name:
                printers.append(new_printer)
                save_printers(printers)
                flash('Impressora adicionada.')
                
        elif action == 'edit':
            p_id = request.form.get('printer_id')
            for p in printers:
                if str(p['id']) == str(p_id):
                    p['name'] = request.form.get('name')
                    p['type'] = request.form.get('type')
                    
                    if p['type'] == 'windows':
                        p['windows_name'] = request.form.get('windows_name')
                        p.pop('ip', None)
                        p.pop('port', None)
                    else:
                        p['ip'] = request.form.get('ip')
                        p['port'] = request.form.get('port', 9100)
                        p.pop('windows_name', None)
                    break
            save_printers(printers)
            flash('Impressora atualizada.')

        elif action == 'delete':
            p_id = request.form.get('printer_id')
            printers = [p for p in printers if str(p.get('id')) != str(p_id)]
            save_printers(printers)
            flash('Impressora removida.')
            
        elif action == 'test':
            p_id = request.form.get('printer_id')
            printer = next((p for p in printers if str(p.get('id')) == str(p_id)), None)
            if printer:
                success, msg = test_printer_connection(printer)
                if success:
                    flash(f'Teste enviado com sucesso para {printer["name"]}.')
                else:
                    flash(f'Falha no teste: {msg}')
            else:
                flash('Impressora não encontrada.')

        elif action == 'update_default_printers':
            printer_settings['bill_printer_id'] = request.form.get('bill_printer_id')
            printer_settings['fiscal_printer_id'] = request.form.get('fiscal_printer_id')
            printer_settings['reception_printer_id'] = request.form.get('reception_printer_id')
            printer_settings['kitchen_printer_id'] = request.form.get('kitchen_printer_id')
            printer_settings['kitchen_portion_printer_id'] = request.form.get('kitchen_portion_printer_id')
            printer_settings['bar_printer_id'] = request.form.get('bar_printer_id')
            
            printer_settings['frigobar_filter_enabled'] = request.form.get('frigobar_filter_enabled') == 'on'
            
            save_printer_settings(printer_settings)
            flash('Configurações gerais salvas.')
            
        elif action == 'update_category_map':
            cats = request.form.getlist('categories[]')
            pids = request.form.getlist('printer_ids[]')
            
            updates = 0
            for i, cat_name in enumerate(cats):
                pid = pids[i] if i < len(pids) else None
                
                # Update all items in this category
                for item in menu_items:
                    if item.get('category') == cat_name:
                        if pid:
                            item['printer_id'] = pid
                            item['should_print'] = True
                        else:
                            item['printer_id'] = None
                            item['should_print'] = False # Optional: Depends on business logic
                        updates += 1
            
            if updates > 0:
                try:
                    secure_save_menu_items(menu_items, session.get('user', 'Sistema'))
                    flash(f'Mapeamento atualizado. {updates} itens modificados.')
                except Exception as e:
                    flash(f'Erro de segurança ao salvar mapeamento: {e}')
            
            # Reload map for display
            return redirect(url_for('admin.printers_config'))

    # Load Windows Printers for dropdown
    try:
        from app.services.printing_service import get_available_windows_printers
        windows_printers = get_available_windows_printers()
    except:
        windows_printers = []

    return render_template('printers_config.html', 
                         printers=printers, 
                         printer_settings=printer_settings,
                         category_map=category_map,
                         windows_printers=windows_printers)

@admin_bp.route('/config/fiscal', methods=['GET', 'POST'])
@login_required
def fiscal_config():
    if session.get('role') != 'admin':
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    settings = load_fiscal_settings()
    
    # Ensure integrations structure exists
    if 'integrations' not in settings:
        settings['integrations'] = []
    
    # Get or Create main integration (Nuvem Fiscal)
    integration = None
    if settings['integrations']:
        integration = settings['integrations'][0]
    else:
        integration = {"provider": "nuvem_fiscal"}
        settings['integrations'].append(integration)

    if request.method == 'POST':
        env_val = request.form.get('environment')
        integration['environment'] = 'homologation' if env_val == '2' else 'production'
        
        sefaz_env_val = request.form.get('sefaz_environment')
        if sefaz_env_val == '2':
            integration['sefaz_environment'] = 'homologation'
        else:
            integration['sefaz_environment'] = 'production'
        
        integration['client_id'] = request.form.get('client_id')
        integration['client_secret'] = request.form.get('client_secret')
        integration['csc_id'] = request.form.get('csc_id')
        integration['csc_token'] = request.form.get('csc_token')
        integration['serie'] = request.form.get('serie') or integration.get('serie')
        integration['next_number'] = request.form.get('next_number') or integration.get('next_number')
        crt_val = request.form.get('crt')
        if crt_val:
            integration['CRT'] = crt_val
        
        # Legacy/Root compatibility (optional, but good for safety if other parts read root)
        settings['environment'] = integration['environment']
        
        save_fiscal_settings(settings)

        try:
            from app.services.fiscal_service import sync_nfce_company_settings
            sync_result = sync_nfce_company_settings(integration)
            if sync_result.get('success'):
                flash('Configurações fiscais salvas e sincronizadas com a Nuvem Fiscal.')
            else:
                flash(f"Configurações salvas, mas falha ao sincronizar com a Nuvem Fiscal: {sync_result.get('message')}")
        except Exception as e:
            flash(f"Configurações salvas, mas ocorreu erro ao sincronizar com a Nuvem Fiscal: {e}")
        
    return render_template('fiscal_config.html', settings=settings)

@admin_bp.route('/admin/fiscal/test_connection', methods=['POST'])
@login_required
def fiscal_test_connection():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.json or {}
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')
    env_val = data.get('environment') # 1 or 2
    
    scope = "nfce" # Default scope for testing connection
    if env_val == '2':
        base_url = "https://api.sandbox.nuvemfiscal.com.br"
    else:
        base_url = "https://api.nuvemfiscal.com.br"
    audience = base_url + "/"
    
    if not client_id or not client_secret:
        return jsonify({'success': False, 'message': 'Credenciais ausentes.'}), 400
        
    token = get_access_token(client_id, client_secret, scope=scope, audience=audience)
    
    if token:
        return jsonify({'success': True, 'token_preview': f"{token[:10]}..."})
    else:
        return jsonify({'success': False, 'message': 'Falha ao obter token. Verifique as credenciais.'})


@admin_bp.route('/admin/fiscal/pool')
@login_required
def fiscal_pool_view():
    if session.get('role') != 'admin':
        return redirect(url_for('main.index'))
    pool = FiscalPoolService._load_pool()
    selected_month = request.args.get('month')
    if not selected_month:
        selected_month = datetime.now().strftime('%Y-%m')
    filtered_pool = []
    for entry in pool:
        try:
            dt_str = entry.get('closed_at')
            if not dt_str:
                continue
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d')
                except ValueError:
                    continue
            if dt.strftime('%Y-%m') == selected_month:
                filtered_pool.append(entry)
        except Exception:
            continue
    months = set()
    for entry in pool:
        try:
            dt_str = entry.get('closed_at')
            if not dt_str:
                continue
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d')
                except ValueError:
                    continue
            months.add(dt.strftime('%Y-%m'))
        except Exception:
            continue
    months = sorted(months, reverse=True)
    total_fiscal = 0.0
    emitted_fiscal = 0.0
    for e in filtered_pool:
        val = 0.0
        try:
            val = float(e.get('fiscal_amount', 0.0) or 0.0)
        except Exception:
            val = 0.0
        total_fiscal += val
        if e.get('status') == 'emitted':
            emitted_fiscal += val
    pending_fiscal = total_fiscal - emitted_fiscal
    return render_template('fiscal_pool.html', pool=filtered_pool, months=months, selected_month=selected_month, total_fiscal=round(total_fiscal, 2), emitted_fiscal=round(emitted_fiscal, 2), pending_fiscal=round(pending_fiscal, 2))

@admin_bp.route('/admin/fiscal/pool/emit_until', methods=['POST'])
@login_required
def fiscal_pool_emit_until():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        payload = request.get_json(silent=True) or {}
        selected_month = payload.get('month') or datetime.now().strftime('%Y-%m')
        pool = FiscalPoolService._load_pool()
        filtered = []
        for entry in pool:
            dt_str = entry.get('closed_at')
            if not dt_str:
                continue
            dt = None
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d')
                except ValueError:
                    continue
            if dt and dt.strftime('%Y-%m') == selected_month:
                filtered.append(entry)
        total_fiscal = 0.0
        emitted_fiscal = 0.0
        for e in filtered:
            try:
                val = float(e.get('fiscal_amount', 0.0) or 0.0)
            except Exception:
                val = 0.0
            total_fiscal += val
            if e.get('status') == 'emitted':
                emitted_fiscal += val
        remaining = round(total_fiscal - emitted_fiscal, 2)
        if remaining <= 0:
            return jsonify({'success': True, 'message': 'Não há saldo a emitir.', 'emitted': 0, 'failed': 0, 'remaining': remaining})
        to_emit = [e for e in filtered if e.get('status') in ['pending', 'failed', 'error', 'error_config']]
        to_emit.sort(key=lambda x: x.get('closed_at') or '')
        from app.services.fiscal_service import process_pending_emissions
        emitted_count = 0
        failed_count = 0
        for entry in to_emit:
            if remaining <= 0:
                break
            res = process_pending_emissions(specific_id=entry['id'])
            if res.get('success', 0) > 0:
                updated = FiscalPoolService.get_entry(entry['id'])
                if updated and updated.get('status') == 'emitted':
                    try:
                        val = float(updated.get('fiscal_amount', 0.0) or 0.0)
                    except Exception:
                        val = 0.0
                    remaining = round(remaining - val, 2)
                    emitted_count += 1
            else:
                failed_count += 1
        return jsonify({'success': True, 'message': 'Processo concluído.', 'emitted': emitted_count, 'failed': failed_count, 'remaining': remaining})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/admin/fiscal/pool/action', methods=['POST'])
@login_required
def fiscal_pool_action():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    action = request.json.get('action')
    entry_id = request.json.get('id')
    
    if action == 'start':
        FiscalPoolService.start_pool()
        msg = "Pool iniciado."
    elif action == 'stop':
        FiscalPoolService.stop_pool()
        msg = "Pool parado."
    elif action == 'restart':
        FiscalPoolService.stop_pool()
        time.sleep(1)
        FiscalPoolService.start_pool()
        msg = "Pool reiniciado."
    elif action == 'emit':
        if not entry_id:
            return jsonify({'success': False, 'error': 'ID ausente'}), 400
        
        try:
            # Use updated process_pending_emissions with specific_id
            from app.services.fiscal_service import process_pending_emissions
            results = process_pending_emissions(specific_id=entry_id)
            
            if results['success'] > 0:
                msg = "Emissão realizada com sucesso."
            elif results['failed'] > 0:
                # Fetch error detail from entry
                entry = FiscalPoolService.get_entry(entry_id)
                error_detail = "Erro desconhecido"
                if entry:
                    if entry.get('last_error'):
                        error_detail = entry.get('last_error')
                    else:
                        error_detail = "Verifique o status da conta ou configurações."
                return jsonify({'success': False, 'error': f"Falha na emissão: {error_detail}"})
            else:
                return jsonify({'success': False, 'error': "Nenhuma emissão processada (Item não encontrado, já emitido ou status inválido)."})
        except Exception as e:
            try:
                # Persist the error into the pool so it appears no modal
                FiscalPoolService.update_status(entry_id, 'failed', user=session.get('user'), error_msg=str(e))
            except Exception:
                pass
            traceback.print_exc()
            return jsonify({'success': False, 'error': f"Erro interno ao emitir: {str(e)}"})
            
    elif action == 'ignore':
        if not entry_id:
            return jsonify({'success': False, 'error': 'ID ausente'}), 400
        
        success = FiscalPoolService.update_status(entry_id, 'ignored', user=session.get('user'))
        if success:
            msg = "Conta marcada como ignorada."
        else:
            return jsonify({'success': False, 'error': "Erro ao atualizar status."})
            
    else:
        return jsonify({'success': False, 'error': 'Ação inválida'}), 400
        
    return jsonify({'success': True, 'message': msg})

import traceback

@admin_bp.route('/admin/fiscal/pool/open_xml', methods=['POST'])
@login_required
def fiscal_pool_open_xml():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.json or {}
    entry_id = data.get('entry_id')
    if not entry_id:
        return jsonify({'success': False, 'error': 'ID ausente'}), 400
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404
    if entry.get('status') != 'emitted':
        return jsonify({'success': False, 'error': 'Nota ainda não emitida'}), 400
    fiscal_doc_uuid = entry.get('fiscal_doc_uuid')
    if not fiscal_doc_uuid:
        return jsonify({'success': False, 'error': 'UUID fiscal ausente'}), 400
    try:
        settings = load_fiscal_settings()
        target_cnpj = entry.get('cnpj_emitente')
        if not target_cnpj:
            payment_methods = entry.get('payment_methods', [])
            for pm in payment_methods:
                if pm.get('fiscal_cnpj'):
                    target_cnpj = pm.get('fiscal_cnpj')
                    break
        integration_settings = get_fiscal_integration(settings, target_cnpj)
        base_dir = get_data_path(os.path.join('fiscal', 'xmls', 'emitted'))
        found_path = None
        for root, dirs, files in os.walk(base_dir):
            name = f"{fiscal_doc_uuid}.xml"
            if name in files:
                found_path = os.path.join(root, name)
                break
        if not found_path:
            try:
                found_path = download_xml(fiscal_doc_uuid, integration_settings)
            except Exception:
                found_path = None
        # If we still don't have the exact file, open the emitted folder as a fallback
        if not found_path or not os.path.exists(found_path):
            base_dir = get_data_path(os.path.join('fiscal', 'xmls', 'emitted'))
            try:
                subprocess.Popen(['explorer', base_dir])
                resp = {'success': True, 'message': 'XML ainda não disponível. Pasta aberta.'}
                return jsonify(resp)
            except Exception:
                return jsonify({'success': False, 'error': 'XML não encontrado'}), 404
        else:
            try:
                subprocess.Popen(['explorer', '/select,', found_path])
            except Exception:
                # If select fails, open the directory
                try:
                    subprocess.Popen(['explorer', os.path.dirname(found_path)])
                    resp2 = {'success': True, 'message': 'Pasta aberta.'}
                    return jsonify(resp2)
                except Exception:
                    return jsonify({'success': False, 'error': 'Falha ao abrir pasta'}), 500
            return jsonify({'success': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/admin/fiscal/pool/open_pdf', methods=['POST'])
@login_required
def fiscal_pool_open_pdf():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.json or {}
    entry_id = data.get('entry_id')
    if not entry_id:
        return jsonify({'success': False, 'error': 'ID ausente'}), 400
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404
    if entry.get('status') != 'emitted':
        return jsonify({'success': False, 'error': 'Nota ainda não emitida'}), 400
    nfe_uuid = entry.get('fiscal_doc_uuid')
    if not nfe_uuid:
        return jsonify({'success': False, 'error': 'UUID fiscal ausente'}), 400
    try:
        # Try existing path first
        pdf_path = entry.get('pdf_path')
        if not (pdf_path and os.path.exists(pdf_path)):
            # Attempt fresh download
            from app.services.fiscal_service import download_pdf
            settings = load_fiscal_settings()
            payment_methods = entry.get('payment_methods', [])
            target_cnpj = None
            for pm in payment_methods:
                if pm.get('fiscal_cnpj'):
                    target_cnpj = pm.get('fiscal_cnpj')
                    break
            integration_settings = get_fiscal_integration(settings, target_cnpj)
            try:
                pdf_path = download_pdf(nfe_uuid, integration_settings)
                if pdf_path:
                    try:
                        FiscalPoolService.set_pdf_ready(entry_id, True, pdf_path)
                    except Exception:
                        pass
            except Exception:
                pdf_path = None
        if not (pdf_path and os.path.exists(pdf_path)):
            return jsonify({'success': False, 'error': 'PDF não encontrado'}), 404
        filename = os.path.basename(pdf_path)
        return send_file(pdf_path, as_attachment=True, download_name=filename)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
@admin_bp.route('/admin/fiscal/pool/xml_status', methods=['POST'])
@login_required
def fiscal_pool_xml_status():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.json or {}
    entry_id = data.get('entry_id')
    if not entry_id:
        return jsonify({'success': False, 'error': 'ID ausente'}), 400
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404
    ready = bool(entry.get('xml_ready'))
    xml_path = entry.get('xml_path')
    return jsonify({'success': True, 'ready': ready, 'xml_path': xml_path})

@admin_bp.route('/admin/fiscal/pool/download_xml/<entry_id>')
@login_required
def fiscal_pool_download_xml(entry_id):
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    entry = FiscalPoolService.get_entry(entry_id)
    if not entry:
        return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404
    if entry.get('status') != 'emitted':
        return jsonify({'success': False, 'error': 'Nota ainda não emitida'}), 400
    fiscal_doc_uuid = entry.get('fiscal_doc_uuid')
    if not fiscal_doc_uuid:
        return jsonify({'success': False, 'error': 'UUID fiscal ausente'}), 400
    try:
        settings = load_fiscal_settings()
        target_cnpj = entry.get('cnpj_emitente')
        if not target_cnpj:
            payment_methods = entry.get('payment_methods', [])
            for pm in payment_methods:
                if pm.get('fiscal_cnpj'):
                    target_cnpj = pm.get('fiscal_cnpj')
                    break
        integration_settings = get_fiscal_integration(settings, target_cnpj)
        base_dir = get_data_path(os.path.join('fiscal', 'xmls', 'emitted'))
        xml_path = entry.get('xml_path')
        if not xml_path or not os.path.exists(xml_path):
            try:
                from app.services.fiscal_service import download_xml
                xml_path = download_xml(fiscal_doc_uuid, integration_settings)
            except Exception:
                xml_path = None
        if not xml_path or not os.path.exists(xml_path):
            return jsonify({'success': False, 'error': 'XML não encontrado'}), 404
        directory = os.path.dirname(xml_path)
        filename = os.path.basename(xml_path)
        return send_file(xml_path, as_attachment=True, download_name=filename)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/fiscal/receive', methods=['POST'])
def api_fiscal_receive():
    """
    Endpoint to receive fiscal data from other instances.
    """
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
            
        pool = FiscalPoolService._load_pool()
        
        # Check if already exists to prevent duplicates (idempotency)
        if any(e['id'] == data['id'] for e in pool):
             return jsonify({'success': True, 'message': 'Already exists'}), 200
             
        # Append directly
        pool.append(data)
        FiscalPoolService._save_pool(pool)
        
        LoggerService.log_acao(
            acao='Sync Fiscal',
            entidade='Sistema',
            detalhes=f"Recebido registro fiscal {data['id']} via API.",
            nivel_severidade='INFO'
        )
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/admin/api/ngrok/status')
@login_required
def api_ngrok_status():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    status_file = "data/ngrok_status.json"
    if not os.path.exists(status_file):
        return jsonify({
            "status": "inactive",
            "message": "Gerenciador de Ngrok não está em execução ou arquivo de status não encontrado."
        })
        
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
