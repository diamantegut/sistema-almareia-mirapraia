# Documento de Especificação de Produto e Plano de Testes - Sistema Almareia Mirapraia

**Versão:** 1.0.0
**Data:** 08/02/2026
**Status:** Aprovado para Desenvolvimento de Testes

---

## Índice

1. [Histórico de Revisões](#histórico-de-revisões)
2. [Visão Geral do Produto](#visão-geral-do-produto)
3. [Tecnologias e Arquitetura](#tecnologias-e-arquitetura)
4. [Especificação Funcional Detalhada](#especificação-funcional-detalhada)
   - [Autenticação e Controle de Acesso](#autenticação-e-controle-de-acesso)
   - [Serviço de Caixa (Cashier)](#serviço-de-caixa-cashier)
   - [Gestão de Reservas e Recepção](#gestão-de-reservas-e-recepção)
   - [Gestão de Restaurante e Pedidos](#gestão-de-restaurante-e-pedidos)
   - [Serviços Fiscais](#serviços-fiscais)
   - [Integração WhatsApp](#integração-whatsapp)
   - [Serviço de Backup](#serviço-de-backup)
5. [Requisitos do Sistema](#requisitos-do-sistema)
   - [Requisitos Funcionais](#requisitos-funcionais)
   - [Requisitos Não-Funcionais](#requisitos-não-funcionais)
6. [Regras de Negócio](#regras-de-negócio)
7. [Limitações e Dependências](#limitações-e-dependências)
8. [Plano de Testes Integrado](#plano-de-testes-integrado)
   - [Estratégia de Testes](#estratégia-de-testes)
   - [Testes de Backend (API e Integração)](#testes-de-backend-api-e-integração)
   - [Testes de Frontend (Interface e Fluxo)](#testes-de-frontend-interface-e-fluxo)

---

## Histórico de Revisões

| Versão | Data       | Autor            | Descrição das Alterações |
|--------|------------|------------------|--------------------------|
| 1.0.0  | 08/02/2026 | Trae Assistant   | Criação inicial do documento consolidado de especificação e plano de testes. |

---

## Visão Geral do Produto

O **Sistema Almareia Mirapraia** é uma plataforma integrada de gestão hoteleira e de restaurante, projetada para unificar as operações de recepção, restaurante, governança, fiscal e administração. O sistema oferece uma interface web segura e responsiva, com controle de acesso baseado em papéis, gestão financeira robusta e integrações externas.

**Objetivos Principais:**
*   Centralizar o controle operacional e financeiro.
*   Automatizar fluxos de caixa e transferências entre departamentos.
*   Gerenciar reservas, check-in/check-out e consumos de hóspedes.
*   Agilizar o atendimento no restaurante com pedidos digitais e impressão na cozinha.
*   Garantir conformidade fiscal com emissão de NF-e/NFC-e.
*   Assegurar a integridade dos dados através de backups e logs de auditoria.

---

## Tecnologias e Arquitetura

*   **Linguagem:** Python 3.14
*   **Framework Web:** Flask
*   **Banco de Dados:** SQLite (via SQLAlchemy)
*   **Frontend:** HTML5, JavaScript (jQuery), Bootstrap 5
*   **Integrações:** WhatsApp (API), Roku TV, Assinafy (Assinatura Digital)
*   **Infraestrutura:** Windows Server, Ngrok (Túneis), Agendamento de Tarefas (Scheduler)

---

## Especificação Funcional Detalhada

### Autenticação e Controle de Acesso
**Descrição:** Sistema de login seguro com controle de sessão e permissões baseadas em hierarquia de cargos (Admin, Gerente, Recepção, Restaurante, Governança).
*   **Rotas:** `/login`, `/logout`, `/admin`, `/reception`, `/restaurant`.
*   **Fluxo:** Usuário insere credenciais -> Validação -> Redirecionamento baseado no papel.

### Serviço de Caixa (Cashier)
**Descrição:** Gestão completa de turnos de caixa, suportando abertura, fechamento, sangrias, suprimentos e transferências.
*   **Funcionalidades:**
    *   Abertura/Fechamento com conferência de valores.
    *   Registro de transações (Entrada/Saída).
    *   Transferência atômica entre caixas (Recepção <-> Restaurante).
    *   Impressão de comprovantes.
*   **API:** `/api/cashier/open`, `/api/cashier/close`, `/api/cashier/transaction`.

### Gestão de Reservas e Recepção
**Descrição:** Módulo para controle de ocupação hoteleira.
*   **Funcionalidades:**
    *   Mapa de reservas (Drag & Drop).
    *   Check-in/Check-out com validação de pagamentos pendentes.
    *   Gestão de hóspedes (criptografia de dados sensíveis).
    *   Lançamento de consumos (Frigobar/Restaurante) na conta do quarto.
*   **API:** `/api/reservations`, `/api/guests`.

### Gestão de Restaurante e Pedidos
**Descrição:** Controle de mesas, pedidos e cardápio.
*   **Funcionalidades:**
    *   Visualização de mesas (Livre/Ocupada).
    *   Lançamento de itens no pedido.
    *   Transferência de itens (Mesa -> Mesa ou Mesa -> Quarto).
    *   Cardápio digital e gestão de estoque.
*   **Rotas:** `/restaurant/table/<id>`, `/api/orders/add`.

### Serviços Fiscais
**Descrição:** Emissão e gestão de documentos fiscais.
*   **Funcionalidades:**
    *   Emissão de NF-e, NFC-e.
    *   Cancelamento e Carta de Correção.
    *   Monitoramento de status da SEFAZ.
*   **API:** `/api/fiscal/emit`.

### Integração WhatsApp
**Descrição:** Comunicação automatizada e manual com clientes.
*   **Funcionalidades:**
    *   Envio de mensagens transacionais (Confirmação de Reserva).
    *   Chat manual via interface web.
    *   Uso de templates pré-aprovados.
*   **API:** `/api/whatsapp/send`.

### Serviço de Backup
**Descrição:** Proteção de dados automatizada.
*   **Funcionalidades:**
    *   Backups agendados (Diário/Semanal).
    *   Backup manual (Full/Parcial).
    *   Retenção configurável.
*   **API:** `/api/backup/create`.

---

## Requisitos do Sistema

### Requisitos Funcionais
1.  **RF001 - Login:** O sistema deve bloquear acesso a rotas protegidas sem autenticação válida.
2.  **RF002 - Caixa:** O sistema não deve permitir transações em caixas fechados.
3.  **RF003 - Transferência:** Transferências entre mesas devem ser atômicas (tudo ou nada).
4.  **RF004 - Reservas:** O sistema deve impedir colisão de reservas no mesmo quarto/horário.
5.  **RF005 - Auditoria:** Todas as ações sensíveis (ex: cancelamento de item) devem exigir justificativa e ser logadas.

### Requisitos Não-Funcionais
1.  **RNF001 - Desempenho:** O tempo de resposta da API deve ser inferior a 500ms para operações de leitura.
2.  **RNF002 - Segurança:** Senhas devem ser armazenadas com hash seguro (PBKDF2/Argon2). Dados de hóspedes devem ser criptografados.
3.  **RNF003 - Disponibilidade:** O sistema deve operar 24/7 com downtime planejado apenas para manutenção.
4.  **RNF004 - Usabilidade:** A interface deve ser responsiva para uso em tablets e desktops.

---

## Regras de Negócio
1.  **RN01:** Um quarto não pode fazer Check-out se houver saldo devedor em aberto.
2.  **RN02:** Sangrias de caixa não podem exceder o saldo atual disponível.
3.  **RN03:** Apenas usuários 'Admin' ou 'Gerente' podem cancelar itens já enviados para produção na cozinha.
4.  **RN04:** O fechamento de caixa deve conferir com o somatório das transações registradas.

---

## Limitações e Dependências
*   **Limitações:** O sistema depende de conexão com a internet para serviços fiscais e WhatsApp. O funcionamento offline é limitado a operações locais sem validação externa.
*   **Dependências:**
    *   Serviço de API do WhatsApp (Meta/Broker).
    *   SEFAZ (para emissão fiscal).
    *   Ngrok (para acesso externo ao ambiente de desenvolvimento).

---

## Plano de Testes Integrado

### Estratégia de Testes
A validação será realizada em três níveis:
1.  **Testes Unitários/Integração (Backend):** Verificação lógica e de API.
2.  **Testes de Interface (Frontend):** Simulação da jornada do usuário.
3.  **Testes End-to-End (E2E):** Fluxos completos de negócio.

### Testes de Backend (API e Integração)

| ID | Título | Descrição | Dados de Entrada (Exemplo) | Resultado Esperado |
|---|---|---|---|---|
| **TC-BE-01** | Login e Controle de Acesso | Verificar autenticação e permissões de rota. | `user: admin, pass: 1234` | Token/Sessão válida, acesso liberado a `/admin`. |
| **TC-BE-02** | Fluxo de Caixa Completo | Testar abertura, transações e fechamento. | `amount: 100.00, type: deposit` | Saldo atualizado, logs criados, status 'open'/'closed'. |
| **TC-BE-03** | Envio de WhatsApp | Validar envio de mensagem e template. | `phone: 5511999999999, msg: Olá` | Status 200, mensagem entregue/enfileirada. |
| **TC-BE-04** | Emissão Fiscal | Testar emissão de NFC-e. | `order_id: 123, payment: cash` | XML gerado, status 'autorizado' ou erro tratado. |
| **TC-BE-05** | Criação de Reserva | Validar inserção de nova reserva. | `room: 10, checkin: 2026-02-10` | Reserva criada, bloqueio no mapa, ID gerado. |
| **TC-BE-06** | Pedido Restaurante | Adicionar item a uma mesa. | `table: 5, item_id: 50, qty: 2` | Pedido atualizado, total recalculado. |
| **TC-BE-07** | Transferência de Itens | Mover item da Mesa 1 para Quarto 10. | `source: table_1, target: room_10` | Item removido da mesa, adicionado ao quarto. |
| **TC-BE-08** | Backup do Sistema | Executar backup manual. | `type: full` | Arquivo .zip gerado no diretório correto. |

### Testes de Frontend (Interface e Fluxo)

| ID | Título | Prioridade | Passos de Execução | Critério de Aceitação |
|---|---|---|---|---|
| **TC-FE-01** | Acesso ao Painel Admin | Alta | 1. Login como Admin.<br>2. Acessar `/admin`. | Dashboard carrega com todos os módulos visíveis. |
| **TC-FE-02** | Bloqueio de Acesso Não-Admin | Alta | 1. Login como Garçom.<br>2. Tentar acessar `/admin`. | Acesso negado ou redirecionamento. |
| **TC-FE-03** | Abertura de Caixa (UI) | Alta | 1. Acessar PDV.<br>2. Clicar 'Abrir Caixa'.<br>3. Informar valor inicial. | Modal fecha, status muda para 'Aberto', saldo exibe valor inicial. |
| **TC-FE-04** | Fechamento de Caixa (UI) | Alta | 1. Com caixa aberto, clicar 'Fechar'.<br>2. Confirmar valores. | Caixa fecha, resumo é exibido, opção de reabrir aparece. |
| **TC-FE-05** | Check-in de Hóspede | Média | 1. Clicar em reserva.<br>2. Preencher ficha.<br>3. Confirmar Check-in. | Status da reserva muda para 'Hospedado', acesso liberado ao consumo. |
| **TC-FE-06** | Pedido na Mesa | Alta | 1. Abrir mesa.<br>2. Selecionar produto.<br>3. Enviar para cozinha. | Produto aparece na lista 'Enviados', impressora é acionada (simulado). |
| **TC-FE-07** | Pagamento Parcial | Média | 1. Fechar conta.<br>2. Selecionar pagamento parcial.<br>3. Pagar restante em outra forma. | Conta zerada, duas transações registradas no caixa. |
| **TC-FE-08** | Responsividade Mobile | Baixa | 1. Acessar em tela pequena (375px).<br>2. Navegar no menu. | Menu colapsa (hambúrguer), elementos não quebram o layout. |
