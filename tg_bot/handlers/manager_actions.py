"""
Обработчики действий менеджера по заказу.

ВАЖНО: все уведомления клиенту уходят через `shared.notifier.send_user_message`,
который сам выберет нужный мессенджер по полю `orders.platform`
(telegram или max). Менеджер работает в Telegram, но может управлять
заказами, созданными и в MAX-боте.
"""

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from shared import settings_store
from shared.database import get_order_by_id, update_order_status, update_order_final_price
from shared.notifier import send_user_message
from tg_bot.states import ManagerPriceStates

router = Router()


@router.callback_query(F.data.startswith("mgr_accept:"))
async def manager_accept(callback: CallbackQuery, bot: Bot) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    await update_order_status(order_id, "confirmed", "Заказ подтверждён менеджером")

    order = await get_order_by_id(order_id)
    if order:
        price = order.get("final_price") or order.get("calculated_price")
        price_line = f"\n💰 <b>Стоимость: {price:,} ₽</b>" if price else ""

        text = settings_store.get_text(
            "text_order_confirmed",
            order_id=order_id,
            from_city=order["from_city"],
            to_city=order["to_city"],
            trip_date=order["trip_date"],
            trip_time=order["trip_time"],
        ) + price_line
        await send_user_message(
            user_id=order["telegram_id"],
            platform=order.get("platform", "telegram"),
            text=text,
        )

    manager_name = callback.from_user.username or callback.from_user.first_name or "менеджер"
    platform_badge = _platform_badge(order)
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>Принят</b> (@{manager_name}){platform_badge}",
        )
    except Exception:
        pass
    await callback.answer("Заказ принят и клиент уведомлён!")


@router.callback_query(F.data.startswith("mgr_reject:"))
async def manager_reject(callback: CallbackQuery, bot: Bot) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    await update_order_status(order_id, "cancelled", "Отклонён менеджером")

    order = await get_order_by_id(order_id)
    if order:
        await send_user_message(
            user_id=order["telegram_id"],
            platform=order.get("platform", "telegram"),
            text=(
                f"❌ <b>По заказу #{order_id} возникли трудности.</b>\n\n"
                "К сожалению, мы не можем выполнить эту поездку на указанных условиях. "
                "Пожалуйста, свяжитесь с нами для уточнения деталей или оформите новый заказ."
            ),
        )

    manager_name = callback.from_user.username or callback.from_user.first_name or "менеджер"
    platform_badge = _platform_badge(order)
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n❌ <b>Отклонён</b> (@{manager_name}){platform_badge}",
        )
    except Exception:
        pass
    await callback.answer("Заказ отклонён и клиент уведомлён")


@router.callback_query(F.data.startswith("mgr_contact:"))
async def manager_contact(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = await get_order_by_id(order_id)
    if order:
        platform = order.get("platform", "telegram").upper()
        await callback.answer(
            f"Клиент: {order.get('client_name', '—')}\n"
            f"Тел.: {order.get('client_phone', '—')}\n"
            f"Платформа: {platform}\n"
            f"User ID: {order['telegram_id']}",
            show_alert=True,
        )
    else:
        await callback.answer("Заказ не найден", show_alert=True)


# ─────────────────────── Установка финальной цены ────────────────────────────


@router.callback_query(F.data.startswith("mgr_set_price:"))
async def manager_set_price_start(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = await get_order_by_id(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    calc = order.get("calculated_price") or 0
    calc_line = f"\nПредварительная: <b>{calc:,} ₽</b>" if calc else ""

    await state.set_state(ManagerPriceStates.waiting_price)
    await state.update_data(order_id=order_id)

    await callback.message.answer(
        f"💰 <b>Установка цены — Заказ #{order_id}</b>\n\n"
        f"📍 {order['from_city']} → {order['to_city']}\n"
        f"📅 {order['trip_date']} в {order['trip_time']}\n"
        f"👥 Пассажиров: {order['passengers']}"
        f"{calc_line}\n\n"
        "Введите <b>финальную стоимость</b> (только цифры, в рублях):",
    )
    await callback.answer()


@router.message(StateFilter(ManagerPriceStates.waiting_price))
async def manager_set_price_input(message: Message, state: FSMContext, bot: Bot) -> None:
    text = message.text.strip() if message.text else ""
    if not text.isdigit() or int(text) <= 0:
        await message.answer("❌ Введите корректную сумму (целое число больше 0):")
        return

    final_price = int(text)
    data = await state.get_data()
    order_id = data["order_id"]
    await state.clear()

    await update_order_final_price(order_id, final_price)
    order = await get_order_by_id(order_id)

    # Уведомляем клиента с финальной ценой — через cross-platform notifier
    if order:
        await send_user_message(
            user_id=order["telegram_id"],
            platform=order.get("platform", "telegram"),
            text=(
                f"✅ <b>Заказ #{order_id} подтверждён!</b>\n\n"
                f"📍 {order['from_city']} → {order['to_city']}\n"
                f"📅 {order['trip_date']} в {order['trip_time']}\n"
                f"👥 Пассажиров: {order['passengers']}\n\n"
                f"💰 <b>Финальная стоимость: {final_price:,} ₽</b>\n\n"
                "Водитель свяжется с вами накануне поездки. Ждём вас! 🚗"
            ),
        )

    manager_name = message.from_user.username or message.from_user.first_name or "менеджер"
    platform_name = (order.get("platform", "telegram") if order else "telegram").upper()
    await message.answer(
        f"✅ Цена <b>{final_price:,} ₽</b> установлена.\n"
        f"Заказ <b>#{order_id}</b> ({platform_name}) подтверждён, клиент уведомлён. (@{manager_name})"
    )


def _platform_badge(order: dict | None) -> str:
    if not order:
        return ""
    p = (order.get("platform") or "telegram").lower()
    return " · 💬 MAX" if p == "max" else ""
