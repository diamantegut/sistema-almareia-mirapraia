# Sistema Almareia Mirapraia

Sistema de gestão hoteleira e restaurante, desenvolvido em Python/Flask.

## 📋 Sobre o Projeto

O Sistema Almareia Mirapraia é uma solução completa para gerenciamento de hotelaria, cobrindo recepção, reservas, restaurante, governança e financeiro. O sistema utiliza uma arquitetura modular baseada em "Application Factory" e Blueprints do Flask.

### Módulos Principais
- **Recepção:** Check-in, Check-out, Gerenciamento de Quartos.
- **Reservas:** Controle de reservas e disponibilidade.
- **Restaurante:** Comandas de mesa, pedidos, integração com cozinha e bar.
- **Governança:** Status de limpeza, inspeção de quartos.
- **Financeiro:** Controle de caixa, pagamentos, relatórios.

## 🚀 Tecnologias Utilizadas

- **Linguagem:** Python 3.x
- **Framework Web:** Flask
- **Template Engine:** Jinja2
- **Banco de Dados:** Arquivos JSON (Armazenamento local)
- **Frontend:** HTML5, CSS3, JavaScript
- **Testes:** pytest
- **Outros:** Werkzeug (WSGI), Gunicorn (Produção - opcional)

## 📂 Estrutura do Projeto

```text
/
├── app/                    # Núcleo da Aplicação
│   ├── __init__.py         # Application Factory (create_app)
│   ├── blueprints/         # Módulos de Rotas (reception, restaurant, admin, etc.)
│   ├── services/           # Regras de Negócio e Serviços (Cashier, DataService, etc.)
│   ├── models/             # Definições de dados
│   ├── utils/              # Funções auxiliares e decoradores
│   ├── templates/          # Arquivos HTML (Jinja2)
│   └── static/             # Assets (CSS, JS, Imagens, Uploads)
├── data/                   # Arquivos de dados persistentes (JSON)
├── tests/                  # Testes automatizados (Unitários e Integração)
├── Backups/                # Backups automáticos do sistema
├── run.py                  # Ponto de entrada da aplicação
└── requirements.txt        # Dependências do projeto
```

## ⚙️ Instalação e Configuração

### Pré-requisitos
- Python 3.8 ou superior
- Git

### Passo a Passo

1.  **Clonar o repositório:**
    ```bash
    git clone https://github.com/SEU_USUARIO/NOME_DO_REPOSITORIO.git
    cd NOME_DO_REPOSITORIO
    ```

2.  **Criar e ativar um ambiente virtual (recomendado):**
    *   Windows:
        ```bash
        python -m venv venv
        venv\Scripts\activate
        ```
    *   Linux/Mac:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```

3.  **Instalar dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuração Inicial:**
    *   Verifique se a pasta `data/` contém os arquivos JSON iniciais necessários.
    *   O sistema cria automaticamente arquivos de dados se não existirem (com estruturas vazias), mas recomenda-se um backup inicial.

5.  **Executar o servidor:**
    ```bash
    python run.py
    ```
    O sistema estará acessível em `http://localhost:5001`.

## 🧪 Executando Testes

Para rodar a suíte de testes automatizados:

```bash
pytest
```

## 🔄 Fluxo de Trabalho Git (Automação)

O projeto inclui um script `git_auto.bat` para facilitar o fluxo de trabalho:

1.  Execute `git_auto.bat`.
2.  Escolha a opção desejada:
    *   `[1] PULL`: Atualiza o repositório local com as mudanças do remoto.
    *   `[2] ADD/COMMIT/PUSH`: Envia suas alterações locais para o remoto.
    *   `[3] STATUS`: Verifica o estado atual dos arquivos.

## 📝 Notas Adicionais

*   **Backups:** O sistema realiza backups automáticos das sessões de caixa a cada 30 segundos em `Backups/Caixa`.
*   **Logs:** Logs de erro e auditoria são armazenados em `logs/`.

---
Desenvolvido para Almareia Mirapraia.

Fluxo Git sincronizado e testado em 2026-02-15.
