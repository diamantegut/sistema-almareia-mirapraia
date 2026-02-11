sub init()
    m.top.functionName = "executeRequest"
end sub

sub executeRequest()
    ' Informa que iniciou
    m.top.response = "Status: Iniciando Request..."

    url = m.top.url
    
    if url <> "" then
        xfer = CreateObject("roUrlTransfer")
        if xfer = invalid then
            m.top.response = "Error: CreateObject roUrlTransfer failed"
            return
        end if
        
        xfer.SetUrl(url)
        xfer.RetainBodyOnError(true)
        xfer.EnablePeerVerification(false)
        xfer.EnableHostVerification(false)
        
        port = CreateObject("roMessagePort")
        xfer.SetPort(port)
        
        ' Inicia a requisição assíncrona
        if xfer.AsyncGetToString() then
            m.top.response = "Status: Aguardando Servidor..."
            
            ' Loop de espera com timeout manual
            timeout_ms = 10000 ' 10 segundos
            msg = wait(timeout_ms, port)
            
            if type(msg) = "roUrlEvent" then
                code = msg.GetResponseCode()
                if code = 200 then
                    m.top.response = msg.GetString()
                else
                    m.top.response = "Error: " + Str(code) + " - " + msg.GetFailureReason()
                end if
            else
                if msg = invalid then
                    m.top.response = "Error: Timeout (10s) connecting to " + url
                else
                    m.top.response = "Error: Unknown event type: " + type(msg)
                end if
                xfer.AsyncCancel()
            end if
        else
            m.top.response = "Error: Failed to create Async Request"
        end if
    else
        m.top.response = "Error: Empty URL"
    end if
end sub
