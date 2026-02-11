# Documentação da Refatoração de Transferência de Mesas

## Visão Geral
Esta documentação detalha a refatoração da lógica de transferência de mesas para quartos (hóspedes), visando resolver problemas de duplicação de código, concorrência, consistência de dados e robustez.

## Mudanças Realizadas

### 1. Criação do Serviço de Transferência (`services/transfer_service.py`)
A lógica de negócio foi extraída do `app.py` e encapsulada em um serviço dedicado.
- **Função Principal:** `transfer_table_to_room(table_id, room_number, user_name)`
- **Responsabilidades:**
  - Validar a existência da mesa e do quarto.
  - Verificar se a mesa pertence a um hóspede.
  - Transferir itens da mesa para a conta do quarto (`room_charges.json`).
  - Limpar/Fechar a mesa (`table_orders.json`) mantendo a lógica de IDs legados (<=35 permanecem abertas).
  - Registrar logs de auditoria.

### 2. Controle de Concorrência e Atomicidade
Para evitar condições de corrida e inconsistência de dados:
- **File Locking:** Implementado uso de `portalocker` (via `FileLock`) para garantir acesso exclusivo aos arquivos JSON (`table_orders.json`, `room_charges.json`) durante a operação.
- **Operações Atômicas:** A escrita nos arquivos JSON é feita primeiro em um arquivo temporário e depois renomeada, garantindo que o arquivo nunca fique corrompido em caso de falha no meio da escrita.
- **Rollback (Reversão):** Se a atualização da mesa falhar após a cobrança ter sido adicionada ao quarto, o sistema reverte a adição da cobrança automaticamente, garantindo que o cliente não seja cobrado sem que a mesa seja baixada.

### 3. Integração com `app.py`
A rota `restaurant_table_order` (ação `transfer_to_room`) foi simplificada.
- Removemos ~175 linhas de código duplicado.
- Agora chama `transfer_table_to_room` e trata as exceções `TransferError`.
- Mantém o comportamento de redirecionamento original (para `governance_rooms` ou `restaurant_tables`).

### 4. Testes
Foram criados testes unitários e de integração para validar a lógica.
- **Unitários (`tests/test_transfer_service.py`):** Testam a lógica do serviço isoladamente, simulando arquivos e cenários de erro/sucesso.
- **Integração:** Validam a interação entre a rota do Flask e o serviço.

## Garantias de Consistência

| Cenário de Falha | Comportamento do Sistema |
|------------------|--------------------------|
| Falha ao ler arquivos | Operação abortada, nenhum dado alterado. |
| Quarto não encontrado | Operação abortada, erro retornado ao usuário. |
| Mesa sem hóspede | Operação abortada, erro retornado. |
| Erro ao salvar cobrança no quarto | Operação abortada, mesa permanece inalterada. |
| Erro ao salvar limpeza da mesa (após salvar quarto) | **Rollback acionado:** A cobrança adicionada ao quarto é removida. O sistema retorna ao estado inicial. |
| Concorrência (2 usuários transferindo mesma mesa) | O sistema de `lock` impede acesso simultâneo. O segundo usuário aguardará ou receberá erro se o timeout exceder. |

## Como Executar os Testes

Para rodar os testes unitários do serviço:
```bash
python -m unittest tests/test_transfer_service.py
```

Para rodar os testes de integração (se houver):
```bash
python -m unittest tests/test_integration_transfer.py
```
