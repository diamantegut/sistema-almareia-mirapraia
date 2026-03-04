from flask import render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app, send_file
import os
import sys
import json
import io
import time
import threading
import subprocess
import pandas as pd
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set
from . import admin_bp
from app.utils.decorators import login_required
from app.services.logger_service import LoggerService
from app.services.system_config_manager import DEPARTMENTS
from app.services.data_service import (
    load_users,
    save_users,
    load_ex_employees,
    normalize_text,
    load_sales_history,
    load_menu_items,
    save_menu_items,
    load_cashier_sessions,
    secure_save_menu_items,
    load_department_permissions,
    save_department_permissions,
)
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
                
                if 'permissions' in request.form:
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


@admin_bp.route('/admin/api/permissions/definitions')
@login_required
def api_permissions_definitions():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    from app.services.permission_service import list_permission_definitions
    return jsonify(list_permission_definitions(current_app))


@admin_bp.route('/admin/api/permissions/targets')
@login_required
def api_permissions_targets():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    target_type = (request.args.get('type') or '').strip().lower()
    query = normalize_text(request.args.get('q') or '')

    results: List[Dict[str, Any]] = []
    users = load_users()

    if target_type in ('', 'user', 'users'):
        if isinstance(users, dict):
            for username, data in users.items():
                if not isinstance(data, dict):
                    continue
                full_name = str(data.get('full_name') or '')
                dept = str(data.get('department') or '')
                role = str(data.get('role') or '')
                haystack = normalize_text(f"{username} {full_name} {dept} {role}")
                if query and query not in haystack:
                    continue
                results.append(
                    {
                        'type': 'user',
                        'id': username,
                        'label': f"{full_name} ({username})",
                        'department': dept,
                        'role': role,
                    }
                )

    if target_type in ('', 'department', 'departments'):
        for dept in DEPARTMENTS:
            dept_s = str(dept)
            if query and query not in normalize_text(dept_s):
                continue
            results.append({'type': 'department', 'id': dept_s, 'label': dept_s})

    results.sort(key=lambda x: (x.get('type') or '', x.get('label') or ''))
    return jsonify({'items': results[:200]})


@admin_bp.route('/admin/api/permissions/get')
@login_required
def api_permissions_get():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    target_type = (request.args.get('type') or '').strip().lower()
    target_id = (request.args.get('id') or '').strip()

    from app.services.permission_service import effective_profile_for_user, merge_profiles, _normalize_profile, _empty_profile

    users = load_users()
    dept_perms = load_department_permissions()

    if target_type == 'user':
        if not target_id or not isinstance(users, dict) or target_id not in users or not isinstance(users.get(target_id), dict):
            return jsonify({'error': 'User not found'}), 404
        profile = effective_profile_for_user(target_id, users, dept_perms)
        data = users[target_id]
        return jsonify(
            {
                'type': 'user',
                'id': target_id,
                'full_name': data.get('full_name'),
                'department': data.get('department'),
                'role': data.get('role'),
                'profile': profile,
            }
        )

    if target_type == 'department':
        if not target_id:
            return jsonify({'error': 'Department not provided'}), 400
        profile = _normalize_profile((dept_perms or {}).get(target_id)) if isinstance(dept_perms, dict) else _empty_profile()
        return jsonify({'type': 'department', 'id': target_id, 'profile': profile})

    return jsonify({'error': 'Invalid type'}), 400


def _diff_profiles(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.permission_service import _normalize_profile

    o = _normalize_profile(old)
    n = _normalize_profile(new)

    def pages_set(p: Dict[str, Any]) -> Set[str]:
        out: Set[str] = set()
        for area_key, area_val in (p.get('areas') or {}).items():
            if bool(area_val.get('all')):
                out.add(f"area:{area_key}:all")
            pages = area_val.get('pages') if isinstance(area_val.get('pages'), dict) else {}
            for ep, v in pages.items():
                if v:
                    out.add(f"page:{ep}")
        for ep in p.get('level_pages') or []:
            out.add(f"level:{ep}")
        return out

    o_set = pages_set(o)
    n_set = pages_set(n)
    added = sorted(list(n_set - o_set))
    removed = sorted(list(o_set - n_set))
    return {'added': added, 'removed': removed}


@admin_bp.route('/admin/api/permissions/set', methods=['POST'])
@login_required
def api_permissions_set():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json(silent=True) or {}
    changes = data.get('changes')
    if not isinstance(changes, list):
        changes = [
            {
                'type': data.get('type'),
                'id': data.get('id'),
                'profile': data.get('profile'),
            }
        ]

    from app.services.permission_service import LEVEL_RESTRICTED_PAGES, ROLE_LEVELS, _empty_profile, _normalize_profile, role_level

    old_users = load_users()
    old_dept_perms = load_department_permissions()
    users = json.loads(json.dumps(old_users)) if isinstance(old_users, dict) else {}
    dept_perms = json.loads(json.dumps(old_dept_perms)) if isinstance(old_dept_perms, dict) else {}

    actor = session.get('user', 'Sistema')
    actor_role = session.get('role')

    audit_entries: List[Dict[str, Any]] = []

    try:
        for ch in changes:
            target_type = (ch.get('type') or '').strip().lower()
            target_id = (ch.get('id') or '').strip()
            profile_raw = ch.get('profile')

            if target_type not in ('user', 'department'):
                return jsonify({'success': False, 'error': 'Tipo inválido'}), 400
            if not target_id:
                return jsonify({'success': False, 'error': 'ID inválido'}), 400

            if target_type == 'user' and target_id == actor:
                return jsonify({'success': False, 'error': 'Usuário não pode alterar suas próprias permissões'}), 400

            new_profile = _normalize_profile(profile_raw)

            if target_type == 'user':
                if not isinstance(users, dict) or target_id not in users or not isinstance(users.get(target_id), dict):
                    return jsonify({'success': False, 'error': 'Usuário não encontrado'}), 404

                user_role = users[target_id].get('role')
                for ep in new_profile.get('level_pages') or []:
                    min_role = LEVEL_RESTRICTED_PAGES.get(str(ep))
                    if min_role and role_level(user_role) < ROLE_LEVELS.get(min_role, ROLE_LEVELS['supervisor']):
                        return jsonify({'success': False, 'error': f'Conflito: {target_id} não tem nível para {ep}'}), 400

                old_profile = users[target_id].get('permissions_v2') if isinstance(users[target_id], dict) else _empty_profile()
                users[target_id]['permissions_v2'] = new_profile
                audit_entries.append(
                    {
                        'type': 'user',
                        'id': target_id,
                        'diff': _diff_profiles(old_profile, new_profile),
                    }
                )

            if target_type == 'department':
                old_profile = dept_perms.get(target_id, _empty_profile())
                dept_perms[target_id] = new_profile
                audit_entries.append(
                    {
                        'type': 'department',
                        'id': target_id,
                        'diff': _diff_profiles(old_profile, new_profile),
                    }
                )

        ok_users = save_users(users)
        ok_dept = save_department_permissions(dept_perms)
        if not ok_users or not ok_dept:
            save_users(old_users if isinstance(old_users, dict) else {})
            save_department_permissions(old_dept_perms if isinstance(old_dept_perms, dict) else {})
            return jsonify({'success': False, 'error': 'Rollback aplicado após erro de gravação'}), 500

        for entry in audit_entries:
            LoggerService.log_acao(
                acao="Alteração de Permissões",
                entidade="Permissões",
                detalhes={
                    'actor': actor,
                    'actor_role': actor_role,
                    'target_type': entry.get('type'),
                    'target_id': entry.get('id'),
                    'diff': entry.get('diff'),
                    'ip': request.remote_addr,
                },
                nivel_severidade='WARNING',
                departamento_id="Sistema",
                colaborador_id=actor,
            )

        return jsonify({'success': True, 'applied': audit_entries})
    except Exception as e:
        save_users(old_users if isinstance(old_users, dict) else {})
        save_department_permissions(old_dept_perms if isinstance(old_dept_perms, dict) else {})
        return jsonify({'success': False, 'error': str(e)}), 500

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

# --- Sales Dashboard ---
@admin_bp.route('/admin/sales/dashboard')
@login_required
def admin_sales_dashboard():
    if session.get('role') not in ['admin', 'gerente']:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    # Get Categories for Filter
    categories = set()
    for item in load_menu_items():
        if item.get('category'):
            categories.add(item['category'])
            
    return render_template('admin_sales_dashboard.html', categories=sorted(list(categories)))

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch

@admin_bp.route('/admin/api/sales/analysis')
@login_required
def api_sales_analysis():
    if session.get('role') not in ['admin', 'gerente']:
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Defaults to today if not provided
        if not start_date:
            start_date = datetime.now().strftime('%Y-%m-%d')
        if not end_date:
            end_date = start_date
            
        category_filter = request.args.get('category')
            
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            # Adjust end_dt to include the whole day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400

        sales_history = load_sales_history()
        if not isinstance(sales_history, list):
            current_app.logger.error(f"sales_history is not a list: {type(sales_history)}")
            sales_history = []

        # Normalize menu items map (by ID and by Name for fallback)
        menu_items_by_id = {}
        menu_items_by_name = {}
        
        loaded_menu_items = load_menu_items()
        if not isinstance(loaded_menu_items, list):
            loaded_menu_items = []

        for item in loaded_menu_items:
            if not isinstance(item, dict): continue
            menu_items_by_id[str(item.get('id'))] = item
            if item.get('name'):
                menu_items_by_name[normalize_text(item.get('name'))] = item
                
        filtered_orders = []
        filtered_orders_ids = set()
        
        total_revenue = 0.0
        total_cost = 0.0
        total_items_sold = 0.0
        
        guest_stats = {'count': 0, 'revenue': 0.0, 'items': 0}
        passenger_stats = {'count': 0, 'revenue': 0.0, 'items': 0}
        
        expected_passenger_revenue = 0.0
        guest_paid_at_cashier_revenue = 0.0
        transferred_to_rooms_revenue = 0.0
        
        product_stats = {}
        hourly_sales = {h: 0.0 for h in range(24)}
        attendant_stats = {}
        
        daily_sales = {}

        room_transfer_items = []
        room_transfer_products = {}
        room_transfer_order_ids = set()
        room_transfer_items_count = 0.0
        
        def safe_float(val):
            try:
                if isinstance(val, str):
                    val = val.replace(',', '.')
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        for order in sales_history:
            if not isinstance(order, dict):
                continue
            
            closed_at_str = order.get('closed_at')
            if not closed_at_str:
                continue
            
            try:
                closed_at = datetime.strptime(closed_at_str, '%d/%m/%Y %H:%M')
            except ValueError:
                continue
                
            if not (start_dt <= closed_at <= end_dt):
                continue

            order_has_matching_items = False
            
            order_attendant = order.get('waiter') or order.get('closed_by') or 'Desconhecido'
            if not order_attendant:
                order_attendant = 'Desconhecido'
            
            is_guest = False
            if order.get('customer_type') == 'hospede' or order.get('room_number'):
                is_guest = True
            
            is_transferred = False
            pm = str(order.get('payment_method') or '').lower()
            if 'room' in pm or 'quarto' in pm or order.get('room_charge'):
                is_transferred = True

            order_id = order.get('id') or order.get('close_id') or order.get('table_id')
            is_room_transfer_order = is_guest and is_transferred
            skip_room_transfer_for_order = False
            if is_room_transfer_order and order_id and order_id in room_transfer_order_ids:
                skip_room_transfer_for_order = True
            
            order_revenue = 0.0
            order_items_count = 0.0

            items = order.get('items')
            if not isinstance(items, list):
                items = []

            for item in items:
                if not isinstance(item, dict):
                    continue
                
                p_id = str(item.get('product_id') or item.get('id') or 'unknown')
                qty = safe_float(item.get('qty', 0))
                price = safe_float(item.get('price', 0))
                name = item.get('name', 'Desconhecido')
                
                cost_unit = 0.0
                category = 'Outros'
                
                menu_item = menu_items_by_id.get(p_id)
                
                if not menu_item:
                    menu_item = menu_items_by_name.get(normalize_text(name))
                
                if menu_item:
                    cost_unit = safe_float(menu_item.get('cost_price', 0))
                    category = menu_item.get('category', 'Outros')
                    name = menu_item.get('name', name)
                
                if category_filter and category != category_filter:
                    continue
                
                order_has_matching_items = True
                
                revenue = price * qty
                cost = cost_unit * qty
                
                total_revenue += revenue
                total_cost += cost
                total_items_sold += qty
                
                order_revenue += revenue
                order_items_count += qty
                
                if p_id not in product_stats:
                    product_stats[p_id] = {
                        'name': name,
                        'category': category,
                        'qty': 0.0,
                        'revenue': 0.0,
                        'cost': 0.0
                    }
                
                product_stats[p_id]['qty'] += qty
                product_stats[p_id]['revenue'] += revenue
                product_stats[p_id]['cost'] += cost
                
                hour = closed_at.hour
                hourly_sales[hour] += revenue
                
                day_key = closed_at.strftime('%Y-%m-%d')
                daily_sales[day_key] = daily_sales.get(day_key, 0) + revenue
                
                if order_attendant not in attendant_stats:
                    attendant_stats[order_attendant] = {'orders': set(), 'revenue': 0.0, 'items': 0}
                
                attendant_stats[order_attendant]['revenue'] += revenue
                attendant_stats[order_attendant]['items'] += qty
                attendant_stats[order_attendant]['orders'].add(order_id)

                if is_room_transfer_order and not skip_room_transfer_for_order:
                    room_number = order.get('room_charge') or order.get('room_number')
                    guest_name = order.get('customer_name') or 'Hóspede'
                    qty_int = int(qty)
                    qty_is_int = qty_int >= 1 and float(qty_int) == float(qty)
                    per_units = qty_int if qty_is_int else 1

                    for _ in range(per_units):
                        room_transfer_items.append({
                            'order_id': order_id,
                            'product_id': p_id,
                            'product_name': name,
                            'qty': 1.0 if qty_is_int else qty,
                            'unit_price': price,
                            'total': price if qty_is_int else revenue,
                            'room_number': room_number,
                            'guest_name': guest_name,
                            'closed_at': closed_at_str
                        })
                    room_transfer_items_count += qty
                    if p_id not in room_transfer_products:
                        room_transfer_products[p_id] = {
                            'product_id': p_id,
                            'name': name,
                            'qty': 0.0,
                            'revenue': 0.0
                        }
                    room_transfer_products[p_id]['qty'] += qty
                    room_transfer_products[p_id]['revenue'] += revenue

            if order_has_matching_items:
                filtered_orders.append(order)
                filtered_orders_ids.add(order_id)
                
                if is_guest:
                    guest_stats['count'] += 1
                    guest_stats['revenue'] += order_revenue
                    guest_stats['items'] += order_items_count
                    
                    if is_transferred:
                        if not (is_room_transfer_order and skip_room_transfer_for_order):
                            transferred_to_rooms_revenue += order_revenue
                    else:
                        guest_paid_at_cashier_revenue += order_revenue
                else:
                    passenger_stats['count'] += 1
                    passenger_stats['revenue'] += order_revenue
                    passenger_stats['items'] += order_items_count
                    
                    if not is_transferred:
                        expected_passenger_revenue += order_revenue

                if is_room_transfer_order and not skip_room_transfer_for_order and order_id:
                    room_transfer_order_ids.add(order_id)

        # Calculate Cashier Received (Restaurant)
        cashier_sessions = load_cashier_sessions()
        if not isinstance(cashier_sessions, list):
            cashier_sessions = []

        received_restaurant_revenue = 0.0
        
        for session_data in cashier_sessions:
            if not isinstance(session_data, dict): continue
            
            stype = session_data.get('type')
            if stype not in ['restaurant', 'restaurant_service']:
                continue
            
            transactions = session_data.get('transactions')
            if not isinstance(transactions, list):
                transactions = []

            for tx in transactions:
                if not isinstance(tx, dict): continue
                
                if tx.get('type') == 'sale':
                    tx_ts_str = tx.get('timestamp')
                    if not tx_ts_str: continue
                    try:
                        tx_ts = datetime.strptime(tx_ts_str, '%d/%m/%Y %H:%M')
                    except:
                        continue
                        
                    if start_dt <= tx_ts <= end_dt:
                        method = str(tx.get('payment_method') or '').lower()
                        # Exclude Room Charges from received_restaurant_revenue
                        # Because received_restaurant_revenue should represent PHYSICAL cash/card received at cashier
                        if 'room' in method or 'quarto' in method or 'credito' in method:
                            if 'room' in method or 'quarto' in method:
                                continue
                        
                        amount = safe_float(tx.get('amount', 0))
                        received_restaurant_revenue += amount

        total_expected_cashier = expected_passenger_revenue + guest_paid_at_cashier_revenue
        discrepancy_val = received_restaurant_revenue - total_expected_cashier
        discrepancy_pct = (discrepancy_val / total_expected_cashier * 100) if total_expected_cashier > 0 else 0
        
        has_alert = abs(discrepancy_pct) > 2.0

        products_list = []
        for p_id, stats in product_stats.items():
            profit = stats['revenue'] - stats['cost']
            margin_pct = (profit / stats['revenue'] * 100) if stats['revenue'] > 0 else 0
            
            products_list.append({
                'id': p_id,
                'name': stats['name'],
                'category': stats['category'],
                'qty': stats['qty'],
                'revenue': stats['revenue'],
                'cost': stats['cost'],
                'profit': profit,
                'margin_pct': margin_pct
            })
            
        products_list.sort(key=lambda x: x['profit'], reverse=True)
        
        accumulated_profit = 0
        total_profit = total_revenue - total_cost
        
        abc_data = []
        for p in products_list:
            accumulated_profit += p['profit']
            p['accumulated_profit_pct'] = (accumulated_profit / total_profit * 100) if total_profit > 0 else 0
            
            if p['accumulated_profit_pct'] <= 80:
                p['abc_class'] = 'A'
            elif p['accumulated_profit_pct'] <= 95:
                p['abc_class'] = 'B'
            else:
                p['abc_class'] = 'C'
            abc_data.append(p)

        hourly_data = [{'hour': h, 'sales': hourly_sales[h]} for h in range(24)]
        
        daily_trend = [{'date': k, 'value': v} for k, v in sorted(daily_sales.items())]

        attendants_list = []
        for name, stats in attendant_stats.items():
            order_count = len(stats['orders'])
            avg_ticket = stats['revenue'] / order_count if order_count > 0 else 0
            attendants_list.append({
                'name': name,
                'orders': order_count,
                'revenue': stats['revenue'],
                'items': stats['items'],
                'avg_ticket': avg_ticket
            })
        attendants_list.sort(key=lambda x: x['revenue'], reverse=True)

        orders_list = []
        for order in filtered_orders:
            orders_list.append({
                'id': order.get('id') or order.get('close_id'),
                'time': order.get('closed_at'),
                'waiter': order.get('waiter') or order.get('closed_by') or 'Desconhecido',
                'total': safe_float(order.get('total', 0)),
                'items_count': len(order.get('items', [])),
                'status': order.get('status', 'closed')
            })
        orders_list.sort(key=lambda x: datetime.strptime(x['time'], '%d/%m/%Y %H:%M') if x['time'] else datetime.min, reverse=True)

        room_transfer_products_list = list(room_transfer_products.values())

        if request.args.get('export') == 'pdf':
            output = io.BytesIO()
            doc = SimpleDocTemplate(output, pagesize=A4, title="Relatório de Vendas")
            elements = []
            styles = getSampleStyleSheet()
            
            # Title
            elements.append(Paragraph(f"Relatório de Vendas - {start_date} a {end_date}", styles['Title']))
            elements.append(Spacer(1, 0.2 * inch))
            
            # Summary
            elements.append(Paragraph("Resumo Geral", styles['Heading2']))
            summary_data = [
                ['Métrica', 'Valor'],
                ['Receita Total', f"R$ {total_revenue:.2f}"],
                ['Custo Total', f"R$ {total_cost:.2f}"],
                ['Lucro Bruto', f"R$ {total_profit:.2f}"],
                ['Margem %', f"{(total_profit / total_revenue * 100) if total_revenue > 0 else 0:.1f}%"],
                ['Pedidos', str(len(filtered_orders))],
                ['Itens Vendidos', f"{total_items_sold:.0f}"]
            ]
            t_summary = Table(summary_data, colWidths=[3*inch, 2*inch])
            t_summary.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t_summary)
            elements.append(Spacer(1, 0.2 * inch))
            
            elements.append(Paragraph("Análise de Atendimento (Hóspedes vs Passageiros)", styles['Heading2']))
            guest_data = [
                ['Métrica', 'Valor'],
                ['Total Hóspedes Atendidos', str(guest_stats['count'])],
                ['Receita Hóspedes', f"R$ {guest_stats['revenue']:.2f}"],
                ['  - Transferido para Quartos', f"R$ {transferred_to_rooms_revenue:.2f}"],
                ['  - Pago no Caixa', f"R$ {guest_paid_at_cashier_revenue:.2f}"],
                ['Total Passageiros Atendidos', str(passenger_stats['count'])],
                ['Receita Passageiros', f"R$ {passenger_stats['revenue']:.2f}"],
                ['Total Esperado em Caixa', f"R$ {total_expected_cashier:.2f}"],
                ['Recebido em Caixa (Restaurante)', f"R$ {received_restaurant_revenue:.2f}"],
                ['Divergência', f"R$ {discrepancy_val:.2f} ({discrepancy_pct:.1f}%)"],
                ['Alerta', 'SIM' if has_alert else 'NÃO']
            ]
            t_guest = Table(guest_data, colWidths=[3.5*inch, 2*inch])
            t_guest.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('TEXTCOLOR', (1, 8), (1, 8), colors.red if has_alert else colors.black)
            ]))
            elements.append(t_guest)
            elements.append(Spacer(1, 0.2 * inch))

            if room_transfer_items:
                elements.append(Paragraph("Transferências para Quartos (Detalhado)", styles['Heading2']))
                rt_data = [['Data/Hora', 'Quarto', 'Hóspede', 'Produto', 'Qtd', 'Total']]
                for rt in room_transfer_items[:50]:
                    rt_data.append([
                        rt.get('closed_at', ''),
                        str(rt.get('room_number') or ''),
                        (rt.get('guest_name') or '')[:20],
                        (rt.get('product_name') or '')[:20],
                        f"{rt.get('qty', 0):.0f}",
                        f"R$ {rt.get('total', 0):.2f}"
                    ])
                t_rt = Table(rt_data, colWidths=[1.2*inch, 0.7*inch, 1.5*inch, 1.8*inch, 0.6*inch, 0.9*inch])
                t_rt.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                ]))
                elements.append(t_rt)
                elements.append(Spacer(1, 0.2 * inch))
            
            # Products (Top 20)
            elements.append(Paragraph("Produtos Mais Vendidos (Top 20)", styles['Heading2']))
            prod_data = [['Produto', 'Qtd', 'Receita', 'Lucro']]
            for p in products_list[:20]:
                prod_data.append([
                    p['name'][:30],
                    f"{p['qty']:.0f}",
                    f"R$ {p['revenue']:.2f}",
                    f"R$ {p['profit']:.2f}"
                ])
            t_prod = Table(prod_data, colWidths=[3*inch, 0.8*inch, 1.2*inch, 1.2*inch])
            t_prod.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
            ]))
            elements.append(t_prod)
            
            doc.build(elements)
            output.seek(0)
            
            filename = f"relatorio_vendas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(
                output,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )

        if request.args.get('export') == 'excel':
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Summary Sheet
                summary_data = [
                    {'Metric': 'Receita Total', 'Value': total_revenue},
                    {'Metric': 'Custo Total', 'Value': total_cost},
                    {'Metric': 'Lucro Bruto', 'Value': total_profit},
                    {'Metric': 'Margem %', 'Value': (total_profit / total_revenue * 100) if total_revenue > 0 else 0},
                    {'Metric': 'Pedidos', 'Value': len(filtered_orders)},
                    {'Metric': 'Itens Vendidos', 'Value': total_items_sold}
                ]
                pd.DataFrame(summary_data).to_excel(writer, sheet_name='Resumo', index=False)
                
                guest_data = [
                    {'Metric': 'Total Hóspedes Atendidos (Pedidos)', 'Value': guest_stats['count']},
                    {'Metric': 'Receita Hóspedes', 'Value': guest_stats['revenue']},
                    {'Metric': 'Itens Hóspedes', 'Value': guest_stats['items']},
                    {'Metric': 'Transferido para Quartos', 'Value': transferred_to_rooms_revenue},
                    {'Metric': 'Pago no Caixa (Hóspedes)', 'Value': guest_paid_at_cashier_revenue},
                    {'Metric': 'Total Passageiros Atendidos (Pedidos)', 'Value': passenger_stats['count']},
                    {'Metric': 'Receita Passageiros', 'Value': passenger_stats['revenue']},
                    {'Metric': 'Itens Passageiros', 'Value': passenger_stats['items']},
                    {'Metric': 'Esperado em Caixa (Passageiros)', 'Value': expected_passenger_revenue},
                    {'Metric': 'Total Esperado em Caixa', 'Value': total_expected_cashier},
                    {'Metric': 'Recebido em Caixa (Restaurante)', 'Value': received_restaurant_revenue},
                    {'Metric': 'Divergência (Valor)', 'Value': discrepancy_val},
                    {'Metric': 'Divergência (%)', 'Value': discrepancy_pct},
                    {'Metric': 'Alerta de Divergência', 'Value': 'SIM' if has_alert else 'NÃO'}
                ]
                pd.DataFrame(guest_data).to_excel(writer, sheet_name='Análise Atendimento', index=False)
                
                if room_transfer_items:
                    pd.DataFrame(room_transfer_items).to_excel(writer, sheet_name='Transf Quartos Detalhe', index=False)
                if room_transfer_products_list:
                    pd.DataFrame(room_transfer_products_list).to_excel(writer, sheet_name='Transf Quartos Produtos', index=False)
                
                # Products Sheet
                if products_list:
                    pd.DataFrame(products_list).to_excel(writer, sheet_name='Produtos ABC', index=False)
                
                # Attendants Sheet
                if attendants_list:
                    pd.DataFrame(attendants_list).to_excel(writer, sheet_name='Atendentes', index=False)
                    
                # Orders Sheet
                if orders_list:
                    pd.DataFrame(orders_list).to_excel(writer, sheet_name='Pedidos', index=False)
                    
            output.seek(0)
            filename = f"analise_vendas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )

        return jsonify({
            'summary': {
                'revenue': total_revenue,
                'cost': total_cost,
                'profit': total_profit,
                'margin_pct': (total_profit / total_revenue * 100) if total_revenue > 0 else 0,
                'orders_count': len(filtered_orders),
                'items_sold': total_items_sold
            },
            'guest_analysis': {
                'guests': guest_stats,
                'passengers': passenger_stats,
                'expected_passenger': expected_passenger_revenue,
                'guest_paid_at_cashier': guest_paid_at_cashier_revenue,
                'total_expected_cashier': total_expected_cashier,
                'received_restaurant': received_restaurant_revenue,
                'transferred_to_rooms': transferred_to_rooms_revenue,
                'discrepancy_val': discrepancy_val,
                'discrepancy_pct': discrepancy_pct,
                'has_alert': has_alert
            },
            'room_transfers': {
                'summary': {
                    'orders_count': len(room_transfer_order_ids),
                    'items_count': room_transfer_items_count,
                    'revenue': transferred_to_rooms_revenue
                },
                'items': room_transfer_items,
                'products': room_transfer_products_list
            },
            'products': abc_data,
            'hourly': hourly_data,
            'daily_trend': daily_trend,
            'attendants': attendants_list,
            'orders': orders_list
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro no dashboard de vendas: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Erro interno: {str(e)}'}), 500

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
        flash('Acesso negado.')
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
    
    # Parameters
    selected_month = request.args.get('month')
    selected_date = request.args.get('date')
    sort_order = request.args.get('sort', 'date_desc')
    
    if not selected_month and not selected_date:
        selected_month = datetime.now().strftime('%Y-%m')
        
    filtered_pool = []
    months = set()
    
    # 1. Collect all available months for the dropdown
    for entry in pool:
        try:
            dt_str = entry.get('closed_at')
            if not dt_str: continue
            
            # Normalize date
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d')
                except ValueError:
                    continue
            
            months.add(dt.strftime('%Y-%m'))
            
            # 2. Filter Logic
            match = True
            
            # Date/Month Filter
            if selected_date:
                # specific date overrides month
                if dt.strftime('%Y-%m-%d') != selected_date:
                    match = False
            elif selected_month:
                if dt.strftime('%Y-%m') != selected_month:
                    match = False
            
            if match:
                filtered_pool.append(entry)
                
        except Exception:
            continue
            
    months = sorted(months, reverse=True)
    
    # 3. Sort Logic
    if sort_order == 'value_desc':
        filtered_pool.sort(key=lambda x: float(x.get('fiscal_amount', 0) or 0), reverse=True)
    else:
        # Default: Date Descending
        filtered_pool.sort(key=lambda x: x.get('closed_at', ''), reverse=True)
    
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
    
    return render_template(
        'fiscal_pool.html', 
        pool=filtered_pool, 
        months=months, 
        selected_month=selected_month,
        selected_date=selected_date,
        sort_order=sort_order,
        total_fiscal=round(total_fiscal, 2), 
        emitted_fiscal=round(emitted_fiscal, 2), 
        pending_fiscal=round(pending_fiscal, 2)
    )

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
    elif action == 'queue_nfse_reservation':
        if not entry_id:
            return jsonify({'success': False, 'error': 'ID ausente'}), 400

        entry = FiscalPoolService.get_entry(entry_id)
        if not entry:
            return jsonify({'success': False, 'error': 'Entrada não encontrada'}), 404

        origin = str(entry.get('origin', '')).lower()
        if origin not in ['reservations', 'reservation_checkin']:
            return jsonify({'success': False, 'error': 'Ação disponível apenas para contas de reservas.'}), 400

        raw_cnpj = (request.json or {}).get('emit_cnpj', '')
        emit_cnpj = ''.join(ch for ch in str(raw_cnpj) if ch.isdigit())
        pool = FiscalPoolService._load_pool()
        updated = False

        for item in pool:
            if item.get('id') != entry_id:
                continue
            item['fiscal_type'] = 'nfse'
            if emit_cnpj:
                item['cnpj_emitente'] = emit_cnpj
            elif not item.get('cnpj_emitente'):
                item['cnpj_emitente'] = '46500590000112'
            item['status'] = 'pending'
            note = "Conta preparada para emissão NFS-e via Nuvem Fiscal (CNPJ alternativo)."
            item['notes'] = f"{(item.get('notes') or '').strip()} | {note}".strip(' |')
            history = item.get('history') if isinstance(item.get('history'), list) else []
            history.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'action': 'queue_nfse_reservation',
                'user': session.get('user'),
                'cnpj_emitente': item.get('cnpj_emitente')
            })
            item['history'] = history
            updated = True
            break

        if not updated:
            return jsonify({'success': False, 'error': 'Não foi possível atualizar a conta.'}), 500

        FiscalPoolService._save_pool(pool)
        LoggerService.log_acao(
            acao='Preparar NFS-e Reserva',
            entidade='Fiscal Pool',
            detalhes={
                'entry_id': entry_id,
                'origin': origin,
                'cnpj_emitente': emit_cnpj or entry.get('cnpj_emitente') or '46500590000112',
                'user': session.get('user')
            },
            nivel_severidade='INFO',
            departamento_id='Financeiro',
            colaborador_id=session.get('user')
        )
        msg = "Conta de reserva preparada para emissão NFS-e."
            
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
