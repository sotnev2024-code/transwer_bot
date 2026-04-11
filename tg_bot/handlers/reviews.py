"""
Обработка отзывов: оценка + текстовый комментарий после завершения поездки.
"""

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from shared import settings_store
from shared.config import ADMIN_IDS
from shared.database import save_review, get_order_by_id, get_review_by_order
from tg_bot.keyboards import review_text_kb, back_to_menu_kb
from tg_bot.states import ReviewStates

router = Router()


@router.callback_query(F.data.startswith("review_rate:"))
async def review_set_rating(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    order_id = int(parts[1])
    rating = int(parts[2])

    existing = await get_review_by_order(order_id)
    if existing:
        await callback.answer("Вы уже оставили отзыв на этот заказ.", show_alert=True)
        return

    await state.update_data(review_order_id=order_id, review_rating=rating)
    await state.set_state(ReviewStates.waiting_text)

    await callback.message.edit_text(
        f"Спасибо за оценку <b>{'⭐' * rating}</b>!\n\n"
        "Напишите комментарий к поездке или нажмите «Пропустить»:",
        reply_markup=review_text_kb(order_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review_skip:"))
async def review_skip(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Хорошо, спасибо! Ждём вас снова 🚗",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review_notext:"))
async def review_no_text(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    order_id = data.get("review_order_id")
    rating = data.get("review_rating")

    if order_id and rating:
        order = await get_order_by_id(order_id)
        tid = order["telegram_id"] if order else callback.from_user.id
        await save_review(order_id, tid, rating, None, platform="telegram")
        await _notify_admins_about_review(bot, order_id, rating, None)

    await state.clear()
    stars = "⭐" * (rating or 0)
    thanks = settings_store.get_text("text_review_thanks", stars=stars)
    await callback.message.edit_text(thanks, reply_markup=back_to_menu_kb())
    await callback.answer()


@router.message(ReviewStates.waiting_text)
async def review_get_text(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    order_id = data.get("review_order_id")
    rating = data.get("review_rating")
    review_text = message.text.strip() if message.text else None

    if order_id and rating:
        order = await get_order_by_id(order_id)
        tid = order["telegram_id"] if order else message.from_user.id
        await save_review(order_id, tid, rating, review_text, platform="telegram")
        await _notify_admins_about_review(bot, order_id, rating, review_text)

    await state.clear()
    stars = "⭐" * (rating or 0)
    thanks = settings_store.get_text("text_review_thanks", stars=stars)
    await message.answer(thanks, reply_markup=back_to_menu_kb())


async def _notify_admins_about_review(
    bot: Bot, order_id: int, rating: int, text: str | None
) -> None:
    order = await get_order_by_id(order_id)
    if not order:
        return

    review_msg = (
        f"📝 <b>Новый отзыв</b>\n\n"
        f"Заказ: <b>#{order_id}</b>\n"
        f"Маршрут: {order['from_city']} → {order['to_city']}\n"
        f"Клиент: {order.get('client_name', '—')}\n"
        f"Оценка: {'⭐' * rating} ({rating}/5)\n"
    )
    if text:
        review_msg += f"\n💬 <i>{text}</i>"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, review_msg)
        except Exception:
            pass
