import json

from app.services import cashier_service


def _configure_cashier_file(monkeypatch, tmp_path):
    sessions_file = tmp_path / "cashier_sessions.json"
    sessions_file.write_text(
        json.dumps(
            [
                {"id": "R1", "status": "open", "type": "restaurant", "transactions": []},
                {"id": "G1", "status": "open", "type": "guest_consumption", "transactions": []},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cashier_service, "CASHIER_SESSIONS_FILE", str(sessions_file))
    return sessions_file


def _load_sessions(path_obj):
    return json.loads(path_obj.read_text(encoding="utf-8"))


def test_contract_normal_restaurant_close(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    tx = cashier_service.CashierService.add_transaction(
        cashier_type="restaurant",
        amount=110.0,
        description="Venda Mesa 70 - Dinheiro",
        payment_method="Dinheiro",
        user="sup1",
        transaction_type="sale",
        details={
            "table_id": "70",
            "close_id": "CLOSE_70_1",
            "category": "Pagamento de Conta",
            "waiter_breakdown": {"garcom1": 110.0},
            "commission_eligible": True,
        },
    )
    assert tx["category"] == "Pagamento de Conta"
    assert tx["commission_eligible"] is True
    assert tx["service_fee_removed"] is False
    assert tx["commission_reference_id"] == "close:CLOSE_70_1"
    sessions = _load_sessions(sessions_file)
    saved = sessions[0]["transactions"][-1]
    assert saved["waiter_breakdown"]["garcom1"] == 110.0


def test_contract_removed_service_fee_not_eligible(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    tx = cashier_service.CashierService.add_transaction(
        cashier_type="restaurant",
        amount=100.0,
        description="Venda Mesa 71 - Pix",
        payment_method="Pix",
        user="sup1",
        transaction_type="sale",
        details={
            "table_id": "71",
            "close_id": "CLOSE_71_1",
            "waiter_breakdown": {"garcom1": 100.0},
            "service_fee_removed": True,
            "category": "Pagamento de Conta",
        },
    )
    assert tx["service_fee_removed"] is True
    assert tx["commission_eligible"] is False
    sessions = _load_sessions(sessions_file)
    saved = sessions[0]["transactions"][-1]
    assert saved["commission_eligible"] is False


def test_contract_multiple_waiters_and_multi_payment_reference(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    group_id = "GROUP_ABC"
    tx1 = cashier_service.CashierService.add_transaction(
        cashier_type="restaurant",
        amount=60.0,
        description="Venda Mesa 72 - Cartão",
        payment_method="Cartão",
        user="sup1",
        transaction_type="sale",
        details={
            "table_id": "72",
            "payment_group_id": group_id,
            "waiter_breakdown": {"garcom1": 60.0, "garcom2": 40.0},
            "category": "Pagamento de Conta",
        },
    )
    tx2 = cashier_service.CashierService.add_transaction(
        cashier_type="restaurant",
        amount=40.0,
        description="Venda Mesa 72 - Dinheiro",
        payment_method="Dinheiro",
        user="sup1",
        transaction_type="sale",
        details={
            "table_id": "72",
            "payment_group_id": group_id,
            "waiter_breakdown": {"garcom1": 60.0, "garcom2": 40.0},
            "category": "Pagamento de Conta",
        },
    )
    assert tx1["commission_reference_id"] == "group:GROUP_ABC"
    assert tx2["commission_reference_id"] == "group:GROUP_ABC"
    sessions = _load_sessions(sessions_file)
    assert len(sessions[0]["transactions"]) == 2


def test_contract_staff_consumption_forces_not_eligible(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    tx = cashier_service.CashierService.add_transaction(
        cashier_type="restaurant",
        amount=16.0,
        description="Consumo Funcionário - JOAO",
        payment_method="Conta Funcionário",
        user="oper1",
        transaction_type="sale",
        details={
            "table_id": "FUNC_JOAO",
            "service_fee_removed": True,
            "category": "Conta Funcionário",
        },
    )
    assert tx["commission_eligible"] is False
    assert tx["service_fee_removed"] is True
    sessions = _load_sessions(sessions_file)
    saved = sessions[0]["transactions"][-1]
    assert saved["category"] == "Conta Funcionário"


def test_contract_reception_payment_promotes_category_from_details(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    tx = cashier_service.CashierService.add_transaction(
        cashier_type="guest_consumption",
        amount=200.0,
        description="Pagamento Quarto 101 (Cartão)",
        payment_method="Cartão",
        user="rec1",
        transaction_type="in",
        details={
            "room_number": "101",
            "category": "Pagamento de Conta",
            "related_charge_id": "CHARGE_101_1",
            "waiter_breakdown": {"garcom1": 200.0},
        },
    )
    assert tx["category"] == "Pagamento de Conta"
    assert tx["commission_eligible"] is True
    assert tx["commission_reference_id"] == "charge:CHARGE_101_1"
    sessions = _load_sessions(sessions_file)
    saved = sessions[1]["transactions"][-1]
    assert saved["category"] == "Pagamento de Conta"


def test_contract_persist_sessions_normalizes_direct_transactions(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_file(monkeypatch, tmp_path)
    sessions = _load_sessions(sessions_file)
    sessions[1]["transactions"].append(
        {
            "id": "MAN_1",
            "type": "in",
            "amount": 150.0,
            "description": "Recebimento Manual Ref. Quarto 102",
            "payment_method": "Outros",
            "timestamp": "17/03/2026 10:30",
            "user": "rec1",
            "details": {
                "category": "Recebimento Manual",
                "room_number": "102",
                "service_fee_removed": False,
            },
        }
    )
    assert cashier_service.CashierService.persist_sessions(sessions, trigger_backup=False) is True
    saved = _load_sessions(sessions_file)[1]["transactions"][-1]
    assert saved["category"] == "Recebimento Manual"
    assert "commission_reference_id" in saved
    assert "commission_contract_version" in saved
