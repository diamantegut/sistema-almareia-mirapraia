# Plano de Contingência - Indisponibilidade do Sistema

Este plano define as ações a serem tomadas em caso de falha crítica do sistema que impeça a operação normal da recepção ou restaurante.

## Cenário: Sistema Web Indisponível (Erro 500 ou Site Fora do Ar)

### Fase 1: Resposta Imediata (0-15 minutos)
1. **Verificar Conectividade:** Confirmar se o problema é local (rede) ou do servidor.
2. **Reiniciar Serviço:** Tentar reiniciar a aplicação Python/Servidor Web.
3. **Diagnóstico Rápido:** Executar `python check_app.py` para verificar integridade das rotas.
4. **Notificação:** Informar a Gerência e a TI sobre a indisponibilidade.

### Fase 2: Operação Manual (Fallback)
Se o sistema não retornar em 15 minutos, ativar modo manual:

#### Recepção (Check-in/Check-out)
- Utilizar **Fichas de Registro de Hóspede (FNRH)** em papel.
- Anotar manualmente: Nome, Quarto, Data Entrada/Saída, Valor da Diária.
- Controlar ocupação visualmente (Quadro de Chaves/Quartos).

#### Restaurante/Consumo
- Utilizar **Comandas de Papel** numeradas.
- Anotar: Número da Mesa/Quarto, Itens consumidos, Valor.
- **Pagamentos:** Receber apenas em dinheiro ou maquininha POS autônoma (guardar comprovantes).
- **Não realizar** lançamentos na conta do quarto (fechar conta na hora).

### Fase 3: Recuperação e Sincronização
Assim que o sistema voltar:
1. **Lançamento Retrospectivo:** Inserir todos os check-ins e consumos realizados manualmente.
    - *Atenção:* Verificar horários para manter a cronologia correta.
2. **Conferência de Caixa:** Validar se o total físico (dinheiro/comprovantes) bate com os lançamentos manuais inseridos.
3. **Validação:** Rodar `check_app.py` novamente para garantir estabilidade.

### Fase 4: Pós-Incidente
- Preencher o **Relatório de Incidente** (`RELATORIO_INCIDENTE.md`).
- Analisar logs para evitar recorrência.
