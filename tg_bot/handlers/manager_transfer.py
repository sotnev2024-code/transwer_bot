import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from tg_bot.states import ManagerStates
from tg_bot.keyboards import back_to_menu_kb, main_menu_kb
from shared.config import MANAGER_CHAT_ID
from shared.database import save_inbox_link

router = Router()


@router.callback_query(F.data == "action:manager")
async def start_manager_transfer(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ManagerStates.describe)
    text = (
        "📞 <b>Связь с менеджером</b>\n\n"
        "Опишите ваш запрос: нестандартный маршрут, дополнительные вопросы, "
        "особые условия или любой другой вопрос.\n\n"
        "Мы ответим в ближайшее время!"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=back_to_menu_kb())
    await callback.answer()


@router.message(StateFilter(ManagerStates.describe))
async def get_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await state.set_state(ManagerStates.get_name)
    await message.answer(
        "✏️ Введите ваше <b>имя</b>:",
        reply_markup=back_to_menu_kb(),
    )


@router.message(StateFilter(ManagerStates.get_name))
async def manager_get_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Введите корректное имя:", reply_markup=back_to_menu_kb())
        return
    await state.update_data(client_name=name)
    await state.set_state(ManagerStates.get_phone)
    await message.answer(
        f"✅ {name}\n\n📱 Введите ваш <b>номер телефона</b>:",
        reply_markup=back_to_menu_kb(),
    )


@router.message(StateFilter(ManagerStates.get_phone))
async def manager_get_phone(message: Message, state: FSMContext, bot: Bot) -> None:
    phone = message.text.strip()
    phone_clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not re.match(r"^[+]?[78]?\d{10}$", phone_clean):
        await message.answer(
            "❌ Введите корректный номер телефона.\n\nПример: +79123456789",
            reply_markup=back_to_menu_kb(),
        )
        return

    data = await state.get_data()
    await state.clear()

    username_str = f"@{message.from_user.username}" if message.from_user.username else "без username"

    if MANAGER_CHAT_ID:
        manager_text = (
            "📩 <b>ЗАПРОС ОТ КЛИЕНТА</b>\n\n"
            f"👤 Имя: <b>{data.get('client_name', '')}</b>\n"
            f"📱 Телефон: <b>{phone}</b>\n"
            f"🆔 Telegram: {username_str} (ID: {message.from_user.id})\n\n"
            f"💬 Запрос:\n{data.get('description', '')}\n\n"
            "<i>↩️ Ответьте реплаем на это сообщение — клиент получит ответ в Telegram.</i>"
        )
        try:
            sent = await bot.send_message(MANAGER_CHAT_ID, manager_text)
            await save_inbox_link(
                chat_id=MANAGER_CHAT_ID,
                message_id=sent.message_id,
                user_id=message.from_user.id,
                platform="telegram",
                kind="request",
                label=data.get("client_name", ""),
            )
        except Exception as e:
            print(f"[WARN] Не удалось уведомить менеджера: {e}")

    await message.answer(
        f"✅ <b>Запрос отправлен!</b>\n\n"
        f"Менеджер получил ваше сообщение и свяжется с вами по номеру <b>{phone}</b>.\n\n"
        "Обычно мы отвечаем в течение 15–30 минут. 🙏",
        reply_markup=main_menu_kb(),
    )
