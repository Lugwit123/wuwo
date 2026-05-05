@echo off
REM Start frp CLIENT (frpc): rez env l_frp + frpc_client.yaml
REM
REM 若出现 "Access is denied"：
REM   1) 不要用全局 taskkill 杀其它会话的 frpc（本脚本默认不再强杀；需要时可设 START_FRPC_KILL=1）
REM   2) 在「Windows 安全中心」对 frpc.exe 放行 / 受控文件夹访问里允许 wuwo 或 rez 使用的 python
REM   3) 在资源管理器右键 frpc.exe → 属性 → 若底部有「解除锁定」请勾选
REM
REM 日志见 frpc_client.yaml 里 log.to（console 或文件路径）
setlocal
set "WUWO_DIR=%~dp0"
cd /d "%WUWO_DIR%"

set "CFG=%WUWO_DIR%..\rez-package-source\l_frp\999.0\frpc_client.yaml"
set "FRPC_BIN=%WUWO_DIR%..\rez-package-source\l_frp\999.0\bin\windows_amd64\frpc.exe"

if not exist "%WUWO_DIR%wuwo.bat" (
    echo [start_frp_c] ERROR: wuwo.bat not found: "%WUWO_DIR%wuwo.bat"
    exit /b 1
)
if not exist "%CFG%" (
    echo [start_frp_c] ERROR: config not found: "%CFG%"
    echo [start_frp_c] TIP: create "%CFG%" then rerun.
    exit /b 1
)
if not exist "%FRPC_BIN%" (
    echo [start_frp_c] ERROR: frpc.exe not found: "%FRPC_BIN%"
    echo [start_frp_c] TIP: run rez-package-source\l_frp\999.0\init.bat or: wuwo.bat rez env l_frp
    exit /b 1
)

REM 去掉「来自 Internet」标记，减轻 SmartScreen 拦截（需本机允许执行 PowerShell）
for %%I in ("%FRPC_BIN%") do (
    powershell -NoProfile -Command "try { Unblock-File -LiteralPath '%%~fI' -ErrorAction SilentlyContinue } catch {}" >nul 2>&1
)

REM 仅当显式要求时才结束 frpc；且只筛当前用户名，降低 Access is denied / 误杀
if /i "%START_FRPC_KILL%"=="1" (
    taskkill /IM frpc.exe /FI "USERNAME eq %USERNAME%" /F >nul 2>&1
    if errorlevel 1 (
        echo [start_frp_c] WARN: taskkill frpc skipped or failed ^(no process / no permission^). Continuing.
    ) else (
        echo [start_frp_c] Stopped frpc.exe for current user.
    )
)

call "%WUWO_DIR%wuwo.bat" rez env l_frp -- frpc -c "%CFG%"
set "EC=%ERRORLEVEL%"
if %EC% neq 0 (
    echo.
    echo [start_frp_c] frpc exited with code %EC%.
    echo [start_frp_c] If you saw "Access is denied": try closing other frpc, set START_FRPC_KILL=1, or allow frpc in Windows Security.
)
exit /b %EC%
