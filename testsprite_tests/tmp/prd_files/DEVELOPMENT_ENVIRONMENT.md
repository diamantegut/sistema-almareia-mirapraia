
# Ambiente de Desenvolvimento Isolado - Sistema Almareia Mirapraia

Este documento descreve a configuração do ambiente de desenvolvimento isolado, garantindo que o sistema utilize exclusivamente recursos do diretório local (`F:\Sistema Almareia Mirapraia`).

## 1. Estrutura do Ambiente

O ambiente é configurado para priorizar o diretório local e o ambiente virtual (`venv`) contido nele.
Nenhuma dependência externa ou caminho absoluto para outros drives (ex: `G:\`) deve ser utilizado.

### Arquivos Chave:
- `activate_isolated.bat`: Script de inicialização que configura `PATH`, `PYTHONPATH` e variáveis de ambiente.
- `validate_environment.py`: Script de validação automática que verifica se o isolamento está ativo.
- `local_requirements.txt`: Lista congelada de todas as dependências instaladas no `venv` local.
- `system_config_manager.py`: Gerenciador de configuração ajustado para ignorar caminhos de produção externos.

## 2. Como Iniciar o Ambiente

Para trabalhar no projeto, **SEMPRE** utilize o script de ativação:

```batch
F:\Sistema Almareia Mirapraia\activate_isolated.bat
```

Este script irá:
1. Adicionar `venv\Scripts` ao início do `PATH`.
2. Definir `PYTHONPATH` para a raiz do projeto.
3. Definir `ALMAREIA_ISOLATED_ENV=1`.
4. Abrir um prompt de comando pronto para uso.

## 3. Validação Contínua

Antes de iniciar o servidor ou realizar deploys, execute o script de validação:

```batch
python validate_environment.py
```

Este script verifica:
- Se o interpretador Python é o do `venv` local.
- Se o `sys.path` prioriza o diretório local.
- Se as configurações do sistema (`system_config_manager`) apontam para diretórios de dados locais.
- Se dependências críticas (Flask, Pandas, SQLAlchemy) são carregáveis.

## 4. Gerenciamento de Dependências

Todas as dependências devem ser instaladas no `venv` local.
Para adicionar uma nova biblioteca:
1. Ative o ambiente isolado.
2. `pip install nome-da-lib`
3. Atualize o arquivo de requisitos:
   ```batch
   python export_requirements.py
   ```

## 5. Regras de Desenvolvimento

- **NUNCA** utilize caminhos absolutos com letras de unidade (ex: `C:\`, `G:\`) no código. Use `os.path.join(BASE_DIR, ...)` ou `system_config_manager.get_data_path()`.
- **NUNCA** dependa de variáveis de ambiente globais do Windows. Defina-as em `activate_isolated.bat` se necessário.
- **SEMPRE** teste o código rodando `validate_environment.py` para garantir que não houve vazamento de escopo.
