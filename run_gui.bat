@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

python -m x11_management gui
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERRO] Falha ao iniciar a interface grafica do X11 Management IMS.
    pause
)
