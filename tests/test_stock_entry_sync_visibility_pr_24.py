from app import create_app
from app.services import stock_nfe_repository_service as repo
from app.blueprints import stock as stock_module
from pathlib import Path


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


def _client_with_login():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "tester"
        sess["role"] = "admin"
        sess["department"] = "Estoque"
        sess["permissions"] = ["estoque"]
    return client


def test_sync_visibility_endpoints_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    from app.services import fiscal_service
    monkeypatch.setattr(
        fiscal_service,
        "list_received_nfes",
        lambda settings: ([_sample_doc("900", "KEY900"), _sample_doc("902", "KEY902")], None),
    )
    sync_result = repo.synchronize_last_nsu(settings={"provider": "sefaz_direto"}, initiated_by="tester")
    assert sync_result.get("success") is True
    repo.detect_nsu_gaps()
    client = _client_with_login()
    state_response = client.get("/stock/nfe/sync-state")
    assert state_response.status_code == 200
    state_payload = state_response.get_json()
    assert "sync_state" in state_payload
    assert "status" in state_payload
    assert "ultimo_erro" in state_payload

    audit_response = client.get("/stock/nfe/sync-audit")
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    assert "rows" in audit_payload
    assert isinstance(audit_payload.get("rows"), list)
    assert "summary" in audit_payload

    gaps_response = client.get("/stock/nfe/gaps")
    assert gaps_response.status_code == 200
    gaps_payload = gaps_response.get_json()
    assert "rows" in gaps_payload
    assert "summary" in gaps_payload
    assert any(str(row.get("nsu") or "") == "901" for row in gaps_payload.get("rows") or [])


def test_stock_entry_template_has_quick_review_mode():
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "stock_entry.html"
    content = template_path.read_text(encoding="utf-8")
    assert "Modo revisão rápida" in content
    assert "function activateQuickReviewMode()" in content
    assert "Lançar entrada no estoque" in content
    assert "conferenceDocumentBadge" in content
    assert "conferenceCompletenessBadge" in content
    assert "registerConferenceManifestation" in content
    assert "attemptFullXmlDownload" in content


def test_certificate_status_endpoint_returns_safe_runtime_info(monkeypatch):
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto"})
    monkeypatch.setattr(
        stock_module,
        "get_sefaz_certificate_runtime_status",
        lambda settings: {
            "provider": "sefaz_direto",
            "environment": "production",
            "cnpj_emitente": "12345678000199",
            "certificate_configured": True,
            "configured_path": "cert.pfx",
            "resolved_path": "C:/cert.pfx",
            "file_exists": True,
            "file_size_bytes": 2048,
            "password_source": "env:SEFAZ_CERT_PASSWORD",
            "password_env_name_used": "SEFAZ_CERT_PASSWORD",
            "load_success": True,
            "error": "",
            "certificate": {"fingerprint_sha256": "ABCDEF", "subject": "CN=Empresa", "issuer": "CN=AC", "serial_number": "123", "valid_from": "2026-01-01", "valid_to": "2027-01-01"},
        },
    )
    client = _client_with_login()
    resp = client.get("/stock/fiscal/certificate-status")
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    assert payload.get("success") is True
    status = payload.get("status") or {}
    assert status.get("password_source") == "env:SEFAZ_CERT_PASSWORD"
    assert (status.get("certificate") or {}).get("fingerprint_sha256") == "ABCDEF"


def test_repository_load_fallback_and_iniciar_conferencia(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[
            {
                "nsu": "990",
                "access_key": "KEY990",
                "created_at": "2026-01-15T10:00:00",
                "issued_at": "2026-01-15T09:00:00",
                "total_amount": 321.0,
                "emitente": {"nome": "Fornecedor XML Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [{"cProd": "A1", "xProd": "ARROZ", "qCom": 2, "uCom": "UN", "vUnCom": 10.5}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-load-fallback",
    )
    client = _client_with_login()
    load_response = client.post("/stock/nfe/repository/load", json={"access_key": "KEY990"})
    assert load_response.status_code == 200
    load_payload = load_response.get_json() or {}
    assert load_payload.get("access_key") == "KEY990"
    assert "request_id" in load_payload
    assert isinstance(load_payload.get("items"), list)
    assert isinstance(load_payload.get("conference_items"), list)
    assert (load_payload.get("conference_items") or [{}])[0].get("descricao_fiscal")
    assert isinstance(load_payload.get("supplier_options"), list)
    assert "items_loaded" in load_payload

    start_response = client.post("/stock/nfe/repository/conference", json={"access_key": "KEY990", "status": "in_conference"})
    assert start_response.status_code == 200
    start_payload = start_response.get_json() or {}
    assert start_payload.get("success") is True
    assert "request_id" in start_payload

    item_status_response = client.post(
        "/stock/nfe/repository/item-review",
        json={"access_key": "KEY990", "item_index": 0, "status": "conferido"},
    )
    assert item_status_response.status_code == 200
    assert (item_status_response.get_json() or {}).get("success") is True


def test_repository_load_reprocess_local_extracts_items_from_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    xml = """
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
      <NFe>
        <infNFe Id="NFeKEY991">
          <ide><nNF>123</nNF><serie>1</serie><dhEmi>2026-01-15T10:00:00-03:00</dhEmi></ide>
          <emit><xNome>Fornecedor XML</xNome><CNPJ>12345678000199</CNPJ></emit>
          <det nItem="1">
            <prod><cProd>P1</cProd><xProd>FEIJAO</xProd><qCom>3.0000</qCom><uCom>UN</uCom><vUnCom>12.50</vUnCom><vProd>37.50</vProd><NCM>10063010</NCM><CFOP>5102</CFOP></prod>
          </det>
          <total><ICMSTot><vNF>37.50</vNF></ICMSTot></total>
        </infNFe>
      </NFe>
    </nfeProc>
    """
    repo.ingest_documents(
        documents=[
            {
                "nsu": "991",
                "access_key": "KEY991",
                "created_at": "2026-01-15T10:00:00",
                "issued_at": "2026-01-15T09:00:00",
                "total_amount": 37.5,
                "emitente": {"nome": "Fornecedor XML", "cpf_cnpj": "12345678000199"},
                "xml_content": xml,
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-load-reprocess",
    )
    client = _client_with_login()
    load_response = client.post("/stock/nfe/repository/load", json={"access_key": "KEY991", "reprocess_local": True})
    assert load_response.status_code == 200
    payload = load_response.get_json() or {}
    assert payload.get("items_loaded") is True
    assert (payload.get("conference_items") or [{}])[0].get("codigo_fornecedor") == "P1"
    assert (payload.get("conference_items") or [{}])[0].get("ncm") == "10063010"


def test_repository_load_reprocess_local_from_storage_when_note_is_resumo(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    xml_storage = tmp_path / "fiscal" / "xmls" / "received" / "2026" / "03"
    xml_storage.mkdir(parents=True, exist_ok=True)
    access_key = "26260308305623000184550010008933751210119451"
    full_xml = f"""
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
      <NFe>
        <infNFe Id="NFe{access_key}">
          <ide><nNF>893375</nNF><serie>1</serie><dhEmi>2026-03-20T10:00:00-03:00</dhEmi></ide>
          <emit><xNome>Fornecedor Completo</xNome><CNPJ>12345678000199</CNPJ></emit>
          <det nItem="1"><prod><cProd>ABC01</cProd><xProd>ARROZ TIPO 1</xProd><qCom>10</qCom><uCom>UN</uCom><vUnCom>5.90</vUnCom><vProd>59.00</vProd><NCM>10063010</NCM><CFOP>1102</CFOP></prod></det>
          <total><ICMSTot><vNF>59.00</vNF></ICMSTot></total>
        </infNFe>
      </NFe>
    </nfeProc>
    """
    (xml_storage / f"{access_key}.xml").write_text(full_xml, encoding="utf-8")
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "xml_storage_path": str(tmp_path / "fiscal" / "xmls")})
    repo.ingest_documents(
        documents=[
            {
                "nsu": "992",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 59.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-load-resumo-reprocess",
    )
    client = _client_with_login()
    pre_response = client.post("/stock/nfe/repository/load", json={"access_key": access_key})
    assert pre_response.status_code == 200
    pre_payload = pre_response.get_json() or {}
    assert pre_payload.get("document_type") == "summarized_nfe"
    assert pre_payload.get("has_full_items") is False
    assert pre_payload.get("completeness_status") == "awaiting_manifestation"
    response = client.post("/stock/nfe/repository/load", json={"access_key": access_key, "reprocess_local": True})
    assert response.status_code == 200
    payload = response.get_json() or {}
    assert payload.get("items_loaded") is True
    assert payload.get("document_type") == "full_nfe"
    assert payload.get("has_full_items") is True
    assert payload.get("completeness_status") == "ready_for_conference"
    assert payload.get("parse_diagnostics", {}).get("source") == "reprocess_local_xml"
    assert (payload.get("conference_items") or [{}])[0].get("codigo_fornecedor") == "ABC01"


def test_repository_manifestation_registration_updates_note_state(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    repo.ingest_documents(
        documents=[
            {
                "nsu": "993",
                "access_key": "KEY993",
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 59.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-manifest",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    monkeypatch.setattr(
        stock_module,
        "send_manifestation_ciencia_operacao",
        lambda access_key, settings, sequencia_evento=1, correlation_id=None, binding_profile=None: {"success": True, "cStat": "135", "xMotivo": "Evento registrado e vinculado", "protocol": "135000000000009", "tpEvento": "210210", "dhRegEvento": "2026-03-20T12:00:00-03:00", "event_cStat": "135", "event_xMotivo": "Evento registrado e vinculado", "event_nProt": "135000000000009", "event_dhRegEvento": "2026-03-20T12:00:00-03:00", "event_result_type": "registered"},
    )
    client = _client_with_login()
    resp = client.post(
        "/stock/nfe/repository/manifestation",
        json={"access_key": "KEY993", "manifestation_type": "ciencia_da_operacao"},
    )
    assert resp.status_code == 200
    assert (resp.get_json() or {}).get("success") is True
    note = repo.get_note_by_access_key("KEY993") or {}
    assert note.get("manifestation_status") == "registered"
    assert note.get("manifestation_type") == "ciencia_da_operacao"
    assert note.get("manifestation_protocol") == "135000000000009"
    assert note.get("manifestation_response_cstat") == "135"
    assert note.get("manifestation_response_xmotivo") == "Evento registrado e vinculado"
    assert note.get("manifestation_registered_at") == "2026-03-20T12:00:00-03:00"
    assert note.get("completeness_status") == "awaiting_full_download"


def test_manifestation_and_full_xml_attempt_endpoints_with_sefaz_mock(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "KEY994"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "994",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 11.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-manif-full",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    monkeypatch.setattr(
        stock_module,
        "send_manifestation_ciencia_operacao",
        lambda access_key, settings, sequencia_evento=1, correlation_id=None, binding_profile=None: {"success": True, "cStat": "135", "xMotivo": "Evento registrado e vinculado", "protocol": "135000000000001", "tpEvento": "210210", "dhRegEvento": "2026-03-20T12:00:00-03:00"},
    )
    full_xml = f'<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe{access_key}"><det nItem="1"><prod><cProd>X1</cProd><xProd>ITEM X</xProd><qCom>1</qCom><uCom>UN</uCom><vUnCom>1.00</vUnCom></prod></det></infNFe></NFe></nfeProc>'
    monkeypatch.setattr(stock_module, "consult_nfe_sefaz", lambda access_key, settings, allow_manifestation=False: (full_xml.encode("utf-8"), None))
    client = _client_with_login()
    manifest_resp = client.post("/stock/nfe/repository/manifestation", json={"access_key": access_key, "manifestation_type": "ciencia_da_operacao"})
    assert manifest_resp.status_code == 200
    manifest_payload = manifest_resp.get_json() or {}
    assert manifest_payload.get("success") is True
    assert (manifest_payload.get("manifestation") or {}).get("protocol") == "135000000000001"
    full_resp = client.post("/stock/nfe/repository/full-xml-attempt", json={"access_key": access_key})
    assert full_resp.status_code == 200
    full_payload = full_resp.get_json() or {}
    assert full_payload.get("success") is True
    assert (full_payload.get("full_xml") or {}).get("upgrade_success") is True
    note = repo.get_note_by_access_key(access_key) or {}
    assert note.get("document_type") == "full_nfe"
    assert note.get("has_full_items") is True
    assert note.get("full_xml_upgrade_success") is True
    assert str(note.get("full_xml_attempt_result") or "") == "success"
    assert str(note.get("last_full_xml_attempt_at") or "") != ""


def test_full_xml_attempt_requires_manifestation(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "KEY995"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "995",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 11.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-full-requires-manif",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    client = _client_with_login()
    resp = client.post("/stock/nfe/repository/full-xml-attempt", json={"access_key": access_key})
    assert resp.status_code == 400
    assert "Ciência da Operação" in str((resp.get_json() or {}).get("error") or "")


def test_full_xml_attempt_allows_already_registered_manifestation_result(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828692"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "995",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 11.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-full-allow-already-registered",
    )
    repo.register_note_manifestation(
        access_key=access_key,
        manifestation_type="ciencia_da_operacao",
        result="already_registered",
        response_cstat="573",
        response_xmotivo="Rejeicao: Duplicidade de evento",
        registered_at="2026-03-23T18:41:42-03:00",
        initiated_by="tester",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    monkeypatch.setattr(stock_module, "consult_nfe_sefaz", lambda access_key, settings, allow_manifestation=False: (None, "XML ainda indisponível"))
    client = _client_with_login()
    resp = client.post("/stock/nfe/repository/full-xml-attempt", json={"access_key": access_key})
    assert resp.status_code == 400
    payload = resp.get_json() or {}
    assert payload.get("category") == "sefaz"
    assert (payload.get("full_xml") or {}).get("full_xml_attempt_result") == "failed"


def test_manifestation_duplicate_is_not_resent(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "KEY996"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "996",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 11.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-manif-dup",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    monkeypatch.setattr(
        stock_module,
        "send_manifestation_ciencia_operacao",
        lambda access_key, settings, sequencia_evento=1, correlation_id=None, binding_profile=None: {"success": True, "cStat": "135", "xMotivo": "Evento registrado e vinculado", "protocol": "135000000000996", "tpEvento": "210210", "dhRegEvento": "2026-03-20T12:00:00-03:00"},
    )
    client = _client_with_login()
    first = client.post("/stock/nfe/repository/manifestation", json={"access_key": access_key, "manifestation_type": "ciencia_da_operacao"})
    assert first.status_code == 200
    second = client.post("/stock/nfe/repository/manifestation", json={"access_key": access_key, "manifestation_type": "ciencia_da_operacao"})
    assert second.status_code == 200
    assert "já registrada" in str((second.get_json() or {}).get("manifestation", {}).get("xMotivo") or "")


def test_manifestation_binding_mode_eventonf_is_forwarded(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "KEY997"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "997",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 11.0,
                "emitente": {"nome": "Fornecedor Resumo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<resNFe></resNFe>",
                "items": [],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-manif-binding",
    )
    monkeypatch.setattr(stock_module, "load_fiscal_settings", lambda: {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "certificate_path": "dummy.pfx", "certificate_password": "x"})
    captured = {}

    def _fake_send(access_key, settings, sequencia_evento=1, correlation_id=None, binding_profile=None):
        captured["binding_profile"] = binding_profile
        return {"success": False, "cStat": "", "xMotivo": "binding test", "protocol": "", "tpEvento": "210210", "dhRegEvento": ""}

    monkeypatch.setattr(stock_module, "send_manifestation_ciencia_operacao", _fake_send)
    client = _client_with_login()
    resp = client.post("/stock/nfe/repository/manifestation", json={"access_key": access_key, "manifestation_type": "ciencia_da_operacao", "binding_mode": "eventonf"})
    assert resp.status_code == 200
    assert (captured.get("binding_profile") or {}).get("soap_operation") == "nfeRecepcaoEventoNF"
    assert (captured.get("binding_profile") or {}).get("wrap_operation") is False
    assert (captured.get("binding_profile") or {}).get("include_nfe_header") is False
    assert (captured.get("binding_profile") or {}).get("payload_mode") == "xml_node"


def test_received_not_stocked_flow_and_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828694"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "994",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 30.0,
                "emitente": {"nome": "Fornecedor Fluxo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "X", "descricao": "ITEM X", "unidade": "UN", "quantidade": 2, "valor_unitario": 15, "valor_total": 30}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-received-flow",
    )
    client = _client_with_login()
    mark_resp = client.post("/stock/nfe/repository/mark-received", json={"access_key": access_key, "observation": "Aguardando aprovação"})
    assert mark_resp.status_code == 200
    mark_payload = mark_resp.get_json() or {}
    assert mark_payload.get("success") is True
    note = repo.get_note_by_access_key(access_key) or {}
    assert str(note.get("status_estoque") or "") == "received_not_stocked"
    assert bool(note.get("stock_applied")) is False
    assert bool(note.get("financial_trace")) is True
    assert bool(note.get("approved_for_stock")) is False
    approve_resp = client.post("/stock/nfe/repository/approve-stock-launch", json={"access_key": access_key, "observation": "Aprovado"})
    assert approve_resp.status_code == 200
    note_after = repo.get_note_by_access_key(access_key) or {}
    assert bool(note_after.get("approved_for_stock")) is True
    assert str(note_after.get("status_estoque") or "") == "received_not_stocked"


def test_stock_entry_post_is_blocked_when_received_not_stocked_without_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828695"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "995",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 30.0,
                "emitente": {"nome": "Fornecedor Fluxo", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "Y", "descricao": "ITEM Y", "unidade": "UN", "quantidade": 2, "valor_unitario": 15, "valor_total": 30}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-received-block",
    )
    repo.mark_note_received_not_stocked(access_key=access_key, user="tester", note_text="pendente", correlation_id="corr")
    client = _client_with_login()
    payload = {
        "header": {
            "supplier": "Fornecedor Fluxo",
            "number": "123",
            "serial": "1",
            "access_key": access_key,
            "entry_date": "2026-03-20",
            "issue_date": "2026-03-20",
        },
        "items": [{"name": "ITEM Y", "qty": 2, "price": 15, "unit": "UN"}],
        "financials": {"bills": []},
    }
    resp = client.post("/stock/entry", data={"data": __import__("json").dumps(payload)}, follow_redirects=False)
    assert resp.status_code in {302, 303}
    note_after = repo.get_note_by_access_key(access_key) or {}
    assert str(note_after.get("status_estoque") or "") == "received_not_stocked"
    assert str(note_after.get("imported_to_stock_at") or "") == ""


def test_manual_entry_modes_and_stock_launch_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    saved_stock_rows = []
    monkeypatch.setattr(
        stock_module,
        "load_products",
        lambda: [{"id": "P1", "name": "ARROZ TESTE", "department": "Geral", "unit": "Kilogramas", "price": 8.0, "suppliers": []}],
    )
    monkeypatch.setattr(stock_module, "secure_save_products", lambda products, user_id="": True)
    monkeypatch.setattr(stock_module, "save_stock_entry", lambda row: saved_stock_rows.append(dict(row)))
    client = _client_with_login()
    create_resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "received_not_stocked",
            "supplier_name": "Fornecedor Manual",
            "document_number": "DOC-1",
            "observation": "Recebido sem nota",
            "entry_date": "2026-03-20",
            "items": [
                {
                    "name": "ARROZ TESTE",
                    "product_id": "P1",
                    "qty": 2,
                    "unit": "UN",
                    "base_unit": "Kilogramas",
                    "conversion_factor": 1.5,
                    "cost": 10.0,
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    created = (create_resp.get_json() or {}).get("entry") or {}
    assert str(created.get("status") or "") == "received_not_stocked"
    assert bool(created.get("stock_applied")) is False
    entry_id = str(created.get("id") or "")
    approve_resp = client.post("/stock/manual-entry/status", json={"entry_id": entry_id, "status": "approved_for_stock"})
    assert approve_resp.status_code == 200
    import_resp = client.post("/stock/manual-entry/status", json={"entry_id": entry_id, "status": "imported"})
    assert import_resp.status_code == 200
    assert len(saved_stock_rows) == 1
    assert str(saved_stock_rows[0].get("product") or "") == "ARROZ TESTE"
    duplicate_resp = client.post("/stock/manual-entry/status", json={"entry_id": entry_id, "status": "imported"})
    assert duplicate_resp.status_code == 400


def test_manual_entry_import_requires_approval_when_received_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    monkeypatch.setattr(
        stock_module,
        "load_products",
        lambda: [{"id": "P2", "name": "FEIJAO TESTE", "department": "Geral", "unit": "Kilogramas", "price": 9.0, "suppliers": []}],
    )
    monkeypatch.setattr(stock_module, "secure_save_products", lambda products, user_id="": True)
    monkeypatch.setattr(stock_module, "save_stock_entry", lambda row: True)
    client = _client_with_login()
    create_resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "received_not_stocked",
            "supplier_name": "Fornecedor Manual",
            "document_number": "DOC-2",
            "entry_date": "2026-03-20",
            "items": [{"name": "FEIJAO TESTE", "product_id": "P2", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 9}],
        },
    )
    created = (create_resp.get_json() or {}).get("entry") or {}
    entry_id = str(created.get("id") or "")
    import_resp = client.post("/stock/manual-entry/status", json={"entry_id": entry_id, "status": "imported"})
    assert import_resp.status_code == 400


def test_manual_entry_draft_update_and_audit_trail(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    client = _client_with_login()
    create_resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "draft",
            "supplier_name": "Fornecedor Inicial",
            "document_number": "DRAFT-1",
            "entry_date": "2026-03-20",
            "items": [{"name": "ITEM A", "product_id": "P1", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 7}],
        },
    )
    created = (create_resp.get_json() or {}).get("entry") or {}
    entry_id = str(created.get("id") or "")
    update_resp = client.post(
        "/stock/manual-entry/update",
        json={
            "entry_id": entry_id,
            "supplier_name": "Fornecedor Editado",
            "document_number": "DRAFT-1A",
            "observation": "Ajuste de custo",
            "entry_date": "2026-03-21",
            "updated_reason": "Correção de dados recebidos",
            "items": [{"name": "ITEM A", "product_id": "P1", "qty": 2, "unit": "UN", "conversion_factor": 1, "cost": 8}],
        },
    )
    assert update_resp.status_code == 200
    updated = (update_resp.get_json() or {}).get("entry") or {}
    assert str(updated.get("status") or "") == "draft"
    assert str(updated.get("supplier_name") or "") == "Fornecedor Editado"
    assert float(updated.get("total_cost") or 0) == 16.0
    assert int(updated.get("edit_count") or 0) >= 1
    assert str(updated.get("updated_reason") or "") == "Correção de dados recebidos"
    assert isinstance(updated.get("audit_trail"), list) and len(updated.get("audit_trail")) >= 1


def test_manual_entry_update_blocked_when_not_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    client = _client_with_login()
    create_resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "received_not_stocked",
            "supplier_name": "Fornecedor Bloqueio",
            "document_number": "DRAFT-2",
            "entry_date": "2026-03-20",
            "items": [{"name": "ITEM B", "product_id": "P2", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 5}],
        },
    )
    created = (create_resp.get_json() or {}).get("entry") or {}
    entry_id = str(created.get("id") or "")
    update_resp = client.post(
        "/stock/manual-entry/update",
        json={
            "entry_id": entry_id,
            "supplier_name": "Fornecedor Tentativa",
            "entry_date": "2026-03-21",
            "updated_reason": "Tentativa indevida",
            "items": [{"name": "ITEM B", "product_id": "P2", "qty": 2, "unit": "UN", "conversion_factor": 1, "cost": 5}],
        },
    )
    assert update_resp.status_code == 400


def test_consolidated_approval_queue_shows_nfe_and_manual_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828696"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "996",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 21.0,
                "emitente": {"nome": "Fornecedor NF", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "A", "descricao": "ITEM A", "unidade": "UN", "quantidade": 1, "valor_unitario": 21, "valor_total": 21}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-approval-queue",
    )
    repo.mark_note_received_not_stocked(access_key=access_key, user="tester", note_text="aguardando", correlation_id="corr")
    client = _client_with_login()
    manual_resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "received_not_stocked",
            "supplier_name": "Fornecedor Manual Queue",
            "document_number": "MQ-1",
            "entry_date": "2026-03-20",
            "items": [{"name": "ITEM M", "product_id": "PM1", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 5}],
        },
    )
    assert manual_resp.status_code == 200
    page = client.get("/stock/entry?approval_status=pending")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Aguardando aprovação" in html
    assert access_key in html
    assert "Fornecedor Manual Queue" in html


def test_consolidated_decision_endpoint_approve_nfe_and_reject_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828697"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "997",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 10.0,
                "emitente": {"nome": "Fornecedor NF", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "B", "descricao": "ITEM B", "unidade": "UN", "quantidade": 1, "valor_unitario": 10, "valor_total": 10}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-approval-decision",
    )
    repo.mark_note_received_not_stocked(access_key=access_key, user="tester", note_text="pendente", correlation_id="corr")
    client = _client_with_login()
    approve_nfe = client.post(
        "/stock/approval/decision",
        json={"origin_type": "nfe", "entry_id": access_key, "decision": "approve", "decision_notes": "ok"},
    )
    assert approve_nfe.status_code == 200
    note = repo.get_note_by_access_key(access_key) or {}
    assert bool(note.get("approved_for_stock")) is True
    manual_create = client.post(
        "/stock/manual-entry",
        json={
            "mode": "received_not_stocked",
            "supplier_name": "Fornecedor Manual Reject",
            "document_number": "MR-1",
            "entry_date": "2026-03-20",
            "items": [{"name": "ITEM R", "product_id": "PR1", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 7}],
        },
    )
    entry = (manual_create.get_json() or {}).get("entry") or {}
    entry_id = str(entry.get("id") or "")
    reject_manual = client.post(
        "/stock/approval/decision",
        json={"origin_type": "manual_entry", "entry_id": entry_id, "decision": "reject", "decision_notes": "divergência"},
    )
    assert reject_manual.status_code == 200
    after = client.get(f"/stock/manual-entry/get?entry_id={entry_id}")
    body = after.get_json() or {}
    assert str((body.get("entry") or {}).get("status") or "") == "rejected"


def test_manual_entry_imported_asset_goes_to_assets_not_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    saved_stock_rows = []
    fake_assets = []
    monkeypatch.setattr(stock_module, "load_products", lambda: [{"id": "PA1", "name": "MICROONDAS", "department": "Geral", "unit": "UN", "price": 500.0, "suppliers": []}])
    monkeypatch.setattr(stock_module, "secure_save_products", lambda products, user_id="": True)
    monkeypatch.setattr(stock_module, "save_stock_entry", lambda row: saved_stock_rows.append(dict(row)))
    monkeypatch.setattr(stock_module, "load_fixed_assets", lambda: list(fake_assets))
    monkeypatch.setattr(stock_module, "save_fixed_assets", lambda assets: fake_assets.__setitem__(slice(None), list(assets)))
    client = _client_with_login()
    resp = client.post(
        "/stock/manual-entry",
        json={
            "mode": "imported_asset",
            "supplier_name": "Fornecedor Patrimonial",
            "document_number": "AT-1",
            "entry_date": "2026-03-20",
            "items": [{"name": "MICROONDAS", "product_id": "PA1", "item_nature": "asset_item", "qty": 1, "unit": "UN", "conversion_factor": 1, "cost": 500}],
        },
    )
    assert resp.status_code == 200
    entry = (resp.get_json() or {}).get("entry") or {}
    assert str(entry.get("status") or "") == "imported_asset"
    assert str(entry.get("destination_type") or "") == "asset"
    assert bool(entry.get("stock_applied")) is False
    assert len(saved_stock_rows) == 0
    assert len(fake_assets) >= 1


def test_nfe_approve_asset_routes_to_assets_and_not_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    fake_assets = []
    monkeypatch.setattr(stock_module, "load_fixed_assets", lambda: list(fake_assets))
    monkeypatch.setattr(stock_module, "save_fixed_assets", lambda assets: fake_assets.__setitem__(slice(None), list(assets)))
    access_key = "26260305429222000148550010012294091588828698"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "998",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 800.0,
                "emitente": {"nome": "Fornecedor Patrimonial", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "MO", "descricao": "MICROONDAS", "unidade": "UN", "quantidade": 1, "valor_unitario": 800, "valor_total": 800}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-asset-nfe",
    )
    repo.mark_note_received_not_stocked(access_key=access_key, user="tester", note_text="pendente", correlation_id="corr")
    client = _client_with_login()
    decision = client.post(
        "/stock/approval/decision",
        json={"origin_type": "nfe", "entry_id": access_key, "decision": "approve_asset", "decision_notes": "item patrimonial"},
    )
    assert decision.status_code == 200
    note = repo.get_note_by_access_key(access_key) or {}
    assert str(note.get("status_estoque") or "") == "imported_asset"
    assert str(note.get("destination_type") or "") == "asset"
    assert bool(note.get("stock_applied")) is False
    assert len(fake_assets) >= 1


def test_repository_load_suppliers_dropdown_normalized_from_service_suppliers(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828699"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "999",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 12.0,
                "emitente": {"nome": "Fornecedor Sugestão", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "C", "descricao": "ITEM C", "unidade": "UN", "quantidade": 1, "valor_unitario": 12, "valor_total": 12}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-supplier-dropdown",
    )
    monkeypatch.setattr(
        stock_module,
        "load_suppliers",
        lambda: [
            "Fornecedor String Legado",
            {"id": "", "name": "Fornecedor Sem Id", "trade_name": "", "cnpj": ""},
        ],
    )
    captured = {"saved": []}
    monkeypatch.setattr(stock_module, "save_suppliers", lambda rows: captured.__setitem__("saved", list(rows)))
    client = _client_with_login()
    resp = client.post("/stock/nfe/repository/load", json={"access_key": access_key})
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    options = payload.get("supplier_options") or []
    assert len(options) >= 2
    assert all(str(x.get("id") or "").strip() for x in options if isinstance(x, dict))
    assert all(str(x.get("name") or "").strip() for x in options if isinstance(x, dict))
    assert len(captured["saved"]) >= 2


def test_supplier_bind_enriches_missing_supplier_fields_from_note(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828700"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "1000",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 20.0,
                "emitente": {"nome": "Fornecedor Razão Fiscal", "cpf_cnpj": "11.222.333/0001-44"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "D", "descricao": "ITEM D", "unidade": "UN", "quantidade": 1, "valor_unitario": 20, "valor_total": 20}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-enrich-supplier",
    )
    suppliers = [{"id": "SUP-ENRICH", "name": "Fornecedor Operacional", "trade_name": "", "cnpj": "", "notes": ""}]
    monkeypatch.setattr(stock_module, "load_suppliers", lambda: list(suppliers))
    monkeypatch.setattr(stock_module, "save_suppliers", lambda rows: suppliers.__setitem__(slice(None), list(rows)))
    client = _client_with_login()
    bind_resp = client.post(
        "/stock/nfe/repository/supplier-bind",
        json={
            "access_key": access_key,
            "supplier_id": "SUP-ENRICH",
            "status_match_fornecedor": "manual_matched",
            "suggestion_used": False,
            "supplier_match_source": "manual_selection",
        },
    )
    assert bind_resp.status_code == 200
    payload = bind_resp.get_json() or {}
    assert (payload.get("enrichment") or {}).get("enriched") is True
    row = next((x for x in suppliers if str(x.get("id") or "") == "SUP-ENRICH"), {})
    assert str(row.get("cnpj") or "") == "11222333000144"
    assert str(row.get("trade_name") or "") != ""


def test_stock_entry_template_has_searchable_product_field_for_conference():
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "stock_entry.html"
    content = template_path.read_text(encoding="utf-8")
    assert "conferenceProductsDatalist" in content
    assert "product-search" in content
    assert "suggestConversionForItem" in content
    assert "normalizeSupplierOptions" in content
    assert "Selecione um fornecedor cadastrado" in content
    assert "formatSupplierCnpj" in content
    assert "supplierSelect.tomselect" in content
    assert "ts.clearOptions()" in content
    assert "supplierFlowBadges" in content
    assert "renderSupplierFlowSummary" in content
    assert "Cadastrar fornecedor da nota" in content
    assert "conferenceGlobalStatusBadge" in content
    assert "conferenceOperationalBreakdown" in content
    assert "renderConferenceOperationalSummary" in content
    assert "conferenceCriteriaStatus" in content
    assert "Atenção necessária" in content


def test_repository_load_suppliers_accepts_dict_source_and_nome_field(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828701"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "1001",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 15.0,
                "emitente": {"nome": "Fornecedor Dict", "cpf_cnpj": "12345678000199"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "E", "descricao": "ITEM E", "unidade": "UN", "quantidade": 1, "valor_unitario": 15, "valor_total": 15}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-supplier-dict",
    )
    monkeypatch.setattr(
        stock_module,
        "load_suppliers",
        lambda: {
            "a": {"id": "", "nome": "Fornecedor em Nome Legado", "cnpj": "123"},
            "b": {"id": "SUP2", "trade_name": "Fornecedor Trade", "cnpj": ""},
        },
    )
    monkeypatch.setattr(stock_module, "save_suppliers", lambda rows: True)
    client = _client_with_login()
    resp = client.post("/stock/nfe/repository/load", json={"access_key": access_key})
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    options = payload.get("supplier_options") or []
    assert len(options) >= 2
    assert any("Fornecedor em Nome Legado" in str(x.get("name") or "") for x in options if isinstance(x, dict))


def test_supplier_bind_enriches_only_missing_fields_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828702"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "1002",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 42.0,
                "emitente": {"nome": "Fornecedor Fiscal Divergente", "cpf_cnpj": "99888777000166"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "F", "descricao": "ITEM F", "unidade": "UN", "quantidade": 1, "valor_unitario": 42, "valor_total": 42}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-enrich-missing-only",
    )
    suppliers = [{"id": "SUP-LOCK", "name": "Fornecedor Operacional", "trade_name": "", "cnpj": "11111111000111", "notes": ""}]
    monkeypatch.setattr(stock_module, "load_suppliers", lambda: list(suppliers))
    monkeypatch.setattr(stock_module, "save_suppliers", lambda rows: suppliers.__setitem__(slice(None), list(rows)))
    client = _client_with_login()
    bind_resp = client.post(
        "/stock/nfe/repository/supplier-bind",
        json={
            "access_key": access_key,
            "supplier_id": "SUP-LOCK",
            "status_match_fornecedor": "manual_matched",
            "suggestion_used": False,
            "supplier_match_source": "manual_selection",
        },
    )
    assert bind_resp.status_code == 200
    payload = bind_resp.get_json() or {}
    enrichment = payload.get("enrichment") or {}
    row = next((x for x in suppliers if str(x.get("id") or "") == "SUP-LOCK"), {})
    assert str(row.get("cnpj") or "") == "11111111000111"
    assert str(row.get("name") or "") == "Fornecedor Operacional"
    assert str(row.get("trade_name") or "") in {"", "Fornecedor Fiscal Divergente", "Fornecedor Operacional"}
    assert "cnpj" in (enrichment.get("divergences") or [])
    note = repo.get_note_by_access_key(access_key) or {}
    assert bool(note.get("enrichment_applied")) is True
    assert isinstance(note.get("enriched_fields"), list)


def test_create_supplier_from_note_creates_and_binds(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "NFE_REPOSITORY_FILE", str(tmp_path / "nfe_repo.json"))
    access_key = "26260305429222000148550010012294091588828703"
    repo.ingest_documents(
        documents=[
            {
                "nsu": "1003",
                "access_key": access_key,
                "created_at": "2026-03-20T10:00:00",
                "issued_at": "2026-03-20T09:00:00",
                "total_amount": 50.0,
                "emitente": {"nome": "Fornecedor Novo NF", "cpf_cnpj": "55444333000122"},
                "xml_content": "<NFe></NFe>",
                "items": [{"codigo": "G", "descricao": "ITEM G", "unidade": "UN", "quantidade": 1, "valor_unitario": 50, "valor_total": 50}],
            }
        ],
        source_method="lastNSU",
        correlation_id="corr-create-from-note",
    )
    suppliers = []
    monkeypatch.setattr(stock_module, "load_suppliers", lambda: list(suppliers))
    monkeypatch.setattr(stock_module, "save_suppliers", lambda rows: suppliers.__setitem__(slice(None), list(rows)))
    client = _client_with_login()
    resp = client.post(
        "/stock/nfe/repository/supplier-create-from-note",
        json={"access_key": access_key, "supplier_name_new": ""},
    )
    assert resp.status_code == 200
    payload = resp.get_json() or {}
    created_id = str(payload.get("created_supplier_id") or "")
    assert payload.get("success") is True
    assert payload.get("created_via_nfe") is True
    assert created_id != ""
    assert any(str(x.get("id") or "") == created_id for x in suppliers if isinstance(x, dict))
    note = repo.get_note_by_access_key(access_key) or {}
    assert str(note.get("supplier_id") or "") == created_id
    assert bool(note.get("created_via_nfe")) is True
    assert str(note.get("supplier_match_source") or "") == "created_from_note"
