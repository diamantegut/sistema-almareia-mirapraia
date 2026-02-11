# Documentação: Sistema de Devolução e Sangria (Recepção)
**Data:** 07/02/2026
**Versão:** 1.0

## 1. Devolução de Consumos ao Restaurante

### Visão Geral
Esta funcionalidade permite que a recepção devolva itens lançados incorretamente na conta de um quarto de volta para uma mesa do restaurante. Isso é útil quando um garçom lança um pedido no quarto errado ou quando o hóspede contesta o lançamento.

### Fluxo de Funcionamento
1. **Localização:** Acesse o modal de "Contas Pendentes" de um quarto na tela `/reception/rooms`.
2. **Ação:** Clique no botão "Devolver ao Restaurante" (ícone de seta retornando) ao lado da conta desejada.
3. **Confirmação:** O sistema solicitará confirmação para evitar ações acidentais.
4. **Processamento:**
   - O sistema verifica se a conta está pendente.
   - O sistema procura uma mesa de destino. Se uma mesa específica foi informada (ex: via prompt anterior), tenta usar ela. Caso contrário, procura a primeira mesa livre (1-60).
   - **Se a mesa estiver livre:** A mesa é aberta automaticamente com o nome "Retorno Quarto X", e os itens são transferidos.
   - **Se a mesa estiver ocupada:** O sistema alerta o usuário e sugere mesas livres, permitindo escolher o destino.
   - A conta original do quarto é removida para evitar cobrança duplicada.
   - Um registro de auditoria é criado.

### Tratamento de Erros e Timeout
- **Timeout:** A operação tem um limite de 30 segundos. Se o servidor demorar mais que isso, uma mensagem de erro orientará o usuário a tentar novamente.
- **Feedback Visual:** Durante a operação, uma tela de "Processando..." bloqueia a interface para impedir cliques múltiplos.

---

## 2. Sistema de Sangria e Suprimento

### Visão Geral
Gestão de entradas (Suprimento) e saídas (Sangria) de dinheiro do caixa da recepção, com controle rigoroso de permissões e auditoria.

### Sangria (Retirada)
- **Acesso:** Botão "Sangria" no painel do caixa (`/reception/cashier`).
- **Permissões:** Exclusivo para usuários com nível **Supervisor**, **Gerente** ou **Admin**. Recepcionistas padrão não têm acesso.
- **Impressão Automática:** Ao confirmar a sangria, o sistema imprime automaticamente um comprovante ("Vale") na impressora configurada na recepção, contendo:
  - Valor e Data/Hora
  - Nome do Usuário Responsável
  - Motivo/Descrição
  - Linha para assinatura
- **Auditoria:** O usuário logado é registrado na transação.

### Suprimento (Entrada)
- **Acesso:** Botão "Suprimento".
- **Permissões:** Disponível para **todos os usuários** com acesso ao caixa.
- **Uso:** Adicionar troco ou reforço de caixa.

---

## 3. Matriz de Permissões

| Funcionalidade | Admin | Gerente | Supervisor | Recepção |
| :--- | :---: | :---: | :---: | :---: |
| **Devolver ao Restaurante** | ✅ | ✅ | ✅ | ✅ |
| **Realizar Sangria** | ✅ | ✅ | ✅ | ❌ |
| **Realizar Suprimento** | ✅ | ✅ | ✅ | ✅ |
| **Ver Relatórios de Caixa** | ✅ | ✅ | ✅ | ✅ (Parcial) |

---

## 4. Diagnóstico e Resolução de Problemas

### Erro 404 ao Devolver Conta
- **Causa:** Rota de API não encontrada ou cache antigo do navegador.
- **Solução:** A rota `/api/reception/return_to_restaurant` foi implementada. Recarregue a página (`Ctrl + F5`) para garantir que o script atualizado seja carregado.

### Erro "Mesa Ocupada"
- **Causa:** O sistema tentou devolver para uma mesa que já tem cliente.
- **Solução:** O sistema exibirá um prompt sugerindo mesas livres. Digite o número de uma mesa livre para concluir a transferência.

### Impressão de Sangria Falhou
- **Causa:** Impressora desligada ou não configurada como padrão.
- **Solução:**
  1. Verifique se a impressora está ligada.
  2. O sistema tenta usar a impressora configurada em "Configurações de Impressão". Se não houver, tenta a primeira impressora do Windows disponível.
  3. A sangria é registrada mesmo se a impressão falhar (apenas um aviso é exibido).
