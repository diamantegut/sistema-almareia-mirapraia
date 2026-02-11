
# Relatório de Análise e Otimização de Arquivos .BAT
**Projeto:** Sistema Almareia Mirapraia  
**Data:** 08/02/2026

## 1. Resumo Executivo

Foi realizada uma análise completa dos arquivos de script em lote (`.bat`) no diretório do projeto. O objetivo foi identificar scripts essenciais, eliminar redundâncias, e garantir que todos os scripts executados utilizem o ambiente de desenvolvimento isolado (`F:\Sistema Almareia Mirapraia`) para prevenir erros de execução e dependência.

- **Total Analisado:** 17 arquivos
- **Otimizados:** 6 arquivos
- **Movidos para Deprecated:** 7 arquivos
- **Mantidos (Inalterados):** 4 arquivos

## 2. Inventário e Classificação

### 2.1. Arquivos Essenciais (Otimizados)

Estes arquivos são críticos para o desenvolvimento e operação diária. Foram atualizados para usar `activate_isolated.bat` e validar o ambiente antes da execução.

| Arquivo | Função | Otimização Realizada |
| :--- | :--- | :--- |
| `run_dev_server.bat` | Inicia servidor Flask para desenvolvimento | Validado e já utilizava isolamento. |
| `run_production_monitored.bat` | Inicia servidor com Watchdog (Monitoramento) | Renomeado (era `run_server_monitored.bat`). Adicionado isolamento e validação. |
| `restart_servers.bat` | Reinicia processos Python e servidores | Adicionado isolamento. Comandos atualizados para garantir ambiente correto. |
| `install.bat` | Instala dependências (`pip install`) | Adicionado isolamento. Gera `local_requirements.txt` automaticamente. |
| `run_tests.bat` | Executa suíte de testes e coverage | Adicionado isolamento. |
| `run_deploy.bat` | Wrapper para script de deploy PowerShell | Adicionado validação de ambiente antes de chamar o PowerShell. |

### 2.2. Arquivos Úteis (Mantidos)

Arquivos que realizam funções específicas ou de infraestrutura, mantidos em sua forma original ou com pequenas alterações.

| Arquivo | Função | Estado |
| :--- | :--- | :--- |
| `activate_isolated.bat` | Configura PATH e variáveis de ambiente | **CRÍTICO**. Script base para todo o isolamento. |
| `check_status.bat` | Verifica saúde do servidor (curl) | Mantido. Útil para diagnóstico rápido. |
| `start_queue_tunnel.bat` | Inicia Ngrok para fila de espera | Mantido. Requer instalação externa do Ngrok. |
| `setup_client.bat` | Cria atalho no Desktop do cliente | Mantido. Script utilitário para setup de estações. |

### 2.3. Arquivos Redundantes/Obsoletos (Arquivados)

Estes arquivos duplicavam funções de scripts melhores ou utilizavam métodos depreciados (ex: execução direta sem venv). Foram movidos para `scripts\deprecated_bat\`.

| Arquivo Removido | Motivo | Substituto Recomendado |
| :--- | :--- | :--- |
| `run.bat` | Execução genérica sem isolamento | `run_dev_server.bat` |
| `run_server.bat` | Execução direta do wsgi.py | `run_production_monitored.bat` |
| `start_server.bat` | Monitoramento via loop batch (menos robusto) | `run_production_monitored.bat` |
| `run_server_monitored.bat` | Renomeado para evitar confusão | `run_production_monitored.bat` |
| `setup_firewall_server.bat` | Configuração única, não recorrente | N/A (Consultar se necessário) |
| `update_production.bat` | Redundante com sistema de deploy | `run_deploy.bat` |
| `safe_update.bat` | Script antigo de atualização | `run_deploy.bat` |
| `scripts\deploy_wrapper.bat` | Wrapper duplicado | `run_deploy.bat` |

## 3. Detalhes das Otimizações

### Padronização de Isolamento
Todos os scripts essenciais agora iniciam com o seguinte bloco (ou equivalente via `call`):

```batch
call "%~dp0activate_isolated.bat" python validate_environment.py
if errorlevel 1 (
    echo [ERRO] Falha na validacao do ambiente.
    exit /b 1
)
```

Isso garante que:
1.  O Python utilizado é sempre o do `venv` local.
2.  As variáveis de ambiente `ALMAREIA_ISOLATED_ENV` estão definidas.
3.  Caminhos para drives externos (`G:`) são ignorados pelo código Python.

### Logs e Tratamento de Erros
- Scripts como `install.bat` agora verificam `%errorlevel%` e pausam em caso de erro.
- `restart_servers.bat` mata processos pendentes antes de iniciar novos, prevenindo conflitos de porta.

## 4. Plano de Rollback

Caso algum script antigo seja necessário, eles podem ser recuperados do diretório:
`F:\Sistema Almareia Mirapraia\scripts\deprecated_bat\`

Para restaurar, basta mover o arquivo de volta para a raiz.

## 5. Próximos Passos Recomendados

1.  Utilizar exclusivamente `run_dev_server.bat` para desenvolvimento.
2.  Utilizar `run_production_monitored.bat` em ambiente de produção (se aplicável rodar neste diretório).
3.  Manter o hábito de rodar `install.bat` ao adicionar libs, para garantir que `local_requirements.txt` fique atualizado.
