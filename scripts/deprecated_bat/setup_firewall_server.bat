@echo off
title Configurar Firewall para Almareia Mirapraia
echo -------------------------------------------------------
echo  LIBERANDO PORTA 5000 NO FIREWALL DO WINDOWS - ALMAREIA MIRAPRAIA
echo -------------------------------------------------------
echo.
echo Este script precisa ser executado como ADMINISTRADOR.
echo.
pause

netsh advfirewall firewall add rule name="AlmareiaMirapraia_Server" dir=in action=allow protocol=TCP localport=5000
netsh advfirewall firewall add rule name="AlmareiaMirapraia_Server" dir=out action=allow protocol=TCP localport=5000

echo.
echo -------------------------------------------------------
echo  Regras adicionadas com sucesso!
echo  Agora outros computadores podem acessar este PC.
echo -------------------------------------------------------
pause
