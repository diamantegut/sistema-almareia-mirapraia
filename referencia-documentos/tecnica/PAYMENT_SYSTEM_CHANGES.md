# Documentação de Alterações no Sistema de Pagamentos

## Resumo das Alterações
Foram realizadas melhorias significativas na estrutura de pagamentos para suportar múltiplos caixas (Restaurante, Recepção, Reservas) e integração fiscal.

## 1. Múltiplos Caixas
O sistema agora suporta três caixas distintos, com controle granular de disponibilidade de formas de pagamento.

### Identificadores de Caixas
- `caixa_restaurante`: Caixa do Restaurante/Bar
- `caixa_recepcao`: Caixa da Recepção (Checkout, Frigobar)
- `caixa_reservas`: Caixa específico para adiantamentos e reservas

### Compatibilidade
Mantida compatibilidade com identificadores antigos (`restaurant`, `reception`).

### Configuração
Acesse `/payment-methods` (Menu Admin) para configurar em quais caixas cada forma de pagamento deve aparecer.

## 2. Lógica de Filtragem
A disponibilidade das formas de pagamento é filtrada no backend:

- **Restaurante**: Exibe métodos marcados com `restaurant` OU `caixa_restaurante`.
- **Recepção**: Exibe métodos marcados com `reception` OU `caixa_recepcao`.
- **Reservas**: Exibe métodos marcados com `caixa_reservas` (ou `reservas`).

## 3. Integração Fiscal (Pool Fiscal)
Implementada lógica para identificar e encaminhar pagamentos fiscais para o `FiscalPoolService`.

### Funcionamento
1. Cada forma de pagamento possui uma flag `is_fiscal`.
2. Ao fechar uma conta (Restaurante ou Recepção), o sistema verifica essa flag.
3. Transações realizadas com métodos fiscais são marcadas como `is_fiscal=True` no payload enviado ao Pool.
4. O `FiscalPoolService` armazena essas transações em `fiscal_pool.json` para processamento/emissão posterior.

### Pontos de Integração
- **Recepção**: `pay_charge` (Pagamento de contas de quarto)
- **Restaurante**: `close_order` (Fechamento de mesa)

## 4. Arquivos Modificados
- `app/blueprints/main/routes_payment.py`: Nova rota global de gestão.
- `app/templates/payment_methods.html`: Interface atualizada com checkboxes por caixa.
- `app/blueprints/restaurant/routes.py`: Atualização da lógica de fechamento e filtragem.
- `app/blueprints/reception/routes.py`: Atualização da lógica de pagamento e filtragem.
- `app/services/fiscal_pool_service.py`: Serviço de pool (existente, agora integrado).

## 5. Testes
Novos testes de unidade criados em `tests/test_payment_fiscal_logic.py` para validar a lógica de filtragem e flags fiscais.
