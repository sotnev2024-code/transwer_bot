"""
10-шаговое бронирование в MAX-боте — порт tg_bot/handlers/booking.py.

Структура та же, отличия только в UI: вместо aiogram FSMContext —
наш собственный, вместо inline_keyboard — MAX-attachments.
"""

from __future__ import annotations

import re
from datetime import datetime

from shared import settings_store
from shared.database import (
    create_order, get_route_price, get_departure_cities, get_destination_cities,
)
from shared.price_calculator import calculate_price, calculate_price_by_km
from shared.geo_calculator import geocode_address, get_route_distance_km
from shared.routes_data import BAGGAGE_LABELS, STOPS_LABELS, CITY_COORDS

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import (
    departure_city_kb, destination_city_kb, date_presets_kb, calendar_kb,
    time_kb, passengers_kb, yes_no_kb, children_count_kb, baggage_kb,
    stops_kb, confirm_order_kb, contact_kb, address_confirm_kb,
    address_not_found_kb, back_to_menu_kb, main_menu_kb,
)
from max_bot.notify_manager import notify_manager_new_max_order


# ── FSM states ──
S_FROM_CITY = "book:from_city"
S_CUSTOM_FROM = "book:custom_from"
S_TO_CITY = "book:to_city"
S_CUSTOM_TO = "book:custom_to"
S_TRIP_DATE_CUSTOM = "book:trip_date_custom"  # ввод даты текстом
S_TRIP_TIME_CUSTOM = "book:trip_time_custom"
S_GET_NAME = "book:get_name"
S_GET_PHONE = "book:get_phone"

_CUSTOM_FROM = "📍 Указать адрес"
_CUSTOM_TO = "📍 Указать место"


def _step_header(step_name: str) -> str:
    all_steps = ["from_city", "to_city", "trip_date", "trip_time", "passengers"]
    for key in ("children", "baggage", "minivan", "stops"):
        if settings_store.is_step_enabled(key):
            all_steps.append(key)
    all_steps.extend(["confirm", "name", "phone"])
    total = len(all_steps)
    num = all_steps.index(step_name) + 1 if step_name in all_steps else "?"
    return f"<b>Оформление трансфера</b> · Шаг {num} из {total}\n\n"


# ═══════════════════════════ ЗАПУСК БРОНИРОВАНИЯ ═══════════════════════════


async def on_start_booking(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.clear()
    await ctx.state.set_state(S_FROM_CITY)
    cities = await get_departure_cities()
    await ctx.edit(
        _step_header("from_city") + "📍 Выберите <b>город отправления</b>:",
        kb=departure_city_kb(cities),
    )


# ═══════════════════════════ ШАГ 1: ОТКУДА ═══════════════════════════════════


async def on_from_selected(ctx: MaxContext) -> None:
    city = ctx.payload.split(":", 1)[1]
    await ctx.answer_callback()

    if city == "Другой город":
        await ctx.state.set_state(S_FROM_CITY)
        await ctx.state.update_data(awaiting_custom_from=True)
        await ctx.edit(
            "✏️ Введите название <b>города отправления</b>:",
            kb=back_to_menu_kb(),
        )
        return

    if city == _CUSTOM_FROM:
        await ctx.state.update_data(use_custom_route=True, use_custom_from=True)
        await ctx.state.set_state(S_CUSTOM_FROM)
        await ctx.edit(
            _step_header("from_city")
            + "📍 Введите <b>адрес или место отправления</b>:\n\n"
            "<i>Например: ул. Ленина 5, Барнаул — или «аэропорт Горно-Алтайск»</i>",
            kb=back_to_menu_kb(),
        )
        return

    await ctx.state.update_data(from_city=city)
    await _proceed_to_destination(ctx, city)


async def _proceed_to_destination(ctx: MaxContext, from_city: str) -> None:
    await ctx.state.set_state(S_TO_CITY)
    dest = await get_destination_cities(from_city)
    await ctx.edit(
        _step_header("to_city")
        + f"✅ Откуда: <b>{from_city}</b>\n\n"
        + "🏁 Выберите <b>пункт назначения</b>:",
        kb=destination_city_kb(dest, exclude_city=from_city),
    )


async def on_custom_from_city_text(ctx: MaxContext) -> None:
    """Пользователь ввёл 'Другой город' текстом (state=from_city)."""
    data = await ctx.state.get_data()
    if not data.get("awaiting_custom_from"):
        return
    city = (ctx.text or "").strip()
    if not city:
        return
    await ctx.state.update_data(from_city=city, awaiting_custom_from=False)
    await _proceed_to_destination(ctx, city)


async def on_custom_from_address_input(ctx: MaxContext) -> None:
    """Ввод адреса отправления — геокодим."""
    address = (ctx.text or "").strip()
    if not address:
        return
    await ctx.edit("🔍 Ищем адрес…")
    result = await geocode_address(address)

    if not result:
        await ctx.state.update_data(from_raw_address=address)
        await ctx.edit(
            "❌ <b>Адрес не найден автоматически.</b>\n\n"
            f"Введённый адрес: <b>{address}</b>\n\n"
            "Вы можете сохранить адрес как есть — менеджер рассчитает стоимость вручную.",
            kb=address_not_found_kb("from"),
        )
        return

    await ctx.state.update_data(
        from_addr_pending=result["display"],
        from_lat_pending=result["lat"],
        from_lon_pending=result["lon"],
    )
    await ctx.edit(
        f"📍 Найдено:\n<b>{result['display']}</b>\n\nЭто верный адрес?",
        kb=address_confirm_kb("from"),
    )


async def on_addr_ok_from(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    data = await ctx.state.get_data()
    display = data.get("from_addr_pending", "")
    await ctx.state.update_data(
        from_city=display,
        from_lat=data.get("from_lat_pending"),
        from_lon=data.get("from_lon_pending"),
        from_addr_pending=None, from_lat_pending=None, from_lon_pending=None,
    )
    await _proceed_to_destination(ctx, display)


async def on_addr_retry_from(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(
        from_addr_pending=None, from_lat_pending=None, from_lon_pending=None,
        from_raw_address=None,
    )
    await ctx.edit(
        _step_header("from_city")
        + "📍 Введите <b>адрес или место отправления</b>:",
        kb=back_to_menu_kb(),
    )


async def on_addr_save_text_from(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    data = await ctx.state.get_data()
    raw = data.get("from_raw_address", "")
    await ctx.state.update_data(
        from_city=raw, from_lat=None, from_lon=None,
        use_custom_route=True, use_custom_from=True,
        from_raw_address=None,
    )
    await _proceed_to_destination(ctx, raw)


# ═══════════════════════════ ШАГ 2: КУДА ════════════════════════════════════


async def on_to_selected(ctx: MaxContext) -> None:
    city = ctx.payload.split(":", 1)[1]
    await ctx.answer_callback()
    data = await ctx.state.get_data()

    if city == "Другой пункт":
        await ctx.state.update_data(awaiting_custom_to=True)
        await ctx.edit(
            "✏️ Введите название <b>пункта назначения</b>:",
            kb=back_to_menu_kb(),
        )
        return

    if city == _CUSTOM_TO:
        await ctx.state.update_data(use_custom_route=True, use_custom_to=True)
        await ctx.state.set_state(S_CUSTOM_TO)
        await ctx.edit(
            _step_header("to_city")
            + "🏁 Введите <b>адрес или место назначения</b>:\n\n"
            "<i>Например: турбаза Чемал — или «с. Манжерок, ул. Центральная 1»</i>",
            kb=back_to_menu_kb(),
        )
        return

    await ctx.state.update_data(to_city=city)
    await _proceed_to_date(ctx, data.get("from_city", ""), city)


async def _proceed_to_date(ctx: MaxContext, from_city: str, to_city: str) -> None:
    await ctx.state.set_state(None)  # в этом шаге не ждём текста
    text = (
        _step_header("trip_date")
        + f"📍 Откуда: <b>{from_city}</b>\n"
        + f"🏁 Куда: <b>{to_city}</b>\n\n"
        + "📅 Выберите <b>дату поездки</b>:"
    )
    await ctx.edit(text, kb=date_presets_kb())


async def on_custom_to_city_text(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    if not data.get("awaiting_custom_to"):
        return
    city = (ctx.text or "").strip()
    if not city:
        return
    await ctx.state.update_data(to_city=city, awaiting_custom_to=False)
    await _proceed_to_date(ctx, data.get("from_city", ""), city)


async def on_custom_to_address_input(ctx: MaxContext) -> None:
    address = (ctx.text or "").strip()
    if not address:
        return
    await ctx.edit("🔍 Ищем адрес…")
    result = await geocode_address(address)

    if not result:
        await ctx.state.update_data(to_raw_address=address)
        await ctx.edit(
            "❌ <b>Адрес не найден автоматически.</b>\n\n"
            f"Введённый адрес: <b>{address}</b>\n\n"
            "Можете сохранить как есть — менеджер рассчитает стоимость.",
            kb=address_not_found_kb("to"),
        )
        return

    await ctx.state.update_data(
        to_addr_pending=result["display"],
        to_lat_pending=result["lat"],
        to_lon_pending=result["lon"],
    )
    await ctx.edit(
        f"📍 Найдено:\n<b>{result['display']}</b>\n\nЭто верный адрес?",
        kb=address_confirm_kb("to"),
    )


async def on_addr_ok_to(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    data = await ctx.state.get_data()
    display = data.get("to_addr_pending", "")
    await ctx.state.update_data(
        to_city=display,
        to_lat=data.get("to_lat_pending"),
        to_lon=data.get("to_lon_pending"),
        to_addr_pending=None, to_lat_pending=None, to_lon_pending=None,
    )
    await _proceed_to_date(ctx, data.get("from_city", ""), display)


async def on_addr_retry_to(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(
        to_addr_pending=None, to_lat_pending=None, to_lon_pending=None,
        to_raw_address=None,
    )
    await ctx.edit(
        _step_header("to_city") + "🏁 Введите <b>адрес или место назначения</b>:",
        kb=back_to_menu_kb(),
    )


async def on_addr_save_text_to(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    data = await ctx.state.get_data()
    raw = data.get("to_raw_address", "")
    await ctx.state.update_data(
        to_city=raw, to_lat=None, to_lon=None,
        use_custom_route=True, use_custom_to=True,
        to_raw_address=None,
    )
    await _proceed_to_date(ctx, data.get("from_city", ""), raw)


# ═══════════════════════════ ШАГ 3: ДАТА ════════════════════════════════════


async def on_date_selected(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    value = ctx.payload.split(":", 1)[1]

    if value == "calendar":
        now = datetime.now()
        await ctx.edit("📅 Выберите дату:", kb=calendar_kb(now.year, now.month))
        return

    await ctx.state.update_data(trip_date=value)
    await _proceed_to_time(ctx, value)


async def on_cal_nav(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    parts = ctx.payload.split(":")  # cal:nav:Y:M
    year, month = int(parts[2]), int(parts[3])
    await ctx.edit("📅 Выберите дату:", kb=calendar_kb(year, month))


async def on_cal_day(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    date_str = ctx.payload.split("cal:day:")[1]
    await ctx.state.update_data(trip_date=date_str)
    await _proceed_to_time(ctx, date_str)


async def on_cal_ignore(ctx: MaxContext) -> None:
    await ctx.answer_callback()


async def _proceed_to_time(ctx: MaxContext, trip_date: str) -> None:
    await ctx.state.set_state(None)
    data = await ctx.state.get_data()
    await ctx.edit(
        _step_header("trip_time")
        + f"📍 {data.get('from_city', '')} → {data.get('to_city', '')}\n"
        + f"📅 {trip_date}\n\n"
        + "🕐 Выберите <b>время отправления</b>:",
        kb=time_kb(),
    )


# ═══════════════════════════ ШАГ 4: ВРЕМЯ ═══════════════════════════════════


async def on_time_selected(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    value = ctx.payload.split(":", 1)[1]

    if value == "custom":
        await ctx.state.set_state(S_TRIP_TIME_CUSTOM)
        await ctx.edit(
            "✏️ Введите время в формате <b>ЧЧ:ММ</b> (например, 14:30):",
            kb=back_to_menu_kb(),
        )
        return

    await ctx.state.update_data(trip_time=value)
    await _proceed_to_passengers(ctx)


async def on_custom_time_input(ctx: MaxContext) -> None:
    text = (ctx.text or "").strip()
    if not re.match(r"^\d{1,2}:\d{2}$", text):
        await ctx.edit("❌ Некорректный формат. Введите как 14:30 или 09:00.")
        return
    await ctx.state.update_data(trip_time=text)
    await ctx.state.set_state(None)
    await _proceed_to_passengers(ctx)


async def _proceed_to_passengers(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    await ctx.edit(
        _step_header("passengers")
        + f"✅ Время: <b>{data.get('trip_time', '')}</b>\n\n"
        "👥 Сколько <b>пассажиров</b>?",
        kb=passengers_kb(),
    )


# ═══════════════════════════ ШАГ 5: ПАССАЖИРЫ ═══════════════════════════════


async def on_passengers_selected(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    n = int(ctx.payload.split(":", 1)[1])
    # Если 9 — считаем как 9 (минивэн автоматически)
    await ctx.state.update_data(passengers=n)
    if n >= 9:
        await ctx.state.update_data(need_minivan=True)
    await _after_passengers(ctx)


async def _after_passengers(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    passengers = data.get("passengers", 1)
    if settings_store.is_step_enabled("children"):
        await ctx.edit(
            _step_header("children")
            + f"✅ Пассажиров: <b>{passengers}</b>\n\n"
            "👶 Будут ли <b>дети до 12 лет</b>? (нужны кресла)",
            kb=yes_no_kb("ch"),
        )
    else:
        await ctx.state.update_data(has_children=False, children_count=0)
        await _after_children(ctx)


async def on_children_yes(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(has_children=True)
    await ctx.edit(
        "👶 Сколько <b>детских кресел</b> нужно?",
        kb=children_count_kb(),
    )


async def on_children_no(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(has_children=False, children_count=0)
    await _after_children(ctx)


async def on_children_count(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    n = int(ctx.payload.split(":", 1)[1])
    await ctx.state.update_data(children_count=n)
    await _after_children(ctx)


async def _after_children(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    if settings_store.is_step_enabled("baggage"):
        info = ""
        if data.get("has_children"):
            info = f"✅ Детей: <b>{data.get('children_count', 0)}</b>\n\n"
        await ctx.edit(
            _step_header("baggage") + info + "🧳 Какой у вас <b>багаж</b>?",
            kb=baggage_kb(),
        )
    else:
        await ctx.state.update_data(baggage="standard")
        await _after_baggage(ctx)


async def on_baggage(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    val = ctx.payload.split(":", 1)[1]
    await ctx.state.update_data(baggage=val)
    await _after_baggage(ctx)


async def _after_baggage(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    if settings_store.is_step_enabled("minivan") and not data.get("need_minivan"):
        label = BAGGAGE_LABELS.get(data.get("baggage", ""), data.get("baggage", ""))
        await ctx.edit(
            _step_header("minivan") + f"✅ Багаж: <b>{label}</b>\n\n🚐 Нужен ли <b>минивэн</b>?",
            kb=yes_no_kb("mv"),
        )
    else:
        await _after_minivan(ctx)


async def on_mv_yes(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(need_minivan=True)
    await _after_minivan(ctx)


async def on_mv_no(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.update_data(need_minivan=False)
    await _after_minivan(ctx)


async def _after_minivan(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    if settings_store.is_step_enabled("stops"):
        mv_label = "Да" if data.get("need_minivan") else "Нет"
        await ctx.edit(
            _step_header("stops")
            + f"✅ Минивэн: <b>{mv_label}</b>\n\n"
            "📍 Нужны ли <b>дополнительные остановки</b>?",
            kb=stops_kb(),
        )
    else:
        await ctx.state.update_data(stops="none")
        await _show_summary(ctx)


async def on_stops(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    val = ctx.payload.split(":", 1)[1]
    await ctx.state.update_data(stops=val)
    await _show_summary(ctx)


# ═══════════════════════════ СВОДКА И ПОДТВЕРЖДЕНИЕ ═════════════════════════


async def _calculate_custom_price(data: dict, stops: str) -> dict:
    def _coords(lat_k: str, lon_k: str, city_k: str):
        if data.get(lat_k):
            return data[lat_k], data[lon_k]
        return CITY_COORDS.get(data.get(city_k, ""), (None, None))

    lat1, lon1 = _coords("from_lat", "from_lon", "from_city")
    lat2, lon2 = _coords("to_lat", "to_lon", "to_city")

    if lat1 is None or lat2 is None:
        return {"needs_manual": True, "total": 0, "breakdown": [], "distance_km": None}

    distance = await get_route_distance_km(lat1, lon1, lat2, lon2)
    if distance is None:
        return {"needs_manual": True, "total": 0, "breakdown": [], "distance_km": None}

    return calculate_price_by_km(
        distance_km=distance,
        passengers=data.get("passengers", 1),
        has_children=data.get("has_children", False),
        children_count=data.get("children_count", 0),
        baggage=data.get("baggage", "standard"),
        need_minivan=data.get("need_minivan", False),
        stops=stops,
    )


async def _show_summary(ctx: MaxContext) -> None:
    data = await ctx.state.get_data()
    stops = data.get("stops", "none")

    if data.get("use_custom_route"):
        price_result = await _calculate_custom_price(data, stops)
    else:
        rp = await get_route_price(data.get("from_city", ""), data.get("to_city", ""))
        price_result = calculate_price(
            from_city=data.get("from_city", ""),
            to_city=data.get("to_city", ""),
            passengers=data.get("passengers", 1),
            has_children=data.get("has_children", False),
            children_count=data.get("children_count", 0),
            baggage=data.get("baggage", "standard"),
            need_minivan=data.get("need_minivan", False),
            stops=stops,
            route_price=rp,
        )

    await ctx.state.update_data(
        calculated_price=price_result["total"],
        price_needs_manual=price_result["needs_manual"],
        distance_km=price_result.get("distance_km"),
    )

    summary = _build_summary(data, price_result, stops)
    await ctx.edit(summary, kb=confirm_order_kb())


def _build_summary(data: dict, price_result: dict, stops: str) -> str:
    children_info = ""
    if data.get("has_children") and data.get("children_count", 0) > 0:
        children_info = f"\n👶 Детей: <b>{data['children_count']}</b>"

    dist = price_result.get("distance_km")
    distance_line = f"📏 Расстояние: <b>{dist} км</b>\n" if dist else ""

    if price_result["needs_manual"] and price_result["total"] == 0:
        price_block = (
            "💰 Стоимость: <b>уточняется менеджером</b>\n"
            "<i>(не удалось рассчитать автоматически)</i>"
        )
    else:
        price_block = f"💰 Стоимость: *{price_result['total']:,} ₽*"
        if len(price_result["breakdown"]) > 1:
            lines = "\n".join(f"   • {line}" for line in price_result["breakdown"])
            price_block += f"\n\n📊 Расчёт:\n{lines}"
        if price_result["needs_manual"]:
            price_block += "\n\n⚠️ <i>Финальная цена уточняется менеджером</i>"

    baggage_label = BAGGAGE_LABELS.get(data.get("baggage", ""), "")
    stops_label = STOPS_LABELS.get(stops, stops)

    return (
        "📋 <b>Сводка вашего заказа</b>\n\n"
        f"📍 Откуда: <b>{data.get('from_city', '')}</b>\n"
        f"🏁 Куда: <b>{data.get('to_city', '')}</b>\n"
        f"{distance_line}"
        f"📅 Дата: <b>{data.get('trip_date', '')}</b>\n"
        f"🕐 Время: <b>{data.get('trip_time', '')}</b>\n"
        f"👥 Пассажиров: <b>{data.get('passengers', 1)}</b>"
        f"{children_info}\n"
        f"🧳 Багаж: <b>{baggage_label}</b>\n"
        f"🚐 Минивэн: <b>{'Да' if data.get('need_minivan') else 'Нет'}</b>\n"
        f"📍 Остановки: <b>{stops_label}</b>\n\n"
        f"{price_block}\n\n"
        "Всё верно?"
    )


async def on_confirm_yes(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.set_state(S_GET_NAME)
    await ctx.edit(
        _step_header("name") + "✏️ Введите ваше <b>имя</b>:",
        kb=back_to_menu_kb(),
    )


async def on_confirm_restart(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.clear()
    await on_start_booking(ctx)


async def on_name_input(ctx: MaxContext) -> None:
    name = (ctx.text or "").strip()
    if len(name) < 2:
        await ctx.edit("❌ Введите корректное имя (минимум 2 символа):")
        return
    await ctx.state.update_data(client_name=name)
    await ctx.state.set_state(S_GET_PHONE)
    await ctx.edit(
        _step_header("phone")
        + f"✅ Имя: <b>{name}</b>\n\n"
        "📱 <b>Отправьте номер телефона</b> кнопкой ниже или введите текстом:",
        kb=contact_kb(),
    )


async def on_phone_input(ctx: MaxContext) -> None:
    # 1) Если пришёл контакт через request_contact — берём его
    phone = ctx.update.contact_phone
    # 2) Иначе — текст
    if not phone and ctx.text:
        phone = ctx.text.strip()

    if not phone:
        return

    phone_clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not re.match(r"^[+]?[78]?\d{10}$", phone_clean):
        await ctx.edit(
            "❌ Введите корректный номер телефона.\nПример: +79123456789 или 89123456789"
        )
        return
    if not phone.startswith("+"):
        phone = "+" + phone_clean.lstrip("78") if len(phone_clean) == 10 else phone
    await _finalize(ctx, phone)


async def _finalize(ctx: MaxContext, phone: str) -> None:
    data = await ctx.state.get_data()

    order_payload = {
        "telegram_id": ctx.user_id,
        "platform": "max",
        "from_city": data.get("from_city", ""),
        "to_city": data.get("to_city", ""),
        "trip_date": data.get("trip_date", ""),
        "trip_time": data.get("trip_time", ""),
        "passengers": data.get("passengers", 1),
        "has_children": 1 if data.get("has_children") else 0,
        "children_count": data.get("children_count", 0),
        "baggage": data.get("baggage", "standard"),
        "need_minivan": 1 if data.get("need_minivan") else 0,
        "stops": data.get("stops", "none"),
        "client_name": data.get("client_name", ""),
        "client_phone": phone,
        "calculated_price": data.get("calculated_price", 0),
    }
    order_id = await create_order(order_payload)
    await ctx.state.clear()

    price_val = data.get("calculated_price", 0)
    price_text = f"{price_val:,} ₽" if price_val else "уточняется"
    dist = data.get("distance_km")
    dist_line = f"📏 Расстояние: {dist} км\n" if dist else ""

    confirmation = settings_store.get_text(
        "text_order_created",
        order_id=order_id,
        from_city=data.get("from_city", ""),
        to_city=data.get("to_city", ""),
        distance_line=dist_line,
        trip_date=data.get("trip_date", ""),
        trip_time=data.get("trip_time", ""),
        passengers=data.get("passengers", 1),
        price_text=price_text,
        client_name=data.get("client_name", ""),
        phone=phone,
    )
    await ctx.edit(confirmation, kb=main_menu_kb())

    # Уведомление менеджеру (в Telegram-чат, единая точка входа)
    # Передаём сводку + реальный user_id из MAX для отладки
    order_payload_for_manager = dict(order_payload)
    order_payload_for_manager["distance_km"] = data.get("distance_km")
    order_payload_for_manager["use_custom_route"] = data.get("use_custom_route", False)
    await notify_manager_new_max_order(order_id, order_payload_for_manager, phone)


# ═══════════════════════════ РЕГИСТРАЦИЯ ═══════════════════════════════════


def register(dp: Dispatcher) -> None:
    # Вход в бронирование
    dp.callback("action:book")(on_start_booking)

    # Шаг 1: откуда
    dp.callback("from:")(on_from_selected)
    dp.state_message(S_FROM_CITY)(on_custom_from_city_text)
    dp.state_message(S_CUSTOM_FROM)(on_custom_from_address_input)
    dp.callback("addr_ok:from")(on_addr_ok_from)
    dp.callback("addr_retry:from")(on_addr_retry_from)
    dp.callback("addr_save_text:from")(on_addr_save_text_from)

    # Шаг 2: куда
    dp.callback("to:")(on_to_selected)
    dp.state_message(S_TO_CITY)(on_custom_to_city_text)
    dp.state_message(S_CUSTOM_TO)(on_custom_to_address_input)
    dp.callback("addr_ok:to")(on_addr_ok_to)
    dp.callback("addr_retry:to")(on_addr_retry_to)
    dp.callback("addr_save_text:to")(on_addr_save_text_to)

    # Шаг 3: дата
    dp.callback("date:")(on_date_selected)
    dp.callback("cal:nav:")(on_cal_nav)
    dp.callback("cal:day:")(on_cal_day)
    dp.callback("cal:ignore")(on_cal_ignore)

    # Шаг 4: время
    dp.callback("time:")(on_time_selected)
    dp.state_message(S_TRIP_TIME_CUSTOM)(on_custom_time_input)

    # Шаг 5: пассажиры
    dp.callback("pass:")(on_passengers_selected)

    # Дети
    dp.callback("ch:yes")(on_children_yes)
    dp.callback("ch:no")(on_children_no)
    dp.callback("chcnt:")(on_children_count)

    # Багаж
    dp.callback("bag:")(on_baggage)

    # Минивэн
    dp.callback("mv:yes")(on_mv_yes)
    dp.callback("mv:no")(on_mv_no)

    # Остановки
    dp.callback("stops:")(on_stops)

    # Подтверждение
    dp.callback("confirm:yes")(on_confirm_yes)
    dp.callback("confirm:restart")(on_confirm_restart)

    # Имя / телефон
    dp.state_message(S_GET_NAME)(on_name_input)
    dp.state_message(S_GET_PHONE)(on_phone_input)
