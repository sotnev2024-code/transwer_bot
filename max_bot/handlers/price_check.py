"""
Быстрый расчёт стоимости без оформления заказа.
"""

from shared.database import get_departure_cities, get_destination_cities, get_route_price
from shared.price_calculator import calculate_price
from shared.routes_data import BAGGAGE_LABELS, STOPS_LABELS

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import (
    departure_city_kb, destination_city_kb, passengers_kb, main_menu_kb, back_to_menu_kb,
)


PFX = "pc_"  # все payload начинаются с pc_ чтобы не конфликтовать с booking

S_FROM = "pc:from"
S_TO = "pc:to"


async def on_start_price(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    await ctx.state.clear()
    await ctx.state.set_state(S_FROM)
    cities = await get_departure_cities()
    # Переделываем клавиатуру на префикс pc_
    kb = _from_kb(cities)
    await ctx.edit("💰 <b>Быстрый расчёт стоимости</b>\n\nВыберите <b>город отправления</b>:", kb=kb)


def _from_kb(cities: list[str]) -> dict:
    from max_bot.keyboards import inline_kb, cb
    rows: list[list[dict]] = []
    for i in range(0, len(cities), 2):
        rows.append([cb(c, f"pc_from:{c}") for c in cities[i:i + 2]])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def _to_kb(cities: list[str], exclude: str) -> dict:
    from max_bot.keyboards import inline_kb, cb
    rows: list[list[dict]] = []
    filtered = [c for c in cities if c != exclude]
    for i in range(0, len(filtered), 2):
        rows.append([cb(c, f"pc_to:{c}") for c in filtered[i:i + 2]])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def _pass_kb() -> dict:
    from max_bot.keyboards import inline_kb, cb
    rows = [
        [cb("1", "pc_pass:1"), cb("2", "pc_pass:2"), cb("3", "pc_pass:3"), cb("4", "pc_pass:4")],
        [cb("5", "pc_pass:5"), cb("6", "pc_pass:6"), cb("7", "pc_pass:7"), cb("8+", "pc_pass:9")],
        [cb("🏠 В главное меню", "action:menu")],
    ]
    return inline_kb(rows)


async def on_pc_from(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    city = ctx.payload.split(":", 1)[1]
    await ctx.state.update_data(pc_from=city)
    await ctx.state.set_state(S_TO)
    dest = await get_destination_cities(city)
    await ctx.edit(
        f"✅ Откуда: <b>{city}</b>\n\n🏁 Выберите <b>пункт назначения</b>:",
        kb=_to_kb(dest, city),
    )


async def on_pc_to(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    city = ctx.payload.split(":", 1)[1]
    data = await ctx.state.get_data()
    await ctx.state.update_data(pc_to=city)
    await ctx.edit(
        f"✅ {data.get('pc_from', '')} → <b>{city}</b>\n\n👥 Сколько <b>пассажиров</b>?",
        kb=_pass_kb(),
    )


async def on_pc_pass(ctx: MaxContext) -> None:
    await ctx.answer_callback()
    n = int(ctx.payload.split(":", 1)[1])
    data = await ctx.state.get_data()
    from_city = data.get("pc_from", "")
    to_city = data.get("pc_to", "")

    rp = await get_route_price(from_city, to_city)
    result = calculate_price(
        from_city=from_city,
        to_city=to_city,
        passengers=n,
        has_children=False,
        children_count=0,
        baggage="standard",
        need_minivan=(n >= 9),
        stops="none",
        route_price=rp,
    )

    if result["needs_manual"]:
        text = (
            f"💰 <b>Расчёт стоимости</b>\n\n"
            f"📍 {from_city} → {to_city}\n"
            f"👥 Пассажиров: {n}\n\n"
            "Стоимость <b>уточняется менеджером</b>."
        )
    else:
        text = (
            f"💰 <b>Расчёт стоимости</b>\n\n"
            f"📍 {from_city} → {to_city}\n"
            f"👥 Пассажиров: {n}\n\n"
            f"💰 Стоимость: *{result['total']:,} ₽*\n\n"
            "<i>Это предварительная цена. Для точного расчёта с доп. услугами — нажмите «Оформить трансфер».</i>"
        )
    await ctx.state.clear()
    await ctx.edit(text, kb=main_menu_kb())


def register(dp: Dispatcher) -> None:
    dp.callback("action:price")(on_start_price)
    dp.callback("pc_from:")(on_pc_from)
    dp.callback("pc_to:")(on_pc_to)
    dp.callback("pc_pass:")(on_pc_pass)
