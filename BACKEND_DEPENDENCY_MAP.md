# BACKEND_DEPENDENCY_MAP.md — Dependências Internas do Backend

## 1. Visão geral das dependências
- Backend em Flask com blueprints por domínio.
- Rotas concentram orquestração e delegam regras para serviços (`app/services`).
- Persistência principal em JSON (com suporte adicional a logs em SQLite via `LoggerService`).
- Dependências críticas de negócio:
  - Restaurante: `data_service` + `cashier_service` + `transfer_service` + `printing_service`.
  - Recepção: `data_service` + `transfer_service` + `cashier_service` + `waiting_list_service`.
  - Cozinha/KDS: `data_service` + `logger_service`.
  - Cardápio/Menu: `data_service` + `menu_security_service`.
  - Admin/Fiscal: `backup_service` + `fiscal_pool_service` + `logger_service`.

## 2. Mapa de rotas → serviços → JSON
### Restaurant
| Rota | Função | Serviços usados | JSON afetados |
|---|---|---|---|
| `GET /restaurant/tables` | Lista mesas/status | `data_service`, `cashier_service` | `table_orders.json`, `restaurant_table_settings.json`, `cashier_sessions.json` |
| `GET|POST /restaurant/table/<table_id>` | Operação completa da mesa (abrir, lançar, transferir, fechar, enviar quarto) | `data_service`, `cashier_service`, `transfer_service`, `printing_service`, `fiscal_pool_service`, `logger_service` | `table_orders.json`, `sales_history.json`, `room_charges.json`, `stock_entries.json`, `cashier_sessions.json` |
| `GET|POST /restaurant/cashier` | Abertura/fechamento e transações de caixa restaurante | `cashier_service`, `printing_service`, `logger_service` | `cashier_sessions.json` |
| `POST /restaurant/transfer_item` | Transferência de item entre mesas | `data_service`, `logger_service` | `table_orders.json` |
| `GET|POST /fila` | Entrada pública da fila | `waiting_list_service` | `waiting_list.json` |

### Reception
| Rota | Função | Serviços usados | JSON afetados |
|---|---|---|---|
| `GET|POST /reception/rooms` | Gestão operacional de quartos/consumos | `data_service`, `logger_service` | `room_occupancy.json`, `room_charges.json`, `table_orders.json`, `cleaning_status.json` |
| `GET /reception/reservations` | Painel de reservas | `ReservationService`, `ReceptionUnifiedRepository`, `data_service` | `manual_reservations.json`, `room_occupancy.json`, `room_charges.json` |
| `GET /reception/waiting-list` | Gestão administrativa da fila | `waiting_list_service`, `logger_service` | `waiting_list.json`, `table_orders.json` |
| `POST /api/reception/return_to_restaurant` | Devolve cobrança de quarto para mesa | `transfer_service`, `logger_service` | `room_charges.json`, `table_orders.json` |
| `GET|POST /reception/cashier` | Caixa da recepção | `cashier_service`, `printing_service`, `logger_service` | `cashier_sessions.json`, `room_charges.json` |

### Kitchen (KDS)
| Rota | Função | Serviços usados | JSON afetados |
|---|---|---|---|
| `GET /kitchen/kds` | Tela KDS | `data_service` | leitura indireta de `table_orders.json` |
| `GET /kitchen/kds/data` | Payload de pedidos para KDS | `data_service` | `table_orders.json`, `menu_items.json` |
| `POST /kitchen/kds/update_status` | Atualiza status de preparo | `data_service`, `logger_service` | `table_orders.json` |
| `POST /kitchen/kds/mark_received` | Marca itens recebidos/arquivados | `data_service`, `logger_service` | `table_orders.json` |

### Menu / Waiting List / Admin
| Rota | Função | Serviços usados | JSON afetados |
|---|---|---|---|
| `GET|POST /menu/management` | Cadastro de produtos do menu | `data_service`, `logger_service`, `menu_security_service` | `menu_items.json`, `flavor_groups.json`, `products.json` |
| `POST /api/queue/send-notification` | Notificação de fila (WhatsApp) | `waiting_list_service` | `waiting_list.json` |
| `POST /admin/fiscal/pool/action` | Ações no pool fiscal | `FiscalPoolService`, `logger_service` | `fiscal_pool.json` |
| `POST /admin/api/backups/trigger` | Dispara backup central | `backup_service`, `logger_service` | metadados de backup + cópias de JSON críticos |

## 3. Mapa de serviços → JSON
| Serviço | JSON manipulados |
|---|---|
| `data_service.py` | `table_orders.json`, `sales_history.json`, `cashier_sessions.json`, `room_charges.json`, `stock_entries.json`, `products.json`, `menu_items.json`, `cleaning_status.json` e outros |
| `cashier_service.py` | `cashier_sessions.json` |
| `transfer_service.py` | `table_orders.json`, `room_charges.json`, `sales_history.json` |
| `waiting_list_service.py` | `waiting_list.json` e vínculo operacional com `table_orders.json` ao sentar cliente |
| `printing_service.py` | Não é persistência primária; consome dados de pedidos/contas para impressão |
| `fiscal_pool_service.py` | `fiscal_pool.json` |
| `scheduler_service.py` | `system_status.json`, `fiscal_settings.json`, `cleaning_status.json` (via jobs) |
| `logger_service.py` | Persistência principal em SQLite (`department_logs.db`), não em JSON |

## 4. Mapa de serviços → serviços
| Serviço origem | Chama serviços |
|---|---|
| `cashier_service.py` | `logger_service`, `ledger_service`, `financial_audit_service` |
| `transfer_service.py` | `data_service`, `cashier_service`, `logger_service` |
| `waiting_list_service.py` | `data_service` (vínculo de mesas), modelos DB de fila |
| `scheduler_service.py` | `fiscal_service`, `stock_security_service`, `menu_security_service`, `financial_risk_service`, `data_service` |
| `fiscal_pool_service.py` | `data_service` (menu), `logger_service` |
| `restaurant routes` | `data_service`, `cashier_service`, `transfer_service`, `printing_service`, `fiscal_pool_service`, `logger_service` |
| `reception routes` | `data_service`, `cashier_service`, `transfer_service`, `waiting_list_service`, `printing_service`, `logger_service` |

## 5. Fluxos entre módulos
### Restaurante → Cozinha
- Lançamento de pedido na mesa grava em `table_orders.json`.
- KDS consome via `GET /kitchen/kds/data`.
- Cozinha atualiza status via `POST /kitchen/kds/update_status` e persiste em `table_orders.json`.

### Restaurante → Caixa
- Fechamento/recebimento chama `CashierService`.
- Movimentos persistem em `cashier_sessions.json`.

### Restaurante → Recepção
- `transfer_to_room` usa `transfer_service`.
- Cria cobrança em `room_charges.json` e registra histórico em `sales_history.json`.
- Retorno usa `POST /api/reception/return_to_restaurant` e restaura em `table_orders.json`.

### Fila → Restaurante
- Entrada pública em `/fila` grava em `waiting_list.json`.
- Recepção chama/senta cliente (`/reception/waiting-list`).
- Ao sentar passante, `waiting_list_service` pode vincular/abrir mesa em `table_orders.json`.

### Estoque ↔ Restaurante/Kitchen
- Pedidos/fechamentos acionam baixa de estoque por item/ficha técnica.
- Registros persistem em `stock_entries.json` e são consumidos em painéis de estoque/cozinha.
