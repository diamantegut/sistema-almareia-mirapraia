import json
from datetime import datetime
import pytest
import sys, os

# Ensure project root is on sys.path for 'app' package import
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services import commission_service as cs


@pytest.fixture
def mock_sessions(monkeypatch):
    now = datetime.now().strftime('%d/%m/%Y %H:%M')

    # tx1: venda normal com comissão (sale)
    tx1 = {
        "id": "tx1",
        "type": "sale",
        "amount": 110.0,
        "waiter": "Waiter A",
        "timestamp": now,
        "waiter_breakdown": {"Waiter A": 110.0},
        "description": "Venda Normal"
    }

    # tx2: venda com taxa de serviço removida (sale) -> deve ser ignorada na comissão
    tx2 = {
        "id": "tx2",
        "type": "sale",
        "amount": 100.0,
        "waiter": "Waiter B",
        "timestamp": now,
        "waiter_breakdown": {"Waiter B": 100.0},
        "description": "Venda Sem Comissao [10% Off]",
        "service_fee_removed": True
    }

    # tx3: pagamento de recepção com waiter_breakdown válido (in: Pagamento de Conta)
    tx3 = {
        "id": "tx3",
        "type": "in",
        "category": "Pagamento de Conta",
        "amount": 220.0,
        "timestamp": now,
        "details": {
            "waiter_breakdown": {"Waiter C": 220.0}
        },
        "description": "Fechamento Conta Quarto"
    }

    # tx4: pagamento de recepção com taxa removida e sem breakdown
    tx4 = {
        "id": "tx4",
        "type": "in",
        "category": "Pagamento de Conta",
        "amount": 150.0,
        "timestamp": now,
        "details": {
            "service_fee_removed": True
        },
        "description": "Fechamento Conta Quarto - 10% Off"
    }

    sessions = [{
        "id": "sess_1",
        "status": "closed",
        "transactions": [tx1, tx2, tx3, tx4]
    }]

    def fake_load_cashier_sessions():
        return sessions

    # Patch tanto no módulo de dados quanto diretamente no commission_service (import time binding)
    monkeypatch.setattr("app.services.data_service.load_cashier_sessions", fake_load_cashier_sessions, raising=False)
    monkeypatch.setattr(cs, "load_cashier_sessions", fake_load_cashier_sessions, raising=False)
    return sessions


def test_compute_month_total_commission_ignores_removed_fee(mock_sessions):
    # Commission rate 10%
    month_str = datetime.now().strftime('%Y-%m')
    total = cs.compute_month_total_commission_by_ranking(month_str, commission_rate=10.0)
    # tx1 -> base 110 => 11.0
    # tx2 -> removida => 0.0
    # tx3 -> base 220 => 22.0
    # tx4 -> removida => 0.0 (porque details.service_fee_removed = True)
    assert round(total, 2) == 33.00


def test_is_service_fee_removed_for_transaction_cases():
    assert cs.is_service_fee_removed_for_transaction({"service_fee_removed": True}) is True
    assert cs.is_service_fee_removed_for_transaction({"details": {"service_fee_removed": True}}) is True
    assert cs.is_service_fee_removed_for_transaction({"flags": [{"type": "service_removed"}]}) is True
    assert cs.is_service_fee_removed_for_transaction({"description": "Pedido 10% Off aplicado"}) is True
    assert cs.is_service_fee_removed_for_transaction({"description": "Pedido normal"}) is False
