# Documentação: Permissões de Gerenciamento de Menu e Auditoria

## Visão Geral
Esta atualização implementa um controle de permissões expandido para o gerenciamento do cardápio digital, permitindo que supervisores e superiores hierárquicos de todos os departamentos (não apenas Restaurante) possam pausar e reativar itens. Além disso, todas as ações são auditadas para segurança e controle.

## 1. Níveis de Acesso e Permissões

### Quem pode acessar?
O sistema agora valida o acesso baseando-se em funções (roles) e palavras-chave na função do usuário. Têm permissão de acesso ao gerenciamento de menu:

*   **Administradores** (`admin`)
*   **Gerentes** (`gerente` e qualquer role contendo "gerente")
*   **Diretores** (qualquer role contendo "diretor")
*   **Recepção** (`recepcao`)
*   **Supervisores** (`supervisor` e qualquer role contendo "supervisor", ex: `supervisor_rh`, `supervisor_manutencao`)

### Ações Permitidas
Usuários com as permissões acima podem:
1.  Visualizar a lista de produtos.
2.  **Pausar** um produto (ocultando-o temporariamente do cardápio digital/totem).
3.  **Reativar** um produto previamente pausado.
4.  Editar detalhes do produto (apenas se não houver pedidos ativos bloqueando a edição).

> **Nota:** Existe um limite de segurança de 15 itens pausados simultaneamente para evitar desconfiguração acidental do cardápio.

## 2. Sistema de Auditoria

Todas as ações de pausa e reativação são registradas automaticamente nos logs do sistema.

### O que é registrado?
Cada registro de auditoria contém:
*   **Timestamp:** Data e hora exata da ação.
*   **Usuário:** Nome do usuário que realizou a ação.
*   **Departamento:** Departamento de origem do usuário (ex: RH, Recepção, Restaurante).
*   **Ação:** "PAUSADO" ou "RETOMADO".
*   **Item Afetado:** Nome do produto.
*   **Motivo:** Justificativa inserida pelo usuário no momento da pausa.

### Visualização dos Logs
Os logs podem ser visualizados na área administrativa em "Logs do Sistema", filtrando pela categoria **Cardápio**.

## 3. Notificações de Impressão
Sempre que um item é pausado ou reativado, o sistema tenta imprimir um comprovante de notificação na impressora configurada para aquele produto (geralmente Cozinha ou Bar), informando a equipe de produção sobre a indisponibilidade do item.

## 4. Testes e Validação
Foram desenvolvidos testes automatizados (`tests/test_permissions_and_print.py`) para garantir:
*   Que usuários com roles como `supervisor_rh` tenham acesso garantido.
*   Que o bloqueio para usuários sem permissão continue funcionando.
*   Que a funcionalidade de impressão de sangria (revisada nesta atualização) esteja operante.
