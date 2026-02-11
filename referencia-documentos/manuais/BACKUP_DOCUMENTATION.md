# Documentação do Sistema de Backup Automático

Este documento descreve o novo sistema de backup implementado para garantir a segurança dos dados do sistema. O sistema opera de forma autônoma, realizando backups periódicos de diferentes módulos com políticas de retenção específicas.

## Visão Geral

O sistema de backup foi reescrito para ser modular, robusto e automático. Ele roda em threads separadas junto com a aplicação principal, garantindo que os backups sejam feitos sem interromper o uso do sistema.

### Localização dos Backups

Os backups são salvos em: `C:\Users\Angelo Diamante\Documents\trae_projects\Back of the house\backups`
O backup completo do sistema é salvo em: `G:\Back Up Sistema`

## Tipos de Backup

### 1. Produtos (Menu e Estoque)
- **Frequência**: A cada 1 hora.
- **Retenção**: 24 horas (backups mais antigos são removidos automaticamente).
- **Destino**: `backups/Produtos`
- **Arquivos**: `menu_items.json`, `products.json`, `product_changes.json`.
- **Rota na Interface**: `/menu/management`

### 2. Mesas do Restaurante
- **Frequência**: A cada 1 minuto (tempo real).
- **Retenção**: 120 minutos (2 horas).
- **Destino**: `backups/Mesas Restaurante`
- **Arquivos**: `table_orders.json`.
- **Rota na Interface**: `/restaurant/tables`

### 3. Recepção (Quartos e Hóspedes)
- **Frequência**: A cada 20 minutos.
- **Retenção**: 72 horas (3 dias).
- **Destino**: `backups/Recepcao`
- **Arquivos**: `room_occupancy.json`, `room_charges.json`, `cleaning_status.json`, `guest_notifications.json`.
- **Rota na Interface**: `/reception/rooms`

### 4. Sistema Completo
- **Frequência**: A cada 12 horas.
- **Retenção**: 72 horas (3 dias).
- **Destino**: `G:\Back Up Sistema`
- **Conteúdo**: Cópia completa (ZIP) de toda a pasta `data/`.

## Monitoramento e Status

O status dos backups pode ser verificado através da API ou dos logs do sistema.
- **Painel Admin**: O status detalhado de todos os backups (última execução, sucesso/erro) é exibido em tempo real no **Painel de Controle do Sistema** (`/admin/system/dashboard`).
- **Logs**: Verifique o console da aplicação ou o arquivo de log configurado.
- **API Status**: `GET /api/backups/status` retorna o estado do último backup de cada tipo (sucesso/erro, data, mensagem).

## Procedimentos de Restauração

### Restauração Parcial (Produtos, Mesas, Recepção)
A restauração destes módulos pode ser feita "a quente" (com o sistema rodando), mas recomenda-se cautela.

1. **Via Interface (Se disponível)**:
   - Navegue até a página do módulo correspondente.
   - Use a funcionalidade de "Restaurar Backup" (se habilitada para seu nível de acesso).

2. **Via API**:
   - Endpoint: `POST /api/backups/restore/<tipo>/<nome_do_arquivo>`
   - Exemplo: `POST /api/backups/restore/products/menu_items_2026-01-29_10-00-00.json`
   - **Nota**: A restauração substitui imediatamente os dados atuais pelos dados do backup.

### Restauração Completa do Sistema
**ATENÇÃO**: A restauração completa DEVE ser feita com o sistema PARADO para evitar corrupção de dados.

1. **Pare o Servidor**: Encerre o processo do Flask/Python.
2. **Localize o Backup**: Vá até `G:\Back Up Sistema`.
3. **Extraia os Arquivos**:
   - Abra o arquivo ZIP desejado (ex: `full_backup_2026-01-29_12-00-00.zip`).
   - Extraia o conteúdo para a pasta `data/` do projeto, substituindo os arquivos existentes.
4. **Reinicie o Servidor**: Inicie a aplicação novamente.

## Resolução de Problemas

- **Backup Falhou**: Verifique se o disco de destino (especialmente `G:`) está acessível e tem espaço livre.
- **Permissões**: Certifique-se de que o usuário que roda o sistema tem permissão de escrita nas pastas de backup.
- **Backup Completo não aparece**: Se o drive `G:` estiver desconectado, o backup completo será pulado e um erro será registrado no status.
