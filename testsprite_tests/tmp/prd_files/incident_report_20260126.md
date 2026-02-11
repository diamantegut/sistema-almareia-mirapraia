# Relatório de Incidente - 26/01/2026

## 1. Descrição do Problema
Relatos recorrentes de desaparecimento de todas as mesas do sistema (dashboard vazio) após as 11:00 do dia 26/01/2026. O problema ocorria principalmente quando o script de teste `verify_pending_tasks.py` era executado ou quando atendentes abriam mesas vinculadas a quartos.

## 2. Diagnóstico (Causa Raiz)
A investigação revelou que o script de teste `verify_pending_tasks.py` estava sobrescrevendo o arquivo de produção `data/table_orders.json` com dados de teste.
- O script não utilizava um arquivo temporário isolado.
- Ao rodar, ele limpava o banco de dados real.
- O sistema, ao recarregar, encontrava zero mesas.
- Qualquer nova mesa aberta (ex: por atendente) se tornava a única mesa existente.

## 3. Ações de Correção

### 3.1 Correção do Script de Teste
O arquivo `verify_pending_tasks.py` foi modificado para utilizar a biblioteca `unittest.mock` e arquivos temporários:
- **Antes:** Escrevia diretamente em `app.TABLE_ORDERS_FILE`.
- **Depois:** Cria um diretório temporário (`tempfile.mkdtemp()`) e faz patch da variável `TABLE_ORDERS_FILE` durante os testes (`@patch('app.TABLE_ORDERS_FILE', ...)`).

### 3.2 Restauração de Dados
Foi desenvolvido e executado o script `restore_tables_v2.py`:
- Recuperou 20 mesas perdidas utilizando os logs de transações (`stock_logs.json`) e logs de ações (`actions`).
- Filtro aplicado: Restaurar apenas mesas ativas após as 11:00 de 26/01/2026.

### 3.3 Melhoria na Restrição de Frigobar
Detectada falha na normalização de nomes de departamento ("Recepção" vs "recepcao").
- **Correção:** Implementada função `normalize_text` na rota `add_item` em `app.py`.
- **Resultado:** Usuários da "Recepção" e "Governança" agora conseguem lançar itens de frigobar corretamente, sem bloqueios indevidos.

## 4. Ferramentas Adicionais Desenvolvidas

### 4.1 Auditoria de Vendas (`audit_sales.py`)
Novo script para gerar relatórios de "Realizado vs Esperado" (Sales Audit).
- Analisa `stock_logs.json` para reconstruir o volume de vendas por produto.
- Comando: `python audit_sales.py --date "26/01/2026" --time "11:00"`

### 4.2 Backup Automático
- Configurado backup específico de `table_orders.json` a cada 10 minutos (`backup_service.py`).
- Retenção de 24 horas para recuperação rápida em caso de falhas futuras.

## 5. Validação
- **Testes Automatizados:** O script `verify_pending_tasks.py` agora roda com sucesso (5/5 testes) sem afetar o banco de produção.
- **Ambiente de Produção:** O arquivo `table_orders.json` permanece íntegro após a execução dos testes.
- **Auditoria:** O relatório de auditoria confirma 20 mesas ativas e vendas registradas (ex: 16 Águas sem Gás, 13 Águas de Coco).

---
**Status Final:** Resolvido. Monitoramento recomendado por 24h.
