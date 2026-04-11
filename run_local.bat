@echo off
REM ══════════════════════════════════════════════════════════════
REM  Запуск обоих ботов (Telegram + MAX) локально на Windows.
REM  Двойной клик — и готово.
REM ══════════════════════════════════════════════════════════════

cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

REM Выбираем python из venv, если он есть
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo.
echo ════════════════════════════════════════════════════════
echo   Алтай Трансфер — локальный запуск (TG + MAX)
echo ════════════════════════════════════════════════════════
echo.

"%PY%" run_local.py

echo.
pause
