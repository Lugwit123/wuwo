@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  wuwo One-Click Installer (Bootstrap)
REM
REM  Usage: place this bat anywhere and double-click.
REM  1. git clone wuwo repo into a "wuwo" folder next to this bat
REM  2. Hand over to wuwo\install.py for all further steps
REM ============================================================

set "INSTALLER_DIR=%~dp0"
set "WUWO_REPO=https://github.com/Lugwit123/wuwo.git"
set "WUWO_DIR=%INSTALLER_DIR%wuwo"

echo ============================================================
echo   wuwo Bootstrap Installer
echo   wuwo target: %WUWO_DIR%
echo ============================================================
echo.

REM ------ Step 0: Check git ------
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] git is not installed or not in PATH.
    echo         Please install Git from https://git-scm.com/ and retry.
    goto :fail
)

REM ------ Step 1: Clone wuwo repo (idempotent) ------
if exist "%WUWO_DIR%\.git" (
    echo [INFO] wuwo already cloned. Pulling latest changes...
    git -C "%WUWO_DIR%" pull --ff-only
    if %errorlevel% neq 0 (
        echo [WARN] git pull failed. Proceeding with existing files.
    )
    echo.
) else if exist "%WUWO_DIR%" (
    echo [INFO] Directory exists but is not a git repo. Proceeding with existing files.
    echo        %WUWO_DIR%
    echo.
) else (
    echo [1/2] Cloning wuwo repository...
    echo       %WUWO_REPO%
    git clone "%WUWO_REPO%" "%WUWO_DIR%"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to clone wuwo! Check network and GitHub access.
        goto :fail
    )
    echo [OK] Cloned to: %WUWO_DIR%
    echo.
)

REM ------ Step 2: Find Python and run install.py ------
REM Try wuwo's own Python first, fall back to system Python
set "PYTHON_EXE=%WUWO_DIR%\py_312\python.exe"
if not exist "%PYTHON_EXE%" (
    REM py_312 not yet installed, use system Python to bootstrap
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        where python3 >nul 2>&1
        if %errorlevel% equ 0 (
            set "PYTHON_EXE=python3"
        ) else (
            echo [ERROR] No Python interpreter found.
            echo         Please install Python 3.8+ from https://www.python.org/ and retry.
            goto :fail
        )
    )
)

if not exist "%WUWO_DIR%\install.py" (
    echo [ERROR] install.py not found in %WUWO_DIR%
    echo         The repository may be incomplete. Please delete "%WUWO_DIR%" and retry.
    goto :fail
)

echo [2/2] Running wuwo\install.py ...
echo.
"%PYTHON_EXE%" "%WUWO_DIR%\install.py" --wuwo-dir "%WUWO_DIR%"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] install.py exited with errors. See above for details.
    goto :fail
)

goto :end

:fail
echo.
echo ============================================================
echo   [FATAL] Bootstrap failed. Please check errors above.
echo ============================================================
echo.
pause
exit /b 1

:end
endlocal
pause
