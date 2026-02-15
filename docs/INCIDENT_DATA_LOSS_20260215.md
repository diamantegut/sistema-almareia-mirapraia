# Relatório de Incidente: Perda de Dados em table_orders.json
**Data:** 15 de Fevereiro de 2026
**Severidade:** Crítica
**Status:** Resolvido

## 1. Resumo do Incidente
Foi reportada a perda completa de pedidos no sistema de restaurante (arquivo `table_orders.json`) referentes ao intervalo operacional entre 11:08 e 12:59. A análise confirmou que o arquivo de dados principal havia sido revertido para uma versão antiga (datada de 01/02/2026), resultando no desaparecimento das mesas ativas.

## 2. Investigação Forense

### 2.1 Análise de Logs (`logs/actions/2026-02-15.json`)
A análise dos logs de sistema confirmou a atividade normal durante o período afetado:
- **12:58:04**: "Pedido Adicionado" na Mesa 43 (usuário: welington).
- **12:59:28**: "Mesa Aberta" Mesa 61 (usuário: adailton).
- **12:59:38**: "Mesa Aberta" Mesa 46 (usuário: welington).
- **13:00 - 13:02**: Atividades contínuas nas mesas 75, 44 e 54.

Os logs provam que o sistema estava operando e gravando dados corretamente em memória/disco até pelo menos 13:02.

### 2.2 Análise de Arquivos
- **Estado Encontrado**: O arquivo `data/table_orders.json` continha apenas dados antigos (mesas `FUNC_TestAdmin`, `FUNC_robson`, `69`), condizentes com o estado do início de Fevereiro.
- **Sistema de Backup**: O sistema de auto-backup funcionou corretamente. Foram encontrados múltiplos backups no diretório `data/backups/table_orders/` cobrindo o período do incidente.
- **Backup Recuperado**: O arquivo `table_orders_20260215_130221_edson.json`, criado às 13:02:21, foi identificado contendo todas as mesas perdidas (43, 61, 46, 75, 44, 54, etc.).

## 3. Causa Raiz
A causa raiz foi identificada como uma **sobrescrita indevida causada pelo controle de versão (Git)**.
- O arquivo `data/table_orders.json` estava sendo rastreado pelo Git (não ignorado).
- Uma operação de sincronização ou restauração (provavelmente um `git restore .` ou `git pull` executado por script de atualização ou manualmente) detectou o arquivo como "modificado" e o reverteu para a versão comitada no repositório, que era antiga.
- Isso explica por que o arquivo "voltou no tempo" instantaneamente.

## 4. Resolução Implementada
1.  **Recuperação de Dados**: O arquivo `data/table_orders.json` foi restaurado com sucesso utilizando a cópia íntegra do backup `table_orders_20260215_130221_edson.json`.
2.  **Verificação**: Confirmada a presença das mesas 43, 61, 46 e demais pedidos no arquivo restaurado.

## 5. Medidas Preventivas
Para evitar que este incidente ocorra novamente:
1.  **Atualização do .gitignore**: O arquivo `.gitignore` foi modificado para incluir explicitamente `data/*.json`, instruindo o Git a ignorar alterações em arquivos de banco de dados JSON.
2.  **Remoção do Rastreamento**: Recomenda-se executar o comando `git rm --cached data/table_orders.json` em todos os ambientes para garantir que o Git pare de monitorar este arquivo sem excluí-lo do disco.

## 6. Conclusão
Os dados foram recuperados integralmente com zero perda de informação confirmada (restore do backup de 13:02 cobriu todo o período reportado). A falha foi de configuração de ambiente (arquivo de dados versionado incorretamente), e as medidas corretivas foram aplicadas para blindar o sistema contra futuras reversões acidentais.
