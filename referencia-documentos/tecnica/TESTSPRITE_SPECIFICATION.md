# Especificação de Produto: TestSprite no Sistema Almareia Mirapraia

**Data:** 08/02/2026
**Versão:** 1.0
**Status:** Aprovado

## 1. Objetivos
O objetivo da integração do TestSprite é automatizar a validação contínua do Sistema Almareia Mirapraia, garantindo que as funcionalidades críticas (Reservas, Caixa, Restaurante, Integrações) estejam operando conforme especificado no PRD e nos Planos de Teste, reduzindo a regressão e acelerando o ciclo de desenvolvimento.

## 2. Requisitos Técnicos e de Ambiente

### Pré-requisitos
*   **Node.js:** Runtime necessário para execução do agente TestSprite.
*   **Python 3.x:** Para execução do servidor backend (Flask).
*   **Dependências do Projeto:** Instaladas via `pip install -r requirements.txt`.
*   **Servidor Local:** O servidor de desenvolvimento deve estar em execução (`localhost:5001`) antes de iniciar os testes.

### Estrutura de Diretórios
O TestSprite utiliza a seguinte estrutura no projeto:
```
F:\Sistema Almareia Mirapraia\
├── testsprite_tests\
│   ├── standard_prd.json                # Especificação do Produto (Fonte da Verdade)
│   ├── testsprite_backend_test_plan.json # Plano de Testes Backend (Casos de Teste)
│   ├── testsprite_frontend_test_plan.json # Plano de Testes Frontend
│   ├── testsprite-mcp-test-report.md    # Relatório Final de Execução
│   └── tmp\                             # Arquivos temporários e logs brutos
```

## 3. Passo-a-Passo de Implementação

### Passo 1: Preparação do Ambiente
1.  **Atualizar Documentação:** Certifique-se de que o `standard_prd.json` reflete as rotas e funcionalidades atuais do sistema. Erros de "Rota não encontrada" (404) geralmente ocorrem por desvios entre este arquivo e o `app.py`.
2.  **Configurar Planos de Teste:** Edite `testsprite_backend_test_plan.json` para adicionar ou modificar casos de teste (IDs únicos, descrições claras).

### Passo 2: Execução dos Testes
1.  **Iniciar Servidor:** Execute `run_dev_server.bat` ou `python app.py` para subir o backend na porta 5001.
2.  **Executar Comando TestSprite:**
    Utilize o comando configurado (via ferramenta MCP ou terminal):
    ```bash
    node "caminho/para/testsprite-mcp/dist/index.js" generateCodeAndExecute
    ```
    *Nota: O agente irá gerar código de teste dinamicamente com base nos planos JSON e executá-lo contra o servidor local.*

### Passo 3: Análise de Resultados
1.  **Verificar Console:** Acompanhe a saída para erros imediatos de conexão ou sintaxe.
2.  **Ler Relatório:** Consulte `testsprite_tests\testsprite-mcp-test-report.md` para ver o status de cada caso de teste (Passou/Falhou) e métricas de cobertura.

## 4. Casos de Uso Específicos

### Validação de Rotas de Caixa
*   **Cenário:** Abertura e Fechamento de Caixa.
*   **Rota Real:** `/reception/cashier` (POST com `action='open_cashier'`).
*   **Erro Comum:** Tentar usar `/api/cashier/open` (Rota inexistente/alucinada).
*   **Correção:** Sempre verifique `app.py` para confirmar a URL exata antes de adicionar ao plano de testes.

### Testes de Integração (WhatsApp/Fiscal)
*   Para testes que dependem de serviços externos, o TestSprite pode simular chamadas ou verificar se a API responde corretamente (mocking pode ser necessário para testes determinísticos).

## 5. Critérios de Aceitação
*   **Taxa de Sucesso:** 100% dos testes críticos (High Priority) devem passar.
*   **Sem Erros 404:** Todas as rotas testadas devem existir e responder (200, 302, 400, etc.).
*   **Cobertura:** O relatório deve indicar cobertura dos principais fluxos de usuário descritos no PRD.

## 6. Troubleshooting Comum

| Sintoma | Causa Provável | Solução |
| :--- | :--- | :--- |
| **Erro 404 (Not Found)** | Rota incorreta no plano de teste ou PRD. | Verificar rota no `app.py` e atualizar JSONs. |
| **Connection Refused** | Servidor backend desligado. | Iniciar `run_dev_server.bat`. |
| **Timeout** | Servidor lento ou teste travado. | Verificar logs do servidor Flask; reiniciar se necessário. |
| **Ngrok Error** | Múltiplas sessões ngrok ativas. | Matar processos ngrok (`taskkill /F /IM ngrok.exe`). |

## 7. Melhores Práticas
*   **Atomicidade:** Mantenha os casos de teste independentes sempre que possível.
*   **Limpeza:** O TestSprite pode gerar dados de teste; configure rotinas de limpeza (teardown) se necessário para não poluir o banco de dados.
*   **Documentação Viva:** Atualize o `standard_prd.json` a cada nova feature implementada.
