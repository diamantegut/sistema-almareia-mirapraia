from flask import render_template, request, redirect, url_for, flash, session
from . import auth_bp
from app.services.user_service import load_users, save_users, load_ex_employees, DEPARTMENTS, load_reset_requests, save_reset_requests
from app.services.logger_service import log_system_action
from app.utils.decorators import login_required
from datetime import datetime
import uuid

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        
        # Busca case-insensitive
        user_data = None
        real_username = None
        
        for u, data in users.items():
            if u.lower() == username.lower():
                user_data = data
                real_username = u
                break
        
        # Verifica se usuário existe
        if user_data:
            stored_password = user_data if isinstance(user_data, str) else user_data.get('password')
            
            if stored_password == password:
                session['user'] = real_username
                if isinstance(user_data, dict):
                    session['department'] = user_data.get('department')
                    session['role'] = user_data.get('role', 'colaborador')
                    session['permissions'] = user_data.get('permissions', [])
                    session['full_name'] = user_data.get('full_name')
                
                try:
                    log_system_action('Login', f"Usuário {real_username} entrou no sistema", user=real_username, category="Autenticação")
                except: pass
                
                # Redirect to index (main blueprint)
                return redirect(url_for('main.index'))
            else:
                try:
                    log_system_action('Login Falhou', f"Tentativa de senha incorreta para {username}", user=username, category="Autenticação")
                except: pass
                flash('Usuário ou senha incorretos.')
        else:
            try:
                log_system_action('Login Falhou', f"Tentativa de usuário inexistente: {username}", user=username, category="Autenticação")
            except: pass
            flash('Usuário ou senha incorretos.')
    
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    user = session.get('user')
    if user:
        try:
            log_system_action('Logout', f"Usuário {user} saiu do sistema", user=user, category="Autenticação")
        except: pass
    
    session.clear()
    flash('Você saiu do sistema.')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        department = request.form.get('department')
        role = request.form.get('role', 'colaborador')
        
        if len(password) != 4 or not password.isdigit():
            flash('A senha deve ter exatamente 4 dígitos numéricos.')
            return redirect(url_for('auth.register'))
            
        if password != confirm_password:
            flash('As senhas não coincidem.')
            return redirect(url_for('auth.register'))
            
        users = load_users()
        if username in users:
            flash('Nome de usuário já existe.')
            return redirect(url_for('auth.register'))
            
        # Check if user is in ex-employees (blocked)
        ex_employees = load_ex_employees()
        for ex in ex_employees:
            if ex.get('username') == username:
                flash('Este usuário consta como ex-funcionário e não pode ser recadastrado.')
                return redirect(url_for('auth.register'))
        
        # Salva estrutura completa do usuário
        users[username] = {
            'password': password,
            'department': department,
            'role': role
        }
        save_users(users)
        try:
            log_system_action('Cadastro Usuário', f"Novo usuário cadastrado: {username} ({role}, {department})", user='Sistema', category="Admin")
        except: pass
        flash('Cadastro realizado com sucesso! Faça login.')
        return redirect(url_for('auth.login'))
            
    return render_template('register.html', departments=DEPARTMENTS)

@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        users = load_users()
        username = session['user']
        
        if username not in users:
            flash('Usuário não encontrado.')
            return redirect(url_for('auth.login'))
            
        user_data = users[username]
        stored_password = user_data['password'] if isinstance(user_data, dict) else user_data
        
        # Verify current password
        if current_password != stored_password:
            flash('A senha atual está incorreta.')
            return redirect(url_for('auth.change_password'))
        
        if len(new_password) != 4 or not new_password.isdigit():
            flash('A senha deve ter exatamente 4 dígitos numéricos.')
            return redirect(url_for('auth.change_password'))
            
        if new_password != confirm_password:
            flash('As senhas não coincidem.')
            return redirect(url_for('auth.change_password'))
            
        if new_password == current_password:
             flash('A nova senha não pode ser igual à senha atual.')
             return redirect(url_for('auth.change_password'))

        # Update password and remove first_login flag
        if isinstance(users[username], dict):
            users[username]['password'] = new_password
            if 'first_login' in users[username]:
                del users[username]['first_login']
        else:
            # Legacy format support (should convert to dict)
            users[username] = {
                'password': new_password,
                'role': session.get('role', 'colaborador'),
                'department': session.get('department', 'Geral')
            }
            
        save_users(users)
        flash('Senha alterada com sucesso!')
        return redirect(url_for('main.index'))
            
    return render_template('change_password.html')

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        users = load_users()
        
        if username in users:
            requests = load_reset_requests()
            
            # Check for existing pending request
            existing = next((r for r in requests if r['username'] == username and r['status'] == 'pending'), None)
            if existing:
                flash('Já existe uma solicitação de reset pendente para este usuário.')
            else:
                new_request = {
                    'id': str(uuid.uuid4()),
                    'username': username,
                    'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'status': 'pending'
                }
                requests.append(new_request)
                save_reset_requests(requests)
                flash('Solicitação enviada ao RH com sucesso. Aguarde o contato.')
        else:
            flash('Usuário não encontrado.')
            
        return redirect(url_for('auth.login'))
        
    return render_template('forgot_password.html')

@auth_bp.route('/admin/reset_password_action/<request_id>/<action>')
@login_required
def admin_reset_password_action(request_id, action):
    if session.get('role') not in ['admin', 'gerente']: # Assuming RH might have gerente role or admin
        # Check if user is explicitly RH department
        if session.get('department') != 'Recursos Humanos' and session.get('role') != 'admin':
             flash('Acesso não autorizado.')
             return redirect(url_for('main.index'))

    requests = load_reset_requests()
    req = next((r for r in requests if r['id'] == request_id), None)
    
    if not req:
        flash('Solicitação não encontrada.')
        return redirect(url_for('admin.admin_users'))
        
    if action == 'approve':
        users = load_users()
        username = req['username']
        
        if username in users:
            # Reset to default '1234' and require change
            if isinstance(users[username], dict):
                users[username]['password'] = '1234'
                users[username]['first_login'] = True
            else:
                # Legacy
                users[username] = {
                    'password': '1234',
                    'first_login': True,
                    'role': 'colaborador', # Default fallback
                    'department': 'Geral'
                }
            
            save_users(users)
            req['status'] = 'approved'
            save_reset_requests(requests)
            flash(f'Senha do usuário {username} resetada para "1234".')
        else:
            flash('Usuário não existe mais.')
            req['status'] = 'error'
            save_reset_requests(requests)
            
    elif action == 'deny':
        req['status'] = 'denied'
        save_reset_requests(requests)
        flash('Solicitação negada.')
        
    return redirect(url_for('admin.admin_users'))

@auth_bp.route('/debug_login')
def debug_login():
    session['user'] = 'admin'
    session['role'] = 'admin'
    session['full_name'] = 'Administrador do Sistema'
    return 'Logged in'
