# Relatório de Limpeza de Arquivos .BAT

Data: 11/02/2026

## Arquivos Mantidos e Atualizados

| Arquivo | Função | Status |
|---------|--------|--------|
| `run.bat` | Inicia o servidor de desenvolvimento (`python run.py`) | **Atualizado** |
| `start_prod.bat` | Inicia o servidor de produção (`python wsgi.py`) | **Criado** |
| `install.bat` | Instala dependências via pip | **Atualizado** |
| `check_status.bat` | Verifica se o servidor está respondendo (Health Check) | **Mantido** |

## Arquivos Removidos (Movidos para `_trash/bat_legacy`)

Os seguintes arquivos foram considerados obsoletos ou redundantes após a reestruturação do projeto para uso de `run.py`/`wsgi.py` e remoção do antigo `app.py` monolítico.

| Arquivo | Motivo da Remoção |
|---------|-------------------|
| `run_dev_server.bat` | Redundante. Substituído por `run.bat`. |
| `start_server.bat` | Lógica de loop antiga e insegura. Substituído por gerenciamento padrão. |
| `run_server.bat` | Substituído por `start_prod.bat` para clareza. |
| `run_production_monitored.bat` | Dependia de `server_watchdog.py` (removido). |
| `restart_servers.bat` | Dependia de `app.py` antigo. |
| `activate_isolated.bat` | Wrapper de ambiente virtual desnecessário para execução padrão. |
| `start_ngrok_tunnels.bat` | Scripts de túnel legados. |
| `start_queue_tunnel.bat` | Scripts de túnel legados. |
| `setup_client.bat` | Configuração legado de cliente. |
| `setup_firewall_server.bat` | Configuração legado de firewall. |
| `update_production.bat` | Script de deploy legado. |
| `run_deploy.bat` | Script de deploy legado. |
| `run_tests.bat` | Runner de testes antigo. |
| `safe_update.bat` | Sistema de update antigo. |

## Instruções

- Para desenvolver: Execute `run.bat`.
- Para produção: Execute `start_prod.bat`.
- Para instalar libs: Execute `install.bat`.
