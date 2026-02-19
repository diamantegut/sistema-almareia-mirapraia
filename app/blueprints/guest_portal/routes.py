from flask import Blueprint, redirect, url_for, current_app, request
from . import guest_portal_bp

# Configuração do domínio de hóspedes
GUEST_DOMAIN = 'hospedes.almareia.mirapraia.ngrok.app'

@guest_portal_bp.route('/', host=GUEST_DOMAIN)
def guest_home():
    """
    Rota raiz para o subdomínio de hóspedes.
    Redireciona para o menu de experiências.
    """
    # Redireciona para a rota de experiências (que é a 'home' deste portal)
    return redirect(url_for('reception.guest_experiences_menu'))

@guest_portal_bp.route('/experiencias', host=GUEST_DOMAIN)
def guest_experiences_alias():
    """Alias explícito para experiências"""
    return redirect(url_for('reception.guest_experiences_menu'))

# As rotas /fila e /cardapio já existem nos blueprints restaurant e menu,
# e funcionarão normalmente neste domínio se acessadas diretamente (/fila, /cardapio).
# Mas criamos aliases aqui para garantir que se o usuário acessar
# hospedes.../fila, ele seja redirecionado corretamente se necessário,
# ou para documentar que essas rotas são suportadas neste domínio.

@guest_portal_bp.route('/fila', host=GUEST_DOMAIN)
def guest_queue_alias():
    return redirect(url_for('restaurant.public_waiting_list'))

@guest_portal_bp.route('/cardapio', host=GUEST_DOMAIN)
def guest_menu_alias():
    return redirect(url_for('menu.client_menu'))
