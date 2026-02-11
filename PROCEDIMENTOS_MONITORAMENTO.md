# Procedimentos de Monitoramento Preventivo

Este documento estabelece as rotinas para garantir a estabilidade e detecção precoce de falhas no Sistema Almareia Mirapraia.

## 1. Monitoramento de Aplicação (Diário)

### Verificação de Rotas Críticas
Executar o script de diagnóstico diariamente ou após atualizações:
```bash
python check_app.py
```
**Critério de Sucesso:** A saída deve indicar "[OK]" para todos os endpoints listados e finalizar com "All critical endpoints verified successfully."

### Análise de Logs
Verificar periodicamente o arquivo de logs de erro:
- **Arquivo:** `f:\Sistema Almareia Mirapraia\service_error.log`
- **O que buscar:** Ocorrências de "500 Internal Server Error", "Traceback", ou "Exception".
- **Ação:** Qualquer erro 500 recorrente deve ser tratado como incidente prioritário.

## 2. Monitoramento de Recursos (Servidor)

### Verificação Básica
- **Espaço em Disco:** Garantir que a unidade `F:` tenha pelo menos 20% de espaço livre.
- **Memória:** Monitorar consumo de RAM pelo processo Python. Reiniciar o serviço se o consumo ultrapassar 2GB de forma sustentada.

## 3. Testes de Fumaça (Smoke Tests)
Após qualquer manutenção, realizar o seguinte roteiro manual:
1. Login como Recepcionista.
2. Acessar Painel da Recepção.
3. Abrir Mapa de Reservas.
4. Simular abertura de modal de Check-in.
5. Verificar se não há mensagens de erro na tela.

## 4. Alertas Automáticos (Futuro)
- Implementar envio de e-mail automático para o suporte em caso de exceções não tratadas capturadas pelo Flask.
