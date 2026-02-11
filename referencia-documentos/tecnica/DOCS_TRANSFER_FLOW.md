# Documentação Técnica: Transferência Entre Caixas

## Visão Geral
O sistema de transferências entre caixas permite movimentar valores entre os caixas do Restaurante e da Recepção (e outros) de forma segura e auditável.

## Fluxo de Transferência

A transferência segue o princípio de **Partida Dobrada Atômica**:
1.  **Débito na Origem**: Criação de transação `type='out'`, reduzindo o saldo da origem.
2.  **Crédito no Destino**: Criação de transação `type='in'`, aumentando o saldo do destino.
3.  **Vínculo Único**: Ambas as transações compartilham o mesmo `document_id` para rastreabilidade.
4.  **Comprovante**: Impressão de comprovante na origem (onde o dinheiro sai) com campo para assinatura do responsável.

### Regras de Negócio
-   **Saldo Suficiente**: Não é permitido transferir valor maior que o saldo disponível (Abertura + Entradas - Saídas).
-   **Caixas Abertos**: Origem e Destino devem estar com sessões abertas.
-   **Atomicidade**: As operações de escrita são protegidas por trava (`lock`) e gravadas atomicamente no arquivo JSON para evitar corrupção de dados.

## Implementação Técnica

### Backend (`services/cashier_service.py`)
A função `transfer_funds` é responsável por toda a lógica:
-   Valida status dos caixas.
-   Calcula saldo atual da origem.
-   Gera `document_id` único baseada em timestamp.
-   Cria par de transações (OUT/IN).
-   Persiste no arquivo `cashier_sessions.json`.

### Frontend e Rotas (`app.py`)
-   **Recepção**: Rota `/reception/cashier` -> Action `add_transaction` (type='transfer').
-   **Restaurante**: Rota `/restaurant/cashier` -> Action `add_transaction` (type='transfer').

### Impressão de Comprovantes
-   **Lógica**: O comprovante é impresso automaticamente após o sucesso da transação.
-   **Alvo**:
    -   **Restaurante**: Prioriza impressora "Bar".
    -   **Recepção**: Prioriza impressora padrão da recepção.
-   **Conteúdo**: Inclui "Assinatura Responsável" para validação física da retirada.

## Procedimentos de Correção e Monitoramento

### Auditoria
Para verificar a integridade das transferências, utilize o script de auditoria (ou lógica similar):
-   Verificar se todo `document_id` possui exatamente 2 transações associadas.
-   Verificar se uma é `out` e a outra é `in`.

### Correção de Saldos (Casos Legados/Erros)
Caso ocorra uma falha onde apenas um lado da transação foi registrado (transação "órfã"), o saldo ficará inconsistente.
-   **Sintoma**: Dinheiro "sumiu" ou "apareceu" sem contrapartida.
-   **Correção**: Identificar a transação órfã e, se necessário, ajustar seu tipo (ex: de 'transfer' genérico para 'out') ou criar manualmente a contrapartida.
-   **Script de Apoio**: `scripts/fix_transfers.py` (exemplo de script utilizado para corrigir transações antigas que estavam como crédito indevido).

## Testes
Testes de validação estão disponíveis em `tests/reproduce_transfer_issue.py`, cobrindo:
-   Transferência com saldo suficiente (sucesso).
-   Transferência com saldo insuficiente (bloqueio).
-   Verificação de integridade dos saldos pós-transferência.
