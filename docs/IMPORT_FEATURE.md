# Funcionalidade de Importação de Reservas e Gestão de Conflitos

## Visão Geral
O sistema de importação de reservas foi aprimorado para suportar detecção de duplicatas, atualizações parciais, verificação de conflitos de disponibilidade e gestão de reservas não alocadas.

## Funcionalidades Implementadas

### 1. Detecção de Duplicatas e Atualização
- **Identificação**: O sistema identifica reservas existentes pelo ID único ou pela combinação (Nome do Hóspede + Data Check-in + Data Check-out).
- **Atualização Inteligente**: Se uma reserva já existe, o sistema compara os campos e identifica apenas as alterações.
- **Deduplicação**: O carregamento de reservas (`get_february_reservations`) agora remove duplicatas automaticamente, priorizando a versão mais recente (baseada na data de modificação do arquivo Excel).

### 2. Detecção de Conflitos
- **Verificação de Disponibilidade**: Durante a pré-visualização da importação, o sistema verifica se há disponibilidade na categoria solicitada para o período.
- **Conflitos**: Reservas sem disponibilidade são marcadas como "Conflito" e não são importadas para o calendário principal automaticamente.

### 3. Gestão de Reservas Não Alocadas
- **Armazenamento**: Reservas com conflito são salvas em um arquivo separado (`unallocated_reservations.json`) para análise posterior.
- **Listagem**: Nova API para listar e filtrar estas reservas.

## API Endpoints

### `POST /api/reception/import_preview`
Analisa um arquivo Excel e retorna um relatório de pré-visualização.
- **Retorno**:
  ```json
  {
    "success": true,
    "report": {
      "new_entries": [...],
      "updates": [{"id": "...", "changes": ["Valor: 100 -> 200"], ...}],
      "conflicts": [{"item": {...}, "reason": "Sem disponibilidade"}],
      "unchanged": [...]
    },
    "token": "temp_file_token"
  }
  ```

### `POST /api/reception/import_confirm`
Confirma a importação do arquivo processado anteriormente.
- **Corpo**: `{"token": "temp_file_token"}`
- **Comportamento**:
  - Salva reservas válidas (Novas + Atualizações) em um novo arquivo Excel na pasta de reservas.
  - Salva reservas conflitantes no armazenamento de não alocadas.
  - Remove o arquivo temporário.
- **Retorno**:
  ```json
  {
    "success": true,
    "summary": {
      "imported": 10,
      "conflicts": 2
    }
  }
  ```

### `GET /api/reception/unallocated_reservations`
Lista reservas que não puderam ser alocadas.
- **Parâmetros (Query Params)**:
  - `date`: Filtrar por data (YYYY-MM-DD) - verifica se a data cai dentro do período da reserva.
  - `category`: Filtrar por nome da categoria (parcial).
  - `guest_name`: Filtrar por nome do hóspede (parcial).
- **Retorno**:
  ```json
  {
    "success": true,
    "results": [
      {
        "guest_name": "Fulano",
        "checkin": "01/02/2026",
        "conflict_reason": "Sem disponibilidade",
        ...
      }
    ]
  }
  ```

## Estrutura de Arquivos
- **Reservas Importadas**: Salvas como `imported_{token}.xlsx` em `data/reservations/`.
- **Reservas Não Alocadas**: Salvas em `data/reservations/unallocated_reservations.json`.

## Testes
Os testes unitários cobrem:
- Detecção de duplicatas (por ID e Chave).
- Identificação de mudanças (diff).
- Detecção de conflitos de disponibilidade.
- Processo de confirmação e separação de arquivos.
- Deduplicação na leitura de reservas.
- Executar testes: `python -m unittest tests/test_import_logic.py`
