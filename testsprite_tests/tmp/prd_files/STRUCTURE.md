# Estrutura do Projeto Sistema Almareia Mirapraia

Este documento descreve a organização de pastas e arquivos do sistema, bem como a localização de logs e dados.

## Estrutura de Diretórios

- **app/**: Código fonte principal da aplicação (Blueprints, Templates, Static).
  - **blueprints/**: Módulos de funcionalidade (stock, kitchen, etc.).
  - **services/**: Serviços de negócio (system_config_manager, etc.).
  - **templates/**: Arquivos HTML.
  - **static/**: Assets (CSS, JS, Imagens).
- **data/**: Armazenamento de dados JSON (sessões, produtos, logs).
  - *cashier_sessions.json*: Sessões de caixa.
  - *products.json*: Cadastro de produtos.
  - *logs.json*: Logs de sistema.
- **services/**: Serviços legados e utilitários (cashier_service, backup_service, etc.).
- **logs/**: Arquivos de log do servidor e debug.
- **scripts/**: Scripts de manutenção e correção.
  - *deploy_to_production.py*: Script de deploy.
  - *cleanup_g_pip.py*: Limpeza de ambiente.
  - *fix_session_balance.py*: Correção de saldos de sessão.

## Configuração de Caminhos

O sistema foi configurado para suportar execução em ambiente local (Drive F:) e produção (Drive G:).
A detecção é feita automaticamente, priorizando o caminho local se o drive de rede não estiver disponível.

- **Configuração**: `app/services/system_config_manager.py` gerencia os caminhos.
- **Dados**: Por padrão, os dados ficam na pasta `data/` na raiz do projeto.

## Logs e Debug

- **Logs de Aplicação**: `logs/app.log` (se configurado) ou saída do console.
- **Logs de Sessão de Caixa**: Erros de carregamento de sessão são logados no console e podem ser vistos no terminal do servidor.

## Procedimentos de Manutenção

### Correção de Sessão de Caixa
Caso haja inconsistência no saldo de fechamento (diferença negativa incorreta devido a transações não-dinheiro):
1. Execute `python scripts/fix_session_balance.py`.
2. O script recalcula o saldo ignorando métodos de pagamento que não afetam a gaveta (cartão, crédito, etc.).

### Deploy
Para deploy em produção:
1. Execute `python scripts/deploy_to_production.py`.
2. O script fará backup e copiará os arquivos para o diretório de destino (G: ou F:).
