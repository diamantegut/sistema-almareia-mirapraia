# Documentação da Funcionalidade de Busca de Reservas

## Visão Geral
Esta funcionalidade permite que a recepção localize rapidamente reservas através de uma barra de busca na página `/reception/reservations`. A busca é realizada em tempo real (com debounce) e suporta pesquisa por nome do hóspede ou CPF/Documento.

## Funcionalidades
- **Busca por Nome**: Pesquisa parcial (mínimo 3 caracteres), case-insensitive e ignora acentuação (ex: "joão" encontra "João").
- **Busca por CPF**: Aceita CPF formatado (ex: 111.222.333-44) ou apenas números.
- **Busca em Detalhes**: Pesquisa tanto no nome principal da reserva quanto nos dados detalhados do hóspede (ficha de registro).
- **Ordenação**: Resultados são ordenados pela data de check-in mais recente.
- **Interface**:
  - Loading indicator durante a requisição.
  - Botão "X" para limpar a busca.
  - Mensagem "Nenhuma reserva encontrada" quando não há correspondência.
  - Integração com o modal de detalhes da reserva existente.

## Implementação Técnica

### Backend
- **Service**: `ReservationService.search_reservations(query)`
  - Realiza normalização de texto (NFD) para remover acentos e converter para minúsculas.
  - Remove caracteres não numéricos para busca de CPF.
  - Realiza busca em duas etapas:
    1.  Nos arquivos de detalhes do hóspede (`guest_details.json`) por Nome, CPF, CNPJ ou Documento.
    2.  Na lista principal de reservas (`minhas_reservas.xlsx`, `manual_reservations.json`) por Nome.
  - Retorna lista de objetos de reserva, ordenados por data de check-in (decrescente).

- **Rota**: `/api/reception/reservations/search` (GET)
  - Parâmetro: `q` (query string).
  - Validação: Exige mínimo de 3 caracteres.
  - Retorno: JSON com lista de reservas encontradas.

### Frontend
- **Arquivo**: `app/templates/reception_reservations.html`
- **Lógica**:
  - Event listener `input` no campo de busca com **debounce de 300ms** para evitar sobrecarga no servidor.
  - `fetch` para a API de busca.
  - Renderização dinâmica dos resultados em uma lista (`list-group`) abaixo do campo de busca.
  - Ao clicar em um resultado, chama a função global `openReservationModal(id)` para exibir os detalhes.

## Testes
Foram adicionados testes unitários no arquivo `tests/test_reservation_logic.py` cobrindo os seguintes cenários:
1.  Busca parcial por nome.
2.  Busca case-insensitive e com acentos.
3.  Busca por CPF (limpo e formatado).
4.  Busca por nome na lista de reservas vs. detalhes.
5.  Busca sem resultados.
6.  Ordenação por data.

### Executando os Testes
Para rodar os testes da funcionalidade:

```bash
python tests/test_reservation_logic.py
```

## Exemplos de Uso

| Entrada | O que busca | Exemplo de Match |
| :--- | :--- | :--- |
| `silva` | Nome contendo "silva" (case-insensitive) | "João da **Silva**" |
| `joão` | Nome contendo "joao" (ignora acento) | "**João** Pedro" |
| `12345678900` | CPF exato (apenas números) | CPF: 123.456.789-00 |
| `123.456` | CPF parcial | CPF: **123.456**.789-00 |

## Arquivos Modificados
- `app/templates/reception_reservations.html`: Adição do HTML da barra de busca e JavaScript.
- `app/services/reservation_service.py`: Adição do método `search_reservations`.
- `app/blueprints/reception/routes.py`: Adição da rota `/api/reception/reservations/search`.
- `tests/test_reservation_logic.py`: Adição de testes unitários.
