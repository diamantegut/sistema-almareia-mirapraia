# Sistema Almareia Mirapraia

Sistema de gestão hoteleira e restaurante, desenvolvido em Python/Flask.

## Estrutura do Projeto (Reestruturado)

O sistema foi migrado para uma arquitetura modular baseada em "Application Factory" e Blueprints.

```text
/
├── app/                    # Núcleo da Aplicação
│   ├── __init__.py         # Application Factory (create_app)
│   ├── blueprints/         # Módulos de Rotas (auth, main, etc.)
│   ├── services/           # Regras de Negócio e Serviços
│   ├── models/             # Modelos de Dados (SQLAlchemy)
│   ├── utils/              # Funções auxiliares
│   ├── templates/          # Arquivos HTML (Jinja2)
│   └── static/             # Assets (CSS, JS, Imagens)
├── data/                   # Arquivos de dados (JSON/SQLite)
├── tests/                  # Testes automatizados
├── run.py                  # Ponto de entrada da aplicação
└── requirements.txt        # Dependências do projeto
```

## Instalação e Execução

1.  **Instalar dependências:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Executar o servidor:**
    ```bash
    python run.py
    ```
    O sistema estará acessível em `http://localhost:5001`.

## Documentação

*   **Auditoria:** Consulte `AUDIT_REPORT.md` para detalhes sobre a refatoração.
*   **API:** A documentação da API está em desenvolvimento e seguirá o padrão RESTful nos novos blueprints.

## Testes

Para rodar os testes:
```bash
pytest
```
