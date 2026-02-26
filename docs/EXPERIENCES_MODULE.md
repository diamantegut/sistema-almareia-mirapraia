# Módulo de Gestão de Experiências

Este documento detalha a implementação do módulo de gestão de experiências para hóspedes no sistema Almareia Mirapraia.

## Visão Geral

O módulo permite que a recepção cadastre, gerencie e lance experiências (passeios, jantares, serviços) para os hóspedes. Ele inclui funcionalidades para controle de comissões, margens de lucro e relatórios financeiros separados das demais receitas do hotel.

## Estrutura de Dados

Os dados são armazenados em arquivos JSON na pasta `data/`:

1.  **`guest_experiences.json`**: Catálogo de experiências disponíveis.
    *   Campos: `id`, `name`, `description`, `type`, `price`, `active`, `images`, `video`, etc.
    *   **Campos Internos** (não visíveis ao hóspede):
        *   `supplier_name`: Nome do fornecedor.
        *   `supplier_phone`: Contato.
        *   `supplier_price`: Custo pago ao fornecedor.
        *   `guest_price`: Valor cobrado do hóspede.
        *   `expected_commission`: Diferença entre Preço Hóspede e Preço Fornecedor (R$). Calculado automaticamente.
        *   `sales_commission`: Comissão destinada à venda (R$).
        *   `hotel_commission`: Comissão destinada ao hotel (R$).
        
    *   **Regras de Validação Financeira**:
        *   `expected_commission` = `guest_price` - `supplier_price`.
        *   `sales_commission` + `hotel_commission` <= `expected_commission`.
        *   Valores não podem ser negativos.

2.  **`launched_experiences.json`**: Registro histórico de experiências vendidas/lançadas.
    *   Campos: `id`, `launched_at`, `scheduled_date`, `experience_id`, `guest_name`, `room_number`, `collaborator_name`, `notes`.
    *   **Snapshot Financeiro**: Os valores financeiros são "congelados" no momento do lançamento para preservar o histórico em caso de alteração de preços.

## Camada de Serviço (`ExperienceService`)

Localizada em `app/services/experience_service.py`.

### Métodos Principais

*   `get_all_experiences(only_active=False)`: Retorna lista de experiências.
*   `create_experience(data)`: Cria nova experiência (com campos internos).
*   `update_experience(id, data)`: Atualiza experiência existente.
*   `toggle_active(id)`: Ativa/Desativa exibição para hóspede.
*   `launch_experience(data)`: Registra venda para hóspede (cria snapshot financeiro).
*   `get_launched_experiences(filters)`: Retorna lançamentos filtrados para relatório.
*   `get_unique_collaborators()`: Retorna lista de nomes de colaboradores que já realizaram vendas (para autocomplete).

## Rotas (`reception_bp`)

### Gestão
*   `POST /reception/experiences/create`: Cadastra experiência.
*   `POST /reception/experiences/<id>/update`: Atualiza experiência.
*   `POST /reception/experiences/<id>/toggle`: Alterna status ativo/inativo.
*   `POST /reception/experiences/<id>/delete`: Remove experiência.

### Lançamento e Relatórios
*   `POST /reception/experiences/launch`: Lança uma experiência para um hóspede.
    *   Parâmetros: `experience_id`, `room_number`, `guest_name`, `collaborator_name`, `notes`.
*   `GET /reception/experiences/report`: Retorna dados JSON para o relatório de comissões.
    *   Filtros (Query Params): `start_date`, `end_date`, `collaborator`, `supplier`.

### Menu Digital
*   `GET /guest/experiences`: Exibição pública das experiências ativas.

## Interface do Usuário (UI)

### Painel de Gestão (`reception_experiences.html`)
*   **Listagem**: Cards com fotos, status e ações.
*   **Modal de Criação/Edição**:
    *   Aba **Geral**: Informações públicas (nome, descrição, fotos).
    *   Aba **Interno**: Informações confidenciais (fornecedor, custos, comissões).
*   **Relatório de Comissões**:
    *   Modal exclusivo com tabela filtrável.
    *   Cálculo automático de totais (Fornecedor, Hóspede, Comissão Hotel).
    *   Modo de impressão otimizado.

### Lançamento em Quartos (`reception_rooms.html`)
*   **Botão "Lançar Experiência"**: Disponível nos cards de quartos ocupados.
*   **Modal de Lançamento**:
    *   Seleção de experiência.
    *   Indicação do colaborador responsável pela venda (para comissão).
    *   Observações.

## Testes Automatizados

Os testes estão localizados em `tests/test_experiences.py` e cobrem:
1.  Criação de experiência com campos internos.
2.  Toggle de ativação/desativação.
3.  Fluxo de lançamento de experiência (verificação de snapshot financeiro).
4.  Filtragem de relatórios por data e colaborador.
5.  Validação de lógica de comissões (distribuição e limites).

Para executar os testes:
```bash
python -m tests.test_experiences
```
