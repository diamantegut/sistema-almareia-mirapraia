# Análise Técnica: Gestão de Quartos (/reception/rooms)

## 1. Visão Geral
A página `/reception/rooms` é o painel central de operações da recepção, permitindo o gerenciamento visual e operacional de todas as unidades habitacionais (quartos). Ela integra funcionalidades de check-in, check-out, governança (limpeza), lançamentos de consumo e pagamentos.

**Rota Principal:** `GET /reception/rooms`
**Rota de Check-in:** `POST /reception/checkin` (Nova rota dedicada)
**Controller:** `app.blueprints.reception.routes`
**Template:** `app/templates/reception_rooms.html`

## 2. Funcionalidades Detalhadas

### 2.1. Check-in de Hóspedes
- **Propósito:** Registrar a entrada de hóspedes, associando-os a um quarto e abrindo uma conta de consumo.
- **Fluxo:**
  1. Usuário clica em "+ Fazer Check-in" (disponível apenas se status for 'inspected').
  2. Modal `checkinModal` é aberto via JavaScript (`openCheckinModal`).
  3. Formulário envia `POST` para `/reception/checkin`.
  4. Frontend realiza validação HTML5 e JS (datas, campos obrigatórios).
  5. Backend valida dados (CPF, datas, disponibilidade, conflitos de ocupação).
  6. Atualiza `room_occupancy.json` e cria mesa no restaurante (`table_orders.json`).
- **Melhorias Recentes:**
  - Lógica de check-in movida para rota dedicada `/reception/checkin` para melhor manutenibilidade.
  - Implementada validação de formulário no lado do cliente (HTML5/JS) para feedback imediato.
  - Adicionada proteção contra sobrescrita de quartos ocupados (bloqueio de check-in em quarto já ocupado por outro hóspede).

### 2.2. Check-out e Fechamento de Conta
- **Propósito:** Finalizar a estadia, processar pagamentos e liberar o quarto.
- **Fluxo:**
  1. Usuário clica em "Check-out" ou "Fechar Conta".
  2. Backend verifica pendências financeiras.
  3. Se houver saldo devedor, redireciona para pagamento (`pay_charge`).
  4. Ao finalizar, atualiza status do quarto para `dirty_checkout` em `cleaning_status.json`.

### 2.3. Governança e Limpeza
- **Propósito:** Controlar o ciclo de limpeza dos quartos.
- **Estados:**
  - `dirty`: Sujo (pós-uso ou manutenção).
  - `cleaning`: Em limpeza.
  - `clean`: Limpo (aguardando inspeção).
  - `inspected`: Inspecionado (liberado para check-in).
- **Integração:** O botão de check-in é bloqueado visualmente e funcionalmente se o quarto não estiver `inspected`.

## 3. Componentes e Tecnologia

### 3.1. Frontend
- **Framework:** Bootstrap 5 (Modais, Grid, Botões).
- **Bibliotecas:**
  - `TomSelect`: Para dropdowns pesquisáveis (seleção de produtos/serviços).
  - `jQuery`: Dependência legada para alguns plugins.
  - `Fetch API`: Para operações assíncronas (ex: cálculo de parciais).
- **Modais Principais:**
  - `#checkinModal`: Formulário de entrada com validação `needs-validation` (Bootstrap) e JS customizado.
  - `#checkoutModal`: Confirmação de saída.
  - `#paymentModal`: Processamento de pagamentos.

### 3.2. Backend (Flask)
- **Validação:** 
  - Backend: Verificação robusta de campos no `routes.py` (CPF, Email, Datas, Ocupação).
  - Frontend: Atributos HTML5 (`required`, `min`) e scripts de validação.
- **Persistência:** Arquivos JSON (`data_service.py`).
- **Controle de Concorrência:** Locks de arquivo implementados em `data_service.py` (embora não explicitamente visíveis no controller, são usados nas funções de save/load).

## 4. Testes Automatizados

Foi desenvolvida uma suíte de testes abrangente cobrindo fluxos de ponta a ponta (E2E).

**Arquivo Principal:** `tests/test_reception_e2e_full.py`

### Cenários Cobertos:
1.  **Check-in Válido (`test_01_checkin_valid`)**:
    *   Verifica processamento correto de check-in com dados completos.
    *   Valida persistência em `room_occupancy.json`.
2.  **Check-in Inválido (`test_02_checkin_invalid`)**:
    *   Testa envio de dados incompletos (validação de campos).
    *   Testa tentativa de check-in em quarto ocupado (bloqueio de sobrescrita).
3.  **Fluxo de Limpeza (`test_03_cleaning_workflow`)**:
    *   Verifica transições de estado de limpeza (sujo -> inspecionado -> rejeitado).
4.  **Transferência de Hóspede (`test_04_guest_transfer`)**:
    *   Valida lógica de transferência entre quartos.
5.  **Edição de Hóspede (`test_05_edit_guest_name`)**:
    *   Verifica permissão para editar nome do hóspede no mesmo quarto.

### Execução dos Testes
```bash
python -m unittest tests/test_reception_e2e_full.py
```

## 5. Status Atual e Próximos Passos

1.  **Refatoração Concluída**: A rota de check-in foi separada com sucesso em `/reception/checkin`.
2.  **Validação Implementada**: Frontend agora possui validação visual antes do envio.
3.  **Testes Estabilizados**: A suíte E2E foi corrigida para usar isolamento de dados (mocking de paths) e passa em todos os cenários.

**Recomendação Futura:**
- Continuar a refatoração para separar outras operações complexas (Check-out, Lançamentos) em rotas dedicadas ou serviços.
- Implementar testes unitários isolados para os serviços de validação (`app.utils.validation`).
