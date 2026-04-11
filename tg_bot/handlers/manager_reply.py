"""
Приём reply-ответов менеджера.

Когда бот отправляет в чат `MANAGER_CHAT_ID` уведомление о новой заявке
или запросе клиента, он сохраняет в таблицу `manager_inbox` пару
`(chat_id, message_id) → (user_id, platform)`.

Этот хендлер ловит ЛЮБОЕ сообщение в чате менеджера, которое является
reply на одно из таких сохранённых сообщений, и доставляет текст ответа
клиенту в его исходный мессенджер (Telegram или MAX) через
`shared.notifier.send_user_message`.

Хендлер должен регистрироваться ПОЗЖЕ `manager_actions`, но обязательно
ДО `booking`/`my_orders` — иначе они могут перехватить сообщение раньше.
В bot.py регистрируем в самом конце.
"""

from __future__ import annotations

import logging
import html as _html

from aiogram import Router, F, Bot
from aiogram.types import Message

from shared.config import MANAGER_CHAT_ID, ADMIN_IDS
from shared.database import get_inbox_link
from shared.notifier import send_user_message

router = Router()
logger = logging.getLogger(__name__)


def _is_manager_chat(chat_id: int) -> bool:
    """Сообщения принимаем только из чата менеджера."""
    return MANAGER_CHAT_ID and chat_id == MANAGER_CHAT_ID


@router.message(F.reply_to_message)
async def on_manager_reply(message: Message, bot: Bot) -> None:
    # 1) Только в чате менеджера
    if not _is_manager_chat(message.chat.id):
        return

    # 2) Reply должен быть на сообщение БОТА (не на чужое)
    src = message.reply_to_message
    if not src or not src.from_user or not src.from_user.is_bot:
        return

    # 3) Ищем линк в БД
    link = await get_inbox_link(message.chat.id, src.message_id)
    if not link:
        # Это reply на наше сообщение, которое мы НЕ зарегистрировали
        # как inbox-запись (например, обычное служебное сообщение).
        try:
            await message.reply(
                "⚠️ Не могу связать этот ответ с клиентом — запись не найдена.\n"
                "Возможно, это старая заявка. Свяжитесь с клиентом напрямую."
            )
        except Exception:
            pass
        return

    # 4) Извлекаем текст ответа менеджера
    reply_text = (message.text or message.caption or "").strip()
    if not reply_text:
        # Возможно медиа без подписи — на этом этапе пересылка медиа не реализована.
        # Сообщим менеджеру в чат.
        try:
            await message.reply(
                "⚠️ Ответ должен содержать текст. Медиа-файлы пока не пересылаются."
            )
        except Exception:
            pass
        return

    # 5) Доставка клиенту
    target_user_id = link["user_id"]
    target_platform = link["platform"]
    label = link.get("label") or ""

    # Имя/подпись менеджера для прозрачности
    sender = message.from_user
    manager_name = (
        (f"@{sender.username}" if sender and sender.username else None)
        or (sender.first_name if sender else None)
        or "Менеджер"
    )

    # Экранируем reply_text для HTML, но без агрессивности — менеджер пишет
    # обычный текст, а не разметку. Если менеджер сам напишет <b>...</b>,
    # они отобразятся как код. Это нормальное безопасное поведение.
    safe = _html.escape(reply_text)

    text_to_client = (
        "💬 <b>Сообщение от менеджера</b>\n\n"
        f"{safe}\n\n"
        f"<i>— {_html.escape(manager_name)}</i>"
    )

    ok = await send_user_message(
        user_id=target_user_id,
        platform=target_platform,
        text=text_to_client,
    )

    # 6) Подтверждение в чате менеджера (короткая «галочка» через reply)
    try:
        if ok:
            badge = "💬 MAX" if target_platform == "max" else "💬 TG"
            note = f"✅ Ответ отправлен клиенту ({badge})"
            if label:
                note += f" · {label}"
            await message.reply(note)
        else:
            await message.reply(
                "⚠️ Не удалось доставить ответ клиенту. "
                "Проверьте, что бот в нужной платформе запущен и имеет доступ."
            )
    except Exception as e:
        logger.warning("Не удалось подтвердить менеджеру: %s", e)
