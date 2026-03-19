import re
from pathlib import Path

from app.services.fiscal_pool_service import FiscalPoolService


def test_scheduler_sem_write_direto_cleaning_status():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "services" / "scheduler_service.py").read_text(encoding="utf-8")
    assert re.search(r"with open\([^\n]*cleaning_status\.json[^\n]*['\"]w['\"]", source) is None
    assert "save_cleaning_status(" in source
    assert "load_cleaning_status(" in source


def test_admin_sem_bypass_save_pool_privado():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "blueprints" / "admin" / "routes.py").read_text(encoding="utf-8")
    assert "FiscalPoolService._save_pool(" not in source
    assert "FiscalPoolService.save_pool(" in source


def test_data_service_sem_compat_dinamica_getattr_save_star(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "services" / "data_service.py").read_text(encoding="utf-8")
    assert "def __getattr__" not in source
    assert "data_service.__getattr__" not in source
    monkeypatch.setattr(FiscalPoolService, "_save_pool", lambda _pool: True)
    assert FiscalPoolService.save_pool([{"id": "ok"}]) is True
