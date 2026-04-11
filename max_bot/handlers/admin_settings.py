"""
Админ-панель → Настройки бота для MAX-бота.
Полный паритет с tg_bot/handlers/admin_settings.py:
тексты, фото, этапы, цены, маршруты, опции.

Доступ ограничен через MAX_ADMIN_IDS из .env. Не-админам всё игнорируется молча.
"""

from __future__ import annotations

from shared import settings_store
from shared.config import MAX_ADMIN_IDS
from shared.database import (
    get_routes_paginated,
    get_route_by_id,
    upsert_route,
    delete_route,
)

from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import (
    admin_settings_menu_kb,
    admin_texts_list_kb,
    admin_text_detail_kb,
    admin_photo_kb,
    admin_steps_kb,
    admin_prices_list_kb,
    admin_routes_list_kb,
    admin_route_detail_kb,
    admin_options_kb,
)


ROUTES_PER_PAGE = 8


def _is_admin(user_id: int) -> bool:
    return user_id in MAX_ADMIN_IDS


# ── FSM-состояния (строки) ──
S_WAITING_TEXT = "adms:waiting_text"
S_WAITING_PRICE = "adms:waiting_price"
S_ROUTE_FROM = "adms:route_from"
S_ROUTE_TO = "adms:route_to"
S_ROUTE_PRICE = "adms:route_price"
S_EDIT_ROUTE_PRICE = "adms:edit_route_price"


# ─────────────── Главное меню настроек ─────────────────────────────────────


async def settings_menu(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.state.clear()
    await ctx.edit(
        "⚙️ <b>Настройки бота</b>\n\nВыберите раздел:",
        kb=admin_settings_menu_kb(),
    )


async def noop(ctx: MaxContext) -> None:
    await ctx.answer_callback()


# ═════════════════════ 1. ТЕКСТЫ ═════════════════════════════════════════


async def texts_list(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.edit(
        "📝 <b>Тексты бота</b>\n\nВыберите текст для редактирования:",
        kb=admin_texts_list_kb(settings_store.TEXT_KEYS, settings_store.SETTING_LABELS),
    )


async def text_detail(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    key = ctx.payload.split("adm_set:text:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    current = settings_store.get(key)
    preview = current[:800] + "…" if len(current) > 800 else current
    # Экранируем HTML-теги в превью, чтобы они отображались как код, а не интерпретировались
    preview_safe = (
        preview.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    await ctx.edit(
        f"📝 <b>{label}</b>\n\nТекущее значение:\n<code>{preview_safe}</code>",
        kb=admin_text_detail_kb(key),
    )


async def text_edit_prompt(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    key = ctx.payload.split("adm_set:text_edit:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    await ctx.state.update_data(editing_text_key=key)
    await ctx.state.set_state(S_WAITING_TEXT)
    await ctx.edit(
        f"✏️ Отправьте новый текст для <b>«{label}»</b>.\n\n"
        "Можно использовать HTML-теги: <code>&lt;b&gt;, &lt;i&gt;, &lt;code&gt;</code>\n"
        "Переменные в фигурных скобках сохраняются: "
        "<code>{order_id}</code>, <code>{from_city}</code> и т.д."
    )


async def text_edit_receive(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    data = await ctx.state.get_data()
    key = data.get("editing_text_key")
    if not key:
        await ctx.state.clear()
        return
    new_text = ctx.text or ""
    await settings_store.save_setting(key, new_text)
    await ctx.state.clear()
    label = settings_store.SETTING_LABELS.get(key, key)
    await ctx.send(
        f"✅ Текст <b>«{label}»</b> обновлён!",
        kb=admin_texts_list_kb(settings_store.TEXT_KEYS, settings_store.SETTING_LABELS),
    )


async def text_reset(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    key = ctx.payload.split("adm_set:text_reset:")[1]
    default_val = settings_store.DEFAULTS.get(key, "")
    await settings_store.save_setting(key, default_val)
    label = settings_store.SETTING_LABELS.get(key, key)
    await ctx.answer_callback(f"🔄 «{label}» сброшен")
    preview = default_val[:800] + "…" if len(default_val) > 800 else default_val
    preview_safe = (
        preview.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    await ctx.edit(
        f"📝 <b>{label}</b>\n\n"
        f"Текущее значение (по умолчанию):\n<code>{preview_safe}</code>",
        kb=admin_text_detail_kb(key),
    )


# ═════════════════════ 2. ФОТО ═══════════════════════════════════════════


async def photo_menu(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    photo_fid = settings_store.get_menu_photo()
    has_photo = bool(photo_fid)
    text = "🖼 <b>Фото главного меню</b>\n\n"
    text += "Фото установлено ✅" if has_photo else "Фото не установлено ❌"
    text += (
        "\n\n<i>Загрузка фото из MAX пока не поддерживается — "
        "используйте Telegram-админку для смены изображения. "
        "Удалить можно отсюда.</i>"
    )
    await ctx.edit(text, kb=admin_photo_kb(has_photo))


async def photo_upload_prompt(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback(
        "Загрузите фото через Telegram-админку"
    )
    # Просто переоткрываем меню фото, не меняя состояния
    await photo_menu(ctx)


async def photo_delete(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await settings_store.save_setting("menu_photo_file_id", "")
    await ctx.answer_callback("🗑 Фото удалено")
    await ctx.edit(
        "🖼 <b>Фото главного меню</b>\n\nФото не установлено ❌",
        kb=admin_photo_kb(False),
    )


# ═════════════════════ 3. ЭТАПЫ ══════════════════════════════════════════


async def steps_list(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.edit(
        "🔀 <b>Этапы бронирования</b>\n\n"
        "Включите или отключите вопросы в процессе оформления.\n"
        "Отключённые шаги будут пропущены, их значения установятся по умолчанию.",
        kb=admin_steps_kb(
            settings_store.STEP_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_bool,
        ),
    )


async def step_toggle(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    key = ctx.payload.split("adm_set:step_toggle:")[1]
    current = settings_store.get_bool(key)
    await settings_store.save_setting(key, "0" if current else "1")
    label = settings_store.SETTING_LABELS.get(key, key)
    new_state = "выключен" if current else "включён"
    await ctx.answer_callback(f"{label}: {new_state}")
    await ctx.edit(
        "🔀 <b>Этапы бронирования</b>\n\n"
        "Включите или отключите вопросы в процессе оформления.\n"
        "Отключённые шаги будут пропущены, их значения установятся по умолчанию.",
        kb=admin_steps_kb(
            settings_store.STEP_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_bool,
        ),
    )


# ═════════════════════ 4. ЦЕНЫ ═══════════════════════════════════════════


async def prices_list(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.edit(
        "💰 <b>Наценки и тарифы</b>\n\nВыберите параметр для изменения:",
        kb=admin_prices_list_kb(
            settings_store.PRICE_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_int,
        ),
    )


async def price_edit_prompt(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    key = ctx.payload.split("adm_set:price:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    current = settings_store.get_int(key)
    await ctx.state.update_data(editing_price_key=key)
    await ctx.state.set_state(S_WAITING_PRICE)
    await ctx.edit(
        f"💰 <b>{label}</b>\n\n"
        f"Текущее значение: <b>{current:,} ₽</b>\n\n"
        "Введите новое значение (целое число):"
    )


async def price_edit_receive(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    data = await ctx.state.get_data()
    key = data.get("editing_price_key")
    if not key:
        await ctx.state.clear()
        return
    try:
        val = int((ctx.text or "").strip())
        if val < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await ctx.send("❌ Введите положительное целое число.")
        return
    await settings_store.save_setting(key, str(val))
    await ctx.state.clear()
    label = settings_store.SETTING_LABELS.get(key, key)
    await ctx.send(
        f"✅ <b>{label}</b> обновлён: <b>{val:,} ₽</b>",
        kb=admin_prices_list_kb(
            settings_store.PRICE_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_int,
        ),
    )


# ═════════════════════ 5. МАРШРУТЫ ═══════════════════════════════════════


async def _show_routes_page(ctx: MaxContext, page: int = 0) -> None:
    routes, total = await get_routes_paginated(page, ROUTES_PER_PAGE)
    text = f"🗺 <b>Маршруты</b>  ({total} всего)\n\nВыберите маршрут или добавьте новый:"
    kb = admin_routes_list_kb(routes, page, total, ROUTES_PER_PAGE)
    await ctx.edit(text, kb=kb)


async def routes_list(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await _show_routes_page(ctx, 0)


async def routes_paginate(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    page = int(ctx.payload.split(":")[-1])
    await _show_routes_page(ctx, page)


async def route_detail(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    route_id = int(ctx.payload.split(":")[-1])
    route = await get_route_by_id(route_id)
    if not route:
        await ctx.answer_callback("Маршрут не найден")
        return
    active = "✅ Активен" if route["is_active"] else "🚫 Отключён"
    await ctx.edit(
        f"🗺 <b>Маршрут #{route['id']}</b>\n\n"
        f"📍 {route['from_city']} → {route['to_city']}\n"
        f"💰 Цена: <b>{route['price']:,} ₽</b>\n"
        f"Статус: {active}",
        kb=admin_route_detail_kb(route_id),
    )


# ── Добавление маршрута ──


async def route_add_start(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.state.set_state(S_ROUTE_FROM)
    await ctx.edit("➕ <b>Новый маршрут</b>\n\nВведите <b>город отправления</b>:")


async def route_add_from(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    from_city = (ctx.text or "").strip()
    if not from_city:
        return
    await ctx.state.update_data(new_route_from=from_city)
    await ctx.state.set_state(S_ROUTE_TO)
    await ctx.send(
        f"✅ Откуда: <b>{from_city}</b>\n\nТеперь введите <b>город назначения</b>:"
    )


async def route_add_to(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    to_city = (ctx.text or "").strip()
    if not to_city:
        return
    await ctx.state.update_data(new_route_to=to_city)
    await ctx.state.set_state(S_ROUTE_PRICE)
    data = await ctx.state.get_data()
    await ctx.send(
        f"✅ {data['new_route_from']} → <b>{to_city}</b>\n\n"
        "Введите <b>цену маршрута</b> (целое число в ₽):"
    )


async def route_add_price(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    try:
        price = int((ctx.text or "").strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await ctx.send("❌ Введите положительное целое число.")
        return
    data = await ctx.state.get_data()
    await upsert_route(data["new_route_from"], data["new_route_to"], price)
    await ctx.state.clear()
    await ctx.send(
        f"✅ Маршрут <b>{data['new_route_from']} → {data['new_route_to']}</b> "
        f"добавлен с ценой <b>{price:,} ₽</b>"
    )
    await _show_routes_page(ctx, 0)


# ── Изменение цены маршрута ──


async def route_edit_prompt(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    route_id = int(ctx.payload.split(":")[-1])
    route = await get_route_by_id(route_id)
    if not route:
        await ctx.answer_callback("Маршрут не найден")
        return
    await ctx.state.update_data(editing_route_id=route_id)
    await ctx.state.set_state(S_EDIT_ROUTE_PRICE)
    await ctx.edit(
        f"✏️ <b>{route['from_city']} → {route['to_city']}</b>\n\n"
        f"Текущая цена: <b>{route['price']:,} ₽</b>\n\n"
        "Введите новую цену (целое число):"
    )


async def route_edit_receive(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        return
    try:
        price = int((ctx.text or "").strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await ctx.send("❌ Введите положительное целое число.")
        return
    data = await ctx.state.get_data()
    route_id = data.get("editing_route_id")
    route = await get_route_by_id(route_id)
    if route:
        await upsert_route(route["from_city"], route["to_city"], price)
    await ctx.state.clear()
    await ctx.send(f"✅ Цена маршрута обновлена: <b>{price:,} ₽</b>")
    await _show_routes_page(ctx, 0)


# ── Удаление маршрута ──


async def route_delete(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    route_id = int(ctx.payload.split(":")[-1])
    await delete_route(route_id)
    await ctx.answer_callback("🗑 Маршрут удалён")
    await _show_routes_page(ctx, 0)


# ═════════════════════ 6. ОПЦИИ ══════════════════════════════════════════


async def options_list(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    await ctx.answer_callback()
    await ctx.edit(
        "📋 <b>Варианты ответов</b>\n\n"
        "Включите или отключите отдельные варианты в вопросах.\n"
        "Отключённые варианты не будут показываться пользователю.",
        kb=admin_options_kb(
            settings_store.OPTION_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_bool,
        ),
    )


async def option_toggle(ctx: MaxContext) -> None:
    if not _is_admin(ctx.user_id):
        await ctx.answer_callback()
        return
    key = ctx.payload.split("adm_set:opt_toggle:")[1]
    current = settings_store.get_bool(key)
    await settings_store.save_setting(key, "0" if current else "1")
    label = settings_store.SETTING_LABELS.get(key, key)
    new_state = "выключен" if current else "включён"
    await ctx.answer_callback(f"{label}: {new_state}")
    await ctx.edit(
        "📋 <b>Варианты ответов</b>\n\n"
        "Включите или отключите отдельные варианты в вопросах.\n"
        "Отключённые варианты не будут показываться пользователю.",
        kb=admin_options_kb(
            settings_store.OPTION_KEYS,
            settings_store.SETTING_LABELS,
            settings_store.get_bool,
        ),
    )


# ─────────────────── Регистрация ───────────────────


def register(dp: Dispatcher) -> None:
    # Главное меню настроек
    dp.callback("adm_set:menu")(settings_menu)
    dp.callback("adm_set:noop")(noop)

    # Тексты — порядок важен: специфичные префиксы ДО общих
    dp.callback("adm_set:text_edit:")(text_edit_prompt)
    dp.callback("adm_set:text_reset:")(text_reset)
    dp.callback("adm_set:texts")(texts_list)
    dp.callback("adm_set:text:")(text_detail)
    dp.state_message(S_WAITING_TEXT)(text_edit_receive)

    # Фото
    dp.callback("adm_set:photo_upload")(photo_upload_prompt)
    dp.callback("adm_set:photo_del")(photo_delete)
    dp.callback("adm_set:photo")(photo_menu)

    # Этапы
    dp.callback("adm_set:step_toggle:")(step_toggle)
    dp.callback("adm_set:steps")(steps_list)

    # Цены
    dp.callback("adm_set:price:")(price_edit_prompt)
    dp.callback("adm_set:prices")(prices_list)
    dp.state_message(S_WAITING_PRICE)(price_edit_receive)

    # Маршруты — снова порядок: спец. префиксы ДО общих
    dp.callback("adm_set:route_add")(route_add_start)
    dp.callback("adm_set:route_edit:")(route_edit_prompt)
    dp.callback("adm_set:route_del:")(route_delete)
    dp.callback("adm_set:routes_pg:")(routes_paginate)
    dp.callback("adm_set:routes")(routes_list)
    dp.callback("adm_set:route:")(route_detail)
    dp.state_message(S_ROUTE_FROM)(route_add_from)
    dp.state_message(S_ROUTE_TO)(route_add_to)
    dp.state_message(S_ROUTE_PRICE)(route_add_price)
    dp.state_message(S_EDIT_ROUTE_PRICE)(route_edit_receive)

    # Опции
    dp.callback("adm_set:opt_toggle:")(option_toggle)
    dp.callback("adm_set:options")(options_list)
