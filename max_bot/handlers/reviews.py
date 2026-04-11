"""
Отзывы в MAX-боте.

Когда Telegram-админ помечает поездку завершённой (adm_done),
notifier отправляет MAX-пользователю сообщение с просьбой оценить поездку.
Здесь мы принимаем:
  • callback review_rate:ORDER:N (1..5)
  • callback review_skip:ORDER
  • следующий текстовый ответ — как комментарий
"""

from shared import settings_store
from shared.database import save_review, get_order_by_id

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import review_rating_kb, review_text_kb, main_menu_kb


S_WAITING_TEXT = "review:waiting_text"


async def on_review_rate(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    parts = ctx.payload.split(":")  # review_rate:ORDER:N
    order_id = int(parts[1])
    rating = int(parts[2])
    await ctx.state.update_data(review_order_id=order_id, review_rating=rating)
    await ctx.state.set_state(S_WAITING_TEXT)
    stars = "⭐" * rating
    await ctx.edit(
        f"Спасибо за оценку {stars}!\n\n"
        "💬 Напишите комментарий к поездке (или нажмите «Пропустить»):",
        kb=review_text_kb(order_id),
    )


async def on_review_skip(ctx: MaxContext) -> None:
    """Пользователь отказался оценивать."""
    await ctx.answer_callback()
    await ctx.state.clear()
    await ctx.edit("Спасибо! Ждём вас снова 🚗", kb=main_menu_kb())


async def on_review_notext(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    data = await ctx.state.get_data()
    order_id = data.get("review_order_id")
    rating = data.get("review_rating")
    if order_id and rating:
        order = await get_order_by_id(order_id)
        uid = order["telegram_id"] if order else ctx.user_id
        await save_review(order_id, uid, rating, None, platform="max")
    await ctx.state.clear()
    stars = "⭐" * (rating or 0)
    thanks = settings_store.get_text("text_review_thanks", stars=stars)
    await ctx.edit(thanks, kb=main_menu_kb())


async def on_review_text(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    order_id = data.get("review_order_id")
    rating = data.get("review_rating")
    review_text = (ctx.text or "").strip() or None

    if order_id and rating:
        order = await get_order_by_id(order_id)
        uid = order["telegram_id"] if order else ctx.user_id
        await save_review(order_id, uid, rating, review_text, platform="max")

    await ctx.state.clear()
    stars = "⭐" * (rating or 0)
    thanks = settings_store.get_text("text_review_thanks", stars=stars)
    await ctx.edit(thanks, kb=main_menu_kb())


def register(dp: Dispatcher) -> None:
    dp.callback("review_rate:")(on_review_rate)
    dp.callback("review_skip:")(on_review_skip)
    dp.callback("review_notext:")(on_review_notext)
    dp.state_message(S_WAITING_TEXT)(on_review_text)
