sub main()
    ' Cria a tela SceneGraph
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.SetMessagePort(port)

    ' Cria a cena principal
    scene = screen.CreateScene("MainScene")
    screen.Show()

    ' Loop de eventos
    while true
        msg = wait(0, port)
        if type(msg) = "roSGScreenEvent" then
            if msg.isScreenClosed() then
                return
            end if
        end if
    end while
end sub
