# Design System Almareia Mirapraia

## Conceitos

- Alma: acolhimento, calor, elegância
- Mar: confiança, profundidade, estabilidade
- Areia: leveza, neutralidade, sofisticação natural

## Paleta Oficial

### Alma

- #C96A3D
- #C6A75E
- #F5E9DD

### Mar

- #0F3057
- #00587A
- #3FA7A3

### Areia

- #E8D8C3
- #D4BFAA
- #A89F91

## Regras de Uso

- Fundo principal neutro com base em Areia/Creme
- Cores fortes só para ações e categorias
- Máximo de 3 cores intensas por tela
- Vermelho apenas para erro real ou cancelamento
- Contraste mínimo recomendado de 4.5:1 para textos

## Tokens Base

- Fundo de página: #F5E9DD
- Fundo de cartão: #FFFFFF
- Borda suave: #D4BFAA
- Texto forte: #0F3057
- Texto regular: #243342
- Primário de ação: #00587A
- Secundário de ação: #C6A75E
- Destaque opcional: #C96A3D

## Mapa de Reservas

- Header geral e filtros: gradiente Mar (#0F3057 para #00587A)
- Blocos de reserva ativos: base clara (#F5E9DD ou #E8D8C3) com borda #D4BFAA
- Estados principais:
  - Confirmada: acento #00587A
  - Pré-check-in/hoje: acento #3FA7A3
  - Em atenção operacional: acento #C6A75E
  - Erro real/cancelamento: vermelho atual do sistema
- Tipografia:
  - Nome do hóspede em #0F3057
  - Metadados em #243342

## Botões e Headers

- Primário: fundo #00587A, texto branco
- Secundário: fundo #C6A75E, texto branco
- Suave/apoio: fundo #E8D8C3, texto #0F3057
- Header principal de módulo: gradiente #0F3057 -> #00587A, texto branco
- Evitar mistura de amarelo, azul vivo e verde saturado na mesma seção

## Adoção Gradual

- Fase 1: /service/rh
- Fase 2: /reception/reservations
- Fase 3: /reception/rooms
- Fase 4: dashboards transversais (financeiro, admin, relatórios)

## Implementação Técnica Atual

- Tokens e classes globais: app/static/css/alma-mar-areia-theme.css
- Import global do tema: app/templates/base.html
- Piloto aplicado: app/templates/service.html quando service.id == 'rh'

## Dark Mode

### Paleta Adaptada

- Fundo principal: #1E252C
- Fundo secundário: #162029
- Superfície de cards: #2A3540
- Borda suave: #445464
- Texto forte: #F5E9DD
- Texto regular: #E8D8C3
- Foco/acessibilidade: rgba(63, 167, 163, 0.45)

### Categorias no Dark

- Alma: #D98760
- Mar: #58BAC0
- Areia: #CBB39A

### Fundo, Cards, Headers e Botões

- Fundo de página: gradiente escuro com nuance Alma
- Cards: #2A3540 com borda #445464
- Header de módulo: gradiente #133B5F -> #0F3057
- Botão primário: #2F7A95 (hover #3FA7A3)
- Botão secundário: #8A6D34 (hover #C6A75E)
- Botão de apoio: #33414E (hover #445464)

### UX no Dark Mode

- Reduzir brilho de acentos em estados padrão
- Usar sombras discretas e não chapadas
- Garantir destaque de foco em navegação por teclado
- Preservar hierarquia visual com contraste de texto
- Evitar excesso de badges coloridos em uma mesma seção

### Pontos de Atenção

- Ícones claros sobre fundos escuros podem parecer maiores visualmente
- Texto muted não pode cair abaixo do contraste AA
- Gradientes escuros exigem teste em monitores de baixa qualidade
- Hover de botões não deve trocar para branco puro
- Vermelho somente para erro/cancelamento permanece obrigatório

### Teste Técnico Atual

- Ativação por parâmetro: ?theme=dark
- Classe no body: theme-dark
- Piloto de teste: /service/rh?theme=dark
