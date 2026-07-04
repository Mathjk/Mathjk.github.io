@echo off
setlocal EnableExtensions

if defined OVERLEAF_TUNNEL_CMD call :try_cmd "%OVERLEAF_TUNNEL_CMD%" && goto :eof
call :try_cmd "%~dp0..\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof
call :try_cmd "%~dp0..\overleaf\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof
call :try_cmd "%~dp0..\..\overleaf\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof
call :try_cmd "%USERPROFILE%\overleaf\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof
call :try_cmd "E:\py_code\dist\myweb\myweb_windows11_test\overleaf\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof
call :try_cmd "E:\py_code\dist\myweb\myweb_windows11_test\myweb\overleaf\windows-launcher\Start-Overleaf-Tunnel-Key.cmd" && goto :eof

echo Overleaf tunnel launcher was not found.
echo.
echo Set OVERLEAF_TUNNEL_CMD to the Windows path of Start-Overleaf-Tunnel-Key.cmd.
echo Example:
echo   setx OVERLEAF_TUNNEL_CMD "E:\path\to\Start-Overleaf-Tunnel-Key.cmd"
echo.
pause
exit /b 1

:try_cmd
set TUNNEL_CMD=%~1
if not exist "%TUNNEL_CMD%" exit /b 1

start "Overleaf Tunnel" "%TUNNEL_CMD%"
exit /b 0
