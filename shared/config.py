"""
Загрузка конфигурации из .env.
Используется обоими ботами (Telegram и MAX).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env лежит в корне проекта (на уровень выше shared/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── Telegram ──
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MANAGER_CHAT_ID: int = int(os.getenv("MANAGER_CHAT_ID", "0"))
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()
]

# ── MAX messenger ──
MAX_BOT_TOKEN: str = os.getenv("MAX_BOT_TOKEN", "")
MAX_ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("MAX_ADMIN_IDS", "0").split(",") if x.strip().isdigit()
]

# ── Прокси (опционально) ──
PROXY_URL: str = os.getenv("PROXY_URL", "")

# ── База ──
# По умолчанию — transfer_bot.db в корне проекта.
# Можно переопределить абсолютным путём через DB_PATH в .env.
_default_db = str(_PROJECT_ROOT / "transfer_bot.db")
# `or` используется вместо default в getenv — чтобы пустая строка в .env
# тоже переходила к дефолту (os.getenv возвращает "" если переменная задана пустой).
DB_PATH: str = os.getenv("DB_PATH") or _default_db

# ── Проверки ──
# Каждый бот проверяет только нужный ему токен на старте,
# здесь мы не валим импорт shared/config, если одного из них нет.
