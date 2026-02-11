# Relatório de Incidente: Falha no Carregamento de Consumo de Funcionários

**Data:** 11/02/2026  
**Status:** Resolvido e Validado

## Descrição do Problema
Usuários relataram falha crítica ao tentar abrir contas de consumo para funcionários. O sistema não persistia a criação da mesa ou falhava silenciosamente, resultando em erro ao tentar acessar a conta recém-criada.

## Diagnóstico
A análise aprofundada revelou que:
1. A rota `/restaurant/open_staff_table` realizava a persistência (`save_table_orders`) mas o tratamento de erro era insuficiente para casos de falha de I/O.
2. Não havia validação robusta para garantir que o ID da mesa gerado (`FUNC_{nome}`) fosse seguro e consistente com o nome do usuário no banco de dados, especialmente se houvesse caracteres especiais.
3. A rota de visualização `/restaurant/table/<id>` não tratava adequadamente o caso onde um ID válido de funcionário era solicitado mas não existia no arquivo de pedidos.

## Correções Implementadas

1. **Reforço na Criação de Mesa (`routes.py`):**
   - Implementada verificação rigorosa do retorno de `save_table_orders`.
   - Adicionado fallback de busca de usuário: agora o sistema compara tanto o nome sanitizado quanto o nome "raw" para garantir que o funcionário seja encontrado mesmo com diferenças de encoding.
   - O ID da mesa agora é gerado com sanitização extra (`safe_staff_id`) substituindo espaços e barras por underscores/hifens para evitar problemas de URL.
   - Adicionado log detalhado (`INFO` e `ERROR`) para cada etapa do processo (solicitação, validação, persistência).

2. **Tratamento de Erro na Visualização:**
   - Adicionada verificação explícita na rota `restaurant_table_order`. Se um ID `FUNC_*` for solicitado e não existir, o sistema loga um erro de integridade e redireciona o usuário com uma mensagem amigável, em vez de quebrar.

3. **Monitoramento:**
   - Logs adicionados com prefixo `CRITICAL` para falhas de salvamento em disco.
   - Logs de `WARNING` para tentativas de abrir mesa para funcionários inexistentes.
   - Logs de `DEBUG` para acesso a mesas de funcionários.

## Validação

Foram criados e executados scripts de teste automatizados:
- **`test_reproduction.py`**: Validou o mecanismo de escrita em disco (`save_table_orders`) e o comportamento de sanitização.
- **`test_integration_staff.py`**: Simulou o fluxo completo via cliente HTTP (mock), confirmando:
  - Criação bem-sucedida de mesa para funcionário válido.
  - Persistência correta dos dados no JSON.
  - Rejeição correta de funcionários inválidos.
  - Mensagens de feedback (`flash`) apropriadas.

Todos os testes passaram com sucesso no ambiente de produção.

## Arquivos Alterados
- `app/blueprints/restaurant/routes.py`
- `test_integration_staff.py` (Novo - Teste de Regressão)
- `test_reproduction.py` (Novo - Teste de Diagnóstico)

## Próximos Passos Recomendados
- Monitorar o arquivo de log para entradas contendo "CRITICAL: Falha ao salvar".
- Manter o script `test_integration_staff.py` na suíte de testes de regressão do projeto.
