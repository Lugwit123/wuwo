@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "WUWO_BAT=%SCRIPT_DIR%wuwo.bat"

if "%~1"=="" (
    echo wuwor usage:
    echo   wuwor ^<package^> [-- command]
    echo.
    echo examples:
    echo   wuwor l_tray -- python -V
    echo   wuwor l_WChat
    exit /b 0
)

if not exist "%WUWO_BAT%" (
    echo [wuwor] ERROR: wuwo.bat not found: "%WUWO_BAT%"
    exit /b 1
)

call "%WUWO_BAT%" rez env %*
exit /b %ERRORLEVEL%
