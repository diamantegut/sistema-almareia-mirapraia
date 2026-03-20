import json
import errno
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import cashier_service
from app.services import data_service


def _configure_cashier_paths(monkeypatch, tmp_path):
    sessions_file = tmp_path / "cashier_sessions.json"
    sessions_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cashier_service, "CASHIER_SESSIONS_FILE", str(sessions_file))
    monkeypatch.setattr(data_service, "_get_cashier_sessions_path", lambda: str(sessions_file))
    return sessions_file


def test_data_service_save_cashier_sessions_delega_ao_owner(monkeypatch, tmp_path):
    _configure_cashier_paths(monkeypatch, tmp_path)
    calls = {"count": 0}
    owner_impl = cashier_service.CashierService.persist_sessions

    def _spy(sessions, trigger_backup=False):
        calls["count"] += 1
        return owner_impl(sessions, trigger_backup=trigger_backup)

    monkeypatch.setattr(cashier_service.CashierService, "persist_sessions", _spy)
    payload = [{"id": "S1", "status": "open", "type": "guest_consumption", "transactions": []}]
    ok = data_service.save_cashier_sessions(payload)
    assert ok is True
    assert calls["count"] == 1


def test_owner_persist_sessions_escreve_e_data_service_le(monkeypatch, tmp_path):
    _configure_cashier_paths(monkeypatch, tmp_path)
    payload = [{"id": "S2", "status": "closed", "type": "restaurant", "transactions": [], "difference": 0}]
    assert cashier_service.CashierService.persist_sessions(payload, trigger_backup=False) is True
    loaded = data_service.load_cashier_sessions()
    assert isinstance(loaded, list)
    assert loaded[0]["id"] == "S2"
    assert loaded[0]["status"] == "closed"


def test_sem_chamada_save_cashier_sessions_nas_rotas_alvo():
    project_root = Path(__file__).resolve().parents[1]
    reception_source = (project_root / "app" / "blueprints" / "reception" / "routes.py").read_text(encoding="utf-8")
    finance_source = (project_root / "app" / "blueprints" / "finance" / "routes.py").read_text(encoding="utf-8")
    assert "save_cashier_sessions(" not in reception_source
    assert "save_cashier_sessions(" not in finance_source
    assert "CashierService.persist_sessions(" in reception_source
    assert "CashierService.persist_sessions(" in finance_source


def test_concorrencia_basica_persistencia_cashier_sessions(monkeypatch, tmp_path):
    sessions_file = _configure_cashier_paths(monkeypatch, tmp_path)

    def _writer(i):
        sessions = cashier_service.CashierService.list_sessions()
        sessions.append(
            {
                "id": f"S{i}",
                "status": "open",
                "type": "guest_consumption",
                "transactions": [],
            }
        )
        return cashier_service.CashierService.persist_sessions(sessions, trigger_backup=False)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_writer, range(20)))

    assert any(results)
    parsed = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)


def test_file_lock_fallback_em_pasta_temp_quando_lock_no_destino_sem_permissao(monkeypatch, tmp_path):
    target_file = tmp_path / "manual_allocations.json"
    target_file.write_text("{}", encoding="utf-8")
    target_lock = f"{target_file}.lock"
    fallback_lock = cashier_service._resolve_fallback_lock_path(str(target_file))
    real_open = cashier_service.os.open
    calls = {"target": 0, "fallback": 0}

    def _open(path, flags):
        if path == target_lock:
            calls["target"] += 1
            raise PermissionError(errno.EACCES, "Permission denied", path)
        if path == fallback_lock:
            calls["fallback"] += 1
        return real_open(path, flags)

    monkeypatch.setattr(cashier_service.os, "open", _open)

    with cashier_service.file_lock(str(target_file), timeout=2):
        assert Path(fallback_lock).exists()

    assert calls["target"] >= 1
    assert calls["fallback"] >= 1
    assert not Path(fallback_lock).exists()


def test_file_lock_fallback_quando_permission_error_sem_errno(monkeypatch, tmp_path):
    target_file = tmp_path / "manual_allocations.json"
    target_file.write_text("{}", encoding="utf-8")
    target_lock = f"{target_file}.lock"
    fallback_lock = cashier_service._resolve_fallback_lock_path(str(target_file))
    real_open = cashier_service.os.open
    calls = {"target": 0, "fallback": 0}

    def _open(path, flags):
        if path == target_lock:
            calls["target"] += 1
            raise PermissionError(None, "Access denied", path)
        if path == fallback_lock:
            calls["fallback"] += 1
        return real_open(path, flags)

    monkeypatch.setattr(cashier_service.os, "open", _open)

    with cashier_service.file_lock(str(target_file), timeout=2):
        assert Path(fallback_lock).exists()

    assert calls["target"] >= 1
    assert calls["fallback"] >= 1
    assert not Path(fallback_lock).exists()
