# SYSTEM OVERVIEW — Sistema Almareia Mirapraia

## 1) Resumo Executivo

O projeto é uma aplicação monolítica em **Flask** voltada para operação hoteleira e de restaurante, com módulos de recepção, financeiro, estoque, cozinha, governança, RH, fiscal, relatórios, auditoria e administração de sistema.

Arquiteturalmente, o sistema combina:
- **Camada web** por blueprints Flask.
- **Persistência híbrida**:
  - JSON como armazenamento operacional principal.
  - SQLite via SQLAlchemy para domínios relacionais (fila, reservas, hóspedes, pesquisas, logs estruturados).
- **Camada de serviços** extensa, com regras de negócio, integrações externas e rotinas de proteção/auditoria.
- **Scheduler** para jobs recorrentes (fiscal, limpeza, risco financeiro e backups de segurança).

---

## 2) Entrypoints e Inicialização

### 2.1 Entradas principais
- `run.py`: inicialização padrão em desenvolvimento.
- `app/__init__.py`: fábrica da aplicação (`create_app`) e registro de blueprints/hook de segurança.

### 2.2 Fluxo de bootstrap
1. Cria app Flask com templates e estáticos.
2. Configura secret key e flag `EXTERNAL_OPEN_MODE`.
3. Inicializa SQLAlchemy (`department_logs.db`).
4. Registra todos os blueprints.
5. Inicializa logging de ações.
6. Sobe scheduler (quando aplicável no contexto do Flask reloader).
7. Registra hooks:
   - `before_request`: timer/performance.
   - `before_request`: modo externo sem login (se habilitado).
   - `before_request`: enforcement de autorização (permission service).
   - `after_request`: logging de requisições lentas.

---

## 3) Stack Tecnológica

### 3.1 Backend
- Python + Flask
- Flask-SQLAlchemy
- APScheduler

### 3.2 Processamento/relatórios
- pandas
- xlsxwriter
- reportlab
- PIL/Pillow

### 3.3 Integrações e segurança
- requests (integrações externas)
- cryptography (Fernet e certificado/SEFAZ)

---

## 4) Organização do Código

## 4.1 Estrutura de alto nível
- `app/blueprints`: camadas web por domínio.
- `app/services`: regras de negócio, persistência, segurança, integrações.
- `app/models`: SQLAlchemy models e sessão DB.
- `app/templates`: HTML server-side.
- `app/static`: CSS/JS/imagens/uploads de UI.
- `tests/`: suíte de testes focada em governança JSON e fundação PATH.
- `docs/architecture`: documentos de arquitetura e trilhas PATH.

### 4.2 Blueprints registrados
- auth, main, reception, stock, kitchen, admin, hr, finance, suppliers, governance, guest, maintenance, menu, quality, reports, restaurant, assets, guest_portal, financial_audit.

---

## 5) Domínios Funcionais Principais

### 5.1 Recepção e reservas
- Gestão de quartos, ocupação, cobranças, restrições de estadia/chegada.
- Operação de caixa de recepção.
- Sinergia com reservas, pré-checkin e canal OTA.

### 5.2 Restaurante e cozinha
- Mesas e pedidos (`table_orders.json`).
- Cardápio (`menu_items.json`), produtos (`products.json`) e fluxo de venda.
- Caixa do restaurante e fechamento/baixa de itens.

### 5.3 Estoque e ativos
- Entradas/saídas, solicitações, transferências e conferências.
- Estoque protegido com trilha de segurança e backups periódicos.
- Módulo de ativo imobilizado com conferência dedicada.

### 5.4 Financeiro e auditoria
- Fechamentos, conciliações, risco financeiro, ledger e auditoria financeira.
- Emissão e fila fiscal (pool fiscal), XML/PDF de documentos.

### 5.5 RH e governança operacional
- Colaboradores, documentos, tracking de jornada, solicitações de reset.
- Governança de limpeza/lavanderia/manutenção.

### 5.6 Administração e segurança
- Painéis administrativos.
- Controle de permissões legado + motor de policies (authz v2).
- Saúde de backups e observabilidade operacional.

---

## 6) Persistência e Dados

## 6.1 Modelo híbrido
- **JSON-first** para operações de negócio (grande maioria dos artefatos).
- **SQLite/SQLAlchemy** para domínios relacionais e eventos rastreáveis.

### 6.2 JSON: camada central de persistência
- `app/services/data_service.py` concentra loaders/savers de arquivos canônicos.
- `app/services/system_config_manager.py` centraliza caminhos de arquivos e diretórios.
- Trilha recente reforçou writer único e hardening em JSON críticos.

### 6.3 SQLAlchemy: entidades relevantes
- Logs de ações departamentais.
- Fila de espera e eventos de fila.
- Pesquisas de satisfação (survey, perguntas, respostas, convites).
- Catálogo de quartos/categorias.
- Hóspedes, preferências, reservas, estadas, histórico de status de quarto.
- Pagamentos, consumos e auditoria de reservas.

### 6.4 Locking e integridade
- Uso de lock de arquivo (`app/utils/lock.py` e pontos especializados).
- Escrita atômica em partes críticas.
- Estratégias anti-overwrite e backups temporais em serviços críticos.

---

## 7) Camada de Paths e Configuração

### 7.1 Estado atual
- `system_config_manager` fornece:
  - `get_data_path`, `get_log_path`, `get_backup_path`, `get_fiscal_path`
  - dezenas de constantes canônicas de arquivo.
- `path_resolver` foi introduzido como fundação da trilha PATH.

### 7.2 Modo de operação
- Modo atual: **legacy**.
- Estrutura física futura planejada:
  - `System`
  - `System_Data`
  - `System_Backup`
- Nesta fase, não há migração física ativada.

### 7.3 Telemetria de resolução
- `audit_resolution(...)` registra eventos de resolução de paths.
- `get_path_resolution_audit(...)` permite inspeção de eventos.

---

## 8) Segurança, Autenticação e Autorização

### 8.1 Autenticação
- Login por sessão Flask.
- Usuários em `users.json`.
- Fluxos de login/logout/registro/troca de senha/solicitação de reset.

### 8.2 Autorização
- Decorators clássicos:
  - `login_required`
  - `role_required`
- Camada avançada:
  - `permission_service` + motor authz (`app/services/authz/*`).
  - Suporte a modos de rollout e fallback entre legado e policies.

### 8.3 Auditoria e rastreabilidade
- Logging operacional por `LoggerService`.
- Trilha para eventos de autorização e conflitos de paridade.
- Módulos de segurança (alertas, limites, settings).

---

## 9) Jobs Agendados (Scheduler)

O `scheduler_service` executa tarefas recorrentes:
- Sincronização fiscal (janela horária controlada).
- Atualização diária de status de limpeza por ocupação.
- Backups de segurança de estoque/menu por serviços especializados.
- Scan periódico de risco financeiro.

Também inicia jobs imediatos ao subir a aplicação (threaded), conforme configuração do bootstrap.

---

## 10) Integrações Externas

Principais integrações identificadas:
- Fiscal/SEFAZ/Nuvem Fiscal.
- Booking.com (credenciais e token cache).
- WhatsApp (mensageria/etiquetas/templates).
- Facebook.
- Assinaturas/documentos e rotinas auxiliares.

Observação: integrações têm persistência local de configuração/cache e logging de sucesso/erro.

---

## 11) Fluxos Críticos de Negócio (Visão Operacional)

### 11.1 Operação de caixa (recepção/restaurante)
1. Abertura de sessão de caixa.
2. Registro de transações.
3. Fechamento com conferência.
4. Auditoria/backup de artefatos e relatórios.

### 11.2 Pedido de mesa e consumo
1. Criação/edição de pedido em mesa.
2. Consumo de itens do menu/produtos.
3. Geração de histórico de vendas.
4. Reflexo em estoque e financeiro.

### 11.3 Limpeza diária automática
1. Scheduler lê ocupação.
2. Calcula status alvo (dirty/dirty_checkout).
3. Persiste status atualizado de limpeza.

### 11.4 Emissão fiscal e fila
1. Eventos de emissão entram no fiscal pool.
2. Serviços marcam disponibilidade de XML/PDF.
3. Financeiro/administrativo consultam e operam o estado.

---

## 12) Testes e Qualidade

### 12.1 Estado atual da suíte
Há uma suíte focada em governança de escrita JSON e fundação PATH:
- `test_users_writer_pr_json_01.py`
- `test_cashier_writer_pr_json_02.py`
- `test_table_orders_pr_json_03.py`
- `test_secure_writers_pr_json_04.py`
- `test_json_hygiene_pr_05.py`
- `test_json_hygiene_pr_06.py`
- `test_path_resolver_pr_path_01.py`
- `test_hotel_backup_foundation_service.py`

### 12.2 Uso recomendado para ferramentas de teste automatizado (ex.: TestSprite)
- Priorizar cenários E2E por domínio:
  - autenticação e sessão;
  - fluxo caixa recepção;
  - fluxo restaurante/mesa/pagamento;
  - fluxo estoque (entrada/ajuste/relatórios);
  - fluxo fiscal pool + emissão;
  - rotas administrativas críticas.
- Incluir verificação de integridade de JSONs críticos e trilhas de auditoria.
- Cobrir comportamento em `EXTERNAL_OPEN_MODE` separado do modo normal.

---

## 13) Riscos Técnicos e Atenções

- **Heterogeneidade de persistência JSON**: coexistem padrões modernos e legados.
- **Acoplamento alto em módulos grandes** (ex.: `restaurant/routes.py`, `finance/routes.py`, `admin/routes.py`).
- **Dependência forte de arquivos locais**: sensível a permissões/caminhos em ambiente Windows.
- **Integrações externas**: requerem mocks/fakes estáveis para testes automatizados.

---

## 14) Convenções Operacionais para Desenvolvimento

- Preferir `data_service`/serviços donos para persistência de domínio.
- Evitar escrita direta de JSON em blueprints.
- Em mudanças de path, seguir trilha PATH (resolver único + telemetria).
- Em mudanças críticas de persistência, manter:
  - lock,
  - escrita atômica,
  - backup,
  - testes de regressão dedicados.

---

## 15) Referências Internas

- Inicialização app: `app/__init__.py`
- Config/path canônico: `app/services/system_config_manager.py`
- Resolver de paths: `app/services/path_resolver.py`
- Persistência JSON central: `app/services/data_service.py`
- Scheduler: `app/services/scheduler_service.py`
- Auth/Authz:
  - `app/utils/decorators.py`
  - `app/services/permission_service.py`
  - `app/services/authz/*`
- Modelos relacionais: `app/models/models.py`
- Trilha PATH:
  - `docs/architecture/PATH-01.1-design-tecnico-camada-unica-paths.md`
  - `docs/architecture/PATH-01.2-blueprint-implementacao-camada-unica-paths.md`
