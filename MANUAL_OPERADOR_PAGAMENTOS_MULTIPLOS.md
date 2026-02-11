# Manual do Operador - Pagamentos Múltiplos
**Versão:** 1.0  
**Data:** 11/02/2026

## Visão Geral
O sistema foi atualizado para permitir o registro de **múltiplos métodos de pagamento** em uma única transação nos caixas da Recepção e de Reservas. Isso permite, por exemplo, que um cliente pague uma parte da conta em dinheiro e o restante no cartão de crédito.

Esta funcionalidade está disponível nos seguintes módulos:
1. **Caixa Recepção** (Consumo de Hóspedes / Guest Consumption)
2. **Caixa Reservas** (Diárias / Daily Rates)

---

## 1. Caixa Recepção (Guest Consumption)

### Como Registrar um Pagamento Múltiplo
1. **Adicionar Itens**: Adicione os itens de consumo normalmente à lista.
2. **Selecionar Pagamento**:
   - No campo de seleção de pagamento, escolha o primeiro método (ex: "Dinheiro").
   - Digite o valor correspondente a este método.
   - Clique no botão **"+" (Adicionar)**.
3. **Adicionar Mais Métodos**:
   - Repita o processo para os próximos métodos (ex: "Cartão de Crédito").
   - O sistema exibirá uma lista com os pagamentos adicionados e o valor restante a pagar.
4. **Finalizar**:
   - O botão "Confirmar Pagamento" só será habilitado quando o valor total dos pagamentos for igual ao valor total da conta.
   - Clique em "Confirmar Pagamento" para registrar a transação.

### Visualização no Histórico
- Na tabela de transações do dia, pagamentos múltiplos aparecerão identificados como **"Múltiplos"**.
- Clique no botão **"Múltiplos"** (ícone de informação) para abrir uma janela detalhando quanto foi pago em cada método (ex: R$ 50,00 Dinheiro + R$ 150,00 Crédito).

### Observações Importantes
- O sistema possui uma tolerância de R$ 0,05 para diferenças de arredondamento.
- Não é possível adicionar pagamentos com valor zero.

---

## 2. Caixa Reservas (Daily Rates)

### Como Registrar um Pagamento Múltiplo
O processo é idêntico ao do Caixa Recepção:
1. Preencha a descrição da transação (ex: "Check-in Apto 101").
2. Digite o valor total da operação.
3. Utilize a seção **"Adicionar Pagamento"** para compor o valor total usando diferentes métodos (Dinheiro, PIX, Cartão, etc.).
4. A lista de pagamentos mostrará o progresso e o valor restante.
5. Finalize a operação quando o total estiver completo.

### Visualização no Histórico
- Assim como na Recepção, as transações serão marcadas como **"Múltiplos"**.
- Um botão de detalhes permitirá visualizar a composição do pagamento.

---

## 3. Resolução de Problemas Comuns

| Problema | Causa Provável | Solução |
|----------|----------------|---------|
| **Botão de confirmar desabilitado** | O valor total dos pagamentos não corresponde ao valor da conta. | Verifique se falta algum valor ou se há excesso. O valor "Restante" deve ser R$ 0,00. |
| **Erro ao adicionar pagamento** | Valor inválido ou método não selecionado. | Certifique-se de digitar um valor numérico positivo e selecionar um método válido. |
| **Diferença de centavos** | Erros de arredondamento. | O sistema aceita diferenças de até R$ 0,05. Se a diferença for maior, ajuste um dos valores. |

---

## Suporte
Em caso de dúvidas ou erros persistentes, entre em contato com o suporte técnico e informe a mensagem de erro exibida na tela.
