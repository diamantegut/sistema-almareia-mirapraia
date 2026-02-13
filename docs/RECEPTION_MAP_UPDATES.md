# Atualizações no Mapa de Reservas (Recepção)

Este documento detalha as alterações técnicas realizadas no módulo de Mapa de Reservas (`/reception/reservations`) para corrigir falhas de usabilidade e implementar novas funcionalidades.

## 1. Novas Funcionalidades

### 1.1. Ficha de Hóspede (Modal)
*   **Ação:** Clique em qualquer barra de reserva.
*   **Comportamento:** Abre um modal carregado dinamicamente com abas para:
    *   **Reserva:** Detalhes financeiros e datas.
    *   **Dados Pessoais:** Edição de contato, documentos e upload de foto.
    *   **Fiscal:** Dados para emissão de nota (CPF/CNPJ, Endereço).
    *   **Operacional:** Restrições alimentares e observações.

### 1.2. Drag & Drop Horizontal (Mudança de Datas)
*   **Ação:** Arrastar uma reserva horizontalmente para outros dias.
*   **Comportamento:**
    *   O sistema calcula automaticamente as novas datas de Check-in e Check-out baseadas na posição solta.
    *   **Snap:** As reservas alinham-se automaticamente ao horário de Check-in (PM) para evitar posições quebradas.
    *   **Confirmação:** Um modal exibe as novas datas e o quarto de destino antes de salvar.

### 1.3. Extensão de Estadia (Resize)
*   **Ação:** Arrastar as bordas (início ou fim) de uma reserva.
*   **Comportamento:**
    *   O sistema calcula a nova duração.
    *   **Cálculo Automático:** Um endpoint de backend calcula a diferença de valor baseada na tarifa média da reserva original.
    *   **Modal:** Exibe o valor adicional sugerido, permitindo ajuste manual se necessário.

### 1.4. Movimentação entre Quartos
*   **Ação:** Arrastar verticalmente para outro quarto.
*   **Validação:** O sistema verifica conflitos de disponibilidade no novo quarto/datas antes de permitir o movimento.

## 2. Detalhes Técnicos

### 2.1. Backend (`ReservationService`)
*   **Novo Método:** `calculate_reservation_update(reservation_id, new_room, new_checkin, new_checkout)`
    *   Calcula novos valores pro-rata.
    *   Valida consistência de datas.
*   **Validação de Conflito:** `check_collision` agora é chamado antes de qualquer cálculo de atualização para garantir integridade.
*   **Capacidade:** Adicionada constante `ROOM_CAPACITIES` para referência futura de validação de pax.

### 2.2. API (`routes.py`)
*   `POST /api/reception/calculate_reservation_update`: Endpoint para simulação de custos e validação.
*   `POST /api/reception/move_reservation`: Atualizado para aceitar datas (`checkin`, `checkout`) além do quarto.
*   `POST /api/reception/resize_reservation`: Atualizado para processar ajustes de preço.

### 2.3. Frontend (`reception_reservations.html`)
*   Refatoração completa da lógica de Drag & Drop usando API nativa HTML5.
*   Implementação de lógica de "Snap" (`snapToDayStart`) para garantir alinhamento à grade de 12h (AM/PM).
*   Integração com API de cálculo para feedback imediato de preços.

## 3. Como Testar

1.  **Mover Datas:** Arraste uma reserva para a direita/esquerda. Verifique se o modal mostra as novas datas corretas.
2.  **Estender Estadia:** Aumente o tamanho da reserva pela borda direita. Verifique se o modal sugere um valor adicional positivo.
3.  **Reduzir Estadia:** Diminua o tamanho. Verifique se o modal sugere valor negativo (crédito).
4.  **Conflitos:** Tente mover uma reserva para cima de outra (ou de um bloqueio ocupado). O sistema deve impedir e alertar.

## 4. Próximos Passos (Sugestões)
*   Implementar tabela de tarifas por temporada para cálculo mais preciso de extensões.
*   Adicionar validação estrita de capacidade de hóspedes (Pax) ao trocar de categoria de quarto.
