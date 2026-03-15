from functools import wraps
import time
from flask import request, session, redirect, url_for, jsonify, flash, current_app
from app.services.user_service import load_users
from app.services.authz.policy_decorators import (
    compare_metadata_with_registry,
    get_policy_metadata,
    get_policy_metadata_conflicts,
    policy_action,
    policy_min_role,
    policy_override,
    policy_page,
    policy_scope,
    public_endpoint,
)


LEGACY_AUTH_METADATA_ATTR = "__legacy_auth_metadata__"


def _set_legacy_auth_metadata(func, **kwargs):
    metadata = getattr(func, LEGACY_AUTH_METADATA_ATTR, None)
    if not isinstance(metadata, dict):
        metadata = {}
    for key, value in kwargs.items():
        metadata[key] = value
    setattr(func, LEGACY_AUTH_METADATA_ATTR, metadata)
    return func


def get_legacy_auth_metadata(func):
    metadata = getattr(func, LEGACY_AUTH_METADATA_ATTR, None)
    if isinstance(metadata, dict):
        return dict(metadata)
    return {}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_app.config.get('EXTERNAL_OPEN_MODE'):
            return f(*args, **kwargs)
        wants_json = ('application/json' in (request.headers.get('Content-Type') or '')) or (request.accept_mimetypes.best == 'application/json')
        if 'user' not in session:
            if wants_json:
                return jsonify({'success': False, 'error': 'Não autenticado'}), 401
            # Redirect to auth.login since we are using blueprints
            return redirect(url_for('auth.login'))
        
        if not current_app.config.get('TESTING'):
            now = time.time()
            last_check = float(session.get('_user_verified_at', 0) or 0)
            if (now - last_check) > 30:
                users = load_users()
                if session['user'] not in users:
                    session.clear()
                    if wants_json:
                        return jsonify({'success': False, 'error': 'Acesso negado'}), 401
                    flash('Acesso negado. Usuário não encontrado ou desativado.')
                    return redirect(url_for('auth.login'))
                session['_user_verified_at'] = now
            
        return f(*args, **kwargs)
    _set_legacy_auth_metadata(decorated_function, login_required=True)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_app.config.get('EXTERNAL_OPEN_MODE'):
                return f(*args, **kwargs)
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
        _set_legacy_auth_metadata(decorated_function, role_required=True, roles=list(roles or []))
        return decorated_function
    return decorator
