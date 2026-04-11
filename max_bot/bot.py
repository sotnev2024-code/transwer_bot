"""
Entry point MAX-бота.
Запуск: `python -m max_bot.bot` из корня проекта.

Аналогично tg_bot/bot.py, но для MAX messenger.
Использует собственный минимальный диспетчер и long polling.

Фоновые задачи:
  • long polling цикла get_updates
  • периодическое обновление кэша настроек (shared.settings_store)

Напоминания 24ч/1ч запускаются только в Telegram-боте (обслуживают обе платформы),
чтобы не было дубликатов.
"""

import asyncio
import logging
import sys
from pathlib import Path

# sys.path fix — чтобы `from shared...` и `from max_bot...` работали при прямом запуске
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.config import MAX_BOT_TOKEN
from shared.database import init_db
from shared.settings_store import load_all_settings, maybe_refresh_cache
from max_bot.max_client import MaxClient
from max_bot.fsm import FSMStorage
from max_bot.dispatcher import Dispatcher, Update
from max_bot.handlers import (
    start, booking, price_check, my_orders, manager_transfer, reviews,
    admin, admin_settings,
)


async def _settings_refresh_loop() -> None:
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
    logger.info("Запуск MAX-бота трансфера по Алтаю...")

    if not MAX_BOT_TOKEN:
        raise ValueError("MAX_BOT_TOKEN не задан в .env")

    await init_db()
    await load_all_settings()
    logger.info("База данных и настройки инициализированы")

    client = MaxClient(MAX_BOT_TOKEN)
    storage = FSMStorage()
    dp = Dispatcher(client, storage)

    # Регистрация модулей. Порядок важен: более специфичные роуты должны
    # регистрироваться первыми, чтобы перехватывать события до общих хендлеров.
    admin_settings.register(dp)   # самый специфичный — adm_set:* префиксы
    admin.register(dp)            # /admin, admin:*, adm_*, admcal:*, admrng:*
    start.register(dp)
    reviews.register(dp)          # отзывы — перед общими текстовыми хендлерами
    booking.register(dp)
    price_check.register(dp)
    my_orders.register(dp)
    manager_transfer.register(dp)

    # bot info — чисто для лога и sanity check токена
    try:
        me = await client.get_me()
        name = me.get("name") or me.get("first_name") or "MAX bot"
        username = me.get("username")
        logger.info(f"MAX bot: {name} (@{username})")
    except Exception as e:
        logger.warning(f"/me failed: {e}")

    # Регистрируем команды — чтобы пользователю не приходилось набирать /start вручную,
    # они появятся в меню команд мессенджера.
    try:
        await client.set_commands([
            {"name": "start", "description": "Главное меню"},
            {"name": "help", "description": "Помощь"},
            {"name": "admin", "description": "Панель администратора"},
        ])
        logger.info("MAX commands registered: /start, /help, /admin")
    except Exception as e:
        logger.warning(f"set_commands failed: {e}")

    # Фоновая задача — refresh настроек
    asyncio.create_task(_settings_refresh_loop())

    logger.info("MAX-бот запущен, стартуем long polling...")
    try:
        async for raw in client.poll_updates():
            upd = Update(raw)
            asyncio.create_task(dp.process(upd))
    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
