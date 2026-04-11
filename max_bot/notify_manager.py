"""
Уведомление менеджера о новой заявке из MAX-бота.

По решению пользователя, ВСЕ заявки (и из Telegram, и из MAX) уходят
в ОДИН и тот же Telegram-чат менеджера. MAX-бот отправляет уведомление
напрямую через Telegram Bot API.

Кнопки "Принять / Отклонить / Указать цену" обслуживаются Telegram-ботом
(его manager_actions.py), который умеет отправлять ответы клиенту
через shared.notifier в нужный мессенджер по полю orders.platform.
"""

import logging
import httpx

from shared.config import BOT_TOKEN, MANAGER_CHAT_ID
from shared.database import save_inbox_link

_log = logging.getLogger(__name__)
_TG_API = "https://api.telegram.org"


async def notify_manager_new_max_order(order_id: int, order_data: dict, phone: str) -> None:
    """
    Отправляет Telegram-менеджеру уведомление о новой заявке из MAX.
    Прикрепляет те же кнопки, что Telegram-бот добавляет к своим заявкам,
    чтобы менеджер мог подтвердить / отклонить / установить цену.
    """
    if not (BOT_TOKEN and MANAGER_CHAT_ID):
        _log.warning("notify_manager: BOT_TOKEN или MANAGER_CHAT_ID не заданы")
        return

    from shared.routes_data import STOPS_LABELS, BAGGAGE_LABELS

    stops_label = STOPS_LABELS.get(order_data.get("stops", "none"), order_data.get("stops", ""))
    baggage_label = BAGGAGE_LABELS.get(order_data.get("baggage", ""), "")
    price_val = order_data.get("calculated_price", 0)
    price_text = f"{price_val:,} ₽" if price_val else "уточняется"
    dist = order_data.get("distance_km")
    dist_line = f"📏 Расстояние: <b>{dist} км</b>\n" if dist else ""
    children_info = (
        f"\n👶 Детей: <b>{order_data.get('children_count', 0)} чел.</b>"
        if order_data.get("children_count", 0) > 0
        else ""
    )
    route_type = (
        "📍 Произвольный маршрут"
        if order_data.get("use_custom_route")
        else "🗺 Стандартный маршрут"
    )

    text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА #{order_id}</b> · 💬 <b>MAX</b>\n\n"
        f"👤 Клиент: <b>{order_data.get('client_name', '')}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n"
        f"🆔 MAX user_id: {order_data.get('telegram_id', '')}\n\n"
        f"{route_type}\n"
        f"📍 Откуда: <b>{order_data.get('from_city', '')}</b>\n"
        f"🏁 Куда: <b>{order_data.get('to_city', '')}</b>\n"
        f"{dist_line}"
        f"📅 Дата: <b>{order_data.get('trip_date', '')}</b>\n"
        f"🕐 Время: <b>{order_data.get('trip_time', '')}</b>\n"
        f"👥 Пассажиров: <b>{order_data.get('passengers', 1)}</b>"
        f"{children_info}\n"
        f"🧳 Багаж: <b>{baggage_label}</b>\n"
        f"🚐 Минивэн: <b>{'Да' if order_data.get('need_minivan') else 'Нет'}</b>\n"
        f"📍 Остановки: <b>{stops_label}</b>\n\n"
        f"💰 Предв. стоимость: <b>{price_text}</b>\n\n"
        "<i>↩️ Ответьте реплаем на это сообщение — клиент получит ответ в MAX.</i>"
    )

    # Inline-клавиатура в формате Telegram Bot API (не MAX!).
    # Те же callback_data, что и у menu_actions в tg_bot — обрабатываются
    # в tg_bot/handlers/manager_actions.py.
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Принять заказ", "callback_data": f"mgr_accept:{order_id}"},
                {"text": "❌ Отклонить", "callback_data": f"mgr_reject:{order_id}"},
            ],
            [
                {"text": "💰 Указать цену", "callback_data": f"mgr_set_price:{order_id}"},
                {"text": "📋 Показать контакт", "callback_data": f"mgr_contact:{order_id}"},
            ],
        ]
    }

    url = f"{_TG_API}/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": MANAGER_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            _log.warning(f"notify_manager: {r.status_code} {r.text[:200]}")
            return
        # Сохраняем message_id, чтобы reply от менеджера мог дойти до клиента в MAX
        msg_id = (r.json().get("result") or {}).get("message_id")
        if msg_id:
            await save_inbox_link(
                chat_id=MANAGER_CHAT_ID,
                message_id=msg_id,
                user_id=order_data.get("telegram_id"),
                platform="max",
                kind="order",
                label=f"#{order_id} {order_data.get('client_name', '')}",
            )
    except Exception as e:
        _log.exception(f"notify_manager failed: {e}")
