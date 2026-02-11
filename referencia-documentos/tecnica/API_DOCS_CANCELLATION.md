# Documentação da API: Cancelamento de Consumo

## Visão Geral
Este documento descreve o endpoint implementado para permitir o cancelamento de consumos de hóspedes por administradores.

## Endpoint

### Cancelar Consumo
`POST /admin/consumption/cancel`

Permite que um administrador cancele um registro de consumo específico.

#### Requisitos de Acesso
- **Autenticação:** Requerida (Sessão ativa).
- **Autorização:** Apenas usuários com a role `admin`.

#### Parâmetros (JSON)
O corpo da requisição deve ser um objeto JSON contendo:

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `charge_id` | String | Sim | O ID único do registro de consumo a ser cancelado. |
| `justification` | String | Sim | Texto justificando o motivo do cancelamento (obrigatório para auditoria). |

#### Exemplo de Requisição
```json
{
  "charge_id": "CHARGE_123456789",
  "justification": "Lançamento duplicado por erro do sistema."
}
```

#### Respostas

**Sucesso (200 OK)**
```json
{
  "success": true,
  "message": "Consumo cancelado com sucesso."
}
```

**Erro: Dados Inválidos (400 Bad Request)**
```json
{
  "success": false,
  "message": "ID do consumo e justificativa são obrigatórios."
}
```
*Ocorre se `charge_id` ou `justification` estiverem ausentes.*

**Erro: Já Cancelado (400 Bad Request)**
```json
{
  "success": false,
  "message": "Este consumo já foi cancelado."
}
```

**Erro: Não Autorizado (403 Forbidden)**
```json
{
  "success": false,
  "message": "Acesso negado. Apenas administradores."
}
```

**Erro: Não Encontrado (404 Not Found)**
```json
{
  "success": false,
  "message": "Consumo não encontrado."
}
```

## Fluxo de Processamento
1.  **Validação:** Verifica permissões de administrador e presença dos campos obrigatórios.
2.  **Busca:** Localiza o consumo em `room_charges.json`.
3.  **Atualização de Status:**
    *   Altera o status para `canceled`.
    *   Registra data/hora (`canceled_at`), usuário (`canceled_by`) e motivo (`cancellation_reason`).
4.  **Auditoria:** Cria um registro imutável em `audit_logs.json` contendo detalhes da ação.
5.  **Notificação:** Tenta notificar o hóspede (via `notify_guest` em `guest_notification_service.py`), registrando a notificação em `data/guest_notifications.json`.

### Integração Frontend
- **Botões de Ação:** Adicionados botões "Cancelar Consumo" (ícone de lixeira) em:
  - `consumption_report.html` (Relatórios de consumo)
  - `reception_rooms.html` (Painel de quartos)
  - `reception_cashier.html` (Caixa/Contas pendentes)
- **Modal de Confirmação:** Modal `cancelConsumptionModal` implementado para confirmar a ação e capturar a justificativa.
- **Feedback:** Spinner de carregamento durante a requisição e alertas de sucesso/erro.
- **Controle de Acesso:** Botões visíveis apenas para usuários com role `admin`.

## Arquivos Relacionados
- **Backend:** `app.py` (Rota), `guest_notification_service.py` (Notificações)
- **Frontend:** `templates/consumption_report.html`, `templates/reception_rooms.html`, `templates/reception_cashier.html` (Botões, Modais e JS)
- **Dados:** `data/room_charges.json`, `data/audit_logs.json`, `data/guest_notifications.json`
