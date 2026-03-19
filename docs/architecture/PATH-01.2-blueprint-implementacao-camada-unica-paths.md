# PATH-01.2 — Blueprint de implementação da camada única de resolução de paths

## Status
- Fase: planejamento de execução
- Implementação de runtime: não iniciada neste documento
- Movimentação física de pastas/arquivos: fora de escopo nesta etapa

## Base de referência
- Este blueprint executa o contrato aprovado em PATH-01.1:
  - [PATH-01.1-design-tecnico-camada-unica-paths.md](file:///e:/Sistema%20Mirapraia/sistema-almareia-mirapraia/docs/architecture/PATH-01.1-design-tecnico-camada-unica-paths.md)

## Objetivo do PATH-01.2
- Converter a especificação aprovada em plano técnico por PRs curtos, rastreáveis e reversíveis.
- Garantir transição segura entre políticas **legacy → dual → new**.
- Preservar operação atual durante toda a trilha de implementação.

## Premissas obrigatórias
- Sem migração física para `System`, `System_Data`, `System_Backup` até critérios de prontidão.
- Backward compatibility obrigatória enquanto houver consumidores legados.
- Toda mudança de path deve ter:
  - métrica de uso,
  - critério de rollback,
  - teste de regressão.

## Estratégia de rollout
- Política por fase:
  - **Legacy**: comportamento atual preservado.
  - **Dual**: novo resolver ativo com adaptadores e telemetria.
  - **New**: resolução única, legado removido por lote.
- Modo de ativação:
  - feature flag de resolver (`PATH_RESOLVER_MODE=legacy|dual|new`),
  - default inicial em `legacy`,
  - promoção para `dual` por ambiente.

## Plano por PRs

### PR-01 — Fundação do Resolver (sem adoção funcional)
- Escopo:
  - criar módulo de `PathResolver` com API definida no PATH-01.1;
  - adicionar tipos de relatório (`ValidationReport`, `PathTopologySnapshot`);
  - incluir normalização e sanitização de path.
- Entregáveis:
  - implementação isolada, sem alterar consumidores.
  - testes unitários da API do resolver.
- Critério de saída:
  - zero impacto comportamental em produção.
  - cobertura de testes do resolver >= 90% da API pública.
- Rollback:
  - remoção do módulo novo sem tocar chamadas existentes.

### PR-02 — Adaptadores Legacy (bridge controlada)
- Escopo:
  - adaptar `get_data_path`, `get_backup_path`, `get_log_path`, `get_fiscal_path` para delegarem ao resolver em modo `dual`;
  - preservar assinaturas atuais e compatibilidade de import.
- Entregáveis:
  - camada bridge com telemetria de chamadas legadas.
- Critério de saída:
  - comportamento idêntico em `legacy`.
  - comportamento equivalente em `dual` para casos cobertos.
- Rollback:
  - flag para voltar instantaneamente para `legacy`.

### PR-03 — Instrumentação e observabilidade
- Escopo:
  - adicionar métricas de resolução por namespace e fallback;
  - registrar eventos estruturados de resolução e fallback.
- Entregáveis:
  - painel mínimo de contadores e dump de snapshot.
- Critério de saída:
  - métricas disponíveis em dev e homolog.
  - zero regressão funcional.
- Rollback:
  - desativar coleta por flag mantendo resolução ativa.

### PR-04 — Migração de constantes canônicas
- Escopo:
  - garantir que constantes de arquivo em `system_config_manager` sejam derivadas pela camada única;
  - remover duplicações locais de resolução canônica.
- Entregáveis:
  - matriz de constantes migradas + diff de risco.
- Critério de saída:
  - nenhum path canônico fora da camada única.
  - smoke tests de leitura/escrita em JSON críticos.
- Rollback:
  - restaurar versão anterior de constantes e manter modo `legacy`.

### PR-05 — Migração de módulos críticos (lote 1)
- Escopo:
  - módulos de maior sensibilidade operacional (users, cashier, table_orders, fiscal pool, scheduler, backups);
  - substituir uso ad hoc por namespaces da camada única.
- Entregáveis:
  - checklist por módulo: concluído/parcial/pendente.
- Critério de saída:
  - regressão funcional da trilha JSON 100% verde.
  - incidência de fallback dentro do limite acordado.
- Rollback:
  - reverter módulo a módulo via PR revert + flag `legacy`.

### PR-06 — Migração de módulos satélite (lote 2)
- Escopo:
  - blueprints e serviços periféricos com uso residual de path.
- Entregáveis:
  - eliminação de resolução ad hoc remanescente.
- Critério de saída:
  - scan automatizado sem achados novos fora whitelist.
- Rollback:
  - rollback granular por pacote/blueprint.

### PR-07 — Cutover controlado para `new` em dev/homolog
- Escopo:
  - promover modo padrão para `new` em dev e homolog;
  - manter fallback operacional para `dual`.
- Entregáveis:
  - relatório de soak test e incidentes.
- Critério de saída:
  - janela estável sem incidentes críticos por período mínimo.
- Rollback:
  - troca imediata para `dual` por configuração.

### PR-08 — Hardening e prontidão para migração física futura
- Escopo:
  - encerrar débitos de telemetria e documentação;
  - publicar checklist de prontidão para futura separação física (`System`, `System_Data`, `System_Backup`).
- Entregáveis:
  - parecer técnico de readiness.
- Critério de saída:
  - critérios de aceite finais da trilha de resolver cumpridos.
- Rollback:
  - não aplicável (PR documental + hardening).

## Matriz de impacto por domínio
- **Core config/path**: `system_config_manager`, bootstrap e constantes globais.
- **Persistência crítica**: `data_service`, `cashier_service`, `fiscal_pool_service`, `scheduler_service`, `backup_service`.
- **Blue/Routes**: admin, finance, reception, restaurant, governance, kitchen.
- **Serviços auxiliares**: módulos que usam `get_data_path` ou `os.path.join` com artefatos operacionais.

## Checklist operacional por PR
- Pré-merge:
  - contrato do PR descrito (escopo, risco, rollback).
  - testes unitários/integrados atualizados.
  - scan de padrões proibidos executado.
- Pós-merge:
  - telemetria conferida.
  - evidência de regressão anexada.
  - status de modo (`legacy/dual/new`) registrado.

## Gates de qualidade
- Gate G1 (design): aderência ao PATH-01.1.
- Gate G2 (compat): zero quebra em modo `legacy`.
- Gate G3 (dual): equivalência funcional com telemetria ativa.
- Gate G4 (new): estabilidade sustentada em homolog.
- Gate G5 (ready): aptidão para discutir movimentação física futura.

## Plano de testes por fase
- Unitário:
  - API do resolver, normalização, precedência, fallback.
- Integração:
  - leitura/escrita de arquivos canônicos por domínio.
- Regressão:
  - suíte da trilha JSON e backups.
- Auditoria:
  - varredura de padrões de path proibidos fora da camada única.

## Gestão de risco
- Risco: regressão silenciosa em paths relativos.
  - Mitigação: snapshot comparativo de topologia antes/depois por PR.
- Risco: fallback excessivo mascarando erro estrutural.
  - Mitigação: threshold e alerta automático por contador.
- Risco: migração prematura para `new`.
  - Mitigação: promoção por ambiente + soak mínimo.

## Métricas de acompanhamento
- `% módulos migrados` (por lote).
- `% chamadas legadas restantes`.
- `fallback rate` por namespace.
- `incidentes por fase` e `MTTR` de rollback.

## Critérios de aceite do PATH-01.2
- Roadmap por PR definido com escopo, risco e rollback.
- Gates de qualidade e testes definidos por fase.
- Estratégia de rollout `legacy/dual/new` explicitada.
- Matriz de impacto e checklist operacional documentados.
- Nenhuma implementação de runtime realizada nesta etapa.

## Fora de escopo do PATH-01.2
- Escrever código de produção da migração.
- Alterar layout físico de diretórios.
- Executar cutover de ambiente.
