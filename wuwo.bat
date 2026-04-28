@echo off

REM ============================================================================
REM Simple Python Script Runner
REM Purpose: Run Python scripts with virtual environment
REM ============================================================================

REM Get script directory
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%py_312"
set "PYTHON_EXE=%VENV_DIR%\python.exe"
set "REZ_EXE=%VENV_DIR%\Scripts\rez.exe"
set "LugwitToolDir=d:\TD_Depot\Software\Lugwit_syncPlug\lugwit_insapp\trayapp"
set "WUWO_CONFIG_DIR=%SCRIPT_DIR%config"


REM Package paths
REM Source repo: <this>/../rez-package-source/<pkg_name>/<version>/package.py (dev, no install needed)
set "SOURCE_PACKAGES=%SCRIPT_DIR%..\rez-package-source"
set "LOCAL_PACKAGES=%SCRIPT_DIR%packages"
set "BUILD_PACKAGES=d:\TD_Depot\Software\Lugwit_syncPlug\lugwit_insapp\trayapp\rez-package-build"
set "RELEASE_PACKAGES=d:\TD_Depot\Software\Lugwit_syncPlug\lugwit_insapp\trayapp\rez-package-release"

REM Set REZ_PACKAGES_PATH
REM Priority: source -> local -> build -> release (source wins for same package during dev)
set "REZ_PACKAGES_PATH=%SOURCE_PACKAGES%;%LOCAL_PACKAGES%;%BUILD_PACKAGES%;%RELEASE_PACKAGES%"

REM Set Rez configuration file
set "REZ_CONFIG_FILE=%SCRIPT_DIR%rezconfig.py"

REM ====== Auto-fetch missing packages from GitHub ======
echo [wuwo] Checking rez packages...
"%PYTHON_EXE%" "%SCRIPT_DIR%auto_fetch_packages.py"
if errorlevel 1 (
    echo [wuwo] WARNING: Some packages could not be downloaded. Continuing anyway...
)

REM ============================================================================
REM Shortcuts
REM ============================================================================
if /i "%~1"=="chatroom_backend" goto :start_chatroom_backend
if /i "%~1"=="chatroom-backend" goto :start_chatroom_backend

REM Check if first argument is 'rez' and second is a rez command (env, build, etc.)
if /i "%~1"=="rez" goto :run_rez_prefixed

REM Run rez_comanf_reconfig.py with all arguments
%PYTHON_EXE% %SCRIPT_DIR%rez_comanf_reconfig.py %*

REM If no arguments provided, start interactive shell
if "%~1"=="" (
    cmd /k
)
goto :eof

:run_rez_prefixed
set "_REST=%*"
REM Drop first token ("rez")
call set "_REST=%%_REST:* =%%"
REM Compatibility: handle accidental "rez rez env ..."
for /f "tokens=1*" %%A in ("%_REST%") do (
    if /i "%%~A"=="rez" set "_REST=%%~B"
)
REM Keep build routed to custom script
for /f "tokens=1*" %%A in ("%_REST%") do (
    if /i "%%~A"=="build" (
        %PYTHON_EXE% %SCRIPT_DIR%rez_comanf_reconfig.py %%B
        goto :eof
    )
)
REM Run native rez command with full forwarded arguments
call "%REZ_EXE%" %_REST%
goto :eof

:start_chatroom_backend
REM Usage:
REM   wuwo.bat chatroom_backend            -> start ChatRoom backend only
REM   wuwo.bat chatroom_backend notepad    -> start ChatRoom backend and mount l_notepad
setlocal
set "CHATROOM_ENABLE_NOTEPAD=0"
if /i "%~2"=="notepad" set "CHATROOM_ENABLE_NOTEPAD=1"

REM Start backend via Rez env (port is controlled by ChatRoom backend code/bat, default 1026)
call "%REZ_EXE%" env ChatRoom -- cmd /c "%LugwitToolDir%\rez-package-source\ChatRoom\999.0\src\ChatRoom\run_backend_server.bat"
endlocal
goto :eof


