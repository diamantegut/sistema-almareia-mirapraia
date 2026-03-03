import os
import sys
from flask import Flask
from app.models.database import db


def create_app(config_name=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = os.environ.get('SECRET_KEY', 'chave_secreta_almareia_hotel')
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    db_path = os.path.join(data_dir, 'department_logs.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    from app.services.data_service import format_room_number

    @app.template_filter('format_room')
    def format_room_filter(s):
        return format_room_number(s)

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
    from app.blueprints.assets import assets_bp
    app.register_blueprint(assets_bp)
    from app.blueprints.guest_portal import guest_portal_bp
    app.register_blueprint(guest_portal_bp)
    from app.services.logger_service import LoggerService
    LoggerService.init_app(app)
    
    # Start Scheduler
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            from app.services.scheduler_service import start_scheduler
            start_scheduler()
        except Exception as e:
            print(f"Failed to start scheduler: {e}")

    import time
    from flask import request, g

    @app.before_request
    def start_timer():
        g.start = time.time()

    @app.before_request
    def enforce_permissions():
        try:
            from app.services.permission_service import enforce_request_access
            return enforce_request_access()
        except Exception:
            return None

    @app.after_request
    def log_request(response):
        if request.path.startswith('/static'):
            return response
        now = time.time()
        duration = round(now - g.start, 2)
        if duration > 1.0:
            severity = 'WARNING' if duration < 5.0 else 'CRITICAL'
            try:
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


app = create_app()

from app.services.system_config_manager import (
    get_data_path,
    PAYABLES_FILE,
    SUPPLIERS_FILE,
    CASHIER_SESSIONS_FILE,
    ROOM_CHARGES_FILE,
    ROOM_OCCUPANCY_FILE,
    TABLE_ORDERS_FILE,
    USERS_FILE,
    AUDIT_LOGS_FILE,
    ACTION_LOGS_DIR,
)
from app.services.data_service import (
    format_room_number,
    load_payables,
    save_payables,
    load_cashier_sessions,
    save_cashier_sessions,
    load_table_orders,
    save_table_orders,
    load_menu_items,
    save_menu_items,
    load_payment_methods,
    save_payment_methods,
    load_users,
    save_users,
    load_room_charges,
    save_room_charges,
    load_room_occupancy,
    save_room_occupancy,
    load_audit_logs,
    save_audit_logs,
    normalize_room_simple,
)
from app.services.commission_service import (
    load_commission_cycles,
    save_commission_cycles,
)
from app.services.cashier_service import CashierService
from app.services.printer_manager import load_printers, load_printer_settings, save_printer_settings
import app.services.commission_service as _commission_module
import app.services.cashier_service as _cashier_module
import app.services.printing_service as _printing_module
import app.services.guest_notification_service as _guest_notification_module
import app.services.security_service as _security_service_module
import app.services.waiting_list_service as _waiting_list_module
import app.models.database as _database_module
import app.models.models as _models_module
import app.services.logger_service as _logger_service_module
from app.utils.logger import log_action as _legacy_log_action
import types

sys.modules.setdefault('commission_service', _commission_module)
sys.modules.setdefault('printing_service', _printing_module)
sys.modules.setdefault('guest_notification_service', _guest_notification_module)
sys.modules.setdefault('security_service', _security_service_module)
sys.modules.setdefault('waiting_list_service', _waiting_list_module)
sys.modules.setdefault('database', _database_module)
sys.modules.setdefault('models', _models_module)
sys.modules.setdefault('logger_service', _logger_service_module)

services_pkg = sys.modules.get('services')
if services_pkg is None:
    services_pkg = types.ModuleType('services')
    sys.modules['services'] = services_pkg

sys.modules.setdefault('services.cashier_service', _cashier_module)
setattr(services_pkg, 'cashier_service', _cashier_module)
setattr(services_pkg, 'transfer_service', __import__('app.services.transfer_service', fromlist=['*']))
setattr(services_pkg, 'closed_account_service', __import__('app.services.closed_account_service', fromlist=['*']))
sys.modules.setdefault('services.closed_account_service', sys.modules['app.services.closed_account_service'])

for _mod_name in (
    'fiscal_pool_service',
    'fiscal_service',
    'logging_service',
):
    _mod = __import__(f'app.services.{_mod_name}', fromlist=['*'])
    setattr(services_pkg, _mod_name, _mod)
    sys.modules.setdefault(f'services.{_mod_name}', _mod)

log_action = _legacy_log_action
