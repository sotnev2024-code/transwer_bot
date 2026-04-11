"""
Entry point Telegram-бота.
Запуск: `python -m tg_bot.bot` из корня проекта.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Если запускается напрямую (python tg_bot/bot.py), добавим корень в sys.path,
# чтобы `from shared...` и `from tg_bot...` работали.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from shared.config import BOT_TOKEN
from shared.database import init_db
from shared.settings_store import load_all_settings, maybe_refresh_cache
from tg_bot.handlers import (
    start, booking, price_check, manager_transfer, my_orders,
    manager_actions, manager_reply, admin, reviews, admin_settings,
)
from tg_bot.handlers.notifications import notification_loop


async def _settings_refresh_loop() -> None:
    """Периодически перезагружает кэш настроек (раз в 60 сек),
    чтобы Telegram-бот видел изменения, сделанные MAX-ботом, и наоборот."""
    while True:
        await asyncio.sleep(60)
        try:
            await maybe_refresh_cache()
        except Exception as e:
            logging.getLogger(__name__).warning(f"settings refresh failed: {e}")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Запуск Telegram-бота трансфера по Алтаю...")

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    await init_db()
    await load_all_settings()
    logger.info("База данных и настройки инициализированы")

    # Порядок важен: более специфичные роутеры регистрируются первыми
    dp.include_router(admin_settings.router)  # настройки — самый специфичный
    dp.include_router(admin.router)           # админ-панель
    dp.include_router(reviews.router)         # отзывы — до общих хендлеров
    dp.include_router(manager_reply.router)   # reply менеджера в чате — раньше FSM-хендлеров,
                                              # т.к. фильтр по reply_to_message + chat_id
    dp.include_router(start.router)
    dp.include_router(booking.router)
    dp.include_router(price_check.router)
    dp.include_router(manager_transfer.router)
    dp.include_router(my_orders.router)
    dp.include_router(manager_actions.router)

    # Фоновые задачи
    asyncio.create_task(notification_loop(bot))
    asyncio.create_task(_settings_refresh_loop())
    logger.info("Фоновые задачи запущены (напоминания + refresh настроек)")

    logger.info("Telegram-бот запущен и слушает обновления...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
