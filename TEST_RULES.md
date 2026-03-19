# Test Rules — Padrão de Validação

## Ambiente
- Base DEV obrigatória: `http://localhost:5001`.
- Evitar trocar porta sem necessidade operacional real.

## Matriz mínima por fluxo alterado
- Backend: regras de negócio e proteção server-side.
- Autorização: perfis permitidos vs bloqueados.
- UI: validação desktop e mobile.
- Persistência: impacto nos JSON críticos.
- Financeiro/estoque: cobrança, caixa e baixas.
- Logs: presença de trilha operacional.

## JSON críticos
- `table_orders.json`
- `sales_history.json`
- `cashier_sessions.json`
- `room_charges.json`
- `stock_entries.json`
- `waiting_list.json`
- `products.json`
- `menu_items.json`

## Evidências obrigatórias
- Status HTTP das rotas testadas.
- Trechos de JSON antes/depois.
- Logs de ação/sistema relacionados ao fluxo.
- Screenshot quando houver mudança visual relevante.

## Relato de resultado
- Mapa técnico, ajustes, desktop, mobile, autorização, evidências, falhas e conclusão objetiva.
