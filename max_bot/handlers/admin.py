"""
Админ-панель MAX-бота.

Полный паритет с tg_bot/handlers/admin.py:
  • /admin — главное меню
  • Все заказы (пагинация + фильтр по статусу)
  • Детали заказа + действия (подтвердить / отменить / завершить)
  • Статистика
  • Поездки на дату (одиночный календарь)
  • Поездки за период (двухэтапный календарь диапазона)
  • Выгрузка пользователей CSV (через MAX file upload API)

Доступ ограничен через MAX_ADMIN_IDS из .env. Не-админам всё игнорируется молча.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
from datetime import datetime

import httpx

from max_bot.max_client import MaxApiError

from shared import settings_store
from shared.config import MAX_ADMIN_IDS, MAX_BOT_TOKEN
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
from shared.routes_data import STATUS_LABELS, BAGGAGE_LABELS, STOPS_LABELS

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import (
    admin_menu_kb, admin_back_kb, admin_orders_kb, admin_order_detail_kb,
    admin_calendar_kb, admin_range_calendar_kb,
)


def _is_admin(user_id: int) -> bool:
    return user_id in MAX_ADMIN_IDS


def _build_order_card(order: dict) -> str:
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
    platform_badge = " · 💬 MAX" if (order.get("platform") or "telegram") == "max" else ""

    return (
        f"📋 <b>Заказ #{order['id']}</b>{platform_badge}\n"
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
        f"🆔 User ID: {order['telegram_id']}"
        f"{mgr_line}\n\n"
        f"🗓 Создан: {str(order['created_at'])[:16]}"
    )


def _status_label(status: str) -> str:
    return {
        "all": "Все", "new": "Новые", "confirmed": "Подтверждённые",
        "cancelled": "Отменённые", "completed": "Завершённые",
    }.get(status, status)


# ─────────────────── /admin команда + меню ───────────────────


async def cmd_admin(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return  # silent
    await ctx.send(
        "🛠 <b>Панель администратора</b>\n\nВыберите раздел:",
        kb=admin_menu_kb(),
    )


async def admin_menu_cb(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.edit(
        "🛠 <b>Панель администратора</b>\n\nВыберите раздел:",
        kb=admin_menu_kb(),
    )


# ─────────────────── Все заказы ───────────────────


async def admin_orders_view(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()

    parts = ctx.payload.split(":")  # admin:orders:status:page
    status = parts[2]
    page = int(parts[3])

    total = await get_orders_total_count(status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    orders = await get_orders_paginated(page, status)

    text = (
        f"📋 <b>Заказы · {_status_label(status)}</b>\n"
        f"Всего: {total} | Страница {page + 1}/{total_pages}"
    )
    if not orders:
        text += "\n\n<i>Заказов в этом разделе пока нет.</i>"

    await ctx.edit(text, kb=admin_orders_kb(orders, page, total_pages, status))


# ─────────────────── Детали заказа ───────────────────


async def admin_order_detail(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()

    # adm_ord:order_id:back_status:back_page
    _, order_id_str, back_status, back_page_str = ctx.payload.split(":")
    order = await get_order_by_id(int(order_id_str))
    if not order:
        await ctx.answer_callback("Заказ не найден")
        return

    text = _build_order_card(order)
    kb = admin_order_detail_kb(order["id"], order["status"], back_status, int(back_page_str))
    await ctx.edit(text, kb=kb)


async def _back_to_orders_list(ctx: MaxContext, back_status: str, back_page_str: str) -> None:
    total = await get_orders_total_count(back_status)
    total_pages = max(1, math.ceil(total / ADMIN_PER_PAGE))
    back_page = min(int(back_page_str), total_pages - 1)
    orders = await get_orders_paginated(back_page, back_status)
    await ctx.edit(
        f"📋 <b>Заказы · {_status_label(back_status)}</b>\n"
        f"Всего: {total} | Страница {back_page + 1}/{total_pages}",
        kb=admin_orders_kb(orders, back_page, total_pages, back_status),
    )


async def admin_confirm_order(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    _, order_id_str, back_status, back_page_str = ctx.payload.split(":")
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

    await ctx.answer_callback("✅ Заказ подтверждён, клиент уведомлён!")
    await _back_to_orders_list(ctx, back_status, back_page_str)


async def admin_cancel_order(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    _, order_id_str, back_status, back_page_str = ctx.payload.split(":")
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

    await ctx.answer_callback("❌ Заказ отменён, клиент уведомлён!")
    await _back_to_orders_list(ctx, back_status, back_page_str)


async def admin_complete_order(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    _, order_id_str, back_status, back_page_str = ctx.payload.split(":")
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
        if platform == "max":
            # MAX-юзер получит запрос отзыва, max_bot/handlers/reviews.py
            # ловит callback review_rate:ID:N
            try:
                from max_bot.keyboards import review_rating_kb
                from max_bot.max_client import MaxClient
                cli = MaxClient(MAX_BOT_TOKEN)
                await cli.send_message(
                    chat_id=order["telegram_id"],
                    text=text,
                    attachments=[review_rating_kb(order_id)],
                    fmt="html",
                )
                await cli.close()
            except Exception:
                pass
        else:
            # Telegram-юзеру отправит inline-клавиатуру со звёздами через TG API.
            # Здесь нам её не построить — поэтому просто шлём текст с инструкцией.
            await send_user_message(
                user_id=order["telegram_id"],
                platform=platform,
                text=text + "\n\nОтправьте сообщение с числом от 1 до 5, чтобы поставить оценку.",
            )

    await ctx.answer_callback("🏁 Поездка завершена, клиенту отправлен запрос отзыва!")
    await _back_to_orders_list(ctx, back_status, back_page_str)


# ─────────────────── Статистика ───────────────────


async def admin_stats(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()

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

    await ctx.edit(text, kb=admin_back_kb())


# ─────────────────── Поездки на дату ───────────────────


async def admin_open_calendar(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    now = datetime.now()
    await ctx.edit(
        "📅 <b>Поездки по дате</b>\n\nВыберите дату в календаре:",
        kb=admin_calendar_kb(now.year, now.month),
    )


async def admin_calendar_nav(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    parts = ctx.payload.split(":")  # admcal:nav:Y:M
    year, month = int(parts[2]), int(parts[3])
    await ctx.edit(
        "📅 <b>Поездки по дате</b>\n\nВыберите дату в календаре:",
        kb=admin_calendar_kb(year, month),
    )


async def admin_calendar_ignore(ctx: MaxContext) -> None:
    await ctx.answer_callback()


async def admin_calendar_day(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    date_str = ctx.payload.split("admcal:day:")[1]  # DD.MM.YYYY
    orders = await get_orders_by_date(date_str)

    if not orders:
        await ctx.edit(
            f"📅 <b>Поездки на {date_str}</b>\n\nНа эту дату заказов не найдено.",
            kb=admin_back_kb(),
        )
        return

    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }
    text = f"📅 <b>Поездки на {date_str}</b>   —   {len(orders)} заказов\n\n"
    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        plat = " 💬MAX" if (order.get("platform") or "telegram") == "max" else ""
        price_val = order.get("final_price") or order.get("calculated_price") or 0
        price = f"{price_val:,} ₽" if price_val else "—"
        children_note = (
            f" + {order['children_count']} реб." if order.get("children_count", 0) > 0 else ""
        )
        text += (
            f"{icon}{plat} <b>#{order['id']}</b>  {order['from_city']} → {order['to_city']}\n"
            f"   🕐 {order['trip_time']}  "
            f"👥 {order['passengers']} чел.{children_note}  "
            f"{'🚐 ' if order['need_minivan'] else ''}"
            f"💰 {price}\n"
            f"   👤 {order.get('client_name', '—')} · {order.get('client_phone', '—')}\n\n"
        )

    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>... и ещё заказы. Используйте список заказов.</i>"

    await ctx.edit(text, kb=admin_back_kb())


# ─────────────────── Поездки за период ───────────────────


def _dmY_to_iso(d: str) -> str:
    dd, mm, yyyy = d.split(".")
    return f"{yyyy}-{mm}-{dd}"


async def admin_open_range(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    now = datetime.now()
    await ctx.edit(
        "🗓 <b>Поездки за период</b>\n\nВыберите <b>начальную дату</b> диапазона:",
        kb=admin_range_calendar_kb(now.year, now.month, stage="start"),
    )


async def admin_range_ignore(ctx: MaxContext) -> None:
    await ctx.answer_callback()


async def admin_range_start_nav(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    parts = ctx.payload.split(":")  # admrng:start:nav:Y:M
    year, month = int(parts[3]), int(parts[4])
    await ctx.edit(
        "🗓 <b>Поездки за период</b>\n\nВыберите <b>начальную дату</b>:",
        kb=admin_range_calendar_kb(year, month, stage="start"),
    )


async def admin_range_start_day(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    start_date = ctx.payload.split("admrng:start:day:")[1]  # DD.MM.YYYY
    dd, mm, yyyy = start_date.split(".")
    await ctx.edit(
        f"🗓 <b>Поездки за период</b>\n\n"
        f"Начало: <b>{start_date}</b>\n\n"
        f"Теперь выберите <b>конечную дату</b>:",
        kb=admin_range_calendar_kb(int(yyyy), int(mm), stage="end", start_date=start_date),
    )


async def admin_range_end_nav(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    parts = ctx.payload.split(":")  # admrng:end:nav:Y:M:START
    year, month = int(parts[3]), int(parts[4])
    start_date = parts[5] if len(parts) > 5 else ""
    await ctx.edit(
        f"🗓 <b>Поездки за период</b>\n\nКОНЕЦ (нач.: <b>{start_date}</b>):",
        kb=admin_range_calendar_kb(year, month, stage="end", start_date=start_date),
    )


async def admin_range_end_day(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    rest = ctx.payload.split("admrng:end:day:")[1]
    end_date, start_date = rest.split(":")

    start_iso = _dmY_to_iso(start_date)
    end_iso = _dmY_to_iso(end_date)
    if start_iso > end_iso:
        start_iso, end_iso = end_iso, start_iso
        start_date, end_date = end_date, start_date

    orders = await get_orders_by_date_range(start_iso, end_iso)

    header = f"🗓 <b>Поездки: {start_date} — {end_date}</b>"
    if not orders:
        await ctx.edit(header + "\n\nВ выбранный период заказов не найдено.", kb=admin_back_kb())
        return

    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }
    total_rev = 0
    for o in orders:
        if o["status"] == "cancelled":
            continue
        total_rev += o.get("final_price") or o.get("calculated_price") or 0

    text = header + f"   —   {len(orders)} заказов\n"
    text += f"💰 Итого (не отменённых): <b>{total_rev:,} ₽</b>\n\n"
    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        plat = " 💬MAX" if (order.get("platform") or "telegram") == "max" else ""
        price_val = order.get("final_price") or order.get("calculated_price") or 0
        price = f"{price_val:,} ₽" if price_val else "—"
        children_note = (
            f" + {order['children_count']} реб." if order.get("children_count", 0) > 0 else ""
        )
        text += (
            f"{icon}{plat} <b>#{order['id']}</b>  {order['trip_date']} {order['trip_time']}\n"
            f"   {order['from_city']} → {order['to_city']}\n"
            f"   👥 {order['passengers']} чел.{children_note}  "
            f"{'🚐 ' if order['need_minivan'] else ''}"
            f"💰 {price}\n"
            f"   👤 {order.get('client_name', '—')} · {order.get('client_phone', '—')}\n\n"
        )

    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>... и ещё заказы. Сузьте диапазон.</i>"

    await ctx.edit(text, kb=admin_back_kb())


# ─────────────────── Выгрузка пользователей CSV ───────────────────


async def admin_export_csv(ctx: MaxContext) -> None:
    """
    Формирует CSV в памяти, заливает в MAX через POST /uploads, прикрепляет
    как file-attachment к новому сообщению.
    """
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback("⏳ Формирую файл…")

    users = await get_all_users_for_export()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "User ID", "Platform", "Username", "Имя", "Фамилия",
        "Кол-во заказов", "Дата последнего заказа",
        "Сумма заказов (руб.)", "Дата регистрации",
    ])
    for u in users:
        writer.writerow([
            u["telegram_id"],
            u.get("platform", "telegram"),
            u["username"] or "",
            u["first_name"] or "",
            u["last_name"] or "",
            u["orders_count"],
            str(u["last_order_date"] or "")[:16],
            u["total_spent"] or 0,
            str(u["created_at"] or "")[:16],
        ])

    csv_bytes = "\ufeff".encode("utf-8") + output.getvalue().encode("utf-8")
    filename = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # ── MAX file upload flow ──
    # 1. POST /uploads?type=file → {url, token?}
    # 2. POST <url> с multipart-полем "data" (важно: SDK использует именно "data",
    #    httpx-default "file" — НЕ работает, MAX upload-сервер вернёт пустой ответ)
    # 3. Ответ: {id: number, token: string} — берём token и кладём в attachment
    upload_ok = False
    file_attachment: dict | None = None
    upload_err: str | None = None

    try:
        upload_info = await ctx.client.get_upload_url(kind="file")
        upload_url = upload_info.get("url")
        # Иногда token уже выдан в ответе на /uploads
        token = upload_info.get("token")

        if upload_url:
            async with httpx.AsyncClient(timeout=30.0) as cli:
                files = {"data": (filename, csv_bytes, "text/csv")}
                up = await cli.post(upload_url, files=files)
            if up.status_code in (200, 201):
                resp = up.json() if up.content else {}
                # Если token не пришёл с /uploads — берём из ответа upload-сервера
                if not token:
                    token = resp.get("token")
            else:
                upload_err = f"upload {up.status_code}: {up.text[:200]}"

        if token:
            file_attachment = {"type": "file", "payload": {"token": token}}
            upload_ok = True
    except Exception as e:
        upload_err = f"exception: {e}"

    if upload_ok and file_attachment:
        # MAX обрабатывает залитый файл асинхронно. Если попытаться прикрепить
        # его к сообщению сразу, придёт 400 attachment.not.ready. Делаем
        # повторные попытки с экспоненциальной задержкой (~22 сек суммарно).
        message_text = (
            f"📤 <b>Выгрузка пользователей</b>\n"
            f"Записей: {len(users)}\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        delays = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
        last_err: str | None = None

        for attempt, delay in enumerate(delays, start=1):
            await asyncio.sleep(delay)
            try:
                await ctx.client.send_message(
                    chat_id=ctx.chat_id,
                    text=message_text,
                    attachments=[file_attachment],
                    fmt="html",
                )
                return  # успех
            except MaxApiError as e:
                last_err = f"{e.status}: {e.body[:200]}"
                # «attachment.not.ready» — файл ещё не обработан, повторяем
                if e.status == 400 and "attachment.not.ready" in e.body:
                    continue
                # Любая другая ошибка — нет смысла ретраить
                break
            except Exception as e:
                last_err = f"send_message: {e}"
                break

        upload_err = last_err or "attachment.not.ready (превышено время ожидания)"

    # Fallback: если файл загрузить не удалось — присылаем хотя бы текстовую сводку
    await ctx.send(
        f"📤 <b>Выгрузка пользователей</b>\n"
        f"Записей: <b>{len(users)}</b>\n\n"
        f"⚠️ Не удалось приложить CSV-файл (MAX API uploads).\n"
        f"<i>Детали: {upload_err or 'unknown'}</i>",
        kb=admin_back_kb(),
    )


# ─────────────────── Заглушка для служебных кнопок ───────────────────


async def admin_pg_info(ctx: MaxContext) -> None:
    await ctx.answer_callback()


# ─────────────────── Регистрация ───────────────────


def register(dp: Dispatcher) -> None:
    dp.command("admin")(cmd_admin)

    # Меню
    dp.callback("admin:menu")(admin_menu_cb)

    # Заказы
    dp.callback("admin:orders:")(admin_orders_view)
    dp.callback("adm_ord:")(admin_order_detail)
    dp.callback("adm_ok:")(admin_confirm_order)
    dp.callback("adm_no:")(admin_cancel_order)
    dp.callback("adm_done:")(admin_complete_order)
    dp.callback("adm:pg_info")(admin_pg_info)

    # Статистика
    dp.callback("admin:stats")(admin_stats)

    # Календарь — одна дата
    dp.callback("admin:calendar")(admin_open_calendar)
    dp.callback("admcal:nav:")(admin_calendar_nav)
    dp.callback("admcal:day:")(admin_calendar_day)
    dp.callback("admcal:ignore")(admin_calendar_ignore)

    # Календарь — диапазон
    dp.callback("admin:range")(admin_open_range)
    dp.callback("admrng:ignore")(admin_range_ignore)
    dp.callback("admrng:start:nav:")(admin_range_start_nav)
    dp.callback("admrng:start:day:")(admin_range_start_day)
    dp.callback("admrng:end:nav:")(admin_range_end_nav)
    dp.callback("admrng:end:day:")(admin_range_end_day)

    # CSV
    dp.callback("admin:export")(admin_export_csv)
