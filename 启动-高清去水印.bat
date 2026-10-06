@echo off
chcp 65001 >nul
title TK去水印高清程序 v4.0
cd /d "%~dp0"

rem ====================================================================
rem  v4.0：本脚本是「开发 / 排查用」的启动方式。
rem  正常使用请直接双击 TK去水印高清程序.exe（原生窗口，不开浏览器）。
rem  这里用 python.exe（保留控制台）便于看到启动错误与 traceback。
rem ====================================================================

rem --- auto-fix venv home (same logic as the exe launcher) ---
set "VENVCFG=%~dp0venv\pyvenv.cfg"
if exist "%VENVCFG%" (
    powershell -NoProfile -Command "$cfg='%~dp0venv\pyvenv.cfg'; $vh='%~dp0python-runtime'.TrimEnd('\'); $txt=Get-Content -LiteralPath $cfg -Raw -Encoding UTF8; if($txt -match 'home\s*='){ $txt=[regex]::Replace($txt,'home\s*=.*','home = '+$vh) } else { $txt=$txt.TrimEnd() + [Environment]::NewLine + 'home = '+$vh + [Environment]::NewLine }; [System.IO.File]::WriteAllText($cfg,$txt,(New-Object System.Text.UTF8Encoding($false)))" >nul 2>nul
)

rem 1) prefer local venv
set "PY=venv\Scripts\python.exe"
if exist "%PY%" goto :run

rem 2) fallback to local embedded runtime
set "PY=python-runtime\python.exe"
if exist "%PY%" goto :run

rem 3) try system python
where python >nul 2>nul
if %errorlevel%==0 (
    echo [info] 使用系统 Python 启动 desktop.py
    python desktop.py
    goto :end
)

echo [error] 未找到 Python 环境，请确认 venv 或 python-runtime 目录完整。
pause
exit /b 1

:run
echo [info] 启动桌面版: %PY% desktop.py
echo [info] 程序会打开自己的窗口；本控制台仅用于查看日志，可最小化。
echo.
"%PY%" desktop.py

:end
echo.
echo [info] 程序已退出。
pause
