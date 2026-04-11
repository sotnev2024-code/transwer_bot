"""
Фоновый планировщик: напоминания за 24 ч и за 1 ч до поездки.
Запускается как asyncio-задача при старте Telegram-бота.

ВАЖНО: работает с заказами ИЗ ОБЕИХ платформ (telegram + max).
Отправка идёт через shared.notifier, который маршрутизирует
сообщение в нужный мессенджер по полю orders.platform.

Планировщик запускается только в Telegram-боте (НЕ в MAX-боте),
чтобы не было дублирующихся напоминаний из двух процессов.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot

from shared import settings_store
from shared.database import (
    get_confirmed_orders_for_reminders,
    check_notification_sent,
    mark_notification_sent,
)
from shared.notifier import send_user_message

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300


def _parse_trip_datetime(order: dict) -> datetime | None:
    try:
        return datetime.strptime(
            f"{order['trip_date']} {order['trip_time']}", "%d.%m.%Y %H:%M"
        )
    except (ValueError, KeyError):
        return None


async def _send_reminder(order: dict, kind: str) -> None:
    order_id = order["id"]
    uid = order["telegram_id"]
    platform = order.get("platform", "telegram")
    key = "text_reminder_24h" if kind == "24h" else "text_reminder_1h"

    text = settings_store.get_text(
        key,
        order_id=order_id,
        from_city=order["from_city"],
        to_city=order["to_city"],
        trip_date=order["trip_date"],
        trip_time=order["trip_time"],
    )

    ok = await send_user_message(user_id=uid, platform=platform, text=text)
    if ok:
        await mark_notification_sent(order_id, kind)
        logger.info("Reminder %s sent for order #%s to %s user %s", kind, order_id, platform, uid)
    else:
        logger.warning("Failed to send %s reminder for order #%s (%s)", kind, order_id, platform)


async def notification_loop(bot: Bot) -> None:
    """Фоновая задача. Параметр bot не используется напрямую, оставлен для совместимости."""
    logger.info("Notification scheduler started (interval=%ds)", CHECK_INTERVAL_SECONDS)

    while True:
        try:
            now = datetime.now()
            orders = await get_confirmed_orders_for_reminders()

            for order in orders:
                trip_dt = _parse_trip_datetime(order)
                if trip_dt is None:
                    continue

                delta = trip_dt - now

                if timedelta(hours=0) < delta <= timedelta(hours=1, minutes=10):
                    if not await check_notification_sent(order["id"], "1h"):
                        await _send_reminder(order, "1h")

                elif timedelta(hours=23) < delta <= timedelta(hours=24, minutes=10):
                    if not await check_notification_sent(order["id"], "24h"):
                        await _send_reminder(order, "24h")

        except Exception as e:
            logger.exception("Error in notification loop: %s", e)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
