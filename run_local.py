"""
Локальный запускатель обоих ботов сразу.

Запускает tg_bot и max_bot как дочерние процессы, склеивает их логи
в один поток с префиксами [TG] / [MAX], по Ctrl+C корректно гасит обоих.

Запуск:
    python run_local.py

или из .bat-файла (run_local.bat рядом).
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

# Windows-консоль по умолчанию cp1251, а мы выводим кириллицу и спецсимволы.
# Принудительно переключаем stdout/stderr на UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parent


# ── выбор интерпретатора ──
def _find_python() -> str:
    """Ищем python из локального venv, иначе — текущий интерпретатор."""
    candidates = [
        _ROOT / ".venv" / "Scripts" / "python.exe",   # Windows
        _ROOT / ".venv" / "bin" / "python",           # Linux/Mac
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


_PYTHON = _find_python()


# ── цветные префиксы ──
_TG_PREFIX = "\033[36m[TG] \033[0m"     # cyan
_MAX_PREFIX = "\033[35m[MAX]\033[0m"    # magenta
_ERR_PREFIX = "\033[31m[ERR]\033[0m"


async def _pipe_stream(stream: asyncio.StreamReader, prefix: str) -> None:
    """Читает stdout/stderr дочернего процесса и пишет в наш stdout с префиксом."""
    while True:
        line = await stream.readline()
        if not line:
            break
        try:
            text = line.decode("utf-8", errors="replace").rstrip()
        except Exception:
            text = repr(line)
        print(f"{prefix} {text}", flush=True)


async def _run_bot(name: str, module: str, prefix: str) -> int:
    """Запускает `python -m <module>` и стримит его логи."""
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    print(f"{prefix} Запуск {name} ({_PYTHON} -m {module})", flush=True)

    proc = await asyncio.create_subprocess_exec(
        _PYTHON, "-m", module,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,   # стягиваем stderr в общий stream
        cwd=str(_ROOT),
        env=env,
    )

    try:
        assert proc.stdout is not None
        await _pipe_stream(proc.stdout, prefix)
        rc = await proc.wait()
    except asyncio.CancelledError:
        # корректное завершение по Ctrl+C
        print(f"{prefix} Останавливаю {name}...", flush=True)
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=8)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass
        rc = proc.returncode or 0
        raise
    finally:
        print(f"{prefix} {name} остановлен (код {proc.returncode})", flush=True)

    return rc


async def _main() -> int:
    # Проверка: .env должен существовать
    env_file = _ROOT / ".env"
    if not env_file.exists():
        print(f"{_ERR_PREFIX} Не найден .env в {_ROOT}", flush=True)
        print(f"{_ERR_PREFIX} Скопируйте .env.example в .env и заполните токены.", flush=True)
        return 1

    # Проверка токенов
    from shared.config import BOT_TOKEN, MAX_BOT_TOKEN, MANAGER_CHAT_ID

    problems: list[str] = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
    if not MAX_BOT_TOKEN:
        problems.append("MAX_BOT_TOKEN не задан")
    if not MANAGER_CHAT_ID:
        problems.append("MANAGER_CHAT_ID не задан")

    if problems:
        for p in problems:
            print(f"{_ERR_PREFIX} {p}", flush=True)
        print(f"{_ERR_PREFIX} Отредактируйте .env и запустите снова.", flush=True)
        return 1

    print("========================================================")
    print("  Запуск ОБОИХ ботов локально (Ctrl+C для остановки)")
    print("========================================================")

    # Две параллельные задачи
    tg_task = asyncio.create_task(_run_bot("Telegram-бот", "tg_bot.bot", _TG_PREFIX))
    max_task = asyncio.create_task(_run_bot("MAX-бот", "max_bot.bot", _MAX_PREFIX))

    try:
        # Ждём пока хоть один не умрёт — и валимся весь раннер
        done, pending = await asyncio.wait(
            [tg_task, max_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Если кто-то из них закончился раньше времени (ошибка/краш) —
        # останавливаем и второго, чтобы не висел один на один с БД
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                print(f"{_ERR_PREFIX} Одна из задач упала: {exc!r}", flush=True)
                return 2
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n⏹  Останавливаем обоих ботов...", flush=True)
        for t in (tg_task, max_task):
            t.cancel()
        # Дождёмся завершения
        await asyncio.gather(tg_task, max_task, return_exceptions=True)
        print("✅ Остановлено.", flush=True)
        return 0


def main() -> None:
    # На Windows для корректной работы asyncio.subprocess
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        rc = asyncio.run(_main())
    except KeyboardInterrupt:
        rc = 0
    sys.exit(rc)


if __name__ == "__main__":
    main()
