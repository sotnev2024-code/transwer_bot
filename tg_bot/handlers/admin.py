"""
Админ-панель: заказы (список + детали + подтверждение/отмена),
статистика, поездки по дате (календарь), выгрузка пользователей CSV.
"""

import csv
import io
import math
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from shared import settings_store
from shared.config import ADMIN_IDS
from shared.database import (
    get_orders_paginated,
    get_orders_total_count,
    get_admin_stats,
    get_orders_by_date,
    get_orders_by_date_range,
    get_all_users_for_export,
    get_order_by_id,
    update_order_status,
    get_review_stats,
    ADMIN_PER_PAGE,
)
from shared.notifier import send_user_message
from tg_bot.keyboards import (
    admin_menu_kb,
    admin_back_kb,
    admin_orders_kb,
    admin_order_detail_kb,
    calendar_kb,
    range_calendar_kb,
    review_rating_kb,
)
from shared.routes_data import STATUS_LABELS, BAGGAGE_LABELS, STOPS_LABELS

router = Router()

# ─────────────────────────── Утилиты ────────────────────────────────────────


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _build_order_card(order: dict) -> str:
    """Подробная карточка заказа для админа."""
    price_text = (
        f"{order['calculated_price']:,} ₽" if order.get("calculated_price") else "уточняется"
    )
    if order.get("final_price"):
        price_text = f"{order['final_price']:,} ₽ (фин.)"

    children_line = (
        f"\n👶 Детей: <b>{order['children_count']} чел.</b>"
        if order.get("children_count", 0) > 0
        else ""
    )
    mgr_line = (
        f"\n\n💬 Комментарий:\n<i>{order['manager_comment']}</i>"
        if order.get("manager_comment")
        else ""
    )
    username_str = f"@{order.get('username', '')}" if order.get("username") else "нет"

    return (
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
        f"💰 Стоимость: <b>{price_text}</b>\n\n"
        f"👤 {order.get('client_name', '—')}\n"
        f"📱 {order.get('client_phone', '—')}\n"
        f"🆔 TG ID: {order['telegram_id']}"
        f"{mgr_line}\n\n"
        f"🗓 Создан: {str(order['created_at'])[:16]}"
    )


# ─────────────────────────── /admin команда + меню ──────────────────────────


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return  # silent — обычный пользователь не должен знать об админке
    await message.answer(
        "🛠 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == "admin:menu")
async def admin_menu_cb(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    text = "🛠 <b>Панель администратора</b>\n\nВыберите раздел:"
    try:
        await callback.message.edit_text(text, reply_markup=admin_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_menu_kb())
    await callback.answer()


# ─────────────────────────── Все заказы ─────────────────────────────────────


@router.callback_query(F.data.startswith("admin:orders:"))
async def admin_orders(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    parts = callback.data.split(":")          # ["admin", "orders", status, page]
    status = parts[2]
    page = int(parts[3])

    total = await get_orders_total_count(status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    orders = await get_orders_paginated(page, status)

    status_label = {
        "all": "Все", "new": "Новые", "confirmed": "Подтверждённые",
        "cancelled": "Отменённые", "completed": "Завершённые",
    }.get(status, status)

    text = (
        f"📋 <b>Заказы · {status_label}</b>\n"
        f"Всего: {total} | Страница {page + 1}/{total_pages}"
    )
    if not orders:
        text += "\n\n<i>Заказов в этом разделе пока нет.</i>"

    try:
        await callback.message.edit_text(
            text, reply_markup=admin_orders_kb(orders, page, total_pages, status)
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=admin_orders_kb(orders, page, total_pages, status)
        )
    await callback.answer()


# ─────────────────────────── Детали заказа ──────────────────────────────────


@router.callback_query(F.data.startswith("adm_ord:"))
async def admin_order_detail(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # adm_ord:order_id:back_status:back_page
    _, order_id_str, back_status, back_page_str = callback.data.split(":")
    order = await get_order_by_id(int(order_id_str))

    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    text = _build_order_card(order)
    kb = admin_order_detail_kb(order["id"], order["status"], back_status, int(back_page_str))

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


# ─────────────────────────── Подтвердить заказ ──────────────────────────────


@router.callback_query(F.data.startswith("adm_ok:"))
async def admin_confirm_order(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # adm_ok:order_id:back_status:back_page
    _, order_id_str, back_status, back_page_str = callback.data.split(":")
    order_id = int(order_id_str)

    await update_order_status(order_id, "confirmed", "Подтверждён администратором")
    order = await get_order_by_id(order_id)

    if order:
        text = settings_store.get_text(
            "text_order_confirmed",
            order_id=order_id,
            from_city=order["from_city"],
            to_city=order["to_city"],
            trip_date=order["trip_date"],
            trip_time=order["trip_time"],
        )
        await send_user_message(
            user_id=order["telegram_id"],
            platform=order.get("platform", "telegram"),
            text=text,
        )

    await callback.answer("✅ Заказ подтверждён, клиент уведомлён!", show_alert=True)

    # Вернуться к обновлённому списку
    total = await get_orders_total_count(back_status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    back_page = min(int(back_page_str), total_pages - 1)
    orders = await get_orders_paginated(back_page, back_status)

    status_label = {
        "all": "Все", "new": "Новые", "confirmed": "Подтверждённые",
        "cancelled": "Отменённые", "completed": "Завершённые",
    }.get(back_status, back_status)

    try:
        await callback.message.edit_text(
            f"📋 <b>Заказы · {status_label}</b>\nВсего: {total} | Страница {back_page + 1}/{total_pages}",
            reply_markup=admin_orders_kb(orders, back_page, total_pages, back_status),
        )
    except Exception:
        pass


# ─────────────────────────── Отменить заказ ─────────────────────────────────


@router.callback_query(F.data.startswith("adm_no:"))
async def admin_cancel_order(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # adm_no:order_id:back_status:back_page
    _, order_id_str, back_status, back_page_str = callback.data.split(":")
    order_id = int(order_id_str)

    await update_order_status(order_id, "cancelled", "Отменён администратором")
    order = await get_order_by_id(order_id)

    if order:
        await send_user_message(
            user_id=order["telegram_id"],
            platform=order.get("platform", "telegram"),
            text=(
                f"❌ <b>Заказ #{order_id} отменён.</b>\n\n"
                "Если у вас есть вопросы — свяжитесь с нами через бота."
            ),
        )

    await callback.answer("❌ Заказ отменён, клиент уведомлён!", show_alert=True)

    total = await get_orders_total_count(back_status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    back_page = min(int(back_page_str), total_pages - 1)
    orders = await get_orders_paginated(back_page, back_status)

    status_label = {
        "all": "Все", "new": "Новые", "confirmed": "Подтверждённые",
        "cancelled": "Отменённые", "completed": "Завершённые",
    }.get(back_status, back_status)

    try:
        await callback.message.edit_text(
            f"📋 <b>Заказы · {status_label}</b>\nВсего: {total} | Страница {back_page + 1}/{total_pages}",
            reply_markup=admin_orders_kb(orders, back_page, total_pages, back_status),
        )
    except Exception:
        pass


# ─────────────────────────── Завершить поездку ─────────────────────────────


@router.callback_query(F.data.startswith("adm_done:"))
async def admin_complete_order(callback: CallbackQuery, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # adm_done:order_id:back_status:back_page
    _, order_id_str, back_status, back_page_str = callback.data.split(":")
    order_id = int(order_id_str)

    await update_order_status(order_id, "completed", "Поездка завершена")
    order = await get_order_by_id(order_id)

    if order:
        text = settings_store.get_text(
            "text_trip_completed",
            order_id=order_id,
            from_city=order["from_city"],
            to_city=order["to_city"],
            trip_date=order["trip_date"],
        )
        platform = order.get("platform", "telegram")
        if platform == "telegram":
            # В Telegram отправляем inline-клавиатуру со звёздами
            try:
                await bot.send_message(
                    order["telegram_id"], text, reply_markup=review_rating_kb(order_id),
                )
            except Exception:
                pass
        else:
            # В MAX отправит свой обработчик завершения: текст + инструкция отправить
            # рейтинг числом (1-5), максимальная клавиатура в MAX обслуживается
            # внутри max_bot/handlers/reviews.py. Здесь отправляем простое сообщение.
            await send_user_message(
                user_id=order["telegram_id"],
                platform=platform,
                text=text + "\n\nОтправьте сообщение с числом от 1 до 5, чтобы поставить оценку.",
            )

    await callback.answer("🏁 Поездка завершена, клиенту отправлен запрос отзыва!", show_alert=True)

    total = await get_orders_total_count(back_status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    back_page = min(int(back_page_str), total_pages - 1)
    orders = await get_orders_paginated(back_page, back_status)

    status_label = {
        "all": "Все", "new": "Новые", "confirmed": "Подтверждённые",
        "cancelled": "Отменённые", "completed": "Завершённые",
    }.get(back_status, back_status)

    try:
        await callback.message.edit_text(
            f"📋 <b>Заказы · {status_label}</b>\nВсего: {total} | Страница {back_page + 1}/{total_pages}",
            reply_markup=admin_orders_kb(orders, back_page, total_pages, back_status),
        )
    except Exception:
        pass


# ─────────────────────────── Статистика ─────────────────────────────────────


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    s = await get_admin_stats()
    rs = await get_review_stats()
    obs = s["orders_by_status"]

    lines_orders = [
        f"   • Всего заказов: <b>{s['total_orders']}</b>",
        f"   • 🆕 Новых: <b>{obs.get('new', 0)}</b>",
        f"   • ✅ Подтверждённых: <b>{obs.get('confirmed', 0)}</b>",
        f"   • 🚗 В пути: <b>{obs.get('in_progress', 0)}</b>",
        f"   • 🏁 Завершённых: <b>{obs.get('completed', 0)}</b>",
        f"   • ❌ Отменённых: <b>{obs.get('cancelled', 0)}</b>",
    ]

    text = (
        f"📊 <b>Статистика</b>\n"
        f"<i>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>\n\n"
        f"👥 <b>Пользователи</b>\n"
        f"   • Запустили бота: <b>{s['total_users']}</b>\n"
        f"   • Оформили заказ: <b>{s['users_with_orders']}</b>\n"
        f"   • Конверсия: <b>{s['conversion_rate']}%</b>\n\n"
        f"📋 <b>Заказы</b>\n"
        + "\n".join(lines_orders)
        + f"\n\n💰 <b>Финансы</b>\n"
        f"   • Сумма заказов (не отменённых): <b>{s['total_revenue']:,} ₽</b>\n"
        f"   • Средний чек: <b>{s['avg_price']:,} ₽</b>\n\n"
        f"⭐ <b>Отзывы</b>\n"
        f"   • Всего отзывов: <b>{rs['total_reviews']}</b>\n"
        f"   • Средняя оценка: <b>{rs['avg_rating']}/5</b>"
    )

    try:
        await callback.message.edit_text(text, reply_markup=admin_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_back_kb())
    await callback.answer()


# ─────────────────────────── Поездки по дате — календарь ────────────────────


@router.callback_query(F.data == "admin:calendar")
async def admin_open_calendar(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    now = datetime.now()
    text = "📅 <b>Поездки по дате</b>\n\nВыберите дату в календаре:"
    try:
        await callback.message.edit_text(text, reply_markup=calendar_kb(now.year, now.month))
    except Exception:
        await callback.message.answer(text, reply_markup=calendar_kb(now.year, now.month))
    await callback.answer()


@router.callback_query(F.data.startswith("cal:nav:"))
async def calendar_navigate(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # cal:nav:year:month
    parts = callback.data.split(":")
    year, month = int(parts[2]), int(parts[3])
    await callback.message.edit_reply_markup(reply_markup=calendar_kb(year, month))
    await callback.answer()


@router.callback_query(F.data == "cal:ignore")
async def calendar_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("cal:day:"))
async def calendar_day_selected(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    date_str = callback.data.split("cal:day:")[1]   # DD.MM.YYYY
    orders = await get_orders_by_date(date_str)

    if not orders:
        text = (
            f"📅 <b>Поездки на {date_str}</b>\n\n"
            "На эту дату заказов не найдено."
        )
        try:
            await callback.message.edit_text(text, reply_markup=admin_back_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=admin_back_kb())
        await callback.answer()
        return

    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }

    text = f"📅 <b>Поездки на {date_str}</b>   —   {len(orders)} заказов\n\n"
    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        price = f"{order.get('calculated_price', 0):,} ₽" if order.get("calculated_price") else "—"
        children_note = (
            f" + {order['children_count']} реб." if order.get("children_count", 0) > 0 else ""
        )
        text += (
            f"{icon} <b>#{order['id']}</b>  {order['from_city']} → {order['to_city']}\n"
            f"   🕐 {order['trip_time']}  "
            f"👥 {order['passengers']} чел.{children_note}  "
            f"{'🚐 ' if order['need_minivan'] else ''}"
            f"💰 {price}\n"
            f"   👤 {order.get('client_name', '—')} · {order.get('client_phone', '—')}\n\n"
        )

    # Если текст слишком длинный — обрезаем
    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>... и ещё заказы. Используйте список заказов для просмотра.</i>"

    try:
        await callback.message.edit_text(text, reply_markup=admin_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_back_kb())
    await callback.answer()


# ─────────────────────── Поездки по диапазону дат ───────────────────────────


def _dmY_to_iso(d: str) -> str:
    """DD.MM.YYYY → YYYY-MM-DD."""
    dd, mm, yyyy = d.split(".")
    return f"{yyyy}-{mm}-{dd}"


@router.callback_query(F.data == "admin:range")
async def admin_open_range_calendar(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    now = datetime.now()
    text = (
        "🗓 <b>Поездки за период</b>\n\n"
        "Выберите <b>начальную дату</b> диапазона:"
    )
    kb = range_calendar_kb(now.year, now.month, stage="start")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "calrng:ignore")
async def range_calendar_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("calrng:start:nav:"))
async def range_calendar_start_navigate(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    # calrng:start:nav:Y:M
    parts = callback.data.split(":")
    year, month = int(parts[3]), int(parts[4])
    await callback.message.edit_reply_markup(
        reply_markup=range_calendar_kb(year, month, stage="start")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("calrng:start:day:"))
async def range_calendar_start_selected(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    start_date = callback.data.split("calrng:start:day:")[1]  # DD.MM.YYYY
    dd, mm, yyyy = start_date.split(".")
    text = (
        f"🗓 <b>Поездки за период</b>\n\n"
        f"Начало: <b>{start_date}</b>\n\n"
        f"Теперь выберите <b>конечную дату</b>:"
    )
    kb = range_calendar_kb(int(yyyy), int(mm), stage="end", start_date=start_date)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("calrng:end:nav:"))
async def range_calendar_end_navigate(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    # calrng:end:nav:Y:M:START
    parts = callback.data.split(":")
    year, month = int(parts[3]), int(parts[4])
    start_date = parts[5] if len(parts) > 5 else ""
    await callback.message.edit_reply_markup(
        reply_markup=range_calendar_kb(year, month, stage="end", start_date=start_date)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("calrng:end:day:"))
async def range_calendar_end_selected(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    # calrng:end:day:DD.MM.YYYY:DD.MM.YYYY
    rest = callback.data.split("calrng:end:day:")[1]
    end_date, start_date = rest.split(":")

    start_iso = _dmY_to_iso(start_date)
    end_iso = _dmY_to_iso(end_date)

    # Если пользователь перепутал порядок — меняем местами
    if start_iso > end_iso:
        start_iso, end_iso = end_iso, start_iso
        start_date, end_date = end_date, start_date

    orders = await get_orders_by_date_range(start_iso, end_iso)

    header = f"🗓 <b>Поездки: {start_date} — {end_date}</b>"

    if not orders:
        text = header + "\n\nВ выбранный период заказов не найдено."
        try:
            await callback.message.edit_text(text, reply_markup=admin_back_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=admin_back_kb())
        await callback.answer()
        return

    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }

    # Подсчёт выручки (кроме отменённых)
    total_rev = 0
    for o in orders:
        if o["status"] == "cancelled":
            continue
        total_rev += o.get("final_price") or o.get("calculated_price") or 0

    text = header + f"   —   {len(orders)} заказов\n"
    text += f"💰 Итого (не отменённых): <b>{total_rev:,} ₽</b>\n\n"

    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        price_val = order.get("final_price") or order.get("calculated_price") or 0
        price = f"{price_val:,} ₽" if price_val else "—"
        children_note = (
            f" + {order['children_count']} реб." if order.get("children_count", 0) > 0 else ""
        )
        text += (
            f"{icon} <b>#{order['id']}</b>  {order['trip_date']} {order['trip_time']}\n"
            f"   {order['from_city']} → {order['to_city']}\n"
            f"   👥 {order['passengers']} чел.{children_note}  "
            f"{'🚐 ' if order['need_minivan'] else ''}"
            f"💰 {price}\n"
            f"   👤 {order.get('client_name', '—')} · {order.get('client_phone', '—')}\n\n"
        )

    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>... и ещё заказы. Сузьте диапазон для просмотра всех.</i>"

    try:
        await callback.message.edit_text(text, reply_markup=admin_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_back_kb())
    await callback.answer()


# ─────────────────────────── Выгрузка CSV ───────────────────────────────────


@router.callback_query(F.data == "admin:export")
async def admin_export_csv(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return

    await callback.answer("⏳ Формирую файл...")

    users = await get_all_users_for_export()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Telegram ID",
        "Username",
        "Имя",
        "Фамилия",
        "Кол-во заказов",
        "Дата последнего заказа",
        "Сумма заказов (руб.)",
        "Дата регистрации",
    ])
    for u in users:
        writer.writerow([
            u["telegram_id"],
            u["username"] or "",
            u["first_name"] or "",
            u["last_name"] or "",
            u["orders_count"],
            str(u["last_order_date"] or "")[:16],
            u["total_spent"] or 0,
            str(u["created_at"] or "")[:16],
        ])

    # UTF-8 с BOM — корректно открывается в Excel
    csv_bytes = "\ufeff".encode("utf-8") + output.getvalue().encode("utf-8")
    filename = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file = BufferedInputFile(csv_bytes, filename=filename)

    await callback.message.answer_document(
        file,
        caption=(
            f"📤 <b>Выгрузка пользователей</b>\n"
            f"Записей: {len(users)}\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        ),
        reply_markup=admin_back_kb(),
    )


# ─────────────────────────── Заглушка для служебных кнопок ──────────────────


@router.callback_query(F.data == "adm:pg_info")
async def admin_page_info(callback: CallbackQuery) -> None:
    await callback.answer()
