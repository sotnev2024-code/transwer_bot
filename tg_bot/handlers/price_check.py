from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from tg_bot.states import PriceStates
from tg_bot.keyboards import (
    departure_city_kb, destination_city_kb, passengers_kb,
    children_kb, minivan_kb, price_check_result_kb, back_to_menu_kb,
)
from shared.price_calculator import calculate_price
from shared.database import get_departure_cities, get_destination_cities, get_route_price

router = Router()


@router.callback_query(F.data == "action:price")
async def start_price_check(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PriceStates.from_city)
    cities = await get_departure_cities()
    text = "💰 <b>Быстрый расчёт стоимости</b>\n\n📍 Выберите <b>город отправления</b>:"
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=departure_city_kb(cities))
    await callback.answer()


@router.callback_query(F.data.startswith("from:"), StateFilter(PriceStates.from_city))
async def price_set_from(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split(":", 1)[1]
    if city in ("Другой город", "📍 Указать адрес"):
        await state.update_data(awaiting_custom_from=True)
        await callback.message.edit_text(
            "✏️ Введите название вашего <b>города отправления</b>:",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return
    await state.update_data(from_city=city, awaiting_custom_from=False)
    await state.set_state(PriceStates.to_city)
    dest_cities = await get_destination_cities(city)
    await callback.message.edit_text(
        f"✅ Откуда: <b>{city}</b>\n\n🏁 Выберите <b>пункт назначения</b>:",
        reply_markup=destination_city_kb(dest_cities, exclude_city=city),
    )
    await callback.answer()


@router.message(StateFilter(PriceStates.from_city))
async def price_custom_from(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_from"):
        return
    city = message.text.strip()
    await state.update_data(from_city=city, awaiting_custom_from=False)
    await state.set_state(PriceStates.to_city)
    dest_cities = await get_destination_cities()
    await message.answer(
        f"✅ Откуда: <b>{city}</b>\n\n🏁 Выберите <b>пункт назначения</b>:",
        reply_markup=destination_city_kb(dest_cities),
    )


@router.callback_query(F.data.startswith("to:"), StateFilter(PriceStates.to_city))
async def price_set_to(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split(":", 1)[1]
    if city in ("Другой пункт", "📍 Указать место"):
        await state.update_data(awaiting_custom_to=True)
        await callback.message.edit_text(
            "✏️ Введите название <b>пункта назначения</b>:",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return
    await state.update_data(to_city=city, awaiting_custom_to=False)
    await state.set_state(PriceStates.passengers)
    await callback.message.edit_text(
        f"✅ Куда: <b>{city}</b>\n\n👥 Укажите <b>количество пассажиров</b>:",
        reply_markup=passengers_kb(),
    )
    await callback.answer()


@router.message(StateFilter(PriceStates.to_city))
async def price_custom_to(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_to"):
        return
    city = message.text.strip()
    await state.update_data(to_city=city, awaiting_custom_to=False)
    await state.set_state(PriceStates.passengers)
    await message.answer(
        f"✅ Куда: <b>{city}</b>\n\n👥 Укажите <b>количество пассажиров</b>:",
        reply_markup=passengers_kb(),
    )


@router.callback_query(F.data.startswith("passengers:"), StateFilter(PriceStates.passengers))
async def price_set_passengers(callback: CallbackQuery, state: FSMContext) -> None:
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
    await state.update_data(passengers=passengers)
    await state.set_state(PriceStates.has_children)
    await callback.message.edit_text(
        f"✅ Пассажиров: <b>{passengers}</b>\n\n👶 Будут ли <b>дети</b>?",
        reply_markup=children_kb(),
    )
    await callback.answer()


@router.message(StateFilter(PriceStates.passengers))
async def price_custom_passengers(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("awaiting_custom_passengers"):
        return
    try:
        passengers = int(message.text.strip())
        if passengers < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное число:", reply_markup=back_to_menu_kb())
        return
    await state.update_data(passengers=passengers, awaiting_custom_passengers=False)
    await state.set_state(PriceStates.has_children)
    await message.answer(
        f"✅ Пассажиров: <b>{passengers}</b>\n\n👶 Будут ли <b>дети</b>?",
        reply_markup=children_kb(),
    )


@router.callback_query(F.data.startswith("children:"), StateFilter(PriceStates.has_children))
async def price_set_children(callback: CallbackQuery, state: FSMContext) -> None:
    has_children = callback.data.split(":", 1)[1] == "yes"
    await state.update_data(has_children=has_children, children_count=1 if has_children else 0)
    await state.set_state(PriceStates.need_minivan)
    await callback.message.edit_text(
        "🚐 Нужен ли <b>минивэн</b>?",
        reply_markup=minivan_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("minivan:"), StateFilter(PriceStates.need_minivan))
async def price_set_minivan(callback: CallbackQuery, state: FSMContext) -> None:
    need_minivan = callback.data.split(":", 1)[1] == "yes"
    data = await state.get_data()
    await state.clear()

    from_city = data.get("from_city", "")
    to_city = data.get("to_city", "")
    passengers = data.get("passengers", 1)

    rp = await get_route_price(from_city, to_city)
    price_result = calculate_price(
        from_city=from_city,
        to_city=to_city,
        passengers=passengers,
        has_children=data.get("has_children", False),
        children_count=data.get("children_count", 0),
        baggage="standard",
        need_minivan=need_minivan,
        stops="none",
        route_price=rp,
    )

    if price_result["needs_manual"] and price_result["total"] == 0:
        result_text = (
            "💰 <b>Расчёт стоимости</b>\n\n"
            f"📍 {from_city} → {to_city}\n"
            f"👥 Пассажиров: {passengers}\n\n"
            "⚠️ <b>Данный маршрут требует индивидуального расчёта.</b>\n\n"
            "Свяжитесь с менеджером — мы уточним стоимость и ответим на все вопросы."
        )
    else:
        breakdown = "\n".join(f"   • {line}" for line in price_result["breakdown"])
        result_text = (
            "💰 <b>Расчёт стоимости</b>\n\n"
            f"📍 {from_city} → {to_city}\n"
            f"👥 Пассажиров: {passengers}\n"
            f"🚐 Минивэн: {'Да' if need_minivan else 'Нет'}\n\n"
            f"📊 Расчёт:\n{breakdown}\n\n"
            f"💵 <b>Итого: от {price_result['total']:,} ₽</b>\n\n"
            "<i>* Предварительная цена. Окончательная стоимость уточняется при подтверждении заказа.</i>\n\n"
            "Хотите оформить бронирование?"
        )

    await callback.message.edit_text(result_text, reply_markup=price_check_result_kb())
    await callback.answer()
