# Restaurant Rules — Operação

## Perfis e autorização
- `restaurante/serviço` e `recepção` operam mesas e pedidos.
- `supervisor`, `gerente`, `admin` cobrem operações financeiras sensíveis.
- `externo` não acessa rotas operacionais do restaurante.

## Regras de mesa e pedido
- Abertura de mesa exige dados mínimos válidos (mesa, pessoas, contexto).
- Lançamento de pedidos deve registrar atendente, horário e rastreabilidade.
- Transferências (mesa/item/quarto) exigem validações de destino e autorização.
- Fechamento de conta deve refletir no caixa correto e no histórico.

## Acompanhamentos e cobrança
- Acompanhamento vinculado a prato principal não deve gerar cobrança indevida.
- Item do tipo “acompanhamento e pedido” pode cobrar quando lançado sozinho.
- Perguntas obrigatórias e restrições críticas devem ser validadas no backend.

## Cozinha, estoque e evidência
- Pedido enviado deve aparecer no fluxo de cozinha/KDS.
- Baixa de estoque deve ocorrer para itens/insumos aplicáveis.
- Toda operação crítica deve deixar evidência em JSON e logs.
