# Estrutura de Diretórios do Sistema Almareia Mirapraia

Este documento descreve a organização correta dos arquivos e pastas do sistema, conforme padronização para o ambiente de produção e desenvolvimento.

## Raiz do Projeto (`F:\Sistema Almareia Mirapraia`)

*   **`app/`**: Código fonte da aplicação Flask.
    *   **`blueprints/`**: Módulos de rotas (auth, main, reception).
    *   **`models/`**: Definições de dados e acesso ao "banco" (JSON).
    *   **`services/`**: Lógica de negócios (CashierService, SystemConfigManager, etc.).
    *   **`static/`**: Arquivos estáticos (CSS, JS, Imagens, Uploads).
    *   **`templates/`**: Templates HTML (Jinja2).
    *   **`__init__.py`**: Inicialização da aplicação (Factory Pattern).
*   **`data/`**: **(IMPORTANTE)** Diretório de persistência de dados JSON.
    *   *Todos os arquivos .json de dados (cashier_sessions.json, products.json, etc.) residem aqui.*
    *   *Nunca hardcoded em G:\ ou outros locais.*
*   **`backups/`**: Diretório local de backups automáticos.
    *   Organizado por tipo: `Caixa`, `Produtos`, `Sistema_Completo`, etc.
*   **`logs/`**: Logs de execução do sistema.
    *   `app.log`, `error.log`, `scheduler.log`.
*   **`fiscal_documents/`**: Armazenamento de XMLs e PDFs fiscais.
*   **`scripts/`**: Scripts de manutenção, deploy e utilitários.
*   **`system_config.json`**: Arquivo mestre de configuração (caminhos relativos).
*   **`app.py`**: Ponto de entrada da aplicação (WSGI entry point).

## Regras de Caminhos

1.  **Caminhos Relativos**: Todo o código deve usar caminhos relativos baseados em `BASE_DIR` (definido em `system_config_manager.py`).
2.  **Centralização**: Nunca construa caminhos manualmente com `os.path.join` espalhado pelo código. Use sempre:
    *   `from app.services.system_config_manager import get_data_path, get_backup_path`
    *   Exemplo: `get_data_path('cashier_sessions.json')`
3.  **Ambiente de Produção (G:)**: A pasta `G:\Almareia Mirapraia Sistema Producao` é considerada um espelho ou backup remoto, mas **não** deve ser usada como fonte de dados ativa (live data) para a aplicação rodando localmente, exceto durante migrações explícitas.

## Logs e Debugging

*   O sistema utiliza o módulo `logging` do Python.
*   Logs principais são gravados em `logs/app.log`.
*   Erros críticos de caixa são logados em `logs/cashier_errors.log` (se configurado) ou no log principal.
*   Para debug de caminhos, verifique `app/services/system_config_manager.py`.

## Fluxo de Sessões de Caixa

1.  **Criação**: `CashierService.open_session` -> Cria entrada em `data/cashier_sessions.json`.
2.  **Persistência**: Gravação atômica (escreve temp -> renomeia) para evitar corrupção.
3.  **Backup**: A cada transação, um backup criptografado (base64) é salvo em `backups/Caixa/`.
