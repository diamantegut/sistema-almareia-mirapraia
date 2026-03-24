from app.services import stock_nfe_repository_service as repo


def _sample_doc(nsu: str, key: str):
    return {
        "nsu": nsu,
        "access_key": key,
        "created_at": "2026-01-15T10:00:00",
        "issued_at": "2026-01-15T09:00:00",
        "total_amount": 123.45,
        "emitente": {"nome": "Fornecedor Teste", "cpf_cnpj": "12345678000199"},
        "xml_content": "<NFe></NFe>",
    }


def test_repository_ingest_dedup_and_status_update(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    result_first = repo.ingest_documents(
        documents=[_sample_doc("100", "KEY100")],
        source_method="lastNSU",
        correlation_id="corr-1",
    )
    result_second = repo.ingest_documents(
        documents=[_sample_doc("100", "KEY100"), _sample_doc("101", "KEY101")],
        source_method="lastNSU",
        correlation_id="corr-2",
    )
    assert int(result_first.get("new") or 0) == 1
    assert int(result_second.get("new") or 0) == 1
    assert int(result_second.get("duplicates") or 0) == 1
    listed = repo.list_notes(limit=10)
    assert len(listed) == 2
    assert repo.update_note_conference("KEY101", "in_conference") is True
    assert repo.update_note_conference("KEY101", "conferenced") is True
    assert repo.mark_note_imported("KEY101") is True
    loaded = repo.get_note_by_access_key("KEY101")
    assert loaded is not None
    assert loaded.get("status_estoque") == "imported"


def test_repository_classifies_full_and_summarized_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    full_xml = """
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
      <NFe><infNFe Id="NFeKEYFULL"><det nItem="1"><prod><cProd>A</cProd><xProd>ITEM A</xProd><qCom>1</qCom><uCom>UN</uCom><vUnCom>10</vUnCom></prod></det></infNFe></NFe>
    </nfeProc>
    """
    summary_xml = "<resNFe></resNFe>"
    repo.ingest_documents(
        documents=[
            {**_sample_doc("150", "KEYFULL"), "xml_content": full_xml, "items": []},
            {**_sample_doc("151", "KEYSUM"), "xml_content": summary_xml, "items": []},
        ],
        source_method="lastNSU",
        correlation_id="corr-classify",
    )
    full_note = repo.get_note_by_access_key("KEYFULL") or {}
    summary_note = repo.get_note_by_access_key("KEYSUM") or {}
    assert full_note.get("document_type") == "full_nfe"
    assert full_note.get("has_full_items") is True
    assert full_note.get("completeness_status") == "ready_for_conference"
    assert summary_note.get("document_type") == "summarized_nfe"
    assert summary_note.get("has_full_items") is False
    assert summary_note.get("items_reason") == "document_summary_without_det"
    assert summary_note.get("completeness_status") == "awaiting_manifestation"


def test_repository_sync_last_nsu_and_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    from app.services import fiscal_service
    monkeypatch.setattr(
        fiscal_service,
        "list_received_nfes",
        lambda settings: ([_sample_doc("200", "KEY200"), _sample_doc("201", "KEY201")], None),
    )
    ok_result = repo.synchronize_last_nsu(settings={"provider": "sefaz_direto"}, initiated_by="tester")
    assert ok_result.get("success") is True
    assert int(ok_result.get("synced_count") or 0) == 2
    monkeypatch.setattr(fiscal_service, "list_received_nfes", lambda settings: (None, "Consumo Indevido 656"))
    err_result = repo.synchronize_last_nsu(settings={"provider": "sefaz_direto"}, initiated_by="tester")
    assert err_result.get("success") is False
    state = repo.get_sync_state()
    assert state.get("cooldown_ate")


def test_manifestation_registration_and_full_download_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[{**_sample_doc("210", "KEY210"), "xml_content": "<resNFe></resNFe>", "items": []}],
        source_method="lastNSU",
        correlation_id="corr-manif",
    )
    assert repo.register_note_manifestation(
        access_key="KEY210",
        manifestation_type="ciencia_da_operacao",
        result="registered",
        initiated_by="tester",
    )
    note = repo.get_note_by_access_key("KEY210") or {}
    assert note.get("manifestation_status") == "registered"
    assert note.get("completeness_status") == "awaiting_full_download"
    assert repo.register_full_download_attempt(
        access_key="KEY210",
        outcome="failed",
        detail="document_summary_without_det",
        initiated_by="tester",
    )
    note_after = repo.get_note_by_access_key("KEY210") or {}
    assert int(note_after.get("full_download_attempts") or 0) >= 1
    assert note_after.get("full_download_last_result") == "failed"


def test_checkpoint_not_advanced_on_partial_error_and_no_dup_by_key(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    from app.services import fiscal_service
    monkeypatch.setattr(
        fiscal_service,
        "list_received_nfes",
        lambda settings: ([_sample_doc("500", "KEY500"), {"nsu": "501", "access_key": "", "xml_content": "<NFe></NFe>"}], None),
    )
    result = repo.synchronize_last_nsu(settings={"provider": "sefaz_direto"}, initiated_by="tester")
    assert result.get("success") is False
    state = repo.get_sync_state()
    assert str(state.get("ultimo_nsu_processado") or "0") in {"0", ""}
    assert len(repo.list_notes(limit=50)) == 0

    monkeypatch.setattr(
        fiscal_service,
        "list_received_nfes",
        lambda settings: ([_sample_doc("600", "KEY600"), _sample_doc("601", "KEY600")], None),
    )
    dup_key = repo.synchronize_last_nsu(settings={"provider": "sefaz_direto"}, initiated_by="tester")
    assert dup_key.get("success") is True
    notes = repo.list_notes(limit=50)
    assert len(notes) == 1
    assert str(notes[0].get("chave_nfe") or "") == "KEY600"


def test_detect_nsu_gaps_and_assisted_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[_sample_doc("700", "KEY700"), _sample_doc("702", "KEY702")],
        source_method="lastNSU",
        correlation_id="corr-gap",
    )
    gaps = repo.detect_nsu_gaps()
    assert any(str(g.get("nsu") or "") == "701" for g in gaps)
    assert any(
        str(g.get("nsu") or "") == "701" and str(g.get("classification") or "") == "ainda_nao_conclusivo"
        for g in gaps
    )

    from app.services import fiscal_service
    monkeypatch.setattr(
        fiscal_service,
        "recover_missing_notes",
        lambda start, end, settings: ([_sample_doc("701", "KEY701")], None),
    )
    rec = repo.synchronize_specific_nsu(settings={"provider": "sefaz_direto"}, nsu="701", initiated_by="tester")
    assert rec.get("success") is True
    assert rec.get("verification_outcome") == "recovered_document"
    gaps_after = repo.list_nsu_gaps(status="resolved", limit=50)
    assert any(str(g.get("nsu") or "") == "701" for g in gaps_after)

    repo.ingest_documents(
        documents=[_sample_doc("798", "KEY798"), _sample_doc("800", "KEY800")],
        source_method="lastNSU",
        correlation_id="corr-gap-2",
    )
    monkeypatch.setattr(
        fiscal_service,
        "recover_missing_notes",
        lambda start, end, settings: (None, "cStat 137 - nenhum documento"),
    )
    rec_137 = repo.synchronize_specific_nsu(settings={"provider": "sefaz_direto"}, nsu="799", initiated_by="tester")
    assert rec_137.get("success") is True
    assert rec_137.get("verification_outcome") == "no_document_137"
    ignored = repo.list_nsu_gaps(status="ignored", limit=50)
    assert any(str(g.get("nsu") or "") == "799" for g in ignored)


def test_gap_assisted_sample_counts_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[_sample_doc("900", "KEY900"), _sample_doc("902", "KEY902"), _sample_doc("904", "KEY904")],
        source_method="lastNSU",
        correlation_id="corr-sample",
    )
    repo.detect_nsu_gaps()
    from app.services import fiscal_service

    def _recover_stub(start, end, settings):
        if str(start) == "901":
            return ([_sample_doc("901", "KEY901")], None)
        if str(start) == "903":
            return (None, "cStat 137 - nenhum documento")
        return ([], None)

    monkeypatch.setattr(fiscal_service, "recover_missing_notes", _recover_stub)
    report = repo.run_assisted_gap_sample(
        settings={"provider": "sefaz_direto"},
        initiated_by="tester",
        sample_size=2,
    )
    summary = report.get("summary") or {}
    assert int(summary.get("sample_size") or 0) == 2
    assert int(summary.get("document_returned") or 0) == 1
    assert int(summary.get("cstat_137") or 0) == 1
    assert int(summary.get("recoverable") or 0) == 1


def test_supplier_match_item_binding_and_manual_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[_sample_doc("300", "KEY300")],
        source_method="lastNSU",
        correlation_id="corr-3",
    )
    suppliers = [
        {"id": "s1", "name": "Fornecedor Teste", "cnpj": "12.345.678/0001-99"},
        {"id": "s2", "name": "Outro", "cnpj": "00000000000000"},
    ]
    suggestion = repo.suggest_supplier_for_note(
        cnpj_emitente="12345678000199",
        nome_emitente="Fornecedor Teste",
        suppliers=suppliers,
    )
    assert suggestion.get("matched") is True
    assert suggestion.get("confidence") == "high"
    assert repo.bind_note_supplier(access_key="KEY300", supplier_id="s1", status_match_fornecedor="auto_matched") is True
    assert repo.bind_note_item(
        access_key="KEY300",
        item_index=0,
        supplier_id="s1",
        product_id="p1",
        supplier_product_code="A1",
        supplier_product_name="ARROZ",
        unidade_fornecedor="CX",
        unidade_estoque="UN",
        fator_conversao=12.0,
        is_preferred=True,
    ) is True
    suggested_binding = repo.suggest_item_binding(
        supplier_id="s1",
        supplier_product_code="A1",
        supplier_product_name="ARROZ",
    )
    assert suggested_binding is not None
    assert suggested_binding.get("confidence") in {"high", "medium", "low"}
    manual = repo.create_manual_entry(
        supplier_id="s1",
        supplier_name="Fornecedor Teste",
        document_type="manual_entry",
        document_number="",
        observation="entrada sem nfe",
        entry_date="2026-01-16",
        items=[{"name": "Farinha", "qty": 2, "unit": "KG", "cost": 10}],
        created_by="tester",
    )
    assert manual.get("origin_type") == "manual"
    listed_manual = repo.list_manual_entries(limit=10)
    assert len(listed_manual) == 1
    assert repo.update_manual_entry_status(str(manual.get("id") or ""), "imported") is True


def test_assisted_conference_analysis_with_divergence_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[_sample_doc("310", "KEY310")],
        source_method="lastNSU",
        correlation_id="corr-31",
    )
    repo.bind_note_supplier(
        access_key="KEY310",
        supplier_id="s1",
        status_match_fornecedor="manual_matched",
        suggestion_used=True,
        supplier_match_source="history_match",
    )
    repo.bind_note_item(
        access_key="KEY310",
        item_index=0,
        supplier_id="s1",
        product_id="p1",
        supplier_product_code="COD-001",
        supplier_product_name="ITEM A",
        unidade_fornecedor="CX",
        unidade_estoque="UN",
        fator_conversao=12.0,
        is_preferred=True,
        suggestion_used=True,
        item_match_source="supplier_product_code",
        accepted_conversion=True,
    )
    note = repo.get_note_by_access_key("KEY310")
    parsed_items = [
        {"code": "COD-001", "name": "ITEM A", "unit": "CX", "qty": 1, "price": 10},
        {"code": "COD-999", "name": "ITEM DESCONHECIDO", "unit": "KG", "qty": 2, "price": 3},
    ]
    assist = repo.analyze_note_conference_assist(note=note or {}, parsed_items=parsed_items, supplier_id="s1")
    assert isinstance(assist.get("items"), list)
    assert len(assist.get("items") or []) == 2
    summary = assist.get("summary") or {}
    assert int(summary.get("items_total") or 0) == 2
    assert "cta" in summary
