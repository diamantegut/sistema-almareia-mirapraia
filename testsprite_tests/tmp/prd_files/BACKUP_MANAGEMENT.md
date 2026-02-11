# Gerenciamento de Backups e Restauração

## Visão Geral
O sistema agora possui um módulo dedicado para gerenciamento de backups e restauração de dados, acessível através do Painel Administrativo.

## Acesso
1. Acesse o Painel Administrativo (`/admin`).
2. Clique no card **"Backups"**.
3. Rota direta: `/admin/backups`

## Funcionalidades

### 1. Tipos de Backup
O sistema gerencia automaticamente quatro tipos de backup:
- **Produtos (Estoque/Menu)**: Salva `menu_items.json`, `products.json` e logs de alterações.
- **Mesas (Restaurante)**: Salva o estado atual das mesas (`table_orders.json`).
- **Recepção**: Salva ocupação de quartos, contas e notificações.
- **Sistema Completo**: Backup integral da pasta de dados (armazenado externamente, se configurado).

### 2. Gerar Backup Manual
- Selecione o tipo desejado no menu lateral.
- Clique em **"Gerar Novo Backup Agora"**.
- O sistema criará um ponto de restauração imediato.

### 3. Restauração de Dados
- Selecione o tipo de backup.
- Na lista de arquivos, identifique o ponto de restauração desejado (pela data/hora).
- Clique no botão **"Restaurar"**.
- **Atenção**: Uma janela de confirmação aparecerá. A restauração é destrutiva, ou seja, substitui os dados atuais pelos dados do backup.

### 4. Segurança e Auditoria
- Apenas administradores podem acessar esta tela.
- Todas as operações de restauração são registradas nos **Logs de Segurança** (`/admin/logs`) com nível de severidade 'High' ou 'Medium'.
- Backups "Full System" não podem ser restaurados automaticamente via interface web por segurança; requerem intervenção manual no servidor.
