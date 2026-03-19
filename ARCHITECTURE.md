# Architecture — Backend, Services e Persistência

## Estrutura de backend
- Framework: Flask com blueprints por domínio em `app/blueprints`.
- Camada web: rotas HTTP, templates Jinja e assets estáticos.
- Camada de serviço: regras reutilizáveis em `app/services`.
- Utilitários: helpers comuns em `app/utils`.

## Blueprints relevantes
- `restaurant`: mesas, pedidos, impressão/cozinha, transferências, fechamento.
- `reception`: ocupação, quartos, consumo em quarto e checkout.
- `menu`: catálogo, regras de produto, perguntas e acompanhamentos.
- `finance`, `main`, `admin` e demais módulos de apoio operacional.

## Serviços chave
- `printing_service.py`: payload e impressão de pedidos/KDS.
- `stock_service.py`: operações de estoque e baixas.
- `cashier_service.py`: sessões e operações de caixa.
- `transfer_service.py`: regras de transferências operacionais.
- `logger_service.py`/`logging_service.py`: trilha de auditoria.

## Persistência operacional
- Modelo predominante em JSON na raiz do projeto.
- Escritas devem preservar integridade estrutural e consistência entre arquivos.
- Mudanças críticas devem considerar efeitos cruzados em pedidos, caixa, quartos e estoque.

## Princípios de engenharia
- Regra crítica sempre validada no backend.
- Frontend orienta UX, mas não é fonte única de segurança.
- Qualquer ajuste deve manter rastreabilidade por logs + JSON.
