"""
Кросс-платформенные уведомления конечным пользователям.

Любой код, который хочет отправить сообщение клиенту (подтверждение заказа,
напоминание о поездке, запрос отзыва), вызывает `send_user_message(...)`
с user_id и platform — модуль сам выберет нужный API.

Telegram сообщения — через Telegram Bot API.
MAX сообщения — через platform-api.max.ru.

ВАЖНО про идентификаторы:
  • Для Telegram chat_id == user_id для приватных диалогов, поэтому можно
    передавать любое из них.
  • Для MAX user_id ≠ chat_id — это разные числа. Но MAX API метод
    POST /messages принимает оба варианта параметра (?user_id=... или
    ?chat_id=...). Мы используем user_id, потому что в наших orders.telegram_id
    хранится именно user_id (его даёт MAX в callback.user.user_id и
    message.sender.user_id).

Использование:
    from shared.notifier import send_user_message
    await send_user_message(
        user_id=order["telegram_id"],
        platform=order["platform"],
        text="<b>Заказ подтверждён</b>",
    )
"""

import logging
import httpx

from shared.config import BOT_TOKEN, MAX_BOT_TOKEN

_log = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org"
_MAX_API = "https://platform-api.max.ru"


async def send_user_message(
    user_id: int,
    platform: str,
    text: str,
    parse_mode: str | None = "HTML",
) -> bool:
    """
    Универсальная отправка текстового сообщения клиенту.
    Возвращает True если успешно, False если нет.
    Не бросает исключения — пишет в лог и возвращает False.
    """
    platform = (platform or "telegram").lower()
    try:
        if platform == "telegram":
            return await _send_telegram(user_id, text, parse_mode)
        elif platform == "max":
            return await _send_max(user_id, text)
        else:
            _log.warning(f"Unknown platform '{platform}' for user {user_id}")
            return False
    except Exception as e:
        _log.exception(f"send_user_message failed ({platform}, {user_id}): {e}")
        return False


async def _send_telegram(chat_id: int, text: str, parse_mode: str | None) -> bool:
    if not BOT_TOKEN:
        _log.error("BOT_TOKEN not set — cannot send Telegram message")
        return False
    url = f"{_TG_API}/bot{BOT_TOKEN}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
    if r.status_code != 200:
        _log.warning(f"Telegram sendMessage {r.status_code}: {r.text[:200]}")
        return False
    return True


async def _send_max(user_id: int, text: str) -> bool:
    """
    Отправка сообщения пользователю MAX.

    Эндпоинт: POST https://platform-api.max.ru/messages?user_id=<user_id>
    Headers:  Authorization: <token>
    Body:     {"text": "...", "format": "html"}

    Используем user_id (а не chat_id) как параметр — MAX это поддерживает,
    и нам не нужно отдельно хранить chat_id диалога в БД (в orders.telegram_id
    лежит именно user_id из MAX-апдейта).

    HTML-теги в тексте сохраняем — MAX рендерит <b>, <i>, <a> при format=html
    (тот же синтаксис, что и в Telegram-боте, поэтому шаблоны из settings_store
    работают one-to-one).
    """
    if not MAX_BOT_TOKEN:
        _log.error("MAX_BOT_TOKEN not set — cannot send MAX message")
        return False

    url = f"{_MAX_API}/messages"
    params = {"user_id": user_id}
    headers = {"Authorization": MAX_BOT_TOKEN}
    payload = {"text": text, "format": "html"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, params=params, json=payload, headers=headers)
    if r.status_code not in (200, 201):
        _log.warning(f"MAX POST /messages user_id={user_id} {r.status_code}: {r.text[:200]}")
        return False
    return True
