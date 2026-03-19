from app.services import fiscal_service


def test_pe_ie_validation_accepts_formatted_and_digits():
    assert fiscal_service._is_valid_pe_ie("0743532-09") is True
    assert fiscal_service._is_valid_pe_ie("074353209") is True


def test_emit_invoice_rejects_invalid_pe_ie_before_api_call():
    tx = {"id": "TX1", "payment_method": "Dinheiro"}
    settings = {
        "provider": "nuvem_fiscal",
        "client_id": "id",
        "client_secret": "secret",
        "cnpj_emitente": "28.952.732/0001-09",
        "ie_emitente": "0743532-00",
        "CRT": "1",
        "environment": "production",
    }
    items = [{"name": "Produto", "qty": 1, "price": 10.0}]
    result = fiscal_service.emit_invoice(tx, settings, items, customer_cpf_cnpj="12345678901")
    assert result["success"] is False
    assert "Inscrição Estadual inválida para PE" in result["message"]


def test_extract_access_key_from_payload_variants():
    assert fiscal_service._extract_access_key({"chave": "26260328952732000109650090000005821234616972"}) == "26260328952732000109650090000005821234616972"
    assert fiscal_service._extract_access_key({"autorizacao": {"chNFe": "26260328952732000109650090000005821234616972"}}) == "26260328952732000109650090000005821234616972"
