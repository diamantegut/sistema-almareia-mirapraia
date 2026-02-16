import sys
from importlib import import_module

_MODULE_NAMES = [
    'cashier_service',
    'transfer_service',
    'closed_account_service',
    'fiscal_pool_service',
    'backup_service',
    'logging_service',
]

for _name in _MODULE_NAMES:
    _full = f'app.services.{_name}'
    _mod = import_module(_full)
    sys.modules[f'services.{_name}'] = _mod
