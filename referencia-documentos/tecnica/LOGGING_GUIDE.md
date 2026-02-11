# Guia de Implementação de Logs Departamentais

Este documento descreve como utilizar o sistema de logs centralizado (`LoggerService`) para registrar ações críticas de cada departamento.

## 1. Visão Geral

O sistema de logs permite rastrear ações de usuários por departamento de forma estruturada e persistente. Os logs são armazenados no banco de dados SQLite (`instance/app.db`) na tabela `logs_acoes_departamento`.

## 2. Como Registrar uma Ação

Para adicionar um novo ponto de log em qualquer rota ou função do `app.py`:

1.  **Importe o LoggerService** (já está importado no `app.py`):
    ```python
    from logger_service import LoggerService
    ```

2.  **Chame o método `log_acao`**:
    ```python
    LoggerService.log_acao(
        acao="Descrição da ação",          # Obrigatório: O que aconteceu
        entidade="Entidade Afetada",       # Obrigatório: Módulo (ex: Estoque, Usuários, Mesas)
        detalhes={ ... },                  # Opcional: Dicionário com metadados (JSON)
        nivel_severidade="INFO",           # Opcional: INFO (padrão), ALERTA, CRITICO
        departamento_id=None,              # Opcional: Se None, tenta pegar da sessão
        colaborador_id=None                # Opcional: Se None, tenta pegar da sessão
    )
    ```

### Exemplo Prático

Ao criar um novo pedido:

```python
LoggerService.log_acao(
    acao=f"Pedido #{order_id} criado",
    entidade="Pedidos",
    detalhes={
        'mesa': table_id,
        'itens': len(items),
        'valor_total': total_value
    },
    nivel_severidade="INFO"
)
```

## 3. Campos Automáticos

Se você estiver dentro de uma rota com usuário logado (sessão ativa), o `LoggerService` preencherá automaticamente:
*   `departamento_id`: Do campo `session['department']`.
*   `colaborador_id`: Do campo `session['user']`.
*   `timestamp`: Data e hora atual (UTC/Servidor).

## 4. Consulta de Logs

### Interface Web
Acesse a rota `/department/log` para visualizar a interface de logs.
*   Se for **Admin**, pode ver logs de qualquer departamento (use `?department=NomeDept`).
*   Se for **Gerente/Usuário**, vê apenas o log do seu departamento.

### API
Endpoint para integração ou consulta via JSON:
`GET /api/logs/department/<department_id>`

Parâmetros (Query String):
*   `page`: Número da página (default: 1)
*   `per_page`: Itens por página (default: 20)
*   `start_date`: Filtro de data inicial (YYYY-MM-DD)
*   `end_date`: Filtro de data final (YYYY-MM-DD)
*   `action_type`: Filtro por texto na ação
*   `user`: Filtro por ID do colaborador

## 5. Manutenção

*   **Arquivo de Banco de Dados**: `instance/app.db`
*   **Modelo**: `LogAcaoDepartamento` em `models.py`
*   **Serviço**: `logger_service.py`
