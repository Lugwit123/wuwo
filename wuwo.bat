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
set "REZ_SCRIPT=%VENV_DIR%\Scripts\rez-script.py"
set "LugwitToolDir=%SCRIPT_DIR%..\.."
set "WUWO_CONFIG_DIR=%SCRIPT_DIR%config"


REM Package paths
REM Source repo: <this>/../rez-package-source/<pkg_name>/<version>/package.py (dev, no install needed)
set "SOURCE_PACKAGES=%SCRIPT_DIR%..\rez-package-source"
set "LOCAL_PACKAGES=%SCRIPT_DIR%packages"
set "THIRD_PARTY_PACKAGES=%SCRIPT_DIR%..\rez-package-3rd"
set "BUILD_PACKAGES=%SCRIPT_DIR%..\rez-package-build"
set "RELEASE_PACKAGES=%SCRIPT_DIR%..\rez-package-release"

REM Set REZ_PACKAGES_PATH
REM Priority: source -> local -> 3rd -> build -> release (source wins for same package during dev)
set "REZ_PACKAGES_PATH=%SOURCE_PACKAGES%;%LOCAL_PACKAGES%;%THIRD_PARTY_PACKAGES%;%BUILD_PACKAGES%;%RELEASE_PACKAGES%"

REM Set Rez configuration file
set "REZ_CONFIG_FILE=%SCRIPT_DIR%rezconfig.py"

REM Rez 包 / pip / NuGet python：仅在 ``rez env ...`` 时由 auto_fetch_packages.py --for-rez-env 按需拉取（无启动全量扫描）

REM ============================================================================
REM Shortcuts
REM ============================================================================
if /i "%~1"=="chatroom_backend" goto :start_chatroom_backend
if /i "%~1"=="chatroom-backend" goto :start_chatroom_backend

REM Check if first argument is 'rez' and second is a rez command (env, build, etc.)
if /i "%~1"=="rez" goto :run_rez_prefixed

REM If no arguments provided, show help
if "%~1"=="" (
    goto :show_help
)

REM Run rez_comanf_reconfig.py with all arguments
%PYTHON_EXE% %SCRIPT_DIR%rez_comanf_reconfig.py %*
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
if exist "%REZ_EXE%" goto :run_rez_exe
if exist "%REZ_SCRIPT%" goto :run_rez_script
echo [wuwo] ERROR: rez executable not found.
echo [wuwo] Try reinstalling dependencies: "%PYTHON_EXE%" -m pip install rez
exit /b 1

:run_rez_exe
REM rez env：先按需克隆 GitHub 包并把 pip/nuget 依赖装进 rez-package-3rd；含 .update 时仅强制同步 GitHub 包（fetch+reset）
if /i "%_REST:~0,4%"=="env " (
    "%PYTHON_EXE%" "%SCRIPT_DIR%auto_fetch_packages.py" --for-rez-env "rez %_REST%"
    if errorlevel 1 exit /b %ERRORLEVEL%
)
"%REZ_EXE%" %_REST%
goto :eof

:run_rez_script
if /i "%_REST:~0,4%"=="env " (
    "%PYTHON_EXE%" "%SCRIPT_DIR%auto_fetch_packages.py" --for-rez-env "rez %_REST%"
    if errorlevel 1 exit /b %ERRORLEVEL%
)
"%PYTHON_EXE%" "%REZ_SCRIPT%" %_REST%
goto :eof

:start_chatroom_backend
REM Usage:
REM   wuwo.bat chatroom_backend            -> start ChatRoom backend only
REM   wuwo.bat chatroom_backend notepad    -> start ChatRoom backend and mount l_notepad
setlocal
set "CHATROOM_ENABLE_NOTEPAD=0"
if /i "%~2"=="notepad" set "CHATROOM_ENABLE_NOTEPAD=1"

REM Start backend via Rez env (port is controlled by ChatRoom backend code/bat, default 1026)
if exist "%REZ_EXE%" (
    "%REZ_EXE%" env ChatRoom -- cmd /c "%LugwitToolDir%\rez-package-source\ChatRoom\999.0\src\ChatRoom\run_backend_server.bat"
) else if exist "%REZ_SCRIPT%" (
    "%PYTHON_EXE%" "%REZ_SCRIPT%" env ChatRoom -- cmd /c "%LugwitToolDir%\rez-package-source\ChatRoom\999.0\src\ChatRoom\run_backend_server.bat"
) else (
    echo [wuwo] ERROR: rez executable not found.
    echo [wuwo] Try reinstalling dependencies: "%PYTHON_EXE%" -m pip install rez
    exit /b 1
)
endlocal
goto :eof

:show_help
echo.
echo wuwo usage:
echo   wuwo.bat rez env ^<package^> [-- command]
echo   wuwo.bat rez build [args]
echo   wuwo.bat chatroom_backend [notepad]
echo   wuwor ^<package^> [-- command]
echo.
echo examples:
echo   wuwo.bat rez env l_tray -- python -V
echo   wuwo.bat rez env l_WChat
echo   wuwo.bat chatroom_backend
echo   wuwor l_WChat
echo.
echo notes:
echo   - rez env will fetch dependencies on demand first
echo   - package names starting with l_ are treated as git packages first
echo.
goto :eof


