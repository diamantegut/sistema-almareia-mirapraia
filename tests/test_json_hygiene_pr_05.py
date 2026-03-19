import re
from pathlib import Path

from app.services.fiscal_pool_service import FiscalPoolService


def test_fontes_sem_open_write_json_dump_em_blueprints_alvo():
    root = Path(__file__).resolve().parents[1]
    governance = (root / "app" / "blueprints" / "governance" / "routes.py").read_text(encoding="utf-8")
    kitchen = (root / "app" / "blueprints" / "kitchen.py").read_text(encoding="utf-8")
    assert re.search(r"open\([^\n]*['\"]w['\"]", governance) is None
    assert "json.dump(" not in governance
    assert re.search(r"open\([^\n]*['\"]w['\"]", kitchen) is None
    assert "json.dump(" not in kitchen


def test_fiscal_pool_sem_bypass_privado_data_service():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "services" / "fiscal_pool_service.py").read_text(encoding="utf-8")
    assert "_backup_before_write" not in source
    assert "_save_json_atomic" not in source
    assert "with open(FISCAL_POOL_FILE, 'w'" not in source


def test_setters_fiscal_pool_persistem_via_save_pool(monkeypatch):
    sample = [{"id": "X1", "status": "pending", "history": []}]
    calls = {"count": 0}

    monkeypatch.setattr(FiscalPoolService, "_load_pool", lambda: [dict(sample[0])])

    def _save_spy(pool):
        calls["count"] += 1
        return isinstance(pool, list) and bool(pool)

    monkeypatch.setattr(FiscalPoolService, "_save_pool", _save_spy)
    assert FiscalPoolService.set_xml_ready("X1", ready=True, xml_path="a.xml") is True
    assert FiscalPoolService.set_pdf_ready("X1", ready=True, pdf_path="a.pdf") is True
    assert calls["count"] == 2
