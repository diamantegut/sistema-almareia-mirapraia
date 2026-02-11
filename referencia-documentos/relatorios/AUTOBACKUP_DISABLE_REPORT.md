# Relatório de Processos de Autobackup Desativados

Data: 11/02/2026

## Processos Identificados e Desativados

### 1. Scheduler Interno (Python)
- **Localização:** `app/services/backup_service.py`
- **Mecanismo:** Threading e Scheduler interno do Python.
- **Configuração Anterior:**
  - `full_system`: a cada 1 hora
  - `tables`: a cada 1 minuto
  - `reception`: a cada 20 minutos
  - `insumos`: a cada 3 horas
  - `cashiers_open`: a cada 20 minutos
  - `logs`: a cada 24 horas
- **Ação:** Configuração `BACKUP_CONFIGS` esvaziada para impedir execução.

### 2. Agendador de Tarefas do Windows
- **Verificação:** Nenhuma tarefa externa vinculada encontrada nos scripts `.bat` ativos. Os scripts de monitoramento (`run_production_monitored.bat`) que poderiam reiniciar processos foram movidos para `_trash`.

### 3. Scripts de Backup Isolados
- **Localização:** `scripts/deprecated_bat/safe_update.bat` e outros.
- **Ação:** Scripts movidos para `_trash` na etapa anterior.

## Justificativa
A desativação centralizada visa preparar o ambiente para um sistema de backup robusto e externo (Cloud + Git), evitando concorrência de I/O e redundância desnecessária que pode causar locks em arquivos JSON críticos (`table_orders.json`).
