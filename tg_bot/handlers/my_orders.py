from aiogram import Router, F
from aiogram.types import CallbackQuery

from tg_bot.keyboards import my_orders_kb, order_detail_kb, confirm_cancel_kb, back_to_menu_kb
from shared.database import get_user_orders, get_order_by_id, cancel_order
from shared.routes_data import BAGGAGE_LABELS, STOPS_LABELS, STATUS_LABELS

router = Router()


@router.callback_query(F.data == "action:my_orders")
async def show_my_orders(callback: CallbackQuery) -> None:
    orders = await get_user_orders(callback.from_user.id, platform="telegram")
    try:
        await callback.message.delete()
    except Exception:
        pass
    if not orders:
        text = (
            "📋 <b>Мои заказы</b>\n\n"
            "У вас пока нет заказов.\n\n"
            "Оформите первый трансфер прямо сейчас!"
        )
        await callback.message.answer(text, reply_markup=back_to_menu_kb())
    else:
        text = f"📋 <b>Мои заказы</b> (последние {len(orders)})\n\nВыберите заказ для просмотра:"
        await callback.message.answer(text, reply_markup=my_orders_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("order:"))
async def show_order_detail(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = await get_order_by_id(order_id)

    if not order or order["telegram_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    price_text = f"{order['calculated_price']:,} ₽" if order.get("calculated_price") else "уточняется"
    if order.get("final_price"):
        price_text = f"{order['final_price']:,} ₽ (подтверждено)"

    children_line = (
        f"\n👶 Детей: <b>{order['children_count']} чел.</b>"
        if order.get("children_count", 0) > 0
        else ""
    )
    manager_line = (
        f"\n\n💬 Комментарий менеджера:\n<i>{order['manager_comment']}</i>"
        if order.get("manager_comment")
        else ""
    )

    text = (
        f"📋 <b>Заказ #{order['id']}</b>\n\n"
        f"Статус: <b>{STATUS_LABELS.get(order['status'], order['status'])}</b>\n\n"
        f"📍 Откуда: <b>{order['from_city']}</b>\n"
        f"🏁 Куда: <b>{order['to_city']}</b>\n"
        f"📅 Дата: <b>{order['trip_date']}</b>\n"
        f"🕐 Время: <b>{order['trip_time']}</b>\n"
        f"👥 Пассажиров: <b>{order['passengers']}</b>"
        f"{children_line}\n"
        f"🧳 Багаж: <b>{BAGGAGE_LABELS.get(order['baggage'], order['baggage'])}</b>\n"
        f"🚐 Минивэн: <b>{'Да' if order['need_minivan'] else 'Нет'}</b>\n"
        f"📍 Остановки: <b>{STOPS_LABELS.get(order['stops'], order['stops'])}</b>\n\n"
        f"💰 Стоимость: <b>{price_text}</b>\n\n"
        f"👤 {order.get('client_name', '—')} · {order.get('client_phone', '—')}"
        f"{manager_line}\n\n"
        f"🗓 Создан: {str(order['created_at'])[:16]}"
    )

    try:
        await callback.message.edit_text(
            text, reply_markup=order_detail_kb(order_id, order["status"])
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=order_detail_kb(order_id, order["status"])
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_order:"))
async def confirm_cancel_order(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    order = await get_order_by_id(order_id)

    if not order or order["telegram_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"❓ Вы уверены, что хотите отменить <b>заказ #{order_id}</b>?\n\n"
        f"📍 {order['from_city']} → {order['to_city']}\n"
        f"📅 {order['trip_date']} в {order['trip_time']}",
        reply_markup=confirm_cancel_kb(order_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def do_cancel_order(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":", 1)[1])
    success = await cancel_order(order_id, callback.from_user.id, platform="telegram")

    if success:
        await callback.message.edit_text(
            f"✅ Заказ <b>#{order_id}</b> успешно отменён.\n\n"
            "Если у вас остались вопросы — свяжитесь с менеджером.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await callback.answer("Не удалось отменить заказ", show_alert=True)
        return
    await callback.answer()
