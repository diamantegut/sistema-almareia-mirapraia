from app.services import fiscal_service


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_emit_invoice_adds_service_fee_item_when_amount_is_higher(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResp({"status": "autorizada", "id": "NF-1", "serie": "1", "numero": "123"})

    monkeypatch.setattr(fiscal_service, "get_access_token", lambda *args, **kwargs: "TOKEN")
    monkeypatch.setattr(fiscal_service.requests, "post", _fake_post)

    tx = {"id": "TX-1", "payment_method": "Dinheiro", "amount": 11.0}
    settings = {
        "provider": "nuvem_fiscal",
        "client_id": "id",
        "client_secret": "secret",
        "cnpj_emitente": "28952732000109",
        "ie_emitente": "074353209",
        "CRT": "1",
        "environment": "homologation",
        "sefaz_environment": "homologation",
        "serie": "1",
        "next_number": "1",
    }
    items = [{"id": "1", "name": "Produto", "qty": 1, "price": 10.0, "ncm": "21069090", "cfop": "5102", "csosn": "102"}]
    out = fiscal_service.emit_invoice(tx, settings, items, customer_cpf_cnpj="12345678901")
    assert out["success"] is True
    det = captured["payload"]["infNFe"]["det"]
    assert any(d["prod"].get("xProd") == "Taxa de Serviço" for d in det)
    assert captured["payload"]["infNFe"]["total"]["ICMSTot"]["vNF"] == 11.0


def test_emit_invoice_does_not_add_service_fee_item_when_amount_matches(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResp({"status": "autorizada", "id": "NF-2", "serie": "1", "numero": "124"})

    monkeypatch.setattr(fiscal_service, "get_access_token", lambda *args, **kwargs: "TOKEN")
    monkeypatch.setattr(fiscal_service.requests, "post", _fake_post)

    tx = {"id": "TX-2", "payment_method": "Dinheiro", "amount": 10.0}
    settings = {
        "provider": "nuvem_fiscal",
        "client_id": "id",
        "client_secret": "secret",
        "cnpj_emitente": "28952732000109",
        "ie_emitente": "074353209",
        "CRT": "1",
        "environment": "homologation",
        "sefaz_environment": "homologation",
        "serie": "1",
        "next_number": "1",
    }
    items = [{"id": "1", "name": "Produto", "qty": 1, "price": 10.0, "ncm": "21069090", "cfop": "5102", "csosn": "102"}]
    out = fiscal_service.emit_invoice(tx, settings, items, customer_cpf_cnpj="12345678901")
    assert out["success"] is True
    det = captured["payload"]["infNFe"]["det"]
    assert all(d["prod"].get("xProd") != "Taxa de Serviço" for d in det)
    assert captured["payload"]["infNFe"]["total"]["ICMSTot"]["vNF"] == 10.0
