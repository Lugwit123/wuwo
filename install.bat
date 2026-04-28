@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  wuwo One-Click Installer (Bootstrap)
REM
REM  Usage: place this bat anywhere and double-click.
REM  Steps:
REM    1. git clone wuwo repo  (wuwo folder next to this bat)
REM    2. Download Python 3.12.8 embeddable zip (if needed)
REM    3. Extract to wuwo\py_312\
REM    4. Hand over to wuwo\install.py for all further steps
REM
REM  No system Python required - fully self-contained!
REM ============================================================

set "INSTALLER_DIR=%~dp0"
set "WUWO_REPO=https://github.com/Lugwit123/wuwo.git"
set "WUWO_DIR=%INSTALLER_DIR%wuwo"
set "PYTHON_DIR=%WUWO_DIR%\py_312"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

set "FULL_VER=3.12.8"
set "PTH_PREFIX=python312"
set "ZIP_NAME=python-%FULL_VER%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%FULL_VER%/%ZIP_NAME%"
set "TEMP_ZIP=%WUWO_DIR%\%ZIP_NAME%"
set "MIN_SIZE=5000000"

echo ============================================================
echo   wuwo Bootstrap Installer
echo   wuwo target : %WUWO_DIR%
echo   Python target: %PYTHON_DIR%
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

REM ------ Step 2: Bootstrap Python (if py_312 not ready) ------
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" --version >nul 2>&1
    if !errorlevel! equ 0 (
        echo [INFO] py_312 Python already installed, skipping bootstrap.
        echo.
        goto :run_install_py
    )
    echo [WARN] python.exe exists but not working, re-extracting...
    rmdir /s /q "%PYTHON_DIR%" 2>nul
)

echo [2/3] Bootstrapping Python %FULL_VER% embeddable...
echo.

REM -- 2a: Download zip --
if exist "%TEMP_ZIP%" (
    set "SZ=0"
    for %%F in ("%TEMP_ZIP%") do set "SZ=%%~zF"
    if !SZ! LSS %MIN_SIZE% (
        echo [INFO] Existing zip too small ^(!SZ! bytes^), re-downloading...
        del /f /q "%TEMP_ZIP%"
    ) else (
        echo [INFO] Reusing existing zip ^(!SZ! bytes^).
        goto :extract_python
    )
)

echo       Downloading from: %ZIP_URL%
curl --ssl-no-revoke -L -o "%TEMP_ZIP%" "%ZIP_URL%" --progress-bar
if !errorlevel! neq 0 (
    echo [ERROR] Download failed! Check network connection.
    if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
    goto :fail
)

REM -- Validate size --
set "SZ=0"
for %%F in ("%TEMP_ZIP%") do set "SZ=%%~zF"
if !SZ! LSS %MIN_SIZE% (
    echo [ERROR] Downloaded zip too small ^(!SZ! bytes^). Possibly corrupted.
    del /f /q "%TEMP_ZIP%"
    goto :fail
)
echo [OK] Downloaded: !SZ! bytes.
echo.

:extract_python
REM -- 2b: Extract --
echo       Extracting to py_312...
if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%"
mkdir "%PYTHON_DIR%"
powershell -NoProfile -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
if !errorlevel! neq 0 (
    echo [ERROR] Extraction failed!
    goto :fail
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe not found after extraction!
    goto :fail
)

REM -- 2c: Enable site-packages in ._pth --
set "PTH_FILE=%PYTHON_DIR%\%PTH_PREFIX%._pth"
if exist "%PTH_FILE%" (
    powershell -NoProfile -Command "(Get-Content '%PTH_FILE%') -replace '^#\s*import site','import site' | Set-Content '%PTH_FILE%'"
    echo [OK] Enabled site-packages in %PTH_PREFIX%._pth.
) else (
    echo [WARN] ._pth not found, creating default...
    (
        echo %PTH_PREFIX%.zip
        echo .
        echo import site
    ) > "%PTH_FILE%"
)

REM -- Cleanup zip --
del /f /q "%TEMP_ZIP%" 2>nul
echo [OK] Python %FULL_VER% bootstrap complete.
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
