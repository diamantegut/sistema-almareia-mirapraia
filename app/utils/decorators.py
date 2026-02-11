from functools import wraps
from flask import request, session, redirect, url_for, jsonify, flash, current_app
from app.services.user_service import load_users

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        wants_json = ('application/json' in (request.headers.get('Content-Type') or '')) or (request.accept_mimetypes.best == 'application/json')
        if 'user' not in session:
            if wants_json:
                return jsonify({'success': False, 'error': 'Não autenticado'}), 401
            # Redirect to auth.login since we are using blueprints
            return redirect(url_for('auth.login'))
        
        if not current_app.config.get('TESTING'):
            users = load_users()
            if session['user'] not in users:
                session.clear()
                if wants_json:
                    return jsonify({'success': False, 'error': 'Acesso negado'}), 401
                flash('Acesso negado. Usuário não encontrado ou desativado.')
                return redirect(url_for('auth.login'))
            
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Ensure user is logged in first (usually used after @login_required but safe to check)
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            
            user_role = session.get('role')
            if user_role not in roles:
                wants_json = ('application/json' in (request.headers.get('Content-Type') or '')) or (request.accept_mimetypes.best == 'application/json')
                if wants_json:
                    return jsonify({'success': False, 'error': 'Permissão negada.'}), 403
                flash('Acesso negado: Você não tem permissão para acessar esta área.', 'error')
                return redirect(url_for('main.index'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

