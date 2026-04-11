"""
Админ-панель → Настройки бота:
тексты, фото, этапы, цены, маршруты, опции.
"""

import math
import logging

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from shared import settings_store
from shared.config import ADMIN_IDS
from tg_bot.states import AdminSettingsStates
from shared.database import (
    get_routes_paginated,
    get_route_by_id,
    upsert_route,
    delete_route,
)
from tg_bot.keyboards import (
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

router = Router()
logger = logging.getLogger(__name__)

ROUTES_PER_PAGE = 8


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _guard(callback: CallbackQuery) -> bool:
    if not _is_admin(callback.from_user.id):
        return False
    return True


# ─────────────── Главное меню настроек ─────────────────────────────────────


@router.callback_query(F.data == "adm_set:menu")
async def settings_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    await state.clear()
    try:
        await callback.message.edit_text(
            "⚙️ <b>Настройки бота</b>\n\nВыберите раздел:",
            reply_markup=admin_settings_menu_kb(),
        )
    except Exception:
        await callback.message.answer(
            "⚙️ <b>Настройки бота</b>\n\nВыберите раздел:",
            reply_markup=admin_settings_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "adm_set:noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ═════════════════════ 1. TEXTS ═══════════════════════════════════════════


@router.callback_query(F.data == "adm_set:texts")
async def texts_list(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            "📝 <b>Тексты бота</b>\n\nВыберите текст для редактирования:",
            reply_markup=admin_texts_list_kb(settings_store.TEXT_KEYS, settings_store.SETTING_LABELS),
        )
    except Exception:
        await callback.message.answer(
            "📝 <b>Тексты бота</b>\n\nВыберите текст для редактирования:",
            reply_markup=admin_texts_list_kb(settings_store.TEXT_KEYS, settings_store.SETTING_LABELS),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:text:"))
async def text_detail(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:text:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    current = settings_store.get(key)
    preview = current[:800] + "…" if len(current) > 800 else current

    try:
        await callback.message.edit_text(
            f"📝 <b>{label}</b>\n\n"
            f"Текущее значение:\n<code>{preview}</code>",
            reply_markup=admin_text_detail_kb(key),
        )
    except Exception:
        await callback.message.answer(
            f"📝 <b>{label}</b>\n\n"
            f"Текущее значение:\n<code>{preview}</code>",
            reply_markup=admin_text_detail_kb(key),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:text_edit:"))
async def text_edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:text_edit:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    await state.update_data(editing_text_key=key)
    await state.set_state(AdminSettingsStates.waiting_new_text)
    await callback.message.edit_text(
        f"✏️ Отправьте новый текст для <b>«{label}»</b>.\n\n"
        "Можно использовать HTML-теги: <code>&lt;b&gt;, &lt;i&gt;, &lt;code&gt;</code>\n"
        "Переменные в фигурных скобках сохраняются: <code>{order_id}</code>, <code>{from_city}</code> и т.д.",
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_new_text)
async def text_edit_receive(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get("editing_text_key")
    if not key:
        await state.clear()
        return
    new_text = message.text or ""
    await settings_store.save_setting(key, new_text)
    await state.clear()
    label = settings_store.SETTING_LABELS.get(key, key)
    await message.answer(
        f"✅ Текст <b>«{label}»</b> обновлён!",
        reply_markup=admin_texts_list_kb(settings_store.TEXT_KEYS, settings_store.SETTING_LABELS),
    )


@router.callback_query(F.data.startswith("adm_set:text_reset:"))
async def text_reset(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:text_reset:")[1]
    default_val = settings_store.DEFAULTS.get(key, "")
    await settings_store.save_setting(key, default_val)
    label = settings_store.SETTING_LABELS.get(key, key)
    await callback.answer(f"🔄 «{label}» сброшен по умолчанию", show_alert=True)
    preview = default_val[:800] + "…" if len(default_val) > 800 else default_val
    try:
        await callback.message.edit_text(
            f"📝 <b>{label}</b>\n\n"
            f"Текущее значение (по умолчанию):\n<code>{preview}</code>",
            reply_markup=admin_text_detail_kb(key),
        )
    except Exception:
        pass


# ═════════════════════ 2. PHOTO ══════════════════════════════════════════


@router.callback_query(F.data == "adm_set:photo")
async def photo_menu(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    photo_fid = settings_store.get_menu_photo()
    has_photo = bool(photo_fid)
    text = "🖼 <b>Фото главного меню</b>\n\n"
    text += "Фото установлено ✅" if has_photo else "Фото не установлено ❌"
    try:
        await callback.message.edit_text(text, reply_markup=admin_photo_kb(has_photo))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_photo_kb(has_photo))
    await callback.answer()


@router.callback_query(F.data == "adm_set:photo_upload")
async def photo_upload_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    await state.set_state(AdminSettingsStates.waiting_new_photo)
    await callback.message.edit_text("📤 Отправьте новое фото для главного меню.")
    await callback.answer()


@router.message(AdminSettingsStates.waiting_new_photo, F.photo)
async def photo_upload_receive(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    file_id = message.photo[-1].file_id
    await settings_store.save_setting("menu_photo_file_id", file_id)
    await state.clear()
    await message.answer(
        "✅ Фото главного меню обновлено!",
        reply_markup=admin_photo_kb(True),
    )


@router.message(AdminSettingsStates.waiting_new_photo)
async def photo_upload_wrong(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer("❌ Пожалуйста, отправьте <b>фото</b> (не файл/документ).")


@router.callback_query(F.data == "adm_set:photo_del")
async def photo_delete(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    await settings_store.save_setting("menu_photo_file_id", "")
    await callback.answer("🗑 Фото удалено", show_alert=True)
    try:
        await callback.message.edit_text(
            "🖼 <b>Фото главного меню</b>\n\nФото не установлено ❌",
            reply_markup=admin_photo_kb(False),
        )
    except Exception:
        pass


# ═════════════════════ 3. STEPS ══════════════════════════════════════════


@router.callback_query(F.data == "adm_set:steps")
async def steps_list(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            "🔀 <b>Этапы бронирования</b>\n\n"
            "Включите или отключите вопросы в процессе оформления.\n"
            "Отключённые шаги будут пропущены, их значения установятся по умолчанию.",
            reply_markup=admin_steps_kb(),
        )
    except Exception:
        await callback.message.answer(
            "🔀 <b>Этапы бронирования</b>\n\nВключите или отключите вопросы:",
            reply_markup=admin_steps_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:step_toggle:"))
async def step_toggle(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:step_toggle:")[1]
    current = settings_store.get_bool(key)
    await settings_store.save_setting(key, "0" if current else "1")
    label = settings_store.SETTING_LABELS.get(key, key)
    new_state = "выключен" if current else "включён"
    await callback.answer(f"{label}: {new_state}", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=admin_steps_kb())
    except Exception:
        pass


# ═════════════════════ 4. PRICES ═════════════════════════════════════════


@router.callback_query(F.data == "adm_set:prices")
async def prices_list(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            "💰 <b>Наценки и тарифы</b>\n\nВыберите параметр для изменения:",
            reply_markup=admin_prices_list_kb(),
        )
    except Exception:
        await callback.message.answer(
            "💰 <b>Наценки и тарифы</b>\n\nВыберите параметр для изменения:",
            reply_markup=admin_prices_list_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:price:"))
async def price_edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:price:")[1]
    label = settings_store.SETTING_LABELS.get(key, key)
    current = settings_store.get_int(key)
    await state.update_data(editing_price_key=key)
    await state.set_state(AdminSettingsStates.waiting_new_price)
    await callback.message.edit_text(
        f"💰 <b>{label}</b>\n\n"
        f"Текущее значение: <b>{current:,} ₽</b>\n\n"
        "Введите новое значение (целое число):"
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_new_price)
async def price_edit_receive(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get("editing_price_key")
    if not key:
        await state.clear()
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введите положительное целое число.")
        return
    await settings_store.save_setting(key, str(val))
    await state.clear()
    label = settings_store.SETTING_LABELS.get(key, key)
    await message.answer(
        f"✅ <b>{label}</b> обновлён: <b>{val:,} ₽</b>",
        reply_markup=admin_prices_list_kb(),
    )


# ═════════════════════ 5. ROUTES ═════════════════════════════════════════


async def _show_routes_page(target, page: int = 0) -> None:
    routes, total = await get_routes_paginated(page, ROUTES_PER_PAGE)
    text = f"🗺 <b>Маршруты</b>  ({total} всего)\n\nВыберите маршрут или добавьте новый:"
    kb = admin_routes_list_kb(routes, page, total, ROUTES_PER_PAGE)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm_set:routes")
async def routes_list(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    await _show_routes_page(callback, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:routes_pg:"))
async def routes_paginate(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    page = int(callback.data.split(":")[-1])
    await _show_routes_page(callback, page)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:route:"))
async def route_detail(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    route_id = int(callback.data.split(":")[-1])
    route = await get_route_by_id(route_id)
    if not route:
        await callback.answer("Маршрут не найден", show_alert=True)
        return
    active = "✅ Активен" if route["is_active"] else "🚫 Отключён"
    try:
        await callback.message.edit_text(
            f"🗺 <b>Маршрут #{route['id']}</b>\n\n"
            f"📍 {route['from_city']} → {route['to_city']}\n"
            f"💰 Цена: <b>{route['price']:,} ₽</b>\n"
            f"Статус: {active}",
            reply_markup=admin_route_detail_kb(route_id),
        )
    except Exception:
        await callback.message.answer(
            f"🗺 <b>Маршрут #{route['id']}</b>\n\n"
            f"📍 {route['from_city']} → {route['to_city']}\n"
            f"💰 Цена: <b>{route['price']:,} ₽</b>\n"
            f"Статус: {active}",
            reply_markup=admin_route_detail_kb(route_id),
        )
    await callback.answer()


# ── Add route ──


@router.callback_query(F.data == "adm_set:route_add")
async def route_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    await state.set_state(AdminSettingsStates.waiting_route_from)
    await callback.message.edit_text(
        "➕ <b>Новый маршрут</b>\n\nВведите <b>город отправления</b>:"
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_route_from)
async def route_add_from(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from_city = message.text.strip()
    await state.update_data(new_route_from=from_city)
    await state.set_state(AdminSettingsStates.waiting_route_to)
    await message.answer(
        f"✅ Откуда: <b>{from_city}</b>\n\nТеперь введите <b>город назначения</b>:"
    )


@router.message(AdminSettingsStates.waiting_route_to)
async def route_add_to(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    to_city = message.text.strip()
    await state.update_data(new_route_to=to_city)
    await state.set_state(AdminSettingsStates.waiting_route_price)
    data = await state.get_data()
    await message.answer(
        f"✅ {data['new_route_from']} → <b>{to_city}</b>\n\n"
        "Введите <b>цену маршрута</b> (целое число в ₽):"
    )


@router.message(AdminSettingsStates.waiting_route_price)
async def route_add_price(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введите положительное целое число.")
        return
    data = await state.get_data()
    await upsert_route(data["new_route_from"], data["new_route_to"], price)
    await state.clear()
    await message.answer(
        f"✅ Маршрут <b>{data['new_route_from']} → {data['new_route_to']}</b> "
        f"добавлен с ценой <b>{price:,} ₽</b>",
    )
    await _show_routes_page(message, 0)


# ── Edit route price ──


@router.callback_query(F.data.startswith("adm_set:route_edit:"))
async def route_edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    route_id = int(callback.data.split(":")[-1])
    route = await get_route_by_id(route_id)
    if not route:
        await callback.answer("Маршрут не найден", show_alert=True)
        return
    await state.update_data(editing_route_id=route_id)
    await state.set_state(AdminSettingsStates.waiting_edit_route_price)
    await callback.message.edit_text(
        f"✏️ <b>{route['from_city']} → {route['to_city']}</b>\n\n"
        f"Текущая цена: <b>{route['price']:,} ₽</b>\n\n"
        "Введите новую цену (целое число):"
    )
    await callback.answer()


@router.message(AdminSettingsStates.waiting_edit_route_price)
async def route_edit_receive(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введите положительное целое число.")
        return
    data = await state.get_data()
    route_id = data.get("editing_route_id")
    route = await get_route_by_id(route_id)
    if route:
        await upsert_route(route["from_city"], route["to_city"], price)
    await state.clear()
    await message.answer(f"✅ Цена маршрута обновлена: <b>{price:,} ₽</b>")
    await _show_routes_page(message, 0)


# ── Delete route ──


@router.callback_query(F.data.startswith("adm_set:route_del:"))
async def route_delete(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    route_id = int(callback.data.split(":")[-1])
    await delete_route(route_id)
    await callback.answer("🗑 Маршрут удалён", show_alert=True)
    await _show_routes_page(callback, 0)


# ═════════════════════ 6. OPTIONS ════════════════════════════════════════


@router.callback_query(F.data == "adm_set:options")
async def options_list(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    try:
        await callback.message.edit_text(
            "📋 <b>Варианты ответов</b>\n\n"
            "Включите или отключите отдельные варианты в вопросах.\n"
            "Отключённые варианты не будут показываться пользователю.",
            reply_markup=admin_options_kb(),
        )
    except Exception:
        await callback.message.answer(
            "📋 <b>Варианты ответов</b>\n\nВключите или отключите варианты:",
            reply_markup=admin_options_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:opt_toggle:"))
async def option_toggle(callback: CallbackQuery) -> None:
    if not _guard(callback):
        await callback.answer()
        return
    key = callback.data.split("adm_set:opt_toggle:")[1]
    current = settings_store.get_bool(key)
    await settings_store.save_setting(key, "0" if current else "1")
    label = settings_store.SETTING_LABELS.get(key, key)
    new_state = "выключен" if current else "включён"
    await callback.answer(f"{label}: {new_state}", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=admin_options_kb())
    except Exception:
        pass
