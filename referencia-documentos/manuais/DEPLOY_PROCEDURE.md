# Procedimento de Atualização do Servidor de Produção
**Data:** 06/02/2026
**Sistema:** Almareia Mirapraia
**Servidor:** Produção (G:\Almareia Mirapraia Sistema Producao)
**Porta:** 5000

Este documento descreve o procedimento padrão para atualização segura da aplicação em ambiente de produção, garantindo backup, validação e possibilidade de rollback automático.

## 1. Pré-requisitos
- Acesso ao diretório `G:\Almareia Mirapraia Sistema Producao`.
- Python 3.14+ instalado e configurado no PATH.
- Permissões administrativas para parar/iniciar processos e escrever em disco.
- Ferramenta PowerShell disponível.

## 2. Dependências e Versões
As dependências atuais do projeto devem ser congeladas antes do deploy.
Execute na raiz do desenvolvimento:
```powershell
python -m pip freeze > requirements.txt
```
Principais bibliotecas esperadas:
- Flask
- Requests
- Waitress (ou servidor WSGI utilizado)
- APScheduler

## 3. Estratégia de Deploy (Zero Downtime / Minimized Downtime)
Devido à natureza da aplicação (servidor único na porta 5000), adotamos uma estratégia de **Substituição Rápida com Backup Prévio**.
O tempo de inatividade estimado é de < 5 segundos (tempo de reinício do processo Python).

### Fluxo Automatizado (`deploy_prod.ps1`):
1.  **Validação Pré-Deploy:** Verifica se o novo código passa nos testes locais.
2.  **Backup Completo:** Comprime a pasta de produção atual para `G:\Backups\App_Backup_{TIMESTAMP}.zip`.
3.  **Parada do Serviço:** Identifica o processo ocupando a porta 5000 e o encerra suavemente.
4.  **Atualização dos Arquivos:** Copia os novos arquivos do ambiente de desenvolvimento/staging para produção.
5.  **Instalação de Dependências:** Atualiza pacotes via `pip install -r requirements.txt`.
6.  **Reinício do Serviço:** Inicia a aplicação em modo background (detached).
7.  **Health Check:** Aguarda o serviço responder na porta 5000.
8.  **Rollback (Se falhar):** Restaura o backup automaticamente se o Health Check falhar.

## 4. Testes de Funcionalidade Crítica
Após a atualização, o script de validação executará os seguintes testes:
- **Status HTTP 200** na rota `/` (Home).
- **Status HTTP 200** na rota `/login` (Página de acesso).
- **Status HTTP 200** na rota `/api/status` (se existir) ou verificação de integridade da API.
- Verificação de logs de erro no arquivo `app.log` ou saída padrão.

## 5. Procedimento de Rollback
Em caso de falha crítica detectada pelo script de deploy:
1.  O processo atual é encerrado imediatamente.
2.  A pasta atual é renomeada para `_failed_{TIMESTAMP}` para análise forense.
3.  O backup `.zip` criado no passo 2 é extraído para o diretório de produção.
4.  O serviço da versão anterior é reiniciado.
5.  Um alerta é exibido no console.

## 6. Checklist Pós-Atualização
- [ ] Verificar se o serviço está rodando (`netstat -ano | findstr 5000`).
- [ ] Acessar o sistema via navegador e realizar login.
- [ ] Verificar logs (`debug_log.txt` ou similar) por erros recentes (Tracebacks).
- [ ] Testar uma funcionalidade de escrita (ex: criar uma nota fiscal ou pedido de teste).
- [ ] Monitorar o uso de CPU/Memória nos primeiros 15 minutos.

## 7. Notificação
O status do deploy (Sucesso/Falha/Rollback) será exibido no terminal e registrado em `deploy_log.txt` na raiz da produção.

---
**Autor:** Equipe de Desenvolvimento Almareia Mirapraia
