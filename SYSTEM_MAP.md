# SYSTEM_MAP.md — Mapa Técnico do Sistema

## 1. Visão geral do sistema
- Ambiente DEV padrão: `http://localhost:5001`.
- Stack principal: Flask (blueprints), templates Jinja, serviços Python e persistência operacional em JSON.
- Domínio: operação integrada hotel + restaurante (recepção, restaurante, caixa, cozinha/KDS, fila de espera, estoque, cardápio).

## 2. Módulos do sistema
| Módulo | Responsabilidade principal |
|---|---|
| Restaurant | Mesas, pedidos, transferências, fechamento, caixa restaurante |
| Reception | Quartos, reservas, consumo em quarto, caixa recepção, devolução para restaurante |
| Cashier | Sessões de caixa, transações, sangria, suprimento, transferências entre caixas |
| Kitchen (KDS) | Leitura de pedidos pendentes, atualização de status de preparo, recebimento |
| Waiting List | Fila pública (`/fila`) e gestão administrativa na recepção |
| Stock / Inventory | Produtos, entradas, movimentações e baixa por consumo |
| Menu Management | Cadastro de itens, preço, tipo de item, acompanhamentos, ficha técnica, perguntas |
| Serviços auxiliares | Fiscal, logging, scheduler, segurança, integrações e auditoria |

## 3. Rotas principais
### Restaurant
- `GET /restaurant/tables`
- `GET|POST /restaurant/table/<table_id>`
- `GET|POST /restaurant/cashier`
- `POST /restaurant/transfer_item`
- `GET|POST /fila`
- `GET /fila/cancel/<id>`

### Reception
- `GET|POST /reception/rooms`
- `GET /reception/reservations`
- `GET /reception/waiting-list`
- `POST /api/reception/return_to_restaurant`
- `GET|POST /reception/cashier`
- `GET|POST /reception/reservations-cashier`
- `POST /api/queue/send-notification`

### Kitchen (KDS)
- `GET /kitchen/kds`
- `GET /kitchen/kds/data`
- `POST /kitchen/kds/update_status`
- `POST /kitchen/kds/mark_received`

### Menu / Stock / Fila
- `GET|POST /menu/management`
- `GET|POST /stock/products`
- `GET|POST /stock/entry`
- `POST /api/queue/log-notification`

## 4. Serviços backend
| Serviço | Papel |
|---|---|
| `data_service.py` | IO JSON central, leitura/escrita e helpers de persistência |
| `cashier_service.py` | Abertura/fechamento de caixa, transações, transferências e auditoria |
| `transfer_service.py` | Transferência mesa→quarto e devolução quarto→restaurante |
| `fiscal_pool_service.py` | Coordenação de emissão/filas fiscais |
| `printing_service.py` | Impressão de pedidos, contas e integrações de cozinha/fiscal |
| `waiting_list_service.py` | Fila, status, métricas, notificações e assentos |
| `logger_service.py` | Log de ação e rastreabilidade operacional |
| `scheduler_service.py` | Jobs recorrentes (fiscal, limpeza, segurança e manutenção) |

## 5. Persistência de dados
- Arquivos JSON críticos:
  - `table_orders.json`
  - `sales_history.json`
  - `cashier_sessions.json`
  - `room_charges.json`
  - `stock_entries.json`
  - `waiting_list.json`
  - `products.json`
  - `menu_items.json`
  - `cleaning_status.json`
  - `cleaning_logs.json`

## 6. Fluxos críticos
### 6.1 Restaurante
- Abrir mesa → lançar pedido (`add_batch_items`) → enviar/imprimir cozinha → transferir mesa/item quando necessário → puxar conta → fechar conta.
- Suporta pagamento parcial e múltiplas formas de pagamento na rotina de fechamento.

### 6.2 Integração restaurante → recepção
- Ação `transfer_to_room` (na mesa) cria cobrança em `room_charges.json`.
- Operação registra histórico em `sales_history.json`.
- Retorno para restaurante via `POST /api/reception/return_to_restaurant`.

### 6.3 Cozinha (KDS)
- KDS lê pedidos de `table_orders.json`.
- Atualiza status (`pending`, `preparing`, `done`, `archived`) e persiste de volta no mesmo arquivo.

### 6.4 Caixa
- Abertura de sessão, pagamentos, sangria, suprimento e transferência entre caixas.
- Persistência em `cashier_sessions.json` com trilha de logs e conciliação.

### 6.5 Fila de espera
- Entrada pública em `/fila`.
- Operação administrativa em `/reception/waiting-list`.
- Notificação via `POST /api/queue/send-notification` (WhatsApp quando configurado).

### 6.6 Estoque
- Baixa automática por ficha técnica/componentes no lançamento/fechamento conforme regras de item.
- Movimentos registrados em `stock_entries.json`.

## 7. Integração entre módulos
- Restaurant ↔ Kitchen: pedido e status de produção.
- Restaurant ↔ Stock: consumo e baixa de insumos/produtos.
- Restaurant ↔ Cashier: recebimento, fechamento e auditoria financeira.
- Restaurant ↔ Reception: transferência para quarto e devolução para mesa.
- Reception ↔ Waiting List: chamada, assento e SLA de atendimento.
- Menu Management ↔ Restaurant/Stock: preço, tipo de item, acompanhamentos e impacto operacional.
