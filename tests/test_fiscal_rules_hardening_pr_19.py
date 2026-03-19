import json
import threading
import time

from app.services import fiscal_pool_service, fiscal_service
import app.services.reservation_service as reservation_service


def _configure_files(monkeypatch, tmp_path):
    pool_file = tmp_path / "fiscal_pool.json"
    pool_file.write_text("[]", encoding="utf-8")
    pending_file = tmp_path / "pending_fiscal_emissions.json"
    pending_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(fiscal_pool_service, "FISCAL_POOL_FILE", str(pool_file))
    monkeypatch.setattr(fiscal_service, "PENDING_EMISSIONS_FILE", str(pending_file))
    monkeypatch.setattr(fiscal_pool_service, "load_menu_items", lambda: [])
    monkeypatch.setattr(
        fiscal_pool_service.FiscalPoolService,
        "sync_entry_to_remote",
        staticmethod(lambda entry: True),
    )
    monkeypatch.setattr(
        fiscal_service,
        "load_fiscal_settings",
        lambda: {
            "integrations": [
                {
                    "provider": "nuvem_fiscal",
                    "cnpj_emitente": "28952732000109",
                    "client_id": "cid",
                    "client_secret": "sec",
                    "ie_emitente": "123456789",
                    "CRT": "1",
                    "environment": "homologation",
                    "sefaz_environment": "homologation",
                    "serie": "1",
                    "next_number": "10",
                }
            ]
        },
    )


def _add_nfce_entry(total_amount=100.0, customer_info=None, notes=None, original_id="MESA_1"):
    return fiscal_pool_service.FiscalPoolService.add_to_pool(
        origin="restaurant",
        original_id=original_id,
        total_amount=total_amount,
        items=[{"id": "1", "name": "Prato", "qty": 1, "price": total_amount, "ncm": "21069090", "cfop": "5102"}],
        payment_methods=[{"method": "Cartão", "amount": total_amount, "is_fiscal": True}],
        user="tester",
        customer_info=customer_info or {},
        notes=notes,
    )


def test_exclusions_are_ignored_by_central_rule(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    e_staff = _add_nfce_entry(total_amount=50.0, customer_info={"type": "funcionario"})
    e_breakfast = _add_nfce_entry(total_amount=70.0, notes="Café da manhã")
    e_courtesy = _add_nfce_entry(total_amount=40.0, notes="Cortesia")
    e_owner = _add_nfce_entry(total_amount=30.0, customer_info={"customer_type": "proprietario"})

    evidence = []
    for eid in [e_staff, e_breakfast, e_courtesy, e_owner]:
        entry = fiscal_pool_service.FiscalPoolService.get_entry(eid)
        assert entry["status"] == "ignored"
        assert float(entry["fiscal_amount"]) == 0.0
        assert entry["eligible_for_fiscal"] is False
        evidence.append(
            {
                "id": eid,
                "status": entry["status"],
                "non_fiscal_reason": entry.get("non_fiscal_reason"),
                "fiscal_amount": entry.get("fiscal_amount"),
            }
        )
    (tmp_path / "evidence_exclusions_ignored.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_amount_above_999_requires_document(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    entry_id = _add_nfce_entry(total_amount=1200.0, customer_info={})
    monkeypatch.setattr(fiscal_service, "emit_invoice", lambda *args, **kwargs: {"success": True, "data": {"id": "NF1", "serie": "1", "numero": "10"}})
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: "x.xml")
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: "x.pdf")
    result = fiscal_service.process_pending_emissions(specific_id=entry_id)
    assert result["failed"] == 1
    entry = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry["status"] == "manual_retry_required"
    assert "CPF/CNPJ obrigatório" in str(entry.get("last_error"))
    (tmp_path / "evidence_above_999_without_doc.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_amount_above_999_with_document_emits(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    entry_id = _add_nfce_entry(total_amount=1200.0, customer_info={"cpf_cnpj": "123.456.789-01"})
    monkeypatch.setattr(fiscal_service, "emit_invoice", lambda *args, **kwargs: {"success": True, "data": {"id": "NF2", "serie": "1", "numero": "11"}})
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: "ok.xml")
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: "ok.pdf")
    result = fiscal_service.process_pending_emissions(specific_id=entry_id)
    assert result["success"] == 1
    entry = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry["status"] == "emitted"


def test_emission_success_without_uuid_goes_to_manual_retry(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    entry_id = _add_nfce_entry(total_amount=150.0, customer_info={"cpf_cnpj": "123.456.789-01"})
    monkeypatch.setattr(
        fiscal_service,
        "emit_invoice",
        lambda *args, **kwargs: {"success": True, "data": {"status": "autorizada", "chave": "26260328952732000109650090000005821234616972"}},
    )
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: None)
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: None)
    result = fiscal_service.process_pending_emissions(specific_id=entry_id)
    assert result["failed"] == 1
    entry = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry["status"] == "manual_retry_required"
    assert "sem UUID fiscal" in str(entry.get("last_error") or "")


def test_reception_guest_above_999_autofills_document_from_reservation(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    monkeypatch.setattr(fiscal_pool_service, "load_room_occupancy", lambda: {"101": {"reservation_id": "R1"}})

    class _ReservationServiceFake:
        def get_reservation_by_id(self, reservation_id):
            return {"id": reservation_id, "doc_id": "123.456.789-01"}

        def get_guest_details(self, reservation_id):
            return {}

    monkeypatch.setattr(reservation_service, "ReservationService", _ReservationServiceFake)
    entry_id = fiscal_pool_service.FiscalPoolService.add_to_pool(
        origin="reception_charge",
        original_id="CHARGE_1",
        total_amount=1500.0,
        items=[{"id": "7", "name": "Jantar", "qty": 1, "price": 1500.0, "ncm": "21069090", "cfop": "5102"}],
        payment_methods=[{"method": "Cartão", "amount": 1500.0, "is_fiscal": True}],
        user="rec1",
        customer_info={"room_number": "101", "guest_name": "Hóspede"},
    )
    entry = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry["customer"]["cpf_cnpj"] == "12345678901"
    monkeypatch.setattr(fiscal_service, "emit_invoice", lambda *args, **kwargs: {"success": True, "data": {"id": "NF3", "serie": "1", "numero": "12"}})
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: "ok.xml")
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: "ok.pdf")
    out = fiscal_service.process_pending_emissions(specific_id=entry_id)
    assert out["success"] == 1
    entry2 = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry2["status"] == "emitted"
    (tmp_path / "evidence_reception_guest_autodoc.json").write_text(
        json.dumps(entry2, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_emission_is_sequential_with_backend_interval(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    e1 = _add_nfce_entry(total_amount=200.0, customer_info={"cpf_cnpj": "12345678901"}, original_id="MESA_2")
    e2 = _add_nfce_entry(total_amount=210.0, customer_info={"cpf_cnpj": "12345678901"}, original_id="MESA_3")
    monkeypatch.setattr(fiscal_service, "EMISSION_MIN_INTERVAL_SECONDS", 0.05)
    times = []

    def _emit_invoice(*args, **kwargs):
        times.append(time.time())
        idx = len(times)
        return {"success": True, "data": {"id": f"NF{idx}", "serie": "1", "numero": str(20 + idx)}}

    monkeypatch.setattr(fiscal_service, "emit_invoice", _emit_invoice)
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: "ok.xml")
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: "ok.pdf")
    result = fiscal_service.process_pending_emissions()
    assert result["success"] == 2
    assert len(times) == 2
    assert (times[1] - times[0]) >= 0.045
    assert fiscal_pool_service.FiscalPoolService.get_entry(e1)["status"] == "emitted"
    assert fiscal_pool_service.FiscalPoolService.get_entry(e2)["status"] == "emitted"


def test_rejected_status_does_not_retry_automatically(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    entry_id = _add_nfce_entry(total_amount=300.0, customer_info={"cpf_cnpj": "12345678901"})
    monkeypatch.setattr(
        fiscal_service,
        "emit_invoice",
        lambda *args, **kwargs: {"success": False, "message": "Rejeição: 539 Duplicidade"},
    )
    first = fiscal_service.process_pending_emissions()
    assert first["failed"] == 1
    entry = fiscal_pool_service.FiscalPoolService.get_entry(entry_id)
    assert entry["status"] == "rejected"
    second = fiscal_service.process_pending_emissions()
    assert second["processed"] == 0
    (tmp_path / "evidence_rejected_no_auto_retry.json").write_text(
        json.dumps(
            {"first": first, "second": second, "entry": entry},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_no_parallel_emission_when_called_concurrently(monkeypatch, tmp_path):
    _configure_files(monkeypatch, tmp_path)
    e1 = _add_nfce_entry(total_amount=220.0, customer_info={"cpf_cnpj": "12345678901"}, original_id="MESA_4")
    e2 = _add_nfce_entry(total_amount=230.0, customer_info={"cpf_cnpj": "12345678901"}, original_id="MESA_5")
    active_lock = threading.Lock()
    active = {"count": 0, "overlap": False, "idx": 0}

    def _emit_invoice(*args, **kwargs):
        with active_lock:
            active["count"] += 1
            if active["count"] > 1:
                active["overlap"] = True
            active["idx"] += 1
            idx = active["idx"]
        time.sleep(0.03)
        with active_lock:
            active["count"] -= 1
        return {"success": True, "data": {"id": f"NF_CONC_{idx}", "serie": "1", "numero": str(40 + idx)}}

    monkeypatch.setattr(fiscal_service, "emit_invoice", _emit_invoice)
    monkeypatch.setattr(fiscal_service, "download_xml", lambda *args, **kwargs: "ok.xml")
    monkeypatch.setattr(fiscal_service, "download_pdf", lambda *args, **kwargs: "ok.pdf")
    t1 = threading.Thread(target=lambda: fiscal_service.process_pending_emissions(specific_id=e1))
    t2 = threading.Thread(target=lambda: fiscal_service.process_pending_emissions(specific_id=e2))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert active["overlap"] is False
    assert fiscal_pool_service.FiscalPoolService.get_entry(e1)["status"] == "emitted"
    assert fiscal_pool_service.FiscalPoolService.get_entry(e2)["status"] == "emitted"
