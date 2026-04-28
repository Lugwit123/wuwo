@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  wuwo One-Click Installer (Bootstrap)
REM
REM  Usage A: install.bat placed OUTSIDE wuwo dir
REM           -> git clone wuwo into a "wuwo" folder next to this bat
REM  Usage B: install.bat placed INSIDE wuwo dir (already cloned)
REM           -> use current directory as wuwo dir directly
REM
REM  Steps:
REM    1. Locate / clone wuwo repo
REM    2. Download Python 3.12.8 standard installer (if needed)
REM    3. Silently install Python to wuwo\py_312\
REM    4. Hand over to wuwo\install.py for all further steps
REM
REM  No system Python required - fully self-contained!
REM ============================================================

set "INSTALLER_DIR=%~dp0"
set "WUWO_REPO=https://github.com/Lugwit123/wuwo.git"

REM ------ Detect if install.bat is already inside wuwo ------
REM install.py next to install.bat  =>  already inside wuwo
if exist "%INSTALLER_DIR%install.py" (
    set "WUWO_DIR=%INSTALLER_DIR:~0,-1%"
    echo [INFO] install.bat is inside wuwo, using: !WUWO_DIR!
) else (
    set "WUWO_DIR=%INSTALLER_DIR%wuwo"
)

set "PYTHON_DIR=%WUWO_DIR%\py_312"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

set "FULL_VER=3.12.8"
set "INSTALLER_NAME=python-%FULL_VER%-amd64.exe"
set "INSTALLER_URL=https://www.python.org/ftp/python/%FULL_VER%/%INSTALLER_NAME%"
set "TEMP_INSTALLER=%WUWO_DIR%\%INSTALLER_NAME%"
set "MIN_SIZE=20000000"

echo ============================================================
echo   wuwo Bootstrap Installer
echo   wuwo   : %WUWO_DIR%
echo   Python : %PYTHON_DIR%
echo ============================================================
echo.

REM ------ Step 0: Check git ------
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] git is not installed or not in PATH.
    echo         Please install Git from https://git-scm.com/ and retry.
    goto :fail
)

REM ------ Step 1: Clone / pull wuwo repo ------
if exist "%WUWO_DIR%\.git" (
    echo [INFO] wuwo already cloned. Pulling latest changes...
    git -C "%WUWO_DIR%" pull --ff-only
    if !errorlevel! neq 0 (
        echo [WARN] git pull failed. Proceeding with existing files.
    )
    echo.
) else if exist "%WUWO_DIR%" (
    echo [INFO] wuwo directory exists ^(not a git repo^). Proceeding with existing files.
    echo.
) else (
    echo [1/3] Cloning wuwo repository...
    echo       %WUWO_REPO%
    git clone "%WUWO_REPO%" "%WUWO_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to clone wuwo! Check network / GitHub access.
        goto :fail
    )
    echo [OK] Cloned to: %WUWO_DIR%
    echo.
)

REM ------ Step 2-3: Bootstrap Python (if py_312 not ready) ------
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" --version >nul 2>&1
    if !errorlevel! equ 0 (
        echo [INFO] py_312 Python already installed, skipping bootstrap.
        echo.
        goto :run_install_py
    )
    echo [WARN] python.exe exists but not working, re-installing...
    rmdir /s /q "%PYTHON_DIR%" 2>nul
)

echo [2/3] Downloading Python %FULL_VER% standard installer...
echo.

REM -- 2a: Download installer --
if exist "%TEMP_INSTALLER%" (
    set "SZ=0"
    for %%F in ("%TEMP_INSTALLER%") do set "SZ=%%~zF"
    if !SZ! LSS %MIN_SIZE% (
        echo [INFO] Existing installer too small ^(!SZ! bytes^), re-downloading...
        del /f /q "%TEMP_INSTALLER%"
    ) else (
        echo [INFO] Reusing existing installer ^(!SZ! bytes^).
        goto :install_python
    )
)

echo       Downloading from: %INSTALLER_URL%
curl --ssl-no-revoke -L -o "%TEMP_INSTALLER%" "%INSTALLER_URL%" --progress-bar
if !errorlevel! neq 0 (
    echo [ERROR] Download failed! Check network connection.
    if exist "%TEMP_INSTALLER%" del /f /q "%TEMP_INSTALLER%"
    goto :fail
)

REM -- Validate size --
set "SZ=0"
for %%F in ("%TEMP_INSTALLER%") do set "SZ=%%~zF"
if !SZ! LSS %MIN_SIZE% (
    echo [ERROR] Installer too small ^(!SZ! bytes^). Possibly corrupted.
    del /f /q "%TEMP_INSTALLER%"
    goto :fail
)
echo [OK] Downloaded: !SZ! bytes.
echo.

:install_python
REM -- 2b: Silent install --
echo [3/3 bootstrap] Silently installing Python %FULL_VER% to py_312...
echo               ^(this may take 1-2 minutes^)
if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%"
"%TEMP_INSTALLER%" /quiet TargetDir="%PYTHON_DIR%" Include_pip=1 Include_tcltk=1 InstallAllUsers=0 PrependPath=0 Shortcuts=0
if !errorlevel! neq 0 (
    echo [ERROR] Python installation failed! exit code: !errorlevel!
    goto :fail
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe not found after installation!
    goto :fail
)

REM -- Cleanup installer --
del /f /q "%TEMP_INSTALLER%" 2>nul
echo [OK] Python %FULL_VER% installed to: %PYTHON_DIR%
echo.

:run_install_py
REM ------ Step 3: Run install.py ------
if not exist "%WUWO_DIR%\install.py" (
    echo [ERROR] install.py not found: %WUWO_DIR%\install.py
    echo         Repository may be incomplete. Delete "%WUWO_DIR%" and retry.
    goto :fail
)

echo [3/3] Running wuwo\install.py ...
echo.
"%PYTHON_EXE%" "%WUWO_DIR%\install.py" --wuwo-dir "%WUWO_DIR%"
if !errorlevel! neq 0 (
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
