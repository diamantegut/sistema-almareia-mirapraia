# Documentação de Navegação e Acesso Administrativo

## Visão Geral
A interface administrativa foi centralizada em um novo **Painel Administrativo**, substituindo o antigo card na tela inicial. Esta mudança visa organizar melhor as ferramentas de gestão e garantir maior segurança no acesso.

## Como Acessar
1. **Login**: Acesse o sistema com um usuário que possua o perfil de **Admin**.
2. **Menu Principal**: No topo da tela (barra de navegação), clique no novo item **"Administração"**.
   - *Nota*: Este item só é visível para usuários logados como administradores.
3. **Acesso Direto**: Alternativamente, você pode acessar diretamente pelo endereço: `/admin`

## Estrutura do Painel
O novo painel (`/admin`) agrupa todas as funcionalidades críticas em um layout de grade intuitivo:

### 1. Gestão de Usuários
- **Ícone**: Pessoas (Azul)
- **Função**: Criar, editar, desativar usuários e redefinir senhas.
- **Rota**: `/admin/users`

### 2. Relatórios
- **Ícone**: Documento (Verde)
- **Função**: Acesso a relatórios de vendas, estoque e auditorias.
- **Rota**: `/admin/reports` (e sub-rotas de faturamento)

### 3. Insumos (Estoque)
- **Ícone**: Prancheta (Roxo)
- **Função**: Cadastro e configuração de produtos e insumos.
- **Rota**: `/stock/products`

### 4. Fiscal
- **Ícone**: Recibo (Amarelo)
- **Função**: Configuração de integração fiscal (Nuvem Fiscal), impostos e certificados.
- **Rota**: `/fiscal/config`

### 5. Impressoras
- **Ícone**: Impressora (Preto)
- **Função**: Gerenciamento de impressoras e direcionamento de pedidos.
- **Rota**: `/admin/printers`

### 6. Segurança
- **Ícone**: Escudo (Vermelho)
- **Função**: Monitoramento de alertas de segurança e configurações de desconto/cancelamento.
- **Rota**: `/admin/security/dashboard`

### 7. Logs de Auditoria
- **Ícone**: Diário (Cinza)
- **Função**: Histórico detalhado de ações realizadas no sistema.
- **Rota**: `/admin/logs`

### 8. Sistema (Dashboard Técnico)
- **Ícone**: Velocímetro (Ciano)
- **Função**: Status em tempo real de backups, saúde do servidor e alertas técnicos.
- **Rota**: `/admin/system/dashboard`

### 9. Recursos Humanos
- **Ícone**: Crachá (Laranja)
- **Função**: Gestão de funcionários e documentos (acessível também via RH).
- **Rota**: `/hr/dashboard`

### 10. Controle do Servidor
- **Ícone**: Botão Power (Vermelho)
- **Função**: Reiniciar o serviço backend em caso de necessidade.
- **Ação**: Requer confirmação explícita.

## Segurança
- O acesso à rota `/admin` é estritamente validado no backend.
- Tentativas de acesso por usuários não autorizados (garçons, recepção, etc.) resultam em redirecionamento para a tela inicial com mensagem de erro.
- O link "Administração" no menu é ocultado automaticamente para não-admins.
