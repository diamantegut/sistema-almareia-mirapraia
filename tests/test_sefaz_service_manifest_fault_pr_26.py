from app.services.sefaz_service import SefazService


def test_parse_soap_fault_extracts_fields():
    service = SefazService("dummy.pfx", "dummy")
    xml = """
    <soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
      <soap:Body>
        <soap:Fault>
          <faultcode>soap:Server</faultcode>
          <faultstring>Erro interno no processamento do evento</faultstring>
        </soap:Fault>
        <retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe">
          <cStat>999</cStat>
          <xMotivo>Falha schema</xMotivo>
          <nProt>123</nProt>
        </retEnvEvento>
      </soap:Body>
    </soap:Envelope>
    """
    parsed = service._parse_soap_fault(xml)
    assert parsed.get("faultcode") == "soap:Server"
    assert parsed.get("faultstring") == "Erro interno no processamento do evento"
    assert parsed.get("cStat") == "999"
    assert parsed.get("xMotivo") == "Falha schema"
    assert parsed.get("nProt") == "123"


def test_parse_soap12_fault_value_and_text():
    service = SefazService("dummy.pfx", "dummy")
    xml = """
    <soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
      <soap:Body>
        <soap:Fault>
          <soap:Code><soap:Value>soap:Sender</soap:Value></soap:Code>
          <soap:Reason><soap:Text xml:lang="en">Unable to handle request without a valid action parameter.</soap:Text></soap:Reason>
          <soap:Detail />
        </soap:Fault>
      </soap:Body>
    </soap:Envelope>
    """
    parsed = service._parse_soap_fault(xml)
    assert parsed.get("faultcode") == "soap:Sender"
    assert "valid action parameter" in str(parsed.get("faultstring") or "")


def test_build_event_soap_envelope_contains_nfe_cabec_msg():
    service = SefazService("dummy.pfx", "dummy")
    envelope, payload_mode, payload_node_type = service._build_event_soap_envelope(
        "<envEvento versao=\"1.00\"></envEvento>",
        cuf_header="91",
        versao_dados="1.00",
    )
    assert "<soap:Header>" in envelope
    assert "<nfeCabecMsg xmlns=\"http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4\">" in envelope
    assert "<cUF>91</cUF>" in envelope
    assert "<versaoDados>1.00</versaoDados>" in envelope
    assert "<nfeRecepcaoEvento xmlns=\"http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4\">" in envelope
    assert "<![CDATA[" in envelope
    assert payload_mode == "cdata"
    assert payload_node_type == "cdata_text"


def test_build_event_soap_envelope_payload_modes():
    service = SefazService("dummy.pfx", "dummy")
    xml = "<envEvento versao=\"1.00\"></envEvento>"
    escaped_env, escaped_mode, escaped_node = service._build_event_soap_envelope(xml, payload_mode="escaped")
    xml_node_env, xml_mode, xml_node = service._build_event_soap_envelope(xml, payload_mode="xml_node")
    assert "&lt;envEvento" in escaped_env
    assert "<![CDATA[" not in escaped_env
    assert escaped_mode == "escaped"
    assert escaped_node == "text_escaped"
    assert "<envEvento versao=\"1.00\"></envEvento>" in xml_node_env
    assert "<![CDATA[" not in xml_node_env
    assert xml_mode == "xml_node"
    assert xml_node == "xml_node"


def test_extract_event_request_context_prefers_chave_uf_for_header():
    service = SefazService("dummy.pfx", "dummy")
    xml = """
    <envEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
      <evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
        <infEvento Id="ID...">
          <cOrgao>91</cOrgao>
          <tpAmb>1</tpAmb>
          <chNFe>26260305429222000148550010012294091588828691</chNFe>
        </infEvento>
      </evento>
    </envEvento>
    """
    ctx = service._extract_event_request_context(xml)
    assert ctx.get("cuf_header") == "26"
    assert ctx.get("cuf_source") == "chNFe_prefix"
    assert ctx.get("versao_dados") == "1.00"


def test_parse_event_response_extracts_retevento_inf_evento():
    service = SefazService("dummy.pfx", "dummy")
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
      <idLote>123</idLote>
      <tpAmb>1</tpAmb>
      <verAplic>SP_EVENTOS_PL_100</verAplic>
      <cOrgao>91</cOrgao>
      <cStat>128</cStat>
      <xMotivo>Lote de evento processado</xMotivo>
      <retEvento versao="1.00">
        <infEvento Id="ID2102102626030542922200014855001001229409158882869101">
          <tpAmb>1</tpAmb>
          <verAplic>SP_EVENTOS_PL_100</verAplic>
          <cOrgao>91</cOrgao>
          <cStat>135</cStat>
          <xMotivo>Evento registrado e vinculado a NF-e</xMotivo>
          <chNFe>26260305429222000148550010012294091588828691</chNFe>
          <tpEvento>210210</tpEvento>
          <xEvento>Ciencia da Operacao</xEvento>
          <nSeqEvento>1</nSeqEvento>
          <dhRegEvento>2026-03-23T18:32:58-03:00</dhRegEvento>
          <nProt>113260000000001</nProt>
        </infEvento>
      </retEvento>
    </retEnvEvento>"""
    parsed = service._parse_event_response(xml.encode("utf-8"))
    assert parsed.get("success") is True
    assert parsed.get("lote_cStat") == "128"
    assert parsed.get("event_cStat") == "135"
    assert parsed.get("event_xMotivo") == "Evento registrado e vinculado a NF-e"
    assert parsed.get("event_nProt") == "113260000000001"
    assert parsed.get("event_dhRegEvento") == "2026-03-23T18:32:58-03:00"


def test_parse_event_response_duplicate_event_is_classified():
    service = SefazService("dummy.pfx", "dummy")
    xml = """<retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
      <cStat>128</cStat>
      <xMotivo>Lote de evento processado</xMotivo>
      <retEvento versao="1.00">
        <infEvento Id="IDX">
          <cStat>573</cStat>
          <xMotivo>Rejeicao: Duplicidade de evento</xMotivo>
          <chNFe>26260305429222000148550010012294091588828691</chNFe>
          <tpEvento>210210</tpEvento>
          <nSeqEvento>1</nSeqEvento>
          <dhRegEvento>2026-03-23T18:41:42-03:00</dhRegEvento>
        </infEvento>
      </retEvento>
    </retEnvEvento>"""
    parsed = service._parse_event_response(xml.encode("utf-8"))
    assert parsed.get("success") is True
    assert parsed.get("event_result_type") == "already_registered"
