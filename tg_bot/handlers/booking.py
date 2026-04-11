import logging
import re
from datetime import datetime, date as _date, timedelta

from aiogram import Router, F, Bot

logger = logging.getLogger(__name__)
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from shared import settings_store
from tg_bot.states import BookingStates
from tg_bot.keyboards import (
    departure_city_kb, destination_city_kb,
    booking_calendar_kb, request_contact_kb, address_confirm_kb,
    address_not_found_kb,
    time_kb, passengers_kb, children_kb, children_count_kb,
    baggage_kb, minivan_kb, stops_kb, confirm_order_kb,
    order_created_kb, back_to_menu_kb, manager_order_kb,
)
from shared.price_calculator import calculate_price, calculate_price_by_km
from shared.geo_calculator import geocode_address, get_route_distance_km
from shared.database import (
    create_order, get_route_price, get_departure_cities, get_destination_cities,
    save_inbox_link,
)
from shared.config import MANAGER_CHAT_ID
from shared.routes_data import BAGGAGE_LABELS, STOPS_LABELS, CITY_COORDS

router = Router()

_CUSTOM_FROM = "📍 Указать адрес"
_CUSTOM_TO   = "📍 Указать место"


def _step_header(step_name: str) -> str:
    all_steps = ["from_city", "to_city", "trip_date", "trip_time", "passengers"]
    for key in ("children", "baggage", "minivan", "stops"):
        if settings_store.is_step_enabled(key):
            all_steps.append(key)
    all_steps.extend(["confirm", "name", "phone"])
    total = len(all_steps)
    num = all_steps.index(step_name) + 1 if step_name in all_steps else "?"
    return f"<b>Оформление трансфера</b> · Шаг {num} из {total}\n\n"


async def _safe_send(target, text: str, reply_markup=None) -> Message:
    """Delete old message (photo-safe) and send new text message."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
        return await target.message.answer(text, reply_markup=reply_markup)
    return await target.answer(text, reply_markup=reply_markup)


# ──── Dynamic step advancement after passengers ──────────────────────────


async def _after_passengers(send_fn, state: FSMContext) -> None:
    data = await state.get_data()
    passengers = data.get("passengers", 1)
    if settings_store.is_step_enabled("children"):
        await state.set_state(BookingStates.has_children)
        await send_fn(
            _step_header("children")
            + f"✅ Пассажиров: <b>{passengers}</b>\n\n"
            + "👶 Будут ли <b>дети до 12 лет</b>? (нужны детские кресла)",
            reply_markup=children_kb(),
        )
    else:
        await state.update_data(has_children=False, children_count=0)
        await _after_children(send_fn, state)


async def _after_children(send_fn, state: FSMContext) -> None:
    data = await state.get_data()
    if settings_store.is_step_enabled("baggage"):
        children_info = ""
        if data.get("has_children"):
            children_info = f"✅ Детей: <b>{data.get('children_count', 0)}</b>\n\n"
        else:
            children_info = "✅ Дети: <b>нет</b>\n\n" if settings_store.is_step_enabled("children") else ""
        await state.set_state(BookingStates.baggage)
        await send_fn(
            _step_header("baggage") + children_info + "🧳 Какой у вас <b>багаж</b>?",
            reply_markup=baggage_kb(),
        )
    else:
        await state.update_data(baggage="standard")
        await _after_baggage(send_fn, state)


async def _after_baggage(send_fn, state: FSMContext) -> None:
    data = await state.get_data()
    if settings_store.is_step_enabled("minivan"):
        label = BAGGAGE_LABELS.get(data.get("baggage", ""), data.get("baggage", ""))
        await state.set_state(BookingStates.need_minivan)
        await send_fn(
            _step_header("minivan") + f"✅ Багаж: <b>{label}</b>\n\n🚐 Нужен ли <b>минивэн</b>?",
            reply_markup=minivan_kb(),
        )
    else:
        await state.update_data(need_minivan=False)
        await _after_minivan(send_fn, state)


async def _after_minivan(send_fn, state: FSMContext) -> None:
    data = await state.get_data()
    if settings_store.is_step_enabled("stops"):
        minivan_label = "Да" if data.get("need_minivan") else "Нет"
        await state.set_state(BookingStates.stops)
        await send_fn(
            _step_header("stops")
            + f"✅ Минивэн: <b>{minivan_label}</b>\n\n"
            + "📍 Нужны ли <b>дополнительные остановки</b> по дороге?",
            reply_markup=stops_kb(),
        )
    else:
        await state.update_data(stops="none")
        await _show_summary(send_fn, state)


async def _show_summary(send_fn, state: FSMContext) -> None:
    await state.set_state(BookingStates.confirm_summary)
    data = await state.get_data()
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

    await state.update_data(
        calculated_price=price_result["total"],
        price_needs_manual=price_result["needs_manual"],
        distance_km=price_result.get("distance_km"),
    )
    summary = _build_summary(data, price_result, stops)
    await send_fn(summary, reply_markup=confirm_order_kb())


# ─────────────────────────── Шаг 1: город / адрес отправления ───────────────


@router.callback_query(F.data == "action:book")
async def start_booking(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingStates.from_city)
    cities = await get_departure_cities()
    text = _step_header("from_city") + "📍 Выберите <b>город отправления</b>:"
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=departure_city_kb(cities))
    await callback.answer()


@router.callback_query(F.data.startswith("from:"), StateFilter(BookingStates.from_city))
async def set_from_city(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split(":", 1)[1]

    if city == "Другой город":
        await state.update_data(awaiting_custom_from=True)
        await callback.message.edit_text(
            "✏️ Введите название <b>города отправления</b>:",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    if city == _CUSTOM_FROM:
        await state.update_data(use_custom_route=True, use_custom_from=True)
        await state.set_state(BookingStates.custom_from_address)
        await callback.message.edit_text(
            _step_header("from_city")
            + "📍 Введите <b>адрес или место отправления</b>:\n\n"
            "<i>Например: ул. Ленина 5, Барнаул — или «аэропорт Горно-Алтайск»</i>",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    await state.update_data(from_city=city, awaiting_custom_from=False)
    await state.set_state(BookingStates.to_city)
    dest_cities = await get_destination_cities(city)
    text = (
        _step_header("to_city")
        + f"✅ Откуда: <b>{city}</b>\n\n"
        + "🏁 Выберите <b>пункт назначения</b>:"
    )
    await callback.message.edit_text(text, reply_markup=destination_city_kb(dest_cities, exclude_city=city))
    await callback.answer()


@router.message(StateFilter(BookingStates.from_city))
async def handle_custom_from_city(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_from"):
        return
    city = message.text.strip()
    await state.update_data(from_city=city, awaiting_custom_from=False)
    await state.set_state(BookingStates.to_city)
    dest_cities = await get_destination_cities()
    await message.answer(
        _step_header("to_city")
        + f"✅ Откуда: <b>{city}</b>\n\n"
        + "🏁 Выберите <b>пункт назначения</b>:",
        reply_markup=destination_city_kb(dest_cities),
    )


# ─────────── Шаг 1 (вариант): ввод и геокодинг произвольного адреса ─────────


@router.message(StateFilter(BookingStates.custom_from_address))
async def handle_custom_from_input(message: Message, state: FSMContext) -> None:
    address_text = message.text.strip()
    wait = await message.answer("🔍 Ищем адрес…")

    result = await geocode_address(address_text)
    try:
        await wait.delete()
    except Exception:
        pass

    if not result:
        await state.update_data(from_raw_address=address_text)
        await message.answer(
            "❌ <b>Адрес не найден автоматически.</b>\n\n"
            f"Введённый адрес: <b>{address_text}</b>\n\n"
            "Вы можете:\n"
            "• <b>Сохранить адрес как текст</b> — менеджер рассчитает стоимость вручную\n"
            "• <b>Ввести снова</b>, уточнив адрес:\n"
            "  <i>«ул. Ленина 5, Барнаул»</i> или <i>«аэропорт Горно-Алтайск»</i>",
            reply_markup=address_not_found_kb("from"),
        )
        return

    await state.update_data(
        from_addr_pending=result["display"],
        from_lat_pending=result["lat"],
        from_lon_pending=result["lon"],
    )
    await message.answer(
        f"📍 Найдено:\n<b>{result['display']}</b>\n\nЭто верный адрес?",
        reply_markup=address_confirm_kb("from"),
    )


@router.callback_query(F.data == "addr_ok:from", StateFilter(BookingStates.custom_from_address))
async def confirm_from_address(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    display = data.get("from_addr_pending", "")
    await state.update_data(
        from_city=display,
        from_lat=data.get("from_lat_pending"),
        from_lon=data.get("from_lon_pending"),
        from_addr_pending=None, from_lat_pending=None, from_lon_pending=None,
    )
    await state.set_state(BookingStates.to_city)
    dest_cities = await get_destination_cities()
    await callback.message.edit_text(
        _step_header("to_city")
        + f"✅ Откуда: <b>{display}</b>\n\n"
        + "🏁 Выберите или введите <b>пункт назначения</b>:",
        reply_markup=destination_city_kb(dest_cities),
    )
    await callback.answer()


@router.callback_query(F.data == "addr_retry:from", StateFilter(BookingStates.custom_from_address))
async def retry_from_address(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(from_addr_pending=None, from_lat_pending=None, from_lon_pending=None,
                            from_raw_address=None)
    await callback.message.edit_text(
        _step_header("from_city")
        + "📍 Введите <b>адрес или место отправления</b>:\n\n"
        "<i>Например: ул. Ленина 5, Барнаул — или «аэропорт Горно-Алтайск»</i>",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "addr_save_text:from", StateFilter(BookingStates.custom_from_address))
async def save_raw_from_address(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохраняет введённый адрес как текст (без координат) и переходит к шагу 2."""
    data = await state.get_data()
    raw = data.get("from_raw_address", "")
    await state.update_data(
        from_city=raw,
        from_lat=None,
        from_lon=None,
        use_custom_route=True,
        use_custom_from=True,
        from_raw_address=None,
    )
    await state.set_state(BookingStates.to_city)
    dest_cities = await get_destination_cities()
    await callback.message.edit_text(
        _step_header("to_city")
        + f"✅ Откуда: <b>{raw}</b>\n\n"
        + "🏁 Выберите или введите <b>пункт назначения</b>:",
        reply_markup=destination_city_kb(dest_cities),
    )
    await callback.answer()


# ─────────────────────────── Шаг 2: пункт / адрес назначения ────────────────


@router.callback_query(F.data.startswith("to:"), StateFilter(BookingStates.to_city))
async def set_to_city(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split(":", 1)[1]
    data = await state.get_data()

    if city == "Другой пункт":
        await state.update_data(awaiting_custom_to=True)
        await callback.message.edit_text(
            "✏️ Введите название <b>пункта назначения</b>:",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    if city == _CUSTOM_TO:
        await state.update_data(use_custom_route=True, use_custom_to=True)
        await state.set_state(BookingStates.custom_to_address)
        await callback.message.edit_text(
            _step_header("to_city")
            + "🏁 Введите <b>адрес или место назначения</b>:\n\n"
            "<i>Например: турбаза Чемал — или «с. Манжерок, ул. Центральная 1»</i>",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    await state.update_data(to_city=city, awaiting_custom_to=False)
    await state.set_state(BookingStates.trip_date)
    from_city = data.get("from_city", "")
    now = datetime.now()
    text = (
        _step_header("trip_date")
        + f"📍 Откуда: <b>{from_city}</b>\n"
        + f"🏁 Куда: <b>{city}</b>\n\n"
        + "📅 Выберите <b>дату поездки</b>:\n"
        + "<i>[день] — сегодня · ·день· — прошедший</i>"
    )
    await callback.message.edit_text(text, reply_markup=booking_calendar_kb(now.year, now.month))
    await callback.answer()


@router.message(StateFilter(BookingStates.to_city))
async def handle_custom_to_city(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_to"):
        return
    city = message.text.strip()
    await state.update_data(to_city=city, awaiting_custom_to=False)
    await state.set_state(BookingStates.trip_date)
    from_city = data.get("from_city", "")
    now = datetime.now()
    await message.answer(
        _step_header("trip_date")
        + f"📍 Откуда: <b>{from_city}</b>\n"
        + f"🏁 Куда: <b>{city}</b>\n\n"
        + "📅 Выберите <b>дату поездки</b>:\n"
        + "<i>[день] — сегодня · ·день· — прошедший</i>",
        reply_markup=booking_calendar_kb(now.year, now.month),
    )


# ─────────── Шаг 2 (вариант): геокодинг произвольного адреса назначения ─────


@router.message(StateFilter(BookingStates.custom_to_address))
async def handle_custom_to_input(message: Message, state: FSMContext) -> None:
    address_text = message.text.strip()
    wait = await message.answer("🔍 Ищем адрес…")

    result = await geocode_address(address_text)
    try:
        await wait.delete()
    except Exception:
        pass

    if not result:
        await state.update_data(to_raw_address=address_text)
        await message.answer(
            "❌ <b>Адрес не найден автоматически.</b>\n\n"
            f"Введённый адрес: <b>{address_text}</b>\n\n"
            "Вы можете:\n"
            "• <b>Сохранить адрес как текст</b> — менеджер рассчитает стоимость вручную\n"
            "• <b>Ввести снова</b>, уточнив адрес:\n"
            "  <i>«Чемал, база отдыха Катунь»</i> или <i>«с. Манжерок, Республика Алтай»</i>",
            reply_markup=address_not_found_kb("to"),
        )
        return

    await state.update_data(
        to_addr_pending=result["display"],
        to_lat_pending=result["lat"],
        to_lon_pending=result["lon"],
    )
    await message.answer(
        f"📍 Найдено:\n<b>{result['display']}</b>\n\nЭто верный адрес?",
        reply_markup=address_confirm_kb("to"),
    )


@router.callback_query(F.data == "addr_ok:to", StateFilter(BookingStates.custom_to_address))
async def confirm_to_address(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    display = data.get("to_addr_pending", "")
    await state.update_data(
        to_city=display,
        to_lat=data.get("to_lat_pending"),
        to_lon=data.get("to_lon_pending"),
        to_addr_pending=None, to_lat_pending=None, to_lon_pending=None,
    )
    await state.set_state(BookingStates.trip_date)
    from_city = data.get("from_city", "")
    now = datetime.now()
    await callback.message.edit_text(
        _step_header("trip_date")
        + f"📍 Откуда: <b>{from_city}</b>\n"
        + f"🏁 Куда: <b>{display}</b>\n\n"
        + "📅 Выберите <b>дату поездки</b>:\n"
        + "<i>[день] — сегодня · ·день· — прошедший</i>",
        reply_markup=booking_calendar_kb(now.year, now.month),
    )
    await callback.answer()


@router.callback_query(F.data == "addr_retry:to", StateFilter(BookingStates.custom_to_address))
async def retry_to_address(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(to_addr_pending=None, to_lat_pending=None, to_lon_pending=None,
                            to_raw_address=None)
    await callback.message.edit_text(
        _step_header("to_city")
        + "🏁 Введите <b>адрес или место назначения</b>:",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "addr_save_text:to", StateFilter(BookingStates.custom_to_address))
async def save_raw_to_address(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохраняет введённый адрес назначения как текст (без координат) и переходит к дате."""
    data = await state.get_data()
    raw = data.get("to_raw_address", "")
    from_city = data.get("from_city", "")
    await state.update_data(
        to_city=raw,
        to_lat=None,
        to_lon=None,
        use_custom_route=True,
        use_custom_to=True,
        to_raw_address=None,
    )
    await state.set_state(BookingStates.trip_date)
    now = datetime.now()
    await callback.message.edit_text(
        _step_header("trip_date")
        + f"✅ Откуда: <b>{from_city}</b>\n"
        + f"✅ Куда: <b>{raw}</b>\n\n"
        + "📅 Выберите <b>дату поездки</b>:",
        reply_markup=booking_calendar_kb(now.year, now.month),
    )
    await callback.answer()


# ─────────────────────────── Шаг 3: дата — календарь ────────────────────────


@router.callback_query(F.data == "bk_cal:ignore")
async def bk_cal_ignore(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("bk_cal:nav:"), StateFilter(BookingStates.trip_date))
async def bk_cal_navigate(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    year, month = int(parts[2]), int(parts[3])
    await callback.message.edit_reply_markup(reply_markup=booking_calendar_kb(year, month))
    await callback.answer()


@router.callback_query(F.data.startswith("bk_cal:day:"), StateFilter(BookingStates.trip_date))
async def bk_cal_day_selected(callback: CallbackQuery, state: FSMContext) -> None:
    date_str = callback.data.split("bk_cal:day:")[1]
    try:
        day, month, year = map(int, date_str.split("."))
        selected = _date(year, month, day)
        if selected <= _date.today() - timedelta(days=1):
            await callback.answer("❌ Нельзя выбрать прошедшую дату", show_alert=True)
            return
    except ValueError:
        await callback.answer("❌ Некорректная дата", show_alert=True)
        return

    await state.update_data(trip_date=date_str, awaiting_custom_date=False)
    await state.set_state(BookingStates.trip_time)
    await callback.message.edit_text(
        _step_header("trip_time")
        + f"✅ Дата: <b>{date_str}</b>\n\n"
        + "🕐 Выберите <b>время отправления</b>:",
        reply_markup=time_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "bk_cal:manual", StateFilter(BookingStates.trip_date))
async def bk_cal_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(awaiting_custom_date=True)
    await callback.message.edit_text(
        _step_header("trip_date")
        + "✏️ Введите дату поездки в формате <b>ДД.ММ.ГГГГ</b>\n\nПример: 15.07.2025",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


@router.message(StateFilter(BookingStates.trip_date))
async def handle_custom_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_date"):
        return
    date_text = message.text.strip()
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_text):
        await message.answer(
            "❌ Неверный формат. Введите дату как <b>ДД.ММ.ГГГГ</b>\n\nПример: 15.07.2025",
            reply_markup=back_to_menu_kb(),
        )
        return
    await state.update_data(trip_date=date_text, awaiting_custom_date=False)
    await state.set_state(BookingStates.trip_time)
    await message.answer(
        _step_header("trip_time")
        + f"✅ Дата: <b>{date_text}</b>\n\n"
        + "🕐 Выберите <b>время отправления</b>:",
        reply_markup=time_kb(),
    )


# ─────────────────────────── Шаг 4: время ───────────────────────────────────


@router.callback_query(F.data.startswith("time:"), StateFilter(BookingStates.trip_time))
async def set_time(callback: CallbackQuery, state: FSMContext) -> None:
    time_val = callback.data.split(":", 1)[1]

    if time_val == "custom":
        await state.update_data(awaiting_custom_time=True)
        await callback.message.edit_text(
            "✏️ Введите удобное время отправления (формат ЧЧ:ММ)\n\nПример: 07:30",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    await state.update_data(trip_time=time_val, awaiting_custom_time=False)
    await state.set_state(BookingStates.passengers)
    await callback.message.edit_text(
        _step_header("passengers")
        + f"✅ Время: <b>{time_val}</b>\n\n"
        + "👥 Укажите <b>количество пассажиров</b>:",
        reply_markup=passengers_kb(),
    )
    await callback.answer()


@router.message(StateFilter(BookingStates.trip_time))
async def handle_custom_time(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_time"):
        return
    time_text = message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", time_text):
        await message.answer(
            "❌ Неверный формат. Введите время как <b>ЧЧ:ММ</b>\n\nПример: 07:30",
            reply_markup=back_to_menu_kb(),
        )
        return
    await state.update_data(trip_time=time_text, awaiting_custom_time=False)
    await state.set_state(BookingStates.passengers)
    await message.answer(
        _step_header("passengers")
        + f"✅ Время: <b>{time_text}</b>\n\n"
        + "👥 Укажите <b>количество пассажиров</b>:",
        reply_markup=passengers_kb(),
    )


# ─────────────────────────── Шаг 5: пассажиры ──────────────────────────────


@router.callback_query(F.data.startswith("passengers:"), StateFilter(BookingStates.passengers))
async def set_passengers(callback: CallbackQuery, state: FSMContext) -> None:
    val = callback.data.split(":", 1)[1]

    if val == "custom":
        await state.update_data(awaiting_custom_passengers=True)
        await callback.message.edit_text(
            "✏️ Введите количество пассажиров цифрой:",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    passengers = int(val)
    await state.update_data(passengers=passengers, awaiting_custom_passengers=False)

    async def _send(text, reply_markup=None):
        await callback.message.edit_text(text, reply_markup=reply_markup)

    await _after_passengers(_send, state)
    await callback.answer()


@router.message(StateFilter(BookingStates.passengers))
async def handle_custom_passengers(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_passengers"):
        return
    try:
        passengers = int(message.text.strip())
        if passengers < 1 or passengers > 20:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите корректное число пассажиров (от 1 до 20):",
            reply_markup=back_to_menu_kb(),
        )
        return
    await state.update_data(passengers=passengers, awaiting_custom_passengers=False)

    async def _send(text, reply_markup=None):
        await message.answer(text, reply_markup=reply_markup)

    await _after_passengers(_send, state)


# ─────────────────────────── Шаг: дети ────────────────────────────────────


@router.callback_query(F.data.startswith("children:"), StateFilter(BookingStates.has_children))
async def set_has_children(callback: CallbackQuery, state: FSMContext) -> None:
    has_children = callback.data.split(":", 1)[1] == "yes"

    if has_children:
        await state.update_data(has_children=True)
        await state.set_state(BookingStates.children_count)
        await callback.message.edit_text(
            _step_header("children") + "👶 Сколько детей едет с вами?",
            reply_markup=children_count_kb(),
        )
    else:
        await state.update_data(has_children=False, children_count=0)

        async def _send(text, reply_markup=None):
            await callback.message.edit_text(text, reply_markup=reply_markup)

        await _after_children(_send, state)
    await callback.answer()


@router.callback_query(F.data.startswith("children_count:"), StateFilter(BookingStates.children_count))
async def set_children_count(callback: CallbackQuery, state: FSMContext) -> None:
    count = int(callback.data.split(":", 1)[1])
    await state.update_data(children_count=count)

    async def _send(text, reply_markup=None):
        await callback.message.edit_text(text, reply_markup=reply_markup)

    await _after_children(_send, state)
    await callback.answer()


# ─────────────────────────── Шаг: багаж ───────────────────────────────────


@router.callback_query(F.data.startswith("baggage:"), StateFilter(BookingStates.baggage))
async def set_baggage(callback: CallbackQuery, state: FSMContext) -> None:
    baggage = callback.data.split(":", 1)[1]
    await state.update_data(baggage=baggage)

    async def _send(text, reply_markup=None):
        await callback.message.edit_text(text, reply_markup=reply_markup)

    await _after_baggage(_send, state)
    await callback.answer()


# ─────────────────────────── Шаг: минивэн ─────────────────────────────────


@router.callback_query(F.data.startswith("minivan:"), StateFilter(BookingStates.need_minivan))
async def set_minivan(callback: CallbackQuery, state: FSMContext) -> None:
    need_minivan = callback.data.split(":", 1)[1] == "yes"
    await state.update_data(need_minivan=need_minivan)

    async def _send(text, reply_markup=None):
        await callback.message.edit_text(text, reply_markup=reply_markup)

    await _after_minivan(_send, state)
    await callback.answer()


# ─────────────────────────── Шаг: остановки + расчёт цены ─────────────────


@router.callback_query(F.data.startswith("stops:"), StateFilter(BookingStates.stops))
async def set_stops(callback: CallbackQuery, state: FSMContext) -> None:
    stops = callback.data.split(":", 1)[1]
    await state.update_data(stops=stops)

    if (await state.get_data()).get("use_custom_route"):
        await callback.message.edit_text("🔍 Рассчитываем расстояние по маршруту…")

    async def _send(text, reply_markup=None):
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            await callback.message.answer(text, reply_markup=reply_markup)

    await _show_summary(_send, state)
    await callback.answer()


async def _calculate_custom_price(data: dict, stops: str) -> dict:
    def _coords(lat_key: str, lon_key: str, city_key: str):
        if data.get(lat_key):
            return data[lat_key], data[lon_key]
        return CITY_COORDS.get(data.get(city_key, ""), (None, None))

    lat1, lon1 = _coords("from_lat", "from_lon", "from_city")
    lat2, lon2 = _coords("to_lat",   "to_lon",   "to_city")

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


def _build_summary(data: dict, price_result: dict, stops: str) -> str:
    children_info = ""
    if data.get("has_children") and data.get("children_count", 0) > 0:
        children_info = f"\n👶 Детей: <b>{data['children_count']} чел.</b>"

    dist = price_result.get("distance_km")
    distance_line = f"📏 Расстояние: <b>{dist} км</b>\n" if dist else ""

    if price_result["needs_manual"] and price_result["total"] == 0:
        price_block = (
            "💰 Стоимость: <b>уточняется менеджером</b>\n"
            "<i>(не удалось рассчитать автоматически)</i>"
        )
    else:
        price_block = f"💰 Предварительная стоимость: <b>{price_result['total']:,} ₽</b>"
        if len(price_result["breakdown"]) > 1:
            lines = "\n".join(f"   • {line}" for line in price_result["breakdown"])
            price_block += f"\n\n📊 Расчёт:\n{lines}"
        if price_result["needs_manual"]:
            price_block += "\n\n⚠️ <i>Остановки по нестандартному маршруту — финальная цена уточняется</i>"

    return (
        "📋 <b>Сводка вашего заказа</b>\n\n"
        f"📍 Откуда: <b>{data.get('from_city', '')}</b>\n"
        f"🏁 Куда: <b>{data.get('to_city', '')}</b>\n"
        f"{distance_line}"
        f"📅 Дата: <b>{data.get('trip_date', '')}</b>\n"
        f"🕐 Время: <b>{data.get('trip_time', '')}</b>\n"
        f"👥 Пассажиров: <b>{data.get('passengers', 1)}</b>\n"
        f"{children_info}\n"
        f"🧳 Багаж: <b>{BAGGAGE_LABELS.get(data.get('baggage', ''), '')}</b>\n"
        f"🚐 Минивэн: <b>{'Да' if data.get('need_minivan') else 'Нет'}</b>\n"
        f"📍 Остановки: <b>{STOPS_LABELS.get(stops, stops)}</b>\n\n"
        f"{price_block}\n\n"
        "Всё верно? Нажмите <b>«Подтвердить заказ»</b>."
    )


# ─────────────────────────── Подтверждение / редактирование ──────────────────


@router.callback_query(F.data == "confirm:edit", StateFilter(BookingStates.confirm_summary))
async def edit_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingStates.from_city)
    cities = await get_departure_cities()
    await callback.message.edit_text(
        "🔄 Начнём сначала.\n\n" + _step_header("from_city") + "📍 Выберите <b>город отправления</b>:",
        reply_markup=departure_city_kb(cities),
    )
    await callback.answer()


@router.callback_query(F.data == "confirm:yes", StateFilter(BookingStates.confirm_summary))
async def ask_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BookingStates.get_name)
    await callback.message.edit_text(
        _step_header("name")
        + "✏️ Введите ваше <b>имя</b> (как к вам обращаться):",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


# ─────────────────────────── Имя ──────────────────────────────────────────


@router.message(StateFilter(BookingStates.get_name))
async def get_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer(
            "❌ Введите корректное имя (минимум 2 символа):",
            reply_markup=back_to_menu_kb(),
        )
        return
    await state.update_data(client_name=name)
    await state.set_state(BookingStates.get_phone)
    await message.answer(
        _step_header("phone")
        + f"✅ Имя: <b>{name}</b>\n\n"
        "📱 <b>Укажите номер телефона</b> для связи.\n\n"
        "Нажмите кнопку ниже или введите номер вручную:",
        reply_markup=request_contact_kb(),
    )


# ─────────────────────────── Телефон → создание заказа ────────────────────


@router.message(StateFilter(BookingStates.get_phone), F.contact)
async def get_phone_from_contact(message: Message, state: FSMContext, bot: Bot) -> None:
    logger.info("Contact received from user %s: %s", message.from_user.id, message.contact.phone_number)
    try:
        phone = message.contact.phone_number
        if not phone.startswith("+"):
            phone = "+" + phone
        await _finalize_booking(message, state, bot, phone)
    except Exception:
        logger.exception("Error in get_phone_from_contact for user %s", message.from_user.id)
        await message.answer("Произошла ошибка при оформлении заявки. Попробуйте ещё раз или введите номер вручную.")


@router.message(StateFilter(BookingStates.get_phone))
async def get_phone_from_text(message: Message, state: FSMContext, bot: Bot) -> None:
    phone = message.text.strip()
    phone_clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not re.match(r"^[+]?[78]?\d{10}$", phone_clean):
        await message.answer(
            "❌ Введите корректный номер телефона.\n\nПример: +79123456789 или 89123456789",
        )
        return
    await _finalize_booking(message, state, bot, phone)


async def _finalize_booking(message: Message, state: FSMContext, bot: Bot, phone: str) -> None:
    data = await state.get_data()
    order_id = await create_order({
        "telegram_id": message.from_user.id,
        "platform": "telegram",
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
    })
    await state.clear()

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

    await message.answer(confirmation, reply_markup=ReplyKeyboardRemove())
    await message.answer("Что хотите сделать дальше?", reply_markup=order_created_kb())

    if MANAGER_CHAT_ID:
        await _notify_manager(bot, order_id, data, phone, message.from_user)


async def _notify_manager(bot: Bot, order_id: int, data: dict, phone: str, user) -> None:
    stops_label = STOPS_LABELS.get(data.get("stops", "none"), data.get("stops", ""))
    baggage_label = BAGGAGE_LABELS.get(data.get("baggage", ""), "")
    price_val = data.get("calculated_price", 0)
    price_text = f"{price_val:,} ₽" if price_val else "уточняется"
    dist = data.get("distance_km")
    dist_line = f"📏 Расстояние: <b>{dist} км</b>\n" if dist else ""
    children_info = (
        f"\n👶 Детей: <b>{data['children_count']} чел.</b>"
        if data.get("children_count", 0) > 0
        else ""
    )
    username_str = f"@{user.username}" if user.username else "без username"
    route_type = "📍 Произвольный маршрут" if data.get("use_custom_route") else "🗺 Стандартный маршрут"

    text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА #{order_id}</b>\n\n"
        f"👤 Клиент: <b>{data.get('client_name', '')}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n"
        f"🆔 Telegram: {username_str} (ID: {user.id})\n\n"
        f"{route_type}\n"
        f"📍 Откуда: <b>{data.get('from_city', '')}</b>\n"
        f"🏁 Куда: <b>{data.get('to_city', '')}</b>\n"
        f"{dist_line}"
        f"📅 Дата: <b>{data.get('trip_date', '')}</b>\n"
        f"🕐 Время: <b>{data.get('trip_time', '')}</b>\n"
        f"👥 Пассажиров: <b>{data.get('passengers', 1)}</b>"
        f"{children_info}\n"
        f"🧳 Багаж: <b>{baggage_label}</b>\n"
        f"🚐 Минивэн: <b>{'Да' if data.get('need_minivan') else 'Нет'}</b>\n"
        f"📍 Остановки: <b>{stops_label}</b>\n\n"
        f"💰 Предв. стоимость: <b>{price_text}</b>\n\n"
        "<i>↩️ Ответьте реплаем на это сообщение — клиент получит ответ в Telegram.</i>"
    )
    try:
        sent = await bot.send_message(MANAGER_CHAT_ID, text, reply_markup=manager_order_kb(order_id))
        await save_inbox_link(
            chat_id=MANAGER_CHAT_ID,
            message_id=sent.message_id,
            user_id=user.id,
            platform="telegram",
            kind="order",
            label=f"#{order_id} {data.get('client_name', '')}",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Не удалось отправить уведомление менеджеру: %s", e)
