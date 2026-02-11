# Documentação Técnica: Transferência Entre Caixas

## Visão Geral
O módulo de transferência entre caixas permite a movimentação de valores entre o **Caixa Restaurante** e o **Caixa Recepção**. Esta operação é atômica, garantindo que o débito na origem e o crédito no destino ocorram simultaneamente, mantendo a consistência financeira.

## Fluxo de Dados

1.  **Solicitação**: O usuário inicia a transferência via interface (Restaurant ou Reception Cashier).
2.  **Validação**:
    *   Verifica se ambos os caixas (Origem e Destino) estão abertos.
    *   Verifica se o caixa de origem possui saldo suficiente (`current_balance >= amount`).
3.  **Execução (`CashierService.transfer_funds`)**:
    *   Bloqueio de Thread (`cashier_lock`) para evitar condições de corrida.
    *   Geração de `document_id` único (timestamp base) para vincular as transações.
    *   Criação da Transação de **Saída (OUT)** no caixa de origem.
    *   Criação da Transação de **Entrada (IN)** no caixa de destino.
    *   Persistência atômica do arquivo `cashier_sessions.json`.
4.  **Impressão**:
    *   Geração de cupom de transferência.
    *   Envio para impressora configurada (Prioridade: Impressora do Bar para assinatura).

## Estrutura de Dados

As transações de transferência são armazenadas em `cashier_sessions.json` e possuem a seguinte estrutura:

**Origem (Débito):**
```json
{
  "id": "TRANS_20260207120000_OUT",
  "document_id": "20260207120000",
  "type": "out",
  "category": "Transferência Enviada",
  "amount": 100.0,
  "description": "Transferência para recepção",
  "payment_method": "Transferência"
}
```

**Destino (Crédito):**
```json
{
  "id": "TRANS_20260207120000_IN",
  "document_id": "20260207120000",
  "type": "in",
  "category": "Transferência Recebida",
  "amount": 100.0,
  "description": "Transferência de restaurante",
  "payment_method": "Transferência"
}
```

O campo `document_id` é a chave que liga as duas pontas da transferência.

## Procedimentos de Monitoramento e Correção

### Auditoria
Utilize o script `scripts/audit_transfers.py` para verificar a integridade das transferências.
*   **Orphans**: Transações com `document_id` nulo ou sem par correspondente.
*   **Broken Links**: `document_id` presente mas contagem de transações != 2.

### Correção de Inconsistências
Caso sejam detectadas inconsistências (ex: falha de sistema durante a gravação):
1.  Execute `scripts/fix_transfers.py` para corrigir tipos de transação incorretos.
2.  Execute `scripts/fix_broken_links.py` para recriar transações parceiras perdidas e recalcular saldos.

### Prevenção de Regressão
*   O uso de `threading.Lock` e escrita atômica de arquivos mitiga 99% dos riscos de corrupção.
*   Testes unitários (`tests/test_cashier_transfer.py`) validam o comportamento atômico.
