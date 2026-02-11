# Como instalar o App na TV Roku (Sideload)

1. **Habilitar Modo Desenvolvedor na TV**:
   - No controle remoto, pressione: Casa (3x) + Cima (2x) + Direita + Esquerda + Direita + Esquerda + Direita.
   - Siga as instruções na tela, anote o IP da TV e defina uma senha (ex: `rokudev`).

2. **Empacotar o App**:
   - Selecione todos os arquivos e pastas dentro de `roku_app` (manifest, source, components, images).
   - Clique com botão direito -> Enviar para -> Pasta compactada (ZIP).
   - Nomeie como `app.zip`.

3. **Instalar**:
   - Abra o navegador no seu PC e acesse o IP da TV (ex: `http://192.168.69.80`).
   - Logue com usuário `rokudev` e a senha que você definiu.
   - Faça upload do `app.zip`.
   - Clique em "Install" (ou "Replace").

## Configuração Importante
20. O arquivo `components/MainScene.brs` aponta para o servidor onde o Python está rodando.
21. Atualmente está configurado para: `http://192.168.69.99:5001/api/roku/tvs`
22.
23. **Verifique se a TV consegue acessar esse IP!**
Como a TV está em `192.168.69.80`, se as redes forem diferentes e não houver roteamento, não vai funcionar.
Se o seu PC tiver um IP na faixa `192.168.69.x`, edite o arquivo `components/MainScene.brs` e coloque esse IP na variável `serverUrl`.
