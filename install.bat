@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  wuwo Python 3.12 Environment Auto-Installer
REM  - Downloads Python 3.12.8 embeddable zip from python.org
REM  - Extracts to py_312 directory (replaces existing)
REM  - Installs pip + all required packages
REM  - Idempotent: skips if py_312\python.exe already valid
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%py_312"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "FULL_VER=3.12.8"
set "PTH_PREFIX=python312"
set "ZIP_NAME=python-%FULL_VER%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%FULL_VER%/%ZIP_NAME%"
set "TEMP_ZIP=%SCRIPT_DIR%%ZIP_NAME%"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "TEMP_PIP=%SCRIPT_DIR%get-pip.py"

echo ============================================================
echo   wuwo Python 3.12 Environment Installer
echo   Target: %PYTHON_DIR%
echo ============================================================
echo.

REM ------ Idempotency check ------
if exist "%PYTHON_EXE%" (
    echo [INFO] Checking existing Python installation...
    "%PYTHON_EXE%" --version >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Python already installed and working:
        "%PYTHON_EXE%" --version
        echo.
        echo [INFO] To reinstall, delete the py_312 directory first, then re-run this script.
        echo.
        goto :install_deps_check
    ) else (
        echo [WARN] python.exe exists but is not working. Reinstalling...
        echo.
    )
)

REM ------ Step 1: Download Python embeddable zip ------
echo [1/5] Downloading Python %FULL_VER% embeddable package...
echo       URL: %ZIP_URL%
echo.

if exist "%TEMP_ZIP%" (
    echo [INFO] Found existing zip file, checking size...
    set "FILE_SIZE=0"
    for %%A in ("%TEMP_ZIP%") do set "FILE_SIZE=%%~zA"
    if !FILE_SIZE! LSS 5000000 (
        echo [INFO] Existing zip too small ^(!FILE_SIZE! bytes^), re-downloading...
        del /f /q "%TEMP_ZIP%"
    ) else (
        echo [INFO] Reusing existing zip ^(!FILE_SIZE! bytes^).
        goto :extract
    )
)

curl --ssl-no-revoke -L -o "%TEMP_ZIP%" "%ZIP_URL%" --progress-bar
if %errorlevel% neq 0 (
    echo [ERROR] Download failed! Check your network connection.
    if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
    goto :fail
)
if not exist "%TEMP_ZIP%" (
    echo [ERROR] Downloaded file not found: %TEMP_ZIP%
    goto :fail
)

REM ------ Validate zip file size (must be > 5MB) ------
set "FILE_SIZE=0"
for %%A in ("%TEMP_ZIP%") do set "FILE_SIZE=%%~zA"
if !FILE_SIZE! LSS 5000000 (
    echo [ERROR] Downloaded file too small ^(!FILE_SIZE! bytes^).
    echo [ERROR] The file may be corrupted or a network error page. Please retry.
    del /f /q "%TEMP_ZIP%"
    goto :fail
)
echo [OK] Download complete. File size: !FILE_SIZE! bytes.
echo.

:extract
REM ------ Step 2: Extract to py_312 directory ------
echo [2/5] Extracting to py_312...
if exist "%PYTHON_DIR%" (
    echo       Removing existing py_312 directory...
    rmdir /s /q "%PYTHON_DIR%"
    if exist "%PYTHON_DIR%" (
        echo [ERROR] Failed to remove existing py_312 directory. It may be in use.
        goto :fail
    )
)
mkdir "%PYTHON_DIR%"
powershell -NoProfile -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
if %errorlevel% neq 0 (
    echo [ERROR] Extraction failed!
    goto :fail
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe not found after extraction. The zip may be corrupted.
    goto :fail
)
echo [OK] Extraction complete.
echo.

REM ------ Step 3: Configure ._pth file to enable site-packages ------
echo [3/5] Configuring %PTH_PREFIX%._pth to enable site-packages...
set "PTH_FILE=%PYTHON_DIR%\%PTH_PREFIX%._pth"
if exist "%PTH_FILE%" (
    powershell -NoProfile -Command "(Get-Content '%PTH_FILE%') -replace '^#\s*import site', 'import site' | Set-Content '%PTH_FILE%'"
    echo [OK] Uncommented 'import site' in %PTH_PREFIX%._pth.
) else (
    echo [WARN] %PTH_PREFIX%._pth not found. Creating a default one...
    (
        echo %PTH_PREFIX%.zip
        echo .
        echo import site
    ) > "%PTH_FILE%"
    echo [OK] Created default %PTH_PREFIX%._pth.
)
echo.

REM ------ Step 4: Install pip ------
echo [4/5] Installing pip...
if not exist "%TEMP_PIP%" (
    echo       Downloading get-pip.py from %GET_PIP_URL% ...
    curl --ssl-no-revoke -L -o "%TEMP_PIP%" "%GET_PIP_URL%" --progress-bar
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download get-pip.py!
        goto :fail
    )
)
echo       Running get-pip.py...
"%PYTHON_EXE%" "%TEMP_PIP%" --no-warn-script-location
if %errorlevel% neq 0 (
    echo [ERROR] pip installation failed!
    goto :fail
)
echo [OK] pip installed successfully.
echo.

REM ------ Step 5: Install required packages ------
:install_deps_check
echo [5/5] Installing required packages...
echo.

set "PIP_EXE=%PYTHON_DIR%\Scripts\pip.exe"
if not exist "%PIP_EXE%" (
    set "PIP_EXE=%PYTHON_EXE% -m pip"
)

REM Core packages required by wuwo
echo       Installing rez...
"%PYTHON_EXE%" -m pip install rez --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] rez installation failed. Please install manually.
) else (
    echo [OK] rez installed.
)

echo.
echo       Installing PyYAML...
"%PYTHON_EXE%" -m pip install PyYAML --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] PyYAML installation failed.
) else (
    echo [OK] PyYAML installed.
)

echo.
echo       Installing pywin32...
"%PYTHON_EXE%" -m pip install pywin32 --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] pywin32 installation failed.
) else (
    echo [OK] pywin32 installed.
    REM Run pywin32 post-install script
    set "PYWIN32_POST=%PYTHON_DIR%\Scripts\pywin32_postinstall.py"
    if exist "!PYWIN32_POST!" (
        "%PYTHON_EXE%" "!PYWIN32_POST!" -install >nul 2>&1
        echo [OK] pywin32 post-install script executed.
    )
)

echo.
echo       Installing PySide6...
"%PYTHON_EXE%" -m pip install PySide6 --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] PySide6 installation failed. It is large and may require a stable connection.
) else (
    echo [OK] PySide6 installed.
)

echo.
echo       Installing PyQt5...
"%PYTHON_EXE%" -m pip install PyQt5 --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] PyQt5 installation failed.
) else (
    echo [OK] PyQt5 installed.
)

echo.
echo       Installing requests...
"%PYTHON_EXE%" -m pip install requests --no-warn-script-location
if %errorlevel% neq 0 (
    echo [WARN] requests installation failed.
) else (
    echo [OK] requests installed.
)

REM ------ Cleanup ------
echo.
echo Cleaning up temporary files...
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
if exist "%TEMP_PIP%" del /f /q "%TEMP_PIP%"
echo [OK] Cleanup complete.

echo.
echo ============================================================
echo   Installation Complete!
echo ============================================================
echo   Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo   pip:    %PYTHON_DIR%\Scripts\pip.exe
echo.
echo   Installed packages:
"%PYTHON_EXE%" -m pip list --format=columns 2>nul
echo.
echo ============================================================
echo.
echo ============================================================
echo   [NEXT STEP] Configure rez package search paths
echo ============================================================
echo.
echo   config.yaml will now open in Notepad.
echo   Please update the following paths to match your machine:
echo.
echo     packages.build   - your rez-package-build directory
echo     packages.release - your rez-packages-release directory
echo.
echo   Save and CLOSE Notepad when done, then press any key to continue
echo   and auto-install the tray app and all related packages.
echo ============================================================
echo.
pause

REM ------ Open config.yaml in Notepad for user to edit ------
start /wait notepad "%SCRIPT_DIR%config.yaml"

echo.
echo [INFO] config.yaml editing complete. Proceeding to install tray packages...
echo.

REM ------ Auto-fetch all rez packages (including l_tray) ------
echo ============================================================
echo   [6/6] Fetching rez packages from GitHub...
echo   (l_tray, l_scheduler, Lugwit_Module, ChatRoom, etc.)
echo ============================================================
echo.

if not exist "%SCRIPT_DIR%auto_fetch_packages.py" (
    echo [WARN] auto_fetch_packages.py not found, skipping package fetch.
    goto :install_done
)

"%PYTHON_EXE%" "%SCRIPT_DIR%auto_fetch_packages.py"
if %errorlevel% neq 0 (
    echo [WARN] Some packages could not be downloaded. You can retry by running:
    echo        wuwo.bat
    echo        or: py_312\python.exe auto_fetch_packages.py
) else (
    echo [OK] All rez packages fetched successfully.
)

:install_done
echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo   Python : %PYTHON_EXE%
echo   Config : %SCRIPT_DIR%config.yaml
echo   Packages: %SCRIPT_DIR%packages
echo.
echo   To start wuwo environment, run:
echo   %SCRIPT_DIR%wuwo.bat
echo ============================================================
goto :end

:fail
echo.
echo ============================================================
echo   [FATAL] Installation failed. Please check the errors above.
echo ============================================================
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
if exist "%TEMP_PIP%" del /f /q "%TEMP_PIP%"
echo.
pause
exit /b 1

:end
endlocal
pause
