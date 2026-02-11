# Guia de Integração Roku TV - Hotel System

Este guia descreve como utilizar o portal de desenvolvedor da Roku para criar um "Canal Privado" (Aplicativo) para o hotel, permitindo exibir publicidades e mensagens de boas-vindas sincronizadas com o nosso sistema.

## 1. Visão Geral

O objetivo é ter um aplicativo instalado em todas as TVs Roku do hotel que:
1.  Inicie automaticamente (ou seja facilmente acessível).
2.9.  Consulte nosso servidor (`http://192.168.69.99:5000/api/roku/tvs`) para saber o que exibir.
10. Exiba uma tela de "Boas-vindas" personalizada para o quarto/hóspede.
4.  Exiba imagens de publicidade (promoções do restaurante, passeios, etc.).

## 2. O Papel do Roku Developer Portal

O site `https://developer.roku.com/pt-br/develop` é onde você irá:
1.  **Criar uma Conta de Desenvolvedor**: Necessário para criar canais.
2.  **Gerenciar Dispositivos**: Habilitar o "Developer Mode" em uma TV física para testes.
3.  **Criar um Canal (App)**:
    *   Usaremos o **SDK (BrightScript)** para criar um canal customizado.
    *   Você pode criar um "Canal Beta" ou "Canal Privado" (não listado na loja pública) para instalar nas TVs do hotel usando um código de acesso.

## 3. Arquitetura da Solução

### Backend (Já implementado no Flask)
*   **Gerenciamento de TVs**: Cadastro de TVs por IP e Localização (Quarto).
*   **API (`/api/roku/tvs`)**: Fornece dados em formato JSON para as TVs.
    *   Exemplo de resposta:
        ```json
        {
          "tvs": [
            {
              "ip": "192.168.69.101",
              "message": "Bem-vindo, Sr. Silva!",
              "ads": ["http://.../img1.jpg", "http://.../img2.jpg"]
            }
          ]
        }
        ```

### Frontend (App Roku)
O aplicativo Roku será desenvolvido usando **BrightScript** e **SceneGraph** (XML).
42. Ele funcionará assim:
43. **Ao abrir**: Identifica seu próprio IP ou ID.
44. **Request**: Faz uma chamada HTTP GET para `http://192.168.69.99:5000/api/roku/tvs`.
45. **Filtragem**: Encontra sua configuração baseada no IP/ID.
4.  **Exibição**:
    *   Se houver `message`, mostra na tela principal.
    *   Se houver `ads`, inicia um slideshow.

## 4. Próximos Passos (Desenvolvimento do Canal Roku)

1.  **Setup do Ambiente**:
    *   Habilitar "Developer Mode" na sua TV Roku (Home 3x, Up 2x, Right, Left, Right, Left, Right).
    *   Acessar o IP da TV no navegador para fazer upload do zip do app.

2.  **Código do Canal (Exemplo Básico)**:
    *   Criar arquivo `manifest` (metadados do app).
    *   Criar `source/main.brs` (lógica de inicialização).
    *   Criar `components/HomeScene.xml` (Interface visual).

3.  **Publicação**:
    *   Empacotar o app.
    *   Subir no Portal Roku como "Canal Privado".
    *   Instalar em todas as TVs usando o Código do Canal.

## 5. Exemplo de Integração (ECP - External Control Protocol)

Além do app, podemos controlar as TVs remotamente (ligar, mudar canal, aumentar volume) enviando comandos HTTP diretamente para o IP da TV, desde que a TV esteja na mesma rede.

70. *   Exemplo: `POST http://192.168.69.101:8060/keypress/Home` (Vai para a tela inicial).

---
**Nota**: Para avançar, precisaremos desenvolver os arquivos do canal Roku (`.zip`).
