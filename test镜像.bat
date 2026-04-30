@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================
REM  Test pip mirrors for connectivity and speed
REM  Downloads a small package (psutil) from each mirror
REM ============================================================

set "PYTHON_EXE=python"
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] python not found in PATH
    pause
    exit /b 1
)

set "TEST_PKG=pyside6"
set "TEMP_DIR=%TEMP%\pip_mirror_test"
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo ============================================================
echo   Testing pip mirrors for package: %TEST_PKG%
echo   Target directory: %TEMP_DIR%
echo ============================================================
echo.

set "MIRRORS[0]=https://pypi.tuna.tsinghua.edu.cn/simple"
set "MIRRORS[1]=https://mirrors.aliyun.com/pypi/simple/"
set "MIRRORS[2]=https://pypi.mirrors.ustc.edu.cn/simple/"
set "MIRRORS[3]=https://pypi.org/simple"

set "LABELS[0]=Tsinghua (清华)"
set "LABELS[1]=Aliyun (阿里云)"
set "LABELS[2]=USTC (中科大)"
set "LABELS[3]=PyPI Official (官方)"

for /L %%i in (0,1,3) do (
    set "MIRROR=!MIRRORS[%%i]!"
    set "LABEL=!LABELS[%%i]!"
    echo [Testing] !LABEL!
    echo           !MIRROR!
    
    if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%" 2>nul
    mkdir "%TEMP_DIR%"
    
    for /f %%T in ('powershell -NoProfile -Command "([datetime]::Now - [datetime]::Today).TotalMilliseconds -as [int]"') do set "T0=%%T"
    "%PYTHON_EXE%" -m pip install %TEST_PKG% --target "%TEMP_DIR%" -i "!MIRROR!" --no-deps --no-warn-script-location --quiet >nul 2>&1
    set "EXIT_CODE=!errorlevel!"
    for /f %%T in ('powershell -NoProfile -Command "([datetime]::Now - [datetime]::Today).TotalMilliseconds -as [int]"') do set "T1=%%T"
    
    set /a "ELAPSED_MS=T1-T0"
    set /a "ELAPSED_S=ELAPSED_MS/1000"
    set /a "ELAPSED_MS_REM=ELAPSED_MS%%1000"
    
    set "DOWN_BYTES=0"
    for /f %%A in ('powershell -NoProfile -Command "$s=(Get-ChildItem -Path '%TEMP_DIR%' -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum; if($s){$s}else{0}"') do set "DOWN_BYTES=%%A"
    
    if !EXIT_CODE! equ 0 (
        if !ELAPSED_S! gtr 0 (
            set /a "SPEED_KB=DOWN_BYTES/1024/ELAPSED_S"
            echo [OK]   Time: !ELAPSED_S!.!ELAPSED_MS_REM!s   Size: !DOWN_BYTES! bytes   Speed: ~!SPEED_KB! KB/s
        ) else (
            echo [OK]   Time: !ELAPSED_S!.!ELAPSED_MS_REM!s   Size: !DOWN_BYTES! bytes   Speed: very fast
        )
    ) else (
        echo [FAIL] Failed
    )
    echo.
)

REM Cleanup
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"

echo ============================================================
echo   Test complete
echo ============================================================
echo.
pause
