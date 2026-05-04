@echo off
REM Start frp CLIENT side (frpc): rez env l_frp + default frpc_client.yaml
setlocal
set "WUWO_DIR=%~dp0"
set "CFG=%WUWO_DIR%..\rez-package-source\l_frp\999.0\frpc_client.yaml"

if not exist "%WUWO_DIR%wuwo.bat" (
    echo [start_frp_c] ERROR: wuwo.bat not found: "%WUWO_DIR%wuwo.bat"
    exit /b 1
)
if not exist "%CFG%" (
    echo [start_frp_c] ERROR: config not found: "%CFG%"
    echo [start_frp_c] TIP: create "%CFG%" then rerun.
    exit /b 1
)

call "%WUWO_DIR%wuwo.bat" rez env l_frp -- frpc -c "%CFG%"
exit /b %ERRORLEVEL%
