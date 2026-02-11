sub init()
    m.welcomeLabel = m.top.findNode("welcomeLabel")
    m.globalLabel = m.top.findNode("globalLabel")
    m.infoLabel = m.top.findNode("infoLabel")
    m.restaurantButton = m.top.findNode("restaurantButton")
    m.minibarButton = m.top.findNode("minibarButton")

    m.selectedMenu = "restaurant"
    
    ' Inicializa UI sem chamadas de rede
    if m.welcomeLabel <> invalid then
        m.welcomeLabel.text = "Carregando dados do menu..."
    end if
    
    if m.globalLabel <> invalid then
        m.globalLabel.text = "Aguardando conexão com servidor local 192.168.69.99..."
    end if
    
    updateButtonHighlight()

    ' Configura Timer para iniciar a busca de dados após 1 segundo
    ' Isso garante que a UI apareça antes de qualquer lógica pesada
    m.loadTimer = m.top.findNode("loadTimer")
    if m.loadTimer <> invalid then
        m.loadTimer.observeField("fire", "startDataFetch")
        m.loadTimer.control = "start"
    end if
end sub

sub startDataFetch()
    ' Cria a Task
    m.apiTask = CreateObject("roSGNode", "APITask")
    
    ' Verificação de segurança: se falhar ao criar a Task (ex: erro no XML), não crashar
    if m.apiTask = invalid then
        if m.globalLabel <> invalid then
            m.globalLabel.text = "Erro interno: Não foi possível criar APITask."
        end if
        return
    end if

    m.apiTask.url = "http://192.168.69.99:5001/api/roku/menu-items"
    m.apiTask.observeField("response", "onMenuDataReceived")
    m.apiTask.control = "RUN"
    
    if m.welcomeLabel <> invalid then
        m.welcomeLabel.text = "Conectando..."
    end if
    
    if m.globalLabel <> invalid then
        m.globalLabel.text = "Aguardando resposta do servidor..."
    end if
end sub

sub onMenuDataReceived()
    print "DEBUG: onMenuDataReceived called"
    response = m.apiTask.response
    
    if response = invalid then
        print "DEBUG: Response is invalid"
        return
    end if
    
    ' Se for mensagem de debug (vinda de versoes anteriores ou atuais), ignora ou exibe
    if Left(response, 5) = "Debug" then
        return
    end if
    
    if Left(response, 7) = "Status:" then
        if m.welcomeLabel <> invalid then m.welcomeLabel.text = response
        return
    end if

    if response = "" then
        if m.globalLabel <> invalid then m.globalLabel.text = "Erro: Resposta vazia"
        return
    end if

    if Left(response, 5) = "Error" then
        if m.globalLabel <> invalid then m.globalLabel.text = response
        if m.welcomeLabel <> invalid then m.welcomeLabel.text = "Erro de Conexão"
        return
    end if

    if m.welcomeLabel <> invalid then
        m.welcomeLabel.text = "Resposta recebida! Processando..."
    end if

    ' Tenta parsear o JSON
    json = ParseJson(response)
    
    if json = invalid then
        if m.globalLabel <> invalid then
            m.globalLabel.text = "Erro: JSON inválido. Conteúdo recebido (primeiros 100 chars): " + Left(response, 100)
        end if
        return
    end if
    
    if m.welcomeLabel <> invalid then
        m.welcomeLabel.text = "Sucesso! Carregando menu..."
    end if

    ' Armazena o JSON para uso na renderização
    m.menuData = json
    
    ' Renderiza o menu atual
    renderCurrentMenu()
end sub

sub renderCurrentMenu()
    if m.menuData = invalid then return

    text = ""
    maxLines = 12 ' Ajustado para caber na tela
    lineCount = 0

    if m.selectedMenu = "minibar" then
        items = m.menuData["Frigobar"]
        if items <> invalid then
            for each item in items
                line = item.name + " - R$ " + Str(item.price).Trim()
                if text = "" then
                    text = line
                else
                    text = text + chr(10) + line
                end if
                lineCount = lineCount + 1
                if lineCount >= maxLines then
                    text = text + chr(10) + "... mais itens."
                    exit for
                end if
            end for
        else
            text = "Nenhum item no frigobar."
        end if
    else ' restaurant
        keys = m.menuData.GetKeyList()
        for each k in keys
            if k <> "Frigobar" then
                items = m.menuData[k]
                if items <> invalid and items.Count() > 0 then
                    header = UCase(k)
                    if text = "" then
                        text = header
                    else
                        text = text + chr(10) + chr(10) + header
                    end if
                    lineCount = lineCount + 1
                    
                    for each item in items
                        line = "  " + item.name + " - R$ " + Str(item.price).Trim()
                        text = text + chr(10) + line
                        lineCount = lineCount + 1
                        if lineCount >= maxLines then
                            exit for
                        end if
                    end for
                    
                    if lineCount >= maxLines then
                        text = text + chr(10) + "... mais itens."
                        exit for
                    end if
                end if
            end if
        end for
    end if
    
    if m.globalLabel <> invalid then
        m.globalLabel.text = text
    end if
end sub

sub updateButtonHighlight()
    if m.restaurantButton <> invalid and m.minibarButton <> invalid then
        if m.selectedMenu = "restaurant" then
            m.restaurantButton.color = &hFFFFFFFF
            m.minibarButton.color = &hAAAAAAFF
        else
            m.restaurantButton.color = &hAAAAAAFF
            m.minibarButton.color = &hFFFFFFFF
        end if
    end if
    
    ' Re-renderiza o menu se já tivermos dados
    renderCurrentMenu()
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false
    
    if key = "left" or key = "right" then
        if m.selectedMenu = "restaurant" then
            m.selectedMenu = "minibar"
        else
            m.selectedMenu = "restaurant"
        end if
        updateButtonHighlight()
        return true
    end if
    
    return false
end function
