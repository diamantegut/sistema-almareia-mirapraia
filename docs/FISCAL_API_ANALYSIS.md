# Análise Técnica de APIs Fiscais: NFC-e (Mirapraia) vs NFS-e (Almareia)

## 1. Visão Geral

O sistema utiliza a **Nuvem Fiscal** como gateway unificado para emissão de documentos fiscais. Embora o provedor seja o mesmo, os serviços de **NFC-e** (Nota Fiscal de Consumidor Eletrônica) e **NFS-e** (Nota Fiscal de Serviço Eletrônica) operam em endpoints e estruturas de dados distintos devido à natureza tributária diferente (Estadual vs Municipal).

| Característica | NFC-e (Mirapraia) | NFS-e (Almareia) |
| :--- | :--- | :--- |
| **Entidade** | Restaurante e Recepção | Reservas e Hospedagem |
| **Tipo Fiscal** | Venda de Produtos (Estadual - SEFAZ) | Prestação de Serviços (Municipal) |
| **CNPJ Emitente** | `28.952.732/0001-09` | `46.500.590/0001-12` |
| **Status Atual** | ✅ **Implementado** (`fiscal_service.py`) | ⚠️ **Mock/Simulado** (`process_nfse_request`) |
| **Escopo OAuth** | `nfce` | `nfse` |

---

## 2. Autenticação e Segurança

Ambos os serviços utilizam **OAuth 2.0 Client Credentials Flow**.

- **Endpoint de Token**: `https://auth.nuvemfiscal.com.br/oauth/token`
- **Método**: `POST`
- **Content-Type**: `application/x-www-form-urlencoded`

### Parâmetros de Requisição

| Parâmetro | Valor Fixo | Descrição |
| :--- | :--- | :--- |
| `grant_type` | `client_credentials` | Tipo de concessão OAuth. |
| `client_id` | *Variável* | ID do cliente (configurado em `fiscal_settings.json`). |
| `client_secret` | *Variável* | Segredo do cliente. |
| `scope` | `nfce` ou `nfse` | **Diferença Crítica**: Define qual API será acessada. |

### Exemplo de Resposta (Sucesso)

```json
{
  "access_token": "eyJhbGciOiJSUzI1Ni...",
  "token_type": "bearer",
  "expires_in": 3600,
  "scope": "nfce"
}
```

> **Nota de Implementação**: O token deve ser cacheado e reutilizado até expirar para evitar rate limiting no servidor de autenticação.

---

## 3. Endpoints e Operações

A URL base varia conforme o ambiente:
- **Produção**: `https://api.nuvemfiscal.com.br`
- **Homologação (Sandbox)**: `https://api.sandbox.nuvemfiscal.com.br`

### 3.1 NFC-e (Mirapraia)

| Operação | Método | Endpoint Relativo | Status no Código |
| :--- | :--- | :--- | :--- |
| **Emitir Nota** | `POST` | `/nfce` | ✅ Implementado |
| **Consultar** | `GET` | `/nfce/{id}` | ❌ Pendente |
| **Cancelar** | `POST` | `/nfce/{id}/cancelamento` | ❌ Pendente |
| **Download XML** | `GET` | `/nfce/{id}/xml` | ✅ Implementado |
| **Config. Empresa**| `PUT` | `/empresas/{cnpj}/nfce` | ✅ Implementado |

### 3.2 NFS-e (Almareia)

| Operação | Método | Endpoint Relativo | Status no Código |
| :--- | :--- | :--- | :--- |
| **Emitir Nota** | `POST` | `/nfse` | ⚠️ **Mock** (Requer Implementação) |
| **Consultar** | `GET` | `/nfse/{id}` | ⚠️ Mock |
| **Cancelar** | `POST` | `/nfse/{id}/cancelamento` | ⚠️ Mock |
| **Config. Empresa**| `PUT` | `/empresas/{cnpj}/nfse` | ❌ Não Implementado |

---

## 4. Estruturas de Payload (Requisição)

### 4.1 NFC-e (Produto) - JSON

A estrutura segue o padrão da NFe (infNFe), encapsulada em JSON.

```json
{
  "ambiente": "homologacao", // ou "producao"
  "infNFe": {
    "versao": "4.00",
    "ide": {
      "tpEmis": 1, // 1=Normal, 9=Offline
      "natOp": "Venda ao Consumidor",
      "mod": 65,
      "serie": 1,
      "nNF": 101,
      "dhEmi": "2023-10-25T14:30:00-03:00"
    },
    "emit": { "CNPJ": "28952732000109" },
    "dest": { "CPF": "12345678901" }, // Opcional para NFC-e < R$ 10k
    "det": [
      {
        "nItem": 1,
        "prod": {
          "cProd": "ITEM01",
          "xProd": "Refrigerante",
          "NCM": "22021000",
          "CFOP": "5102",
          "uCom": "UN",
          "qCom": 1.0,
          "vUnCom": 5.00,
          "vProd": 5.00
        },
        "imposto": { "ICMS": { ... }, "PIS": { ... }, "COFINS": { ... } }
      }
    ],
    "pag": {
      "detPag": [ { "tPag": "01", "vPag": 5.00 } ] // 01=Dinheiro, 03=Crédito, 04=Débito, 17=Pix
    }
  }
}
```

### 4.2 NFS-e (Serviço) - JSON (Recomendado)

A NFS-e utiliza o conceito de **DPS** (Declaração de Prestação de Serviço) ou um payload simplificado que a Nuvem Fiscal converte para o padrão do município.

```json
{
  "ambiente": "homologacao",
  "referencia": "REF-12345", // ID interno do sistema
  "infDPS": {
    "dhEmi": "2023-10-25T14:30:00-03:00",
    "prest": {
      "CNPJ": "46500590000112"
    },
    "toma": {
      "cpfCnpj": { "Cnpj": "99999999000191" }, // Ou CPF
      "razaoSocial": "Empresa Cliente Ltda",
      "endereco": { ... } // Obrigatório para NFS-e em muitos municípios
    },
    "serv": {
      "cServ": {
        "cTribNac": "0901", // Código de Tributação Nacional (Hospedagem)
        "xDescServ": "Hospedagem - Diárias"
      },
      "vServ": 200.00,
      "iss": {
        "vAliq": 5.00 // 5%
      }
    }
  }
}
```

> **Diferença Importante**: Na NFS-e, os dados do **Tomador** (Endereço, Email) são frequentemente obrigatórios pela prefeitura, enquanto na NFC-e são opcionais.

---

## 5. Guia de Implementação Comparativo

### Passo 1: Configuração Inicial
- **NFC-e**: Requer CSC (Código de Segurança do Contribuinte) configurado via endpoint `/empresas/{cnpj}/nfce`.
- **NFS-e**: Requer configuração de certificado digital e credenciais da prefeitura no painel da Nuvem Fiscal.

### Passo 2: Construção do Payload
- **NFC-e**: Focar em **NCM**, **CFOP** e **tPag**. Erros comuns envolvem tributação (CSOSN/CST) incorreta.
- **NFS-e**: Focar em **Código de Serviço (LC 116)** e dados do **Tomador**. Erros comuns envolvem rejeição pela prefeitura por cadastro incompleto do cliente.

### Passo 3: Tratamento de Resposta
- **Síncrono vs Assíncrono**:
  - **NFC-e**: Geralmente síncrono. A resposta já contém o XML e protocolo de autorização.
  - **NFS-e**: Frequentemente **assíncrono**. A API retorna um ID de pedido, e o sistema deve fazer polling (`GET /nfse/{id}`) ou usar Webhooks para saber quando a prefeitura processou.

### Código de Exemplo (Python) - Adaptação para NFS-e

```python
def emitir_nfse(transacao, cliente, itens):
    # 1. Autenticação
    token = get_access_token(client_id, client_secret, scope="nfse")
    
    # 2. Payload
    payload = {
        "ambiente": "homologacao",
        "infDPS": {
            "toma": {
                "cpfCnpj": { "Cpf": cliente['cpf'] },
                "razaoSocial": cliente['nome']
            },
            "serv": {
                "cServ": { "cTribNac": "0901", "xDescServ": "Hospedagem" },
                "vServ": transacao['valor_total'],
                "iss": { "vAliq": 5.00 }
            }
        }
    }
    
    # 3. Envio
    resp = requests.post("https://api.nuvemfiscal.com.br/nfse", json=payload, headers=...)
    
    # 4. Tratamento Assíncrono (Diferença da NFC-e)
    if resp.status_code == 200:
        dados = resp.json()
        if dados['status'] == 'PROCESSANDO':
            return {"status": "pending", "id": dados['id']}
    return {"status": "error"}
```

---

## 6. Critérios de Sucesso e Limites

### Limites de Rate (Rate Limiting)
- A Nuvem Fiscal impõe limites padrão (ex: 600 requisições/minuto), mas o gargalo real costuma ser a **SEFAZ** (NFC-e) ou a **Prefeitura** (NFS-e).
- **Estratégia**: Implementar *exponential backoff* em caso de HTTP 429 ou erros 5xx da SEFAZ.

### Critérios de Aceite para Produção
1.  **Tempo de Resposta**:
    -   NFC-e: < 5 segundos (síncrono).
    -   NFS-e: < 30 segundos (ou fluxo assíncrono robusto).
2.  **Contingência**:
    -   NFC-e: O sistema **deve** suportar emissão offline (`tpEmis=9`) quando a internet cair.
    -   NFS-e: Geralmente aceita RPS (Recibo Provisório de Serviço) para envio posterior (lote).
3.  **Validação de Dados**:
    -   O sistema deve impedir o envio se CPF/CNPJ for inválido (algoritmo de dígito verificador) antes de chamar a API.

## 7. Recomendações Imediatas

1.  **Implementar NFS-e Real**: Substituir o método `process_nfse_request` mockado em `fiscal_service.py` pela chamada real à API, seguindo a estrutura de payload acima.
2.  **Separar Filas**: Garantir que o `FiscalPoolService` direcione corretamente itens de "Hospedagem" para a fila de NFS-e e "Consumo" para NFC-e.
3.  **Logs de Auditoria**: Persistir o `id` da transação da Nuvem Fiscal e o `status` retornado para conciliação futura.
