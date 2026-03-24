from app.services import fiscal_service


class _FakeSefazService:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def load_certificate(self):
        return {
            "ok": True,
            "metadata": {
                "subject": "CN=Empresa Teste",
                "issuer": "CN=Autoridade Teste",
                "serial_number": "123456",
                "fingerprint_sha256": "ABCDEF",
                "not_valid_before": "2026-01-01T00:00:00+00:00",
                "not_valid_after": "2027-01-01T00:00:00+00:00",
            },
        }

    def manifestar_ciencia_operacao(self, access_key, cnpj, ambiente=1, sequencia_evento=1, correlation_id=None, binding_profile=None):
        return {
            "success": True,
            "cStat": "135",
            "xMotivo": "Evento registrado e vinculado",
            "protocol": "135000000000123",
            "tpEvento": "210210",
            "dhRegEvento": "2026-03-20T12:00:00-03:00",
            "raw_xml": "<retEnvEvento></retEnvEvento>",
        }


class _FakeSefazServiceError:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def load_certificate(self):
        return {"ok": True, "metadata": {}}

    def manifestar_ciencia_operacao(self, access_key, cnpj, ambiente=1, sequencia_evento=1, correlation_id=None, binding_profile=None):
        return {
            "success": False,
            "http_status": 500,
            "faultcode": "soap:Server",
            "faultstring": "Falha de schema",
            "cStat": "999",
            "xMotivo": "Erro no schema do XML",
            "protocol": "",
            "remote_body_excerpt": "<soap:Fault>...</soap:Fault>",
            "request_diagnostics": {"url": "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx"},
        }


def test_load_certificate_returns_clear_error_without_config(monkeypatch):
    monkeypatch.setattr(fiscal_service, "_get_sefaz_service_instance", lambda settings: None)
    result = fiscal_service.load_certificate({"provider": "sefaz_direto"})
    assert result.get("success") is False
    assert "Certificado A1" in str(result.get("message") or "")


def test_send_manifestation_requires_sefaz_direto():
    result = fiscal_service.send_manifestation_ciencia_operacao("KEY", {"provider": "nuvem_fiscal"})
    assert result.get("success") is False
    assert "sefaz_direto" in str(result.get("message") or "")


def test_send_manifestation_success_with_mocked_service(monkeypatch):
    monkeypatch.setattr(fiscal_service, "check_xml_signature_dependencies", lambda: {"ok": True, "missing": []})
    monkeypatch.setattr(fiscal_service, "_get_sefaz_service_instance", lambda settings: _FakeSefazService())
    result = fiscal_service.send_manifestation_ciencia_operacao(
        "26260308305623000184550010008933751210119451",
        {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "environment": "production"},
    )
    assert result.get("success") is True
    assert result.get("cStat") == "135"
    assert result.get("tpEvento") == "210210"


def test_send_manifestation_returns_clear_message_when_xml_libs_missing(monkeypatch):
    monkeypatch.setattr(fiscal_service, "check_xml_signature_dependencies", lambda: {"ok": False, "missing": ["signxml", "lxml"]})
    result = fiscal_service.send_manifestation_ciencia_operacao(
        "26260308305623000184550010008933751210119451",
        {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "environment": "production"},
    )
    assert result.get("success") is False
    assert "Assinatura fiscal indisponível" in str(result.get("message") or "")
    assert result.get("missing_dependencies") == ["signxml", "lxml"]


def test_certificate_runtime_status_uses_safe_fields(monkeypatch):
    monkeypatch.setattr(
        fiscal_service,
        "_resolve_sefaz_certificate_config",
        lambda settings: {
            "provider": "sefaz_direto",
            "environment": "production",
            "cnpj_emitente": "12345678000199",
            "configured_path": "cert.pfx",
            "resolved_path": "C:/cert.pfx",
            "exists": True,
            "size_bytes": 2048,
            "password_source": "env:SEFAZ_CERT_PASSWORD",
            "password_env_name": "",
            "password_value": "secret",
        },
    )
    monkeypatch.setattr(fiscal_service, "_get_sefaz_service_instance", lambda settings: _FakeSefazService())
    status = fiscal_service.get_sefaz_certificate_runtime_status({"provider": "sefaz_direto"})
    assert status.get("load_success") is True
    assert status.get("password_source") == "env:SEFAZ_CERT_PASSWORD"
    assert status.get("certificate", {}).get("fingerprint_sha256") == "ABCDEF"


def test_send_manifestation_propagates_fault_details(monkeypatch):
    monkeypatch.setattr(fiscal_service, "check_xml_signature_dependencies", lambda: {"ok": True, "missing": []})
    monkeypatch.setattr(fiscal_service, "_get_sefaz_service_instance", lambda settings: _FakeSefazServiceError())
    result = fiscal_service.send_manifestation_ciencia_operacao(
        "26260308305623000184550010008933751210119451",
        {"provider": "sefaz_direto", "cnpj_emitente": "12345678000199", "environment": "production"},
    )
    assert result.get("success") is False
    assert result.get("http_status") == 500
    assert result.get("faultcode") == "soap:Server"
    assert result.get("faultstring") == "Falha de schema"
    assert result.get("cStat") == "999"
