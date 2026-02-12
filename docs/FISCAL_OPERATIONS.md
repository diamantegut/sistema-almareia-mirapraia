# Manual de Operações Fiscais e Contingência

## 1. Visão Geral
Este documento estabelece o comportamento operacional e fiscal dos caixas do sistema Mirapraia/Almareia, definindo responsabilidades, fluxos de emissão e procedimentos de contingência.

## 2. Estrutura de Emissão (Multi-CNPJ)

O sistema opera com duas empresas distintas, selecionadas automaticamente conforme a natureza da operação:

| Caixa / Origem | Natureza | Tipo Fiscal | Emitente | CNPJ |
| :--- | :--- | :--- | :--- | :--- |
| **Restaurante** | Consumo (Alimentação) | **NFC-e** | Mirapraia Hotelaria | `28.952.732/0001-09` |
| **Recepção** (Frigobar) | Consumo (Produtos) | **NFC-e** | Mirapraia Hotelaria | `28.952.732/0001-09` |
| **Recepção** (Diárias) | Serviço (Hospedagem) | **NFS-e** | Almareia Hotelaria | `46.500.590/0001-12` |
| **Reservas** | Serviço (Antecipado) | **NFS-e** | Almareia Hotelaria | `46.500.590/0001-12` |

### 2.1 Lógica de Seleção Automática
O sistema analisa os itens da transação:
- Se houver itens do tipo "Diária", "Hospedagem" ou serviços, a emissão é direcionada para a **Almareia (NFS-e)**.
- Se forem apenas produtos (Restaurante, Frigobar), a emissão é direcionada para a **Mirapraia (NFC-e)**.

---

## 3. Caixa do Restaurante e Recepção (NFC-e)

### 3.1 Fluxo Operacional
1.  **Abertura de Conta**: Garçom/Recepcionista lança itens na conta (Mesa ou Quarto).
2.  **Fechamento**: O operador seleciona a forma de pagamento e solicita o fechamento.
3.  **Emissão Automática**:
    - Ao confirmar o pagamento, o sistema envia a transação para a **Fila Fiscal**.
    - O processador fiscal valida os dados e transmite para a SEFAZ via Nuvem Fiscal.
    - O XML é gerado e armazenado.
    - O DANFE (Cupom) é impresso automaticamente.

### 3.2 Validações Obrigatórias
O sistema valida automaticamente antes do envio:
- **CPF/CNPJ do Cliente**: Obrigatório se solicitado pelo cliente ou para valores acima do limite legal (R$ 10.000,00).
- **NCM**: Produtos sem NCM cadastrado utilizam o fallback `21069090`.
- **Forma de Pagamento**: Mapeamento correto para códigos SEFAZ (01=Dinheiro, 03=Crédito, etc.).

### 3.3 Contingência Offline (NFC-e)
Em caso de falha de conexão com a SEFAZ ou Nuvem Fiscal:
1.  O sistema detecta o erro de comunicação.
2.  A nota pode ser emitida em **Modo de Contingência Offline** (`tpEmis=9`).
3.  O DANFE é impresso em duas vias com a mensagem "EMITIDA EM CONTINGÊNCIA".
4.  O XML deve ser transmitido para a SEFAZ assim que a conexão for restabelecida (prazo legal de 24h).
    *   *Nota: A transmissão do XML de contingência é automática pelo processador de fila.*

---

## 4. Caixa de Reservas (NFS-e)

### 4.1 Preparação para Futuro
Atualmente, o módulo de Reservas está preparado para:
- Registrar pagamentos de diárias.
- Armazenar dados para futura emissão de NFS-e (ISSQN, Código de Serviço).
- A integração com a Prefeitura (via Almareia) está configurada como *MOCK* (Simulação) aguardando credenciamento final.

---

## 5. Auditoria e Conciliação

### 5.1 Logs de Auditoria
Todas as operações fiscais são registradas em `logs/fiscal_audit.log` contendo:
- ID da Transação
- Usuário Responsável
- Status da Emissão (Sucesso/Erro)
- UUID do Documento Fiscal

### 5.2 Backup de XMLs
Os arquivos XML são armazenados localmente e organizados por CNPJ e Data:
`fiscal_documents/xmls/{ANO}/{MES}/{CHAVE}.xml`
Backup recomendado: Cópia diária desta pasta para nuvem ou disco externo (responsabilidade da TI local).

### 5.3 Alertas
O sistema exibe alertas no Dashboard Administrativo para:
- Notas em estado `pending` por mais de 1 hora.
- Notas com status `error` que exigem correção manual.
- Falhas consecutivas de comunicação (indício de problema de internet).
