"""
«Связаться с менеджером» — нестандартный запрос.
Пользователь описывает задачу своими словами, затем оставляет контакт,
и его сообщение пересылается в Telegram-чат менеджера.
"""

import re
import httpx

from shared.config import BOT_TOKEN, MANAGER_CHAT_ID
from shared.database import save_inbox_link

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import main_menu_kb, back_to_menu_kb, contact_kb


S_DESCRIBE = "mgr:describe"
S_NAME = "mgr:name"
S_PHONE = "mgr:phone"

_TG_API = "https://api.telegram.org"


async def on_start_manager(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.clear()
    await ctx.state.set_state(S_DESCRIBE)
    await ctx.edit(
        "📞 <b>Связаться с менеджером</b>\n\n"
        "Опишите вашу задачу:\n"
        "• куда и откуда нужен трансфер\n"
        "• когда и во сколько\n"
        "• сколько человек, детали\n\n"
        "Напишите всё в одном сообщении.",
        kb=back_to_menu_kb(),
    )


async def on_describe(ctx: MaxContext) -> None:
    text = (ctx.text or "").strip()
    if len(text) < 10:
        await ctx.edit("❌ Опишите задачу подробнее (хотя бы 10 символов).")
        return
    await ctx.state.update_data(mgr_description=text)
    await ctx.state.set_state(S_NAME)
    await ctx.edit("✏️ Введите ваше <b>имя</b>:", kb=back_to_menu_kb())


async def on_name(ctx: MaxContext) -> None:
    name = (ctx.text or "").strip()
    if len(name) < 2:
        await ctx.edit("❌ Введите корректное имя (минимум 2 символа).")
        return
    await ctx.state.update_data(mgr_name=name)
    await ctx.state.set_state(S_PHONE)
    await ctx.edit(
        "📱 <b>Отправьте номер телефона</b> кнопкой ниже или введите текстом:",
        kb=contact_kb(),
    )


async def on_phone(ctx: MaxContext) -> None:
    phone = ctx.update.contact_phone
    if not phone and ctx.text:
        phone = ctx.text.strip()
    if not phone:
        return

    clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not re.match(r"^[+]?[78]?\d{10}$", clean):
        await ctx.edit("❌ Введите корректный номер. Пример: +79123456789")
        return

    data = await ctx.state.get_data()
    await ctx.state.clear()

    # Отправляем менеджеру в Telegram. Сохраняем message_id, чтобы менеджер
    # мог ответить реплаем, и мы знали, кому именно отправить ответ обратно (в MAX).
    if BOT_TOKEN and MANAGER_CHAT_ID:
        text = (
            "📩 <b>ЗАПРОС ОТ КЛИЕНТА</b> · 💬 MAX\n\n"
            f"👤 Имя: <b>{data.get('mgr_name', '')}</b>\n"
            f"📱 Телефон: <b>{phone}</b>\n"
            f"🆔 MAX user_id: {ctx.user_id}\n\n"
            f"💬 Запрос:\n{data.get('mgr_description', '')}\n\n"
            "<i>↩️ Ответьте реплаем на это сообщение — клиент получит ответ в MAX.</i>"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(
                    f"{_TG_API}/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": MANAGER_CHAT_ID,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
            if r.status_code == 200:
                msg_id = (r.json().get("result") or {}).get("message_id")
                if msg_id:
                    await save_inbox_link(
                        chat_id=MANAGER_CHAT_ID,
                        message_id=msg_id,
                        user_id=ctx.user_id,
                        platform="max",
                        kind="request",
                        label=data.get("mgr_name", ""),
                    )
        except Exception:
            pass

    await ctx.edit(
        "✅ Ваш запрос отправлен менеджеру.\n"
        "Мы свяжемся с вами в ближайшее время. Спасибо!",
        kb=main_menu_kb(),
    )


def register(dp: Dispatcher) -> None:
    dp.callback("action:manager")(on_start_manager)
    dp.state_message(S_DESCRIBE)(on_describe)
    dp.state_message(S_NAME)(on_name)
    dp.state_message(S_PHONE)(on_phone)
