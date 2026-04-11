"""
«Мои заказы» для MAX-бота.
"""

from shared.database import get_user_orders, get_order_by_id, cancel_order
from shared.routes_data import BAGGAGE_LABELS, STOPS_LABELS, STATUS_LABELS

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import (
    my_orders_kb, order_detail_kb, confirm_cancel_kb, main_menu_kb, back_to_menu_kb,
)


async def on_show_orders(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    orders = await get_user_orders(ctx.user_id, platform="max")
    if not orders:
        await ctx.edit(
            "📋 <b>Мои заказы</b>\n\nУ вас пока нет оформленных заказов.\n"
            "Нажмите <b>Оформить трансфер</b>, чтобы создать первый.",
            kb=main_menu_kb(),
        )
        return

    text = f"📋 <b>Мои заказы</b> ({len(orders)})\n\nВыберите заказ для просмотра:"
    await ctx.edit(text, kb=my_orders_kb(orders))


async def on_order_detail(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    order_id = int(ctx.payload.split(":", 1)[1])
    order = await get_order_by_id(order_id)
    if not order or order.get("platform") != "max" or order.get("telegram_id") != ctx.user_id:
        await ctx.edit("❌ Заказ не найден.", kb=main_menu_kb())
        return

    price = order.get("final_price") or order.get("calculated_price") or 0
    price_text = f"{price:,} ₽" if price else "уточняется"
    children_line = (
        f"\n👶 Детей: <b>{order['children_count']}</b>"
        if order.get("children_count", 0) > 0
        else ""
    )
    text = (
        f"📋 <b>Заказ #{order['id']}</b>\n"
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
        f"💰 Стоимость: <b>{price_text}</b>"
    )
    await ctx.edit(text, kb=order_detail_kb(order["id"], order["status"]))


async def on_cancel_confirm_ask(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    order_id = int(ctx.payload.split(":", 1)[1])
    await ctx.edit(
        f"Вы уверены, что хотите отменить заказ #{order_id}?",
        kb=confirm_cancel_kb(order_id),
    )


async def on_cancel_confirmed(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    order_id = int(ctx.payload.split(":", 1)[1])
    ok = await cancel_order(order_id, ctx.user_id, platform="max")
    if ok:
        await ctx.edit(
            f"✅ Заказ #{order_id} отменён.\n\nМенеджер получит уведомление.",
            kb=main_menu_kb(),
        )
        # Сообщим менеджеру в Telegram
        try:
            from max_bot.notify_manager import _TG_API
            import httpx
            from shared.config import BOT_TOKEN, MANAGER_CHAT_ID
            if BOT_TOKEN and MANAGER_CHAT_ID:
                async with httpx.AsyncClient(timeout=10.0) as cli:
                    await cli.post(
                        f"{_TG_API}/bot{BOT_TOKEN}/sendMessage",
                        json={
                            "chat_id": MANAGER_CHAT_ID,
                            "text": f"ℹ️ Клиент отменил заказ *#{order_id}* (MAX).",
                            "parse_mode": "Markdown",
                        },
                    )
        except Exception:
            pass
    else:
        await ctx.edit(
            "❌ Не удалось отменить заказ (возможно, он уже подтверждён или завершён).",
            kb=main_menu_kb(),
        )


def register(dp: Dispatcher) -> None:
    dp.callback("action:my_orders")(on_show_orders)
    dp.callback("order:")(on_order_detail)
    dp.callback("cancel_order:")(on_cancel_confirm_ask)
    dp.callback("confirm_cancel:")(on_cancel_confirmed)
