import os
import re

BASE_HTML_PATH = r"F:\Sistema Almareia Mirapraia\app\templates\base.html"

def fix_base_html():
    with open(BASE_HTML_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix CSS Links (Head)
    # Remove broken local assets and use CDNs
    head_replacements = [
        # Bootstrap CSS
        (r'<link rel="stylesheet" href="/assets/css/bootstrap.min.css">', 
         '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">'),
        
        # FontAwesome
        (r'<link rel="stylesheet" href="/assets/css/fontawesome.min.css">', 
         '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">'),
        
        # Animate
        (r'<link rel="stylesheet" href="/assets/css/animate.css">', 
         '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">'),
        
        # Slick
        (r'<link rel="stylesheet" href="/assets/css/slick.min.css">', 
         '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/1.8.1/slick.min.css">'),
        
        # Swiper
        (r'<link rel="stylesheet" href="/assets/css/swiper.min.css">', 
         '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swiper@9/swiper-bundle.min.css">'),
        
        # Daterangepicker
        (r'<link rel="stylesheet" href="/assets/css/daterangepicker.css">', 
         '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/daterangepicker/daterangepicker.css">'),
        
        # LightGallery
        (r'<link rel="stylesheet" href="/assets/css/lightgallery.min.css">', 
         '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/lightgallery/2.7.1/css/lightgallery.min.css">'),
        
        # Remove broken theme style (we rely on app/static/style.css and Bootstrap)
        (r'<link rel="stylesheet" href="/assets/css/style.css">', ''),
    ]

    for old, new in head_replacements:
        content = content.replace(old, new)

    # 2. Fix JS Scripts (Bottom)
    js_replacements = [
        # jQuery
        (r'<script src="/assets/js/jquery-3.6.0.min.js"></script>', 
         '<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>'),
        
        # WOW
        (r'<script src="/assets/js/wow.min.js"></script>', 
         '<script src="https://cdnjs.cloudflare.com/ajax/libs/wow/1.1.2/wow.min.js"></script>'),
        
        # Slick
        (r'<script src="/assets/js/jquery.slick.min.js"></script>', 
         '<script src="https://cdnjs.cloudflare.com/ajax/libs/slick-carousel/1.8.1/slick.min.js"></script>'),
        
        # Swiper
        (r'<script src="/assets/js/swiper.min.js"></script>', 
         '<script src="https://cdn.jsdelivr.net/npm/swiper@9/swiper-bundle.min.js"></script>'),
        
        # Moment
        (r'<script src="/assets/js/moment.min.js"></script>', 
         '<script src="https://cdn.jsdelivr.net/npm/moment@2.29.4/moment.min.js"></script>'),
        
        # Daterangepicker
        (r'<script src="/assets/js/daterangepicker.min.js"></script>', 
         '<script src="https://cdn.jsdelivr.net/npm/daterangepicker/daterangepicker.min.js"></script>'),
        
        # LightGallery
        (r'<script src="/assets/js/lightgallery.min.js"></script>', 
         '<script src="https://cdnjs.cloudflare.com/ajax/libs/lightgallery/2.7.1/lightgallery.min.js"></script>'),
        
        # YTPlayer (Maybe remove if not critical)
        (r'<script src="/assets/js/YTPlayer.min.js"></script>', ''),
        
        # Main JS (Custom theme js - likely missing, comment out)
        (r'<script src="/assets/js/main.js"></script>', '<!-- <script src="/assets/js/main.js"></script> (Missing) -->'),
    ]

    for old, new in js_replacements:
        content = content.replace(old, new)

    # 3. Rebuild Header using Bootstrap Navbar
    # We extract the logic and wrap it in Bootstrap structure
    
    # Check if we need to replace the header. Look for the old header class.
    if 'cs_site_header' in content:
        print("Replacing header structure...")
        
        # Regex to capture the header block is tricky. 
        # But we can reconstruct it completely since we know the logic from previous read.
        
        new_header = """    <header class="fixed-top">
      <nav class="navbar navbar-expand-lg navbar-dark" style="background-color: #26211c; border-bottom: 1px solid #3e362e;">
        <div class="container">
          <!-- Logo -->
          <a class="navbar-brand d-flex align-items-center gap-3" href="{{ url_for('main.index') }}">
            <img src="{{ url_for('static', filename='img/LOGO-almareia.png') }}" alt="Almareia Logo" style="height: 40px; width: auto;">
            <img src="{{ url_for('static', filename='img/LOGO-MIRA.PNG') }}" alt="Mirapraia Logo" style="height: 55px; width: auto;">
          </a>

          <!-- Toggler for Mobile -->
          <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarContent" aria-controls="navbarContent" aria-expanded="false" aria-label="Toggle navigation">
            <span class="navbar-toggler-icon"></span>
          </button>

          <div class="collapse navbar-collapse" id="navbarContent">
            <!-- Center Menu (Only if logged in) -->
            {% if session.get('user') %}
            <ul class="navbar-nav mx-auto mb-2 mb-lg-0 fw-semibold">
              <li class="nav-item">
                <a class="nav-link" href="{{ url_for('main.index') }}">Painel</a>
              </li>
              
              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">Restaurante</a>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="{{ url_for('restaurant.restaurant_tables') }}">Mesas</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('governance.checklist_view') }}">Checklist Cozinha</a></li>
                </ul>
              </li>

              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">Recepção</a>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="{{ url_for('reception.reception_waiting_list') }}">Fila de Espera</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('reception.reception_reservations') }}">Mapa de Reservas</a></li>
                </ul>
              </li>

              <li class="nav-item">
                <a class="nav-link" href="{{ url_for('main.index') }}">Estoque</a>
              </li>

              {% if session.get('role') == 'admin' or session.get('department') == 'Recursos Humanos' or 'rh' in session.get('permissions', []) %}
              <li class="nav-item">
                <a class="nav-link" href="{{ url_for('hr.hr_dashboard') }}">RH</a>
              </li>
              {% endif %}

              {% if session.get('role') == 'admin' %}
              <li class="nav-item">
                <a class="nav-link" href="{{ url_for('admin.admin_dashboard') }}">Administração</a>
              </li>
              
              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">Relatórios</a>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="{{ url_for('reports.invoice_report') }}">Faturamento</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('quality.quality_audit_history') }}">Auditoria de Qualidade</a></li>
                </ul>
              </li>

              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">Config</a>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="{{ url_for('admin.fiscal_config') }}">Fiscal</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('finance.finance_reconciliation') }}">Conciliação</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('admin.printers_config') }}">Impressoras</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('admin.admin_security_dashboard') }}">Segurança</a></li>
                    <li><a class="dropdown-item" href="{{ url_for('admin.admin_dashboard') }}">Sistema</a></li>
                </ul>
              </li>
              {% endif %}
            </ul>
            {% else %}
            <ul class="navbar-nav mx-auto"></ul>
            {% endif %}

            <!-- Right Side (User/Login) -->
            <div class="d-flex align-items-center">
              {% if session.get('user') %}
                <div class="text-white me-3 d-none d-lg-block">
                  Olá, {{ session['user'] }}
                  {% if session.get('department') %}
                  <small class="opacity-75">({{ session['department'] }})</small>
                  {% endif %}
                </div>
                <a href="{{ url_for('auth.logout') }}" class="btn btn-outline-light btn-sm rounded-pill px-3">
                  Sair
                </a>
              {% else %}
                <a href="{{ url_for('auth.login') }}" class="btn btn-outline-light btn-sm rounded-pill px-3">
                  Entrar
                </a>
              {% endif %}
            </div>
          </div>
        </div>
      </nav>
    </header>"""

        # Replace the old header block
        # We need to match everything from <header ...> to </header>
        # Using regex with DOTALL
        content = re.sub(r'<header class="cs_site_header.*?</header>', new_header, content, flags=re.DOTALL)
        
        # 4. Adjust Main Padding
        # Old: style="padding-top: 140px;"
        # New: style="padding-top: 100px;" (Bootstrap navbar is smaller)
        content = content.replace('style="padding-top: 140px;"', 'style="padding-top: 100px;"')

    with open(BASE_HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Successfully updated base.html")

if __name__ == "__main__":
    fix_base_html()
