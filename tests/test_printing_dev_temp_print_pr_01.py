from pathlib import Path

from app.services import printing_service


def _latest_file(path: Path) -> Path:
    files = sorted(path.glob("*.txt"))
    assert files
    return files[-1]


def test_dev_print_order_items_writes_ticket_with_observations_and_accompaniments(tmp_path, monkeypatch):
    monkeypatch.setenv("ALMAREIA_ENV", "development")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        printing_service,
        "load_printers",
        lambda: [{"id": "2", "name": "Cozinha", "ip": "10.10.10.2", "port": 9100, "type": "network"}],
    )

    printers_config = [{"id": "2", "name": "Cozinha", "ip": "10.10.10.2", "port": 9100, "type": "network"}]
    products_db = [{"name": "Parmegiana de Camarão", "printer_id": "2", "should_print": True}]
    items = [
        {
            "id": "it1",
            "name": "Parmegiana de Camarão",
            "qty": 1,
            "observations": ["SEM SAL"],
            "accompaniments": [{"id": "518", "name": "Arroz", "price": 0.0}],
            "questions_answers": [{"question": "Ponto", "answer": "Bem passado"}],
        }
    ]

    result = printing_service.print_order_items("88", "adailton", items, printers_config, products_db)

    assert result["results"]["Cozinha"] == "OK"
    output_dir = tmp_path / "temp_print" / "Cozinha"
    output_file = _latest_file(output_dir)
    content = output_file.read_text(encoding="utf-8")
    assert "print_type: kitchen_order" in content
    assert "table_id: 88" in content
    assert "SEM SAL" in content
    assert "Arroz" in content
    assert "Ponto: Bem passado" in content


def test_dev_print_bill_writes_file_to_bill_printer_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("ALMAREIA_ENV", "development")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        printing_service,
        "get_default_printer",
        lambda role: {"id": "bill1", "name": "Caixa", "type": "network", "ip": "10.10.10.10", "port": 9100}
        if role == "bill"
        else None,
    )
    monkeypatch.setattr(
        printing_service,
        "load_printers",
        lambda: [{"id": "bill1", "name": "Caixa", "type": "network", "ip": "10.10.10.10", "port": 9100}],
    )

    ok, err = printing_service.print_bill(
        printer_config=None,
        table_id="14",
        items=[{"name": "Coca Cola", "qty": 2, "price": 6.0}],
        subtotal=12.0,
        service_fee=1.2,
        total=13.2,
        waiter_name="jose",
    )

    assert ok is True
    assert err is None
    output_dir = tmp_path / "temp_print" / "Caixa"
    output_file = _latest_file(output_dir)
    content = output_file.read_text(encoding="utf-8")
    assert "print_type: bill" in content
    assert "table_id: 14" in content
    assert "TOTAL: R$ 13.20" in content


def test_dev_print_routes_to_correct_printer_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("ALMAREIA_ENV", "development")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        printing_service,
        "load_printers",
        lambda: [
            {"id": "2", "name": "Cozinha", "ip": "10.10.10.2", "port": 9100, "type": "network"},
            {"id": "3", "name": "Bar", "ip": "10.10.10.3", "port": 9100, "type": "network"},
        ],
    )

    printers_config = [
        {"id": "2", "name": "Cozinha", "ip": "10.10.10.2", "port": 9100, "type": "network"},
        {"id": "3", "name": "Bar", "ip": "10.10.10.3", "port": 9100, "type": "network"},
    ]
    products_db = [{"name": "Caipirinha", "printer_id": "3", "should_print": True}]
    items = [{"id": "it2", "name": "Caipirinha", "qty": 1}]

    result = printing_service.print_order_items("31", "maria", items, printers_config, products_db)

    assert result["results"]["Bar"] == "OK"
    assert (tmp_path / "temp_print" / "Bar").exists()
    assert not (tmp_path / "temp_print" / "Cozinha").exists()


def test_production_uses_network_path_not_temp_print(tmp_path, monkeypatch):
    class _FakeSocket:
        connect_calls = []
        sent_payloads = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, value):
            return None

        def connect(self, target):
            _FakeSocket.connect_calls.append(target)

        def sendall(self, payload):
            _FakeSocket.sent_payloads.append(payload)

    monkeypatch.setenv("ALMAREIA_ENV", "production")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "0")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(printing_service.socket, "socket", lambda *args, **kwargs: _FakeSocket())

    ok, err = printing_service.send_to_printer("10.10.10.9", 9100, b"abc")

    assert ok is True
    assert err is None
    assert _FakeSocket.connect_calls == [("10.10.10.9", 9100)]
    assert _FakeSocket.sent_payloads == [b"abc"]
    assert not (tmp_path / "temp_print").exists()


def test_production_ignores_dev_flag_and_stays_fail_safe(tmp_path, monkeypatch):
    class _FakeSocket:
        connect_calls = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, value):
            return None

        def connect(self, target):
            _FakeSocket.connect_calls.append(target)

        def sendall(self, payload):
            return None

    monkeypatch.setenv("ALMAREIA_ENV", "production")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(printing_service.socket, "socket", lambda *args, **kwargs: _FakeSocket())

    status = printing_service.get_print_mode_status()
    ok, err = printing_service.send_to_printer("10.10.10.20", 9100, b"payload")

    assert status["runtime_env"] == "production"
    assert status["dev_disk_print_enabled"] is False
    assert status["reason"] == "production_fail_safe"
    assert ok is True
    assert err is None
    assert _FakeSocket.connect_calls == [("10.10.10.20", 9100)]
    assert not (tmp_path / "temp_print").exists()


def test_print_mode_startup_log_reports_active_mode(monkeypatch, caplog):
    monkeypatch.setenv("ALMAREIA_ENV", "production")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")

    with caplog.at_level("INFO"):
        status = printing_service.log_print_mode_startup()

    assert status["runtime_env"] == "production"
    assert status["dev_disk_print_enabled"] is False
    assert "PRINT_MODE active=physical_printer runtime_env=production reason=production_fail_safe" in caplog.text


def test_app_env_development_is_ignored_without_almareia_env(tmp_path, monkeypatch):
    class _FakeSocket:
        connect_calls = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, value):
            return None

        def connect(self, target):
            _FakeSocket.connect_calls.append(target)

        def sendall(self, payload):
            return None

    monkeypatch.delenv("ALMAREIA_ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALMAREIA_DEV_PRINT_MODE", "1")
    monkeypatch.setattr(printing_service, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(printing_service.socket, "socket", lambda *args, **kwargs: _FakeSocket())

    status = printing_service.get_print_mode_status()
    ok, err = printing_service.send_to_printer("10.10.10.30", 9100, b"payload")

    assert status["runtime_env"] == "production"
    assert status["dev_disk_print_enabled"] is False
    assert ok is True
    assert err is None
    assert _FakeSocket.connect_calls == [("10.10.10.30", 9100)]
    assert not (tmp_path / "temp_print").exists()
