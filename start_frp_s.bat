@echo off
REM Start frp SERVER side (frps): rez env l_frp + default frps_backend.yaml
setlocal
set "WUWO_DIR=%~dp0"
set "CFG=%WUWO_DIR%..\rez-package-source\l_frp\999.0\frps_backend.yaml"

if not exist "%WUWO_DIR%wuwo.bat" (
    echo [start_frp_s] ERROR: wuwo.bat not found: "%WUWO_DIR%wuwo.bat"
    exit /b 1
)
if not exist "%CFG%" (
    echo [start_frp_s] ERROR: config not found: "%CFG%"
    exit /b 1
)

call "%WUWO_DIR%wuwo.bat" rez env l_frp -- frps -c "%CFG%"
exit /b %ERRORLEVEL%
