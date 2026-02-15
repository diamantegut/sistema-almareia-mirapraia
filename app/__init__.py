import os
from flask import Flask
from app.models.database import db

def create_app(config_name=None):
    # Initialize Flask app
    # Explicitly set template and static folders because we moved them inside app/
    app = Flask(__name__, template_folder='templates', static_folder='static')
    
    # Configuration
    # In a full production setup, this should come from config.py
    app.secret_key = os.environ.get('SECRET_KEY', 'chave_secreta_almareia_hotel')
    
    # Database Configuration
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    db_path = os.path.join(data_dir, 'department_logs.db')
    
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize Extensions
    db.init_app(app)
    
    # Register Filters
    from app.services.data_service import format_room_number
    @app.template_filter('format_room')
    def format_room_filter(s):
        return format_room_number(s)

    # Register Blueprints
    from app.blueprints.auth import auth_bp
    app.register_blueprint(auth_bp)
    
    from app.blueprints.main import main_bp
    app.register_blueprint(main_bp)
    
    from app.blueprints.reception import reception_bp
    app.register_blueprint(reception_bp)
    
    from app.blueprints.stock import stock_bp
    app.register_blueprint(stock_bp)
    
    from app.blueprints.kitchen import kitchen_bp
    app.register_blueprint(kitchen_bp)

    from app.blueprints.admin import admin_bp
    app.register_blueprint(admin_bp)
    
    from app.blueprints.hr import hr_bp
    app.register_blueprint(hr_bp)

    from app.blueprints.finance import finance_bp
    app.register_blueprint(finance_bp)

    from app.blueprints.suppliers import suppliers_bp
    app.register_blueprint(suppliers_bp)

    from app.blueprints.governance import governance_bp
    app.register_blueprint(governance_bp)

    from app.blueprints.guest import guest_bp
    app.register_blueprint(guest_bp)

    from app.blueprints.maintenance import maintenance_bp
    app.register_blueprint(maintenance_bp)

    from app.blueprints.menu import menu_bp
    app.register_blueprint(menu_bp)

    from app.blueprints.quality import quality_bp
    app.register_blueprint(quality_bp)

    from app.blueprints.reports import reports_bp
    app.register_blueprint(reports_bp)

    from app.blueprints.restaurant import restaurant_bp
    app.register_blueprint(restaurant_bp)

    # Initialize LoggerService with App Context
    from app.services.logger_service import LoggerService
    LoggerService.init_app(app)

    # Performance Monitoring Middleware
    import time
    from flask import request, g
    
    @app.before_request
    def start_timer():
        g.start = time.time()

    @app.after_request
    def log_request(response):
        if request.path.startswith('/static'):
            return response
            
        now = time.time()
        duration = round(now - g.start, 2)
        
        # Log slow requests (> 1s)
        if duration > 1.0:
            severity = 'WARNING' if duration < 5.0 else 'CRITICAL'
            try:
                # Avoid recursive logging if logger itself is slow or DB locked
                # Use a simplified logging or print for now to avoid circular dependency
                # But here we call LoggerService directly.
                user = "Anônimo"
                # Accessing session outside of context might be tricky in some hooks, 
                # but after_request usually has session context.
                from flask import session
                user = session.get('user', 'Anônimo')
                
                LoggerService.log_acao(
                    acao="Slow Request",
                    entidade="Performance",
                    detalhes={
                        "path": request.path,
                        "method": request.method,
                        "duration_seconds": duration,
                        "status_code": response.status_code,
                        "ip": request.remote_addr
                    },
                    nivel_severidade=severity,
                    colaborador_id=user,
                    departamento_id="Sistema"
                )
            except Exception as e:
                print(f"Error logging slow request: {e}")
                
        return response

    return app
