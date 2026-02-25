# Relatório de Auditoria de Estoque: Deduções Anômalas de Ostras M

**Data do Relatório:** 23/02/2026
**Período Auditado:** 12/02/2026 a 21/02/2026
**Produto Alvo:** Ostras M (ID: 111)

## 1. Resumo Executivo
Foi identificada uma falha crítica de integridade de dados causando a dedução incorreta do produto "Ostras M" sempre que o prato "Filé de peixe branco na folha de bananeira (individual)" é vendido. A causa raiz é uma **colisão de ID (ID 111)** entre o produto de estoque e o item de menu, combinada com uma lógica de baixa de estoque que não diferencia adequadamente entre produtos diretos e itens compostos (receitas).

**Impacto:**
- **Ostras M**: 15 unidades baixadas indevidamente (Estoque Virtual < Estoque Físico).
- **Peixe Branco (ID 225)**: 15 porções NÃO baixadas (Estoque Virtual > Estoque Físico).

## 2. Análise de Movimentações (Deduções Detectadas)
Todas as movimentações abaixo foram classificadas como "Venda" e ocorreram automaticamente após o fechamento de mesas/contas.

| Data | Qtd | Origem | Usuário |
|---|---|---|---|
| 12/02/2026 | -1.0 | Venda Mesa 61 | filipe |
| 13/02/2026 | -1.0 | Venda Quarto 32 | priscila |
| 15/02/2026 | -1.0 | Venda Mesa 57 | eduardo |
| 16/02/2026 | -1.0 | Venda Quarto 03 | jose |
| 16/02/2026 | -1.0 | Venda Mesa 42 | eduardo |
| 17/02/2026 | -1.0 | Venda Quarto 16 | jose |
| 17/02/2026 | -1.0 | Venda Mesa 59 | eduardo |
| 18/02/2026 | -1.0 | Venda Mesa 47 | eduardo |
| 19/02/2026 | -1.0 | Venda Quarto 33 | priscila |
| 19/02/2026 | -1.0 | Venda Quarto 02 | priscila |
| 19/02/2026 | -2.0 | Venda Mesa 44 | filipe |
| 20/02/2026 | -1.0 | Venda Mesa 52 | eduardo |
| 20/02/2026 | -1.0 | Venda Mesa 45 | eduardo |
| 21/02/2026 | -1.0 | Venda Mesa 43 | eduardo |

**Total Deduzido:** 15.0 Unidades

## 3. Validação de Pedidos e Correlação
- **Ostras M**: NENHUM pedido de "Ostras M" foi encontrado no histórico de vendas para as mesas citadas.
- **Correlação Perfeita**: Em 100% dos casos acima, houve a venda do item **"Filé de peixe branco na folha de bananeira (individual)"**.
- **Coincidência de ID**:
    - Produto "Ostras M" (data/products.json) -> **ID 111**
    - Menu "Filé de peixe branco..." (data/menu_items.json) -> **ID 111**

## 4. Diagnóstico Técnico (Causa Raiz)
O sistema de vendas, ao processar a baixa de estoque, utiliza o ID do item vendido para buscar o produto correspondente.
1. O cliente pede "Filé de peixe branco..." (ID 111).
2. O sistema busca no cadastro de produtos se existe algo com ID 111.
3. Encontra "Ostras M" (ID 111).
4. Realiza a baixa direta de 1 unidade de "Ostras M".
5. **Falha**: O sistema ignora que o ID 111 é um prato composto (Menu Item) com ficha técnica (Receita) que deveria baixar o insumo "Peixe Branco" (ID 225).

## 5. Plano de Ação Corretiva

### Imediato (Alta Prioridade)
1. **Alterar ID do Item de Menu**: Modificar o ID do "Filé de peixe branco..." para um novo ID único (ex: 11100 ou UUID), evitando a colisão.
2. **Correção de Estoque**:
    - **Estornar** as 15 unidades de Ostras M.
    - **Baixar** 15 unidades de Peixe Branco (ID 225).

### Estrutural (Prevenção)
1. **Refatoração da Lógica de Baixa**: Alterar `routes.py` para verificar primeiro se o item vendido possui ficha técnica (recipe) em `menu_items.json` antes de buscar por ID em `products.json`.
2. **Validação de IDs**: Implementar check para impedir que Produtos e Itens de Menu compartilhem o mesmo ID numérico.

### Responsáveis
- **Auditoria/Dados**: Agente Trae (Concluído)
- **Correção de Código**: Equipe de Desenvolvimento (Pendente)
- **Ajuste Manual**: Gerente de Estoque (Pendente)

---
*Relatório gerado automaticamente pelo Agente de Auditoria do Sistema.*
