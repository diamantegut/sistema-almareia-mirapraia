# Manual do Usuário - Caixa de Reservas

## Visão Geral
O sistema de Caixa de Reservas permite gerenciar pagamentos antecipados, sinais e quitação de reservas de forma separada do caixa da recepção (consumo/diárias).

## Acesso
1.  Navegue até o menu **Recepção**.
2.  Clique em **Caixa de Reservas** (ou acesse `/reception/reservations-cashier`).

## Funcionalidades Principais

### 1. Abertura de Caixa
Antes de receber qualquer pagamento, é necessário abrir o caixa.
-   Insira o **Saldo Inicial** (geralmente R$ 0,00 ou o fundo de troco).
-   Clique em **Abrir Caixa**.

### 2. Recebimento de Pagamento (Nova Reserva)
Ao criar uma reserva manual:
1.  Preencha os dados do hóspede e datas.
2.  No campo **Pago (R$)**, insira o valor do sinal (se houver).
3.  O sistema calculará automaticamente o valor **A Receber**.
4.  Se houver valor pago, selecione a **Forma de Pagamento**.
5.  Clique em **Salvar**.
    -   *Nota*: O caixa deve estar aberto para registrar o pagamento.

### 3. Recebimento de Pagamento (Reserva Existente)
Para reservas já criadas (ex: via Booking ou telefone):
1.  Acesse o painel de **Quartos** (`/reception/rooms`).
2.  No card do quarto, clique em **Receber Reserva**.
3.  O sistema mostrará o valor total, já pago e o saldo pendente.
4.  Confirme o **Valor a Receber** e a **Forma de Pagamento**.
5.  Clique em **Confirmar Pagamento**.

### 4. Fechamento de Caixa
Ao final do turno:
1.  Acesse o **Caixa de Reservas**.
2.  Confira o saldo calculado pelo sistema.
3.  Insira os valores reais em **Dinheiro** e **Outros** (Cartão/Pix) para conferência (opcional).
4.  Clique em **Fechar Caixa**.

### 5. Conferência Financeira
O gerente ou financeiro pode visualizar o balanço:
1.  Acesse o menu **Financeiro**.
2.  Vá em **Balanços**.
3.  Localize o card **Recepção (Reservas)** para ver o resumo das movimentações.

## Perguntas Frequentes

**Q: Posso receber pagamento com o caixa fechado?**
R: Não. O sistema bloqueará a operação e solicitará a abertura do caixa.

**Q: Onde vejo o histórico de pagamentos de uma reserva?**
R: No momento, o histórico detalhado fica no **Caixa de Reservas** (transações). Na reserva, você vê o total pago acumulado.

**Q: Como corrijo um lançamento errado?**
R: Se o caixa ainda estiver aberto, você pode fazer um lançamento de estorno (Sangria ou Devolução) com a descrição do erro, ou contatar o gerente para editar o JSON se necessário (somente admin).
