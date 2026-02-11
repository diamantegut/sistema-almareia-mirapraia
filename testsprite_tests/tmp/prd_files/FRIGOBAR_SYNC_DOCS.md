# Documentação: Sincronização de Frigobar (Governança ↔ Recepção)

## Visão Geral
Este documento descreve o mecanismo de sincronização em tempo real implementado para garantir que alterações nos produtos do Frigobar (adição, remoção, alteração de preço/nome) sejam refletidas imediatamente na interface de lançamento da Governança e nos registros da Recepção.

## Fluxo de Dados

1.  **Gerenciamento de Produtos (Backoffice/Estoque)**
    *   **Arquivo Fonte:** `menu_items.json`
    *   **Ação:** Quando um administrador adiciona ou edita um produto e define sua categoria como "Frigobar", o arquivo JSON é atualizado.
    *   **Trigger:** Nenhuma ação manual é necessária para propagar a mudança.

2.  **Interface de Governança (`governance_rooms.html`)**
    *   **Carregamento Dinâmico:** Ao clicar no botão "Lançar Frigobar", a interface faz uma chamada AJAX `GET` para a rota `/api/frigobar/items`.
    *   **API Backend:** A rota `/api/frigobar/items` lê o arquivo `menu_items.json` em tempo real a cada requisição.
    *   **Vantagem:** Isso elimina a necessidade de recarregar a página (F5) para ver novos produtos. Se um produto for adicionado enquanto a camareira está na tela de governança, basta ela abrir o modal novamente para ver a lista atualizada.

3.  **Lançamento de Consumo**
    *   **Ação:** A camareira seleciona os itens e confirma.
    *   **Rota:** `POST /governance/launch_frigobar`
    *   **Processamento:**
        *   O backend lê `menu_items.json` novamente para garantir que preços e nomes estejam atualizados no momento exato do lançamento.
        *   Cria um registro em `room_charges.json` com `source: "minibar"` (ou `category: "Frigobar"`).
        *   Registra a ação em `action_logs.json`.

4.  **Recepção (`reception_rooms.html` / `reception_cashier.html`)**
    *   **Visualização:** A recepção carrega `room_charges.json`.
    *   **Identificação:** Itens lançados pela governança aparecem com um badge "Frigobar" (azul), diferenciando-os de pedidos de restaurante.
    *   **Checkout:** No momento do checkout, todos os itens pendentes (incluindo Frigobar) são somados à conta.

## Regras de Negócio

1.  **Categoria Obrigatória:** Apenas produtos com a categoria exata "Frigobar" (case-sensitive, embora o sistema tente normalizar em alguns pontos) são exibidos na lista de lançamento rápido da Governança.
2.  **Preço Dinâmico:** O preço utilizado é o do momento do lançamento. Alterações posteriores no preço do produto não afetam lançamentos já realizados (histórico preservado em `room_charges`).
3.  **Disponibilidade Imediata:** Não há cache de longa duração na lista de produtos da governança. A lista é sempre "fresh" do disco.
4.  **Resiliência a Falhas:**
    *   Se a API `/api/frigobar/items` falhar (ex: erro de rede), o frontend tenta reconectar automaticamente até 3 vezes (backoff exponencial).
    *   Se falhar definitivamente, exibe mensagem de erro amigável com botão de "Tentar Novamente".

## Arquitetura Técnica

*   **Backend:** Flask (Python).
*   **Frontend:** JavaScript (Fetch API) + Bootstrap 5.
*   **Armazenamento:** JSON (Flat files).

### Estrutura da API (`/api/frigobar/items`)

**Request:**
`GET /api/frigobar/items`

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": "101",
      "name": "Água sem Gás",
      "price": 5.00
    },
    {
      "id": "102",
      "name": "Chocolate",
      "price": 8.50
    }
  ]
}
```

**Response (Error):**
```json
{
  "error": "Erro ao carregar itens do servidor."
}
```

## Testes Automatizados
O arquivo `test_frigobar_sync.py` contém testes que validam:
1.  Adição de produto e verificação imediata na API.
2.  Remoção de produto e desaparecimento imediato.
3.  Consistência após múltiplas operações.
