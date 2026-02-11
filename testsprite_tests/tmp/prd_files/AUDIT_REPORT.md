# Relatório de Auditoria e Análise de Código
**Data:** 08/02/2026
**Projeto:** Sistema Almareia Mirapraia

## 1. Visão Geral
O sistema apresenta uma arquitetura monolítica baseada em Flask, com um único arquivo `app.py` contendo mais de 18.000 linhas de código. A estrutura de diretórios está poluída, com misturas de scripts de manutenção, testes, serviços e arquivos de configuração na raiz.

## 2. Problemas Identificados

### 2.1. Monólito `app.py`
O arquivo `app.py` viola o Princípio da Responsabilidade Única (SRP), acumulando:
- Configuração da aplicação e banco de dados.
- Definição de mais de 100 rotas (endpoints).
- Lógica de negócios misturada com lógica de apresentação.
- Tarefas agendadas (scheduler).

**Ação Recomendada:** Dividir em Blueprints por domínio (Recepção, Estoque, Cozinha, Admin, API).

### 2.2. Poluição da Raiz do Projeto
A raiz contém 50+ arquivos que deveriam estar em subdiretórios:
- **Serviços:** `assinafy_service.py`, `checklist_service.py`, `commission_service.py`, etc. (Mover para `app/services/`)
- **Testes:** `test_route.py`, `test_all_components.py`, etc. (Mover para `tests/`)
- **Scripts de Debug:** `debug_routes.py`, `debug_reservations.py` (Mover para `scripts/debug/` ou excluir)
- **Legado:** `Update_Package_20260202` (Excluir/Arquivar)

### 2.3. Código Morto e Duplicado
- **Pasta `Update_Package_20260202`**: Contém cópias antigas de `app.py` e outros arquivos core.
- **Pasta `scripts/deprecated_bat`**: Scripts .bat obsoletos.
- **Arquivos de Backup**: Múltiplos arquivos `.bak` e `.migration` dispersos.

### 2.4. Dependências
O arquivo `requirements.txt` lista dependências essenciais, mas há imports no código que precisam ser verificados contra esta lista durante a refatoração para garantir que o ambiente de produção seja reproduzível.

## 3. Plano de Reestruturação de Arquivos

### 3.1. Nova Estrutura Proposta (`app/`)
```text
app/
├── __init__.py          # Application Factory
├── blueprints/          # Rotas divididas por módulo
├── services/            # Lógica de negócios centralizada
├── models/              # Definições de dados (SQLAlchemy + Schemas)
├── utils/               # Helpers
├── templates/           # Movido da raiz
└── static/              # Movido da raiz
```

### 3.2. Movimentação de Arquivos Chave
| Arquivo Atual | Novo Destino |
|---|---|
| `models.py` | `app/models/models.py` |
| `database.py` | `app/models/database.py` |
| `*_service.py` (Raiz) | `app/services/` |
| `templates/` | `app/templates/` |
| `static/` | `app/static/` |

## 4. Conclusão
A reestruturação é crítica para a manutenibilidade. A prioridade imediata é criar a estrutura de pacotes `app/` e mover os arquivos estáticos e de template, seguido pela centralização dos serviços.
