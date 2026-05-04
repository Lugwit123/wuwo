@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion



REM ============================================================
REM  wuwo One-Click Installer (Bootstrap)
REM
REM  Usage A: install.bat not in a folder literally named "wuwo" (case-sensitive)
REM           -> git clone wuwo into a "wuwo" folder next to this bat
REM  Usage B: install.bat inside a folder named exactly "wuwo" (already cloned)
REM           -> use that directory as wuwo root (no sibling "wuwo" subfolder)
REM
REM  Steps:
REM    1. Locate / clone wuwo repo
REM    2. Download Python 3.12.10 via nuget (full green, no install needed)
REM       URL: https://www.nuget.org/api/v2/package/python/3.12.10
REM    3. Extract nupkg -> py_312\  (includes tkinter + pip)
REM    4. Hand over to wuwo\install.py for all further steps
REM
REM  No system Python required - fully self-contained!
REM  No system registration - fully portable/green!
REM ============================================================

set "INSTALLER_DIR=%~dp0"
set "WUWO_REPO=https://github.com/Lugwit123/wuwo.git"
set "WUWO_REPO_MIRROR1=https://ghproxy.com/https://github.com/Lugwit123/wuwo.git"
set "WUWO_REPO_MIRROR2=https://gitclone.com/github.com/Lugwit123/wuwo.git"

REM ------ Detect if install.bat is already inside wuwo ------
REM Only by folder name (case-sensitive): basename must be exactly "wuwo"
for %%I in ("%INSTALLER_DIR:~0,-1%") do set "INSTALLER_FOLDER=%%~nxI"
if "!INSTALLER_FOLDER!"=="wuwo" (
    set "WUWO_DIR=%INSTALLER_DIR:~0,-1%"
    echo [INFO] install.bat is under a folder named exactly wuwo, using: !WUWO_DIR!
) else (
    set "WUWO_DIR=%INSTALLER_DIR%wuwo"
)

set "PYTHON_DIR=%WUWO_DIR%\py_312"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

REM -- Python 3.12.10 via nuget (portable package, pip available; tkinter may be unavailable)
set "FULL_VER=3.12.10"
set "NUGET_URL=https://www.nuget.org/api/v2/package/python/%FULL_VER%"
set "NUPKG_FILE=%WUWO_DIR%\python.%FULL_VER%.zip"
set "NUPKG_EXTRACT=%WUWO_DIR%\.nupkg_tmp"
set "MIN_SIZE=10000000"

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
    git -C "%WUWO_DIR%" pull --ff-only --autostash
    if !errorlevel! neq 0 (
        echo [WARN] git pull --autostash failed. Forcing sync with remote ^(discards local changes to tracked files e.g. config.yaml, install.bat^)...
        git -C "%WUWO_DIR%" fetch origin
        if !errorlevel! neq 0 (
            echo [WARN] fetch origin failed, retrying mirrors...
            git -C "%WUWO_DIR%" fetch "%WUWO_REPO_MIRROR1%"
            if !errorlevel! neq 0 (
                git -C "%WUWO_DIR%" fetch "%WUWO_REPO_MIRROR2%"
            )
        )
        set "WUWO_UPSTREAM="
        for /f "delims=" %%U in ('git -C "%WUWO_DIR%" rev-parse --abbrev-ref --symbolic-full-name @{u} 2^>nul') do set "WUWO_UPSTREAM=%%U"
        if defined WUWO_UPSTREAM (
            git -C "%WUWO_DIR%" reset --hard "!WUWO_UPSTREAM!"
        ) else (
            for /f "delims=" %%B in ('git -C "%WUWO_DIR%" rev-parse --abbrev-ref HEAD 2^>nul') do (
                git -C "%WUWO_DIR%" reset --hard origin/%%B
            )
        )
        if !errorlevel! neq 0 (
            echo [ERROR] Forced git sync failed. Check remote / branch / network.
            goto :fail
        )
        echo [OK] wuwo repo reset to match remote.
    )
    echo.
    goto :after_repo_ready
) else if exist "%WUWO_DIR%" (
    if exist "%WUWO_DIR%\install.py" if exist "%WUWO_DIR%\wuwo.bat" (
        echo [INFO] wuwo directory exists ^(not a git repo^) and key files are present. Proceeding with existing files.
        echo.
        goto :after_repo_ready
    )
    echo [WARN] wuwo directory exists ^(not a git repo^) but key files are missing.
    echo [INFO] Attempting to bootstrap repository content from remote...
    set "BOOTSTRAP_CLONE_DIR=%TEMP%\wuwo_bootstrap_clone_%RANDOM%%RANDOM%"
    if exist "!BOOTSTRAP_CLONE_DIR!" rmdir /s /q "!BOOTSTRAP_CLONE_DIR!" 2>nul
    git clone "%WUWO_REPO%" "!BOOTSTRAP_CLONE_DIR!"
    if !errorlevel! neq 0 (
        echo [WARN] Primary clone failed, retrying mirror #1...
        git clone "%WUWO_REPO_MIRROR1%" "!BOOTSTRAP_CLONE_DIR!"
        if !errorlevel! neq 0 (
            echo [WARN] Mirror #1 failed, retrying mirror #2...
            git clone "%WUWO_REPO_MIRROR2%" "!BOOTSTRAP_CLONE_DIR!"
            if !errorlevel! neq 0 (
                echo [ERROR] Failed to clone wuwo on all mirrors! Check network / GitHub access.
                if exist "!BOOTSTRAP_CLONE_DIR!" rmdir /s /q "!BOOTSTRAP_CLONE_DIR!" 2>nul
                goto :fail
            )
        )
    )
    robocopy "!BOOTSTRAP_CLONE_DIR!" "%WUWO_DIR%" /E /NFL /NDL /NJH /NJS >nul
    set "RC=%ERRORLEVEL%"
    if !RC! GEQ 8 (
        echo [ERROR] Failed to copy repository files into existing wuwo directory.
        if exist "!BOOTSTRAP_CLONE_DIR!" rmdir /s /q "!BOOTSTRAP_CLONE_DIR!" 2>nul
        goto :fail
    )
    if exist "!BOOTSTRAP_CLONE_DIR!" rmdir /s /q "!BOOTSTRAP_CLONE_DIR!" 2>nul
    if not exist "%WUWO_DIR%\install.py" (
        echo [ERROR] install.py still missing after bootstrap clone.
        goto :fail
    )
    echo [OK] Repository files bootstrapped into: %WUWO_DIR%
    echo.
    goto :after_repo_ready
) else (
    echo [1/3] Cloning wuwo repository...
    echo       %WUWO_REPO%
    git clone "%WUWO_REPO%" "%WUWO_DIR%"
    if !errorlevel! neq 0 (
        echo [WARN] Primary clone failed, retrying mirror #1...
        git clone "%WUWO_REPO_MIRROR1%" "%WUWO_DIR%"
        if !errorlevel! neq 0 (
            echo [WARN] Mirror #1 failed, retrying mirror #2...
            git clone "%WUWO_REPO_MIRROR2%" "%WUWO_DIR%"
            if !errorlevel! neq 0 (
                echo [ERROR] Failed to clone wuwo on all mirrors! Check network / GitHub access.
                goto :fail
            )
        )
    )
    echo [OK] Cloned to: %WUWO_DIR%
    echo.
    goto :after_repo_ready
)

:after_repo_ready
REM ------ Step 2-3: Bootstrap Python (if py_312 not ready) ------
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

echo [2/3] Downloading Python %FULL_VER% (nuget portable package, tkinter not guaranteed)...
echo       URL: %NUGET_URL%
echo.

REM -- 2a: Download nupkg  --
if exist "%NUPKG_FILE%" (
    set "SZ=0"
    for %%F in ("%NUPKG_FILE%") do set "SZ=%%~zF"
    if !SZ! LSS %MIN_SIZE% (
        echo [INFO] Existing nupkg too small ^(!SZ! bytes^), re-downloading...
        del /f /q "%NUPKG_FILE%"
    ) else (
        echo [INFO] Reusing existing nupkg ^(!SZ! bytes^).
        goto :extract_python
    )
)

curl --ssl-no-revoke -L -o "%NUPKG_FILE%" "%NUGET_URL%" --progress-bar
if !errorlevel! neq 0 (
    echo [ERROR] Download failed! Check network connection.
    if exist "%NUPKG_FILE%" del /f /q "%NUPKG_FILE%"
    goto :fail
)

REM -- Validate size --
set "SZ=0"
for %%F in ("%NUPKG_FILE%") do set "SZ=%%~zF"
if !SZ! LSS %MIN_SIZE% (
    echo [ERROR] nupkg too small ^(!SZ! bytes^). Possibly corrupted.
    del /f /q "%NUPKG_FILE%"
    goto :fail
)
echo [OK] Downloaded: !SZ! bytes.
echo.

:extract_python
REM -- 2b: Extract nupkg (it is a zip), Python files are in tools\ subdirectory --
echo [3/3 bootstrap] Extracting Python %FULL_VER% to py_312...
if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%"
if exist "%NUPKG_EXTRACT%" rmdir /s /q "%NUPKG_EXTRACT%"
mkdir "%NUPKG_EXTRACT%"
powershell -NoProfile -Command "Expand-Archive -Path '%NUPKG_FILE%' -DestinationPath '%NUPKG_EXTRACT%' -Force"
if !errorlevel! neq 0 (
    echo [ERROR] Extraction failed!
    goto :fail
)
REM nuget Python package structure: tools\ is the full Python directory; also handle case where python.exe is at root
if exist "%NUPKG_EXTRACT%\tools\python.exe" (
    move "%NUPKG_EXTRACT%\tools" "%PYTHON_DIR%"
) else if exist "%NUPKG_EXTRACT%\python.exe" (
    mkdir "%PYTHON_DIR%"
    robocopy "%NUPKG_EXTRACT%" "%PYTHON_DIR%" /E /NFL /NDL /NJH /NJS >nul
) else (
    echo [ERROR] nuget package structure invalid: tools\python.exe not found!
    echo         Extracted contents:
    dir "%NUPKG_EXTRACT%" /b
    goto :fail
)
if exist "%NUPKG_EXTRACT%" rmdir /s /q "%NUPKG_EXTRACT%" 2>nul

if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe not found after extraction!
    goto :fail
)

REM -- Cleanup nupkg --
del /f /q "%NUPKG_FILE%" 2>nul

REM -- 2c: 检查 tkinter 所需的 Tcl/Tk DLL --
if not exist "%PYTHON_DIR%\tcl86t.dll" (
    echo [WARN] tcl86t.dll not found - tkinter may be unavailable in nuget Python.
    echo        install.py will fall back to PowerShell/command-line prompt mode.
)
echo [OK] Python %FULL_VER% ready at: %PYTHON_DIR%
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

echo [INFO] Verifying Lugwit_PackageRegistry / package_registry.yaml ...
"%PYTHON_EXE%" "%WUWO_DIR%\install.py" --wuwo-dir "%WUWO_DIR%" --ensure-registry-package
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Registry package check failed. See above for details.
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
echo.
echo ============================================================
echo   Installation complete! Launching tray...
echo ============================================================
echo.
REM -- Start tray via wuwo.bat (runs rez env l_tray -- start_tray)
if exist "%WUWO_DIR%\wuwo.bat" (
    start "wuwo tray" /d "%WUWO_DIR%" cmd /k "wuwo.bat rez env l_tray .update -- start_tray"
) else (
    echo [WARN] wuwo.bat not found, skipping auto-start.
    echo        Run manually: %WUWO_DIR%\wuwo.bat
)
endlocal
pause
