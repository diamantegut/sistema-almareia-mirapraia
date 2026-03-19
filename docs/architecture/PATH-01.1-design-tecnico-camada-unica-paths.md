# PATH-01.1 — Design técnico da camada única de resolução de paths

## Status
- Fase: design técnico
- Implementação: não iniciada
- Movimentação física de pastas/arquivos: não autorizada nesta etapa

## Contexto
- O projeto possui resolução de paths distribuída entre funções utilitárias, constantes e uso direto de `os.path`.
- O núcleo atual concentra boa parte da definição em `app/services/system_config_manager.py`, incluindo `get_data_path`, `get_backup_path` e constantes de arquivos.
- Há consumo heterogêneo: partes usam constantes centralizadas, partes usam chamadas diretas de resolução, e partes usam caminhos estáticos de assets.
- A estrutura alvo futura está definida como:
  - `\Sistema Mirapraia\System\`
  - `\Sistema Mirapraia\System_Data\`
  - `\Sistema Mirapraia\System_Backup\`
- O diagnóstico prévio concluiu que mover pastas agora aumenta risco operacional.

## Objetivo do PATH-01.1
- Formalizar o contrato técnico de uma camada única de paths.
- Definir API, regras de resolução, compatibilidade e critérios de aceite.
- Preparar a base de governança para migração futura sem alteração de layout físico nesta etapa.

## Não objetivos desta etapa
- Não alterar código de execução.
- Não mover/renomear diretórios existentes.
- Não introduzir novos PRs de refatoração agora.
- Não remover compatibilidade legada nesta fase de design.

## Princípios de arquitetura
- Fonte única de verdade para resolução de paths.
- Resolução determinística e testável.
- Compatibilidade progressiva com legado.
- Separação entre domínio lógico e localização física.
- Observabilidade de fallback e de uso legado.
- Segurança operacional para Windows como ambiente primário.

## Modelo conceitual de roots
- **Root lógico de aplicação (`system_root`)**: diretório do executável/sistema (`System` no alvo).
- **Root lógico de dados (`data_root`)**: diretório de JSON, DB, uploads e runtime state (`System_Data` no alvo).
- **Root lógico de backup (`backup_root`)**: diretório de snapshots e históricos (`System_Backup` no alvo).

## Contrato da camada única (API proposta)
- `PathResolver.get_root(kind: Literal["system","data","backup"]) -> Path`
- `PathResolver.resolve_data(relative_name: str) -> Path`
- `PathResolver.resolve_backup(relative_name: str = "") -> Path`
- `PathResolver.resolve_log(relative_name: str = "") -> Path`
- `PathResolver.resolve_static(relative_name: str = "") -> Path`
- `PathResolver.resolve_upload(relative_name: str = "") -> Path`
- `PathResolver.ensure_dir(path: Path) -> Path`
- `PathResolver.validate(required: list[str] | None = None) -> ValidationReport`
- `PathResolver.snapshot() -> PathTopologySnapshot`

### Regras do contrato
- Toda API retorna `Path` absoluto normalizado.
- Entrada relativa é resolvida pela root lógica apropriada.
- Entrada absoluta só é aceita para chaves explicitamente marcadas como override.
- A camada cria diretórios somente quando explicitamente necessário (`ensure_dir` ou APIs que exigem escrita).
- A camada nunca escreve conteúdo de negócio, apenas resolve e garante estrutura de diretórios.

## Tabela canônica de namespaces lógicos
- `data:*` → arquivos de dados de negócio (`users.json`, `cashier_sessions.json`, `table_orders.json`, etc.).
- `backup:*` → backups técnicos e operacionais.
- `log:*` → trilhas de log e auditoria.
- `asset:*` → estáticos do sistema.
- `upload:*` → uploads operacionais.

## Contrato de configuração
- Chaves de configuração canônicas:
  - `system_root`
  - `data_root`
  - `backup_root`
  - `logs_root` (opcional; default em `data_root/logs`)
  - `uploads_root` (opcional; default em `data_root/uploads`)
- Regras:
  - Se não definidas, resolver por defaults legados atuais.
  - Variáveis de ambiente podem sobrepor configuração de arquivo, com precedência explícita.
  - Paths relativos em configuração são relativos a `system_root`.

## Ordem de precedência de resolução
- 1) Override explícito de runtime (somente para testes/ferramentas internas).
- 2) Variáveis de ambiente.
- 3) Configuração persistida.
- 4) Defaults de compatibilidade legada.

## Compatibilidade legada (obrigatória na migração)
- Adaptadores de compatibilidade devem manter assinaturas públicas atuais (`get_data_path`, `get_backup_path`, etc.) delegando internamente ao resolver único.
- Constantes de arquivo devem ser derivadas da camada única.
- Não quebrar importações existentes durante fases intermediárias.

## Política de fallback e erro
- Falha de criação de diretório:
  - registrar evento estruturado de path-resolution;
  - aplicar fallback somente quando definido em contrato;
  - em falha crítica sem fallback, propagar erro tipado.
- Diretório inexistente:
  - criar apenas quando operação exigir escrita;
  - leitura não cria diretório por padrão.

## Observabilidade
- Métricas mínimas:
  - contador de resoluções por namespace (`data`, `backup`, `log`, `asset`, `upload`);
  - contador de fallback acionado;
  - contador de uso de APIs legadas.
- Log estruturado mínimo:
  - `event=path_resolution`
  - `namespace`
  - `input`
  - `resolved_path`
  - `source` (runtime/env/config/default)
  - `fallback_used`

## Segurança e robustez
- Sanitização de segmentos relativos para evitar path traversal.
- Bloqueio de resolução para fora das roots canônicas quando namespace for controlado.
- Normalização para ambiente Windows (`Path.resolve`, separador nativo, suporte a drive letter).

## Estratégia de migração (macro, sem execução nesta etapa)
- **Fase A**: introduzir resolver único com adaptadores, sem alterar layout físico.
- **Fase B**: migrar consumidores para API única e remover resolução ad hoc.
- **Fase C**: habilitar roots alvo (`System`, `System_Data`, `System_Backup`) com compatibilidade.
- **Fase D**: desativar legados e limpar adaptadores.

## Critérios de aceite do PATH-01.1 (design)
- Contrato documentado com API, regras e precedência.
- Modelo de roots lógico definido e alinhado ao alvo futuro.
- Política de compatibilidade e fallback explicitada.
- Estratégia de migração em fases definida.
- Nenhuma mudança de execução e nenhuma movimentação física realizada.

## Riscos e controles
- **Risco**: quebra de módulos com path fixo.
  - **Controle**: adaptadores legados + telemetria de uso.
- **Risco**: divergência entre ambiente dev e produção.
  - **Controle**: validação de topologia e snapshot de paths por ambiente.
- **Risco**: fallback silencioso mascarar erro estrutural.
  - **Controle**: fallback com log obrigatório e contador de incidência.

## Entregáveis desta etapa
- Documento de contrato técnico da camada única de paths.
- Definição formal de API, precedência, fallback, observabilidade e migração.

## Próxima etapa sugerida (fora deste PATH-01.1)
- Preparar PATH-01.2 com plano de implementação incremental e matriz de impacto por módulo.
