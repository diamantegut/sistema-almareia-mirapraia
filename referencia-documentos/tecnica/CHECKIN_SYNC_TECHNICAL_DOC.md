
# Documentação Técnica: Sincronização de Check-in (Reservas <-> Recepção)

## Visão Geral
Este documento descreve a implementação da sincronização bidirecional entre os módulos de Reservas (`/reception/reservations`) e Recepção de Quartos (`/reception/rooms`). O objetivo é garantir que o ciclo de vida do hóspede seja consistente em todo o sistema, eliminando a necessidade de atualização manual de status em múltiplos lugares.

## Arquitetura da Solução

### 1. Modelo de Dados Unificado (Virtualmente)
Embora os dados residam em fontes distintas (Excel para reservas importadas, JSON para ocupação atual), criamos uma camada de abstração no `ReservationService` que unifica a visão.

*   **Fonte da Verdade (Reservas):** Arquivos Excel (`minhas_reservas.xlsx`) + `manual_reservations.json`.
*   **Camada de Overrides:** `reservation_status_overrides.json` permite alterar o status de qualquer reserva (mesmo as do Excel) sem modificar o arquivo original.
*   **Vínculo de Ocupação:** O arquivo `room_occupancy.json` agora armazena o campo `reservation_id`, criando um link forte entre o quarto ocupado e a reserva original.

### 2. Fluxos de Dados

#### A. Fluxo de Pré-Check-in (Visualização)
1.  O usuário acessa `/reception/rooms`.
2.  O sistema carrega `upcoming_checkins` via `ReservationService`.
3.  Esta lista agora inclui o `reservation_id` de cada reserva alocada para hoje/amanhã.
4.  O frontend (`reception_rooms.html`) recebe esses dados em `upcomingCheckinsData`.

#### B. Fluxo de Check-in (Execução)
1.  **Gatilho:** O usuário clica em "Fazer Check-in" (no mapa de reservas ou no painel de quartos).
2.  **Interface:** O modal de Check-in abre.
    *   Se aberto via mapa de reservas: Redireciona para `/reception/rooms` com parâmetros URL (`reservation_id`).
    *   Se aberto via painel de quartos: O JS detecta o quarto e busca os dados em `upcomingCheckinsData`.
3.  **Preenchimento:** O formulário é preenchido automaticamente (Nome, etc) e o `reservation_id` é inserido em um campo oculto.
4.  **Submissão:** O formulário é enviado para `/reception/rooms` (POST `action=checkin`).
5.  **Processamento (Backend):**
    *   O sistema valida o check-in normalmente.
    *   **Sincronização:** Se `reservation_id` estiver presente, chama `ReservationService.update_reservation_status(id, 'Checked-in')`.
    *   **Persistência:** Salva os dados de ocupação no `room_occupancy.json` incluindo o `reservation_id`.

#### C. Fluxo de Check-out (Atualização)
*   Atualmente, o check-out libera o quarto e move para limpeza.
*   Futuramente, este fluxo pode atualizar o status da reserva para "Checked-out" (ainda não implementado automaticamente para manter flexibilidade operacional, mas o link existe).

## Componentes Modificados

### Backend (`app/services/reservation_service.py`)
*   `get_reservation_status_overrides()`: Lê o arquivo de overrides.
*   `update_reservation_status()`: Grava um novo status para uma reserva.
*   `get_february_reservations()`: Aplica os overrides na lista mestre de reservas.
*   `get_upcoming_checkins()`: Inclui o ID da reserva no retorno.

### Frontend (`app/templates/reception_reservations.html`)
*   Adicionado botão "Fazer Check-in" no modal de detalhes da reserva.
*   Lógica JS para exibir o botão apenas se a reserva for para hoje/amanhã e ainda não estiver "Checked-in".

### Frontend (`app/templates/reception_rooms.html`)
*   Script para detecção automática de `reservation_id` baseado no quarto selecionado.
*   Lógica de auto-abertura do modal via parâmetros de URL (`open_checkin=true`).

## Testes e Validação
*   **Testes Automatizados:** `tests/test_reservation_sync_logic.py` valida a lógica de persistência de status e estrutura de dados.
*   **Testes Manuais:** Validado fluxo de ponta a ponta (clique no mapa -> redirecionamento -> check-in -> verificação de status).

## Plano de Rollback
Em caso de falha crítica:
1.  Restaurar `app/services/reservation_service.py` para a versão anterior (sem overrides).
2.  Remover `reservation_status_overrides.json`.
3.  O sistema voltará a funcionar baseando-se apenas nos arquivos Excel/JSON originais, ignorando os status atualizados, mas sem perda de dados críticos de ocupação.
