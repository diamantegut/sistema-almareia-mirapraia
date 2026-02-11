# Documentação do Processo de Atualização do Sistema

Este documento descreve o comportamento do atualizador do sistema (`scripts/safe_updater.py`), especificamente como ele lida com a preservação de dados personalizados durante as atualizações.

## Visão Geral

O atualizador foi aprimorado para realizar um "Merge Inteligente" (Smart Merge) dos arquivos de dados, em vez de sobrescrevê-los completamente. Isso garante que personalizações feitas pelo usuário (como nomes de produtos, descrições, perguntas e estoque) sejam mantidas, enquanto ainda permite que o sistema receba novos produtos e atualizações de preços.

## Arquivos Protegidos e Campos Preservados

Os seguintes arquivos são tratados com lógica de merge:

### 1. `data/menu_items.json` (Menu do Sistema)

Ao atualizar este arquivo, o sistema **preserva** os seguintes campos se o produto já existir localmente:

*   **`name`**: Nome do produto (para manter correções ou nomes personalizados).
*   **`description`**: Descrição do produto.
*   **`questions`**: Perguntas obrigatórias/opcionais configuradas.
*   **`observations`**: Observações internas.
*   **`paused`**: Status de pausa do item (se está indisponível).
*   **`active`**: Se o item está ativo ou não.
*   **`image_url`**: URL da imagem (caso tenha sido alterada localmente).

**Campos Atualizados:**
*   **`price`**: O preço será atualizado para o valor do novo pacote de atualização (exceto se incluído na lista de proteção futura). *Nota: Atualmente o preço é atualizado.*
*   **Novos Produtos**: Produtos que não existem no arquivo local serão adicionados integralmente.

### 2. `data/products.json` (Insumos e Estoque)

Ao atualizar este arquivo, o sistema **preserva**:

*   **`min_stock`**: Estoque mínimo configurado.
*   **`suppliers`**: Lista de fornecedores.
*   **`unit`**: Unidade de medida.
*   **`package_size`**: Tamanho da embalagem.
*   **`purchase_unit`**: Unidade de compra.
*   **`frequency`**: Frequência de compra.
*   **`is_internal`**: Flag de uso interno.

## Como Funciona o Merge

1.  O sistema lê o arquivo local atual (`data/...`).
2.  Lê o arquivo de atualização (`update_source/data/...`).
3.  Para cada item no arquivo de atualização:
    *   Se o ID já existe no local: Cria uma cópia do item novo, mas restaura os valores dos campos protegidos (listados acima) usando os dados do arquivo local.
    *   Se o ID é novo: Adiciona o item novo.
4.  Itens que existem apenas no local (e não na atualização) são mantidos.
5.  O arquivo local é sobrescrito com a lista mesclada (um backup `.pre_merge_bak` é criado antes).

## Executando a Atualização

Para aplicar a atualização com segurança:

1.  Coloque os arquivos da nova versão na pasta `update_source/` na raiz do projeto.
2.  Execute o script:
    ```bash
    python scripts/safe_updater.py
    ```
3.  O script irá:
    *   Criar um backup completo em `backups/`.
    *   Aplicar atualizações de código (ignorando arquivos protegidos).
    *   Executar o **Smart Merge** para `menu_items.json` e `products.json`.
    *   Executar migrações de esquema se necessário.

## Logs

O processo gera logs detalhados em `scripts/updater.log` e no console, informando quais arquivos foram mesclados e quaisquer erros ocorridos.
