"""
Хелперы для сборки inline-клавиатур MAX.

Формат MAX:
{
  "type": "inline_keyboard",
  "payload": {
    "buttons": [
      [ { "type": "callback", "text": "✅ Да", "payload": "confirm:yes" }, ... ],
      [ { "type": "link", "text": "Сайт", "url": "https://..." } ],
      [ { "type": "request_contact", "text": "📱 Телефон" } ],
      ...
    ]
  }
}

Функция `inline_kb(rows)` возвращает dict, готовый для передачи в поле
`attachments` метода `MaxClient.send_message`.
"""

from __future__ import annotations

import calendar as _cal
from datetime import datetime


_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def cb(text: str, payload: str) -> dict:
    """Кнопка типа callback (обычная кнопка действия)."""
    return {"type": "callback", "text": text, "payload": payload}


def link(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def request_contact(text: str = "📱 Отправить телефон") -> dict:
    return {"type": "request_contact", "text": text}


def inline_kb(rows: list[list[dict]]) -> dict:
    """
    rows — список строк, каждая строка — список кнопок.
    Возвращает attachment, который нужно передать в MaxClient.send_message(attachments=[...]).
    """
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": rows},
    }


# ────────────────────────── готовые клавиатуры ──────────────────────────────


def main_menu_kb() -> dict:
    return inline_kb([
        [cb("🚗 Оформить трансфер", "action:book")],
        [cb("💰 Узнать стоимость", "action:price")],
        [cb("📋 Мои заказы", "action:my_orders")],
        [cb("📞 Связаться с менеджером", "action:manager")],
    ])


def back_to_menu_kb() -> dict:
    return inline_kb([[cb("🏠 В главное меню", "action:menu")]])


def departure_city_kb(cities: list[str]) -> dict:
    rows: list[list[dict]] = []
    # по 2 в ряд
    for i in range(0, len(cities), 2):
        row = [cb(c, f"from:{c}") for c in cities[i:i + 2]]
        rows.append(row)
    rows.append([cb("Другой город", "from:Другой город")])
    rows.append([cb("📍 Указать адрес", "from:📍 Указать адрес")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def destination_city_kb(cities: list[str], exclude_city: str = "") -> dict:
    rows: list[list[dict]] = []
    filtered = [c for c in cities if c != exclude_city]
    for i in range(0, len(filtered), 2):
        row = [cb(c, f"to:{c}") for c in filtered[i:i + 2]]
        rows.append(row)
    rows.append([cb("Другой пункт", "to:Другой пункт")])
    rows.append([cb("📍 Указать место", "to:📍 Указать место")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def address_confirm_kb(side: str) -> dict:
    return inline_kb([
        [cb("✅ Верно", f"addr_ok:{side}"), cb("✏️ Ввести снова", f"addr_retry:{side}")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def address_not_found_kb(side: str) -> dict:
    return inline_kb([
        [cb("💾 Сохранить адрес и продолжить", f"addr_save_text:{side}")],
        [cb("✏️ Ввести снова", f"addr_retry:{side}")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def date_presets_kb() -> dict:
    today = datetime.now()
    labels = ["Сегодня", "Завтра", "Послезавтра"]
    from datetime import timedelta
    rows: list[list[dict]] = []
    row: list[dict] = []
    for i, lbl in enumerate(labels):
        d = today + timedelta(days=i)
        row.append(cb(lbl, f"date:{d.strftime('%d.%m.%Y')}"))
    rows.append(row)
    rows.append([cb("📅 Выбрать другую дату", "date:calendar")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def calendar_kb(year: int, month: int) -> dict:
    """
    Компактный инлайн-календарь для MAX.
    Callback payload: `cal:day:DD.MM.YYYY` / `cal:nav:Y:M`.

    Структура: 1 ряд навигации + до 6 рядов дней = максимум 7 рядов.
    Без weekday header (Пн/Вт/...) и без кнопки «в меню» — чтобы вся клавиатура
    точно влезала в UI MAX, у которого, похоже, более жёсткий лимит по высоте,
    чем у Telegram.
    """
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    rows: list[list[dict]] = []
    # Навигация: ◀️  Месяц Год  ▶️
    rows.append([
        cb("◀️", f"cal:nav:{prev_year}:{prev_month}"),
        cb(f"{_MONTHS_RU[month]} {year}", "cal:ignore"),
        cb("▶️", f"cal:nav:{next_year}:{next_month}"),
    ])

    # Сетка дней — 4–6 рядов по 7 кнопок
    for week in _cal.monthcalendar(year, month):
        row: list[dict] = []
        for day in week:
            if day == 0:
                row.append(cb("·", "cal:ignore"))
            else:
                row.append(cb(str(day), f"cal:day:{day:02d}.{month:02d}.{year}"))
        rows.append(row)

    return inline_kb(rows)


def time_kb() -> dict:
    times = ["05:00", "06:00", "07:00", "08:00", "09:00", "10:00",
             "11:00", "12:00", "13:00", "14:00", "15:00", "16:00",
             "17:00", "18:00", "19:00", "20:00", "21:00", "22:00"]
    rows: list[list[dict]] = []
    for i in range(0, len(times), 3):
        rows.append([cb(t, f"time:{t}") for t in times[i:i + 3]])
    rows.append([cb("✏️ Другое время", "time:custom")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def passengers_kb() -> dict:
    rows: list[list[dict]] = []
    nums = [1, 2, 3, 4, 5, 6, 7, 8]
    for i in range(0, len(nums), 4):
        rows.append([cb(str(n), f"pass:{n}") for n in nums[i:i + 4]])
    rows.append([cb("9+ (минивэн)", "pass:9")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def yes_no_kb(prefix: str) -> dict:
    return inline_kb([
        [cb("✅ Да", f"{prefix}:yes"), cb("❌ Нет", f"{prefix}:no")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def children_count_kb() -> dict:
    rows = [[cb(str(n), f"chcnt:{n}") for n in (1, 2, 3, 4)]]
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def baggage_kb() -> dict:
    return inline_kb([
        [cb("Без багажа", "bag:none")],
        [cb("Стандартный багаж", "bag:standard")],
        [cb("Крупный / много вещей", "bag:large")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def stops_kb() -> dict:
    return inline_kb([
        [cb("Без остановок", "stops:none")],
        [cb("1–2 остановки", "stops:1-2")],
        [cb("3+ остановки", "stops:3+")],
        [cb("Обсудить с менеджером", "stops:custom")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def confirm_order_kb() -> dict:
    return inline_kb([
        [cb("✅ Подтвердить", "confirm:yes")],
        [cb("🔄 Начать заново", "confirm:restart")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def contact_kb() -> dict:
    """Клавиатура с кнопкой запроса телефона."""
    return inline_kb([
        [request_contact("📱 Отправить телефон")],
        [cb("🏠 В главное меню", "action:menu")],
    ])


def my_orders_kb(orders: list[dict]) -> dict:
    rows: list[list[dict]] = []
    for o in orders[:10]:
        label = f"#{o['id']} · {o['from_city']} → {o['to_city']} · {o['trip_date']}"
        rows.append([cb(label, f"order:{o['id']}")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def order_detail_kb(order_id: int, status: str) -> dict:
    rows: list[list[dict]] = []
    if status not in ("cancelled", "completed"):
        rows.append([cb("❌ Отменить заказ", f"cancel_order:{order_id}")])
    rows.append([cb("🔙 К списку заказов", "action:my_orders")])
    rows.append([cb("🏠 В главное меню", "action:menu")])
    return inline_kb(rows)


def confirm_cancel_kb(order_id: int) -> dict:
    return inline_kb([
        [cb("✅ Да, отменить заказ", f"confirm_cancel:{order_id}")],
        [cb("🔙 Нет, вернуться", f"order:{order_id}")],
    ])


def review_rating_kb(order_id: int) -> dict:
    rows = [
        [cb("⭐", f"review_rate:{order_id}:1"),
         cb("⭐⭐", f"review_rate:{order_id}:2"),
         cb("⭐⭐⭐", f"review_rate:{order_id}:3")],
        [cb("⭐⭐⭐⭐", f"review_rate:{order_id}:4"),
         cb("⭐⭐⭐⭐⭐", f"review_rate:{order_id}:5")],
        [cb("⏩ Пропустить", f"review_skip:{order_id}")],
    ]
    return inline_kb(rows)


def review_text_kb(order_id: int) -> dict:
    return inline_kb([[cb("⏩ Пропустить комментарий", f"review_notext:{order_id}")]])


# ═══════════════════════════ АДМИН-ПАНЕЛЬ ════════════════════════════════════


def admin_menu_kb() -> dict:
    return inline_kb([
        [cb("📋 Все заказы", "admin:orders:all:0")],
        [cb("📊 Статистика", "admin:stats")],
        [cb("📅 Поездки на дату", "admin:calendar")],
        [cb("🗓 Поездки за период", "admin:range")],
        [cb("📤 Выгрузить пользователей CSV", "admin:export")],
        [cb("⚙️ Настройки бота", "adm_set:menu")],
        [cb("🏠 В главное меню бота", "action:menu")],
    ])


def admin_back_kb() -> dict:
    return inline_kb([[cb("🔙 Меню администратора", "admin:menu")]])


def admin_orders_kb(orders: list[dict], page: int, total_pages: int, status: str) -> dict:
    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }
    rows: list[list[dict]] = []
    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        plat = " 💬" if (order.get("platform") or "telegram") == "max" else ""
        label = f"{icon}{plat} №{order['id']} | {order['from_city']} → {order['to_city']} | {order['trip_date']}"
        rows.append([cb(label, f"adm_ord:{order['id']}:{status}:{page}")])

    nav: list[dict] = []
    if page > 0:
        nav.append(cb("◀️ Пред.", f"admin:orders:{status}:{page - 1}"))
    nav.append(cb(f"{page + 1}/{total_pages}", "adm:pg_info"))
    if page < total_pages - 1:
        nav.append(cb("След. ▶️", f"admin:orders:{status}:{page + 1}"))
    if nav:
        rows.append(nav)

    def _filter_btn(label: str, val: str) -> dict:
        active = status == val
        return cb(f"[{label}]" if active else label, f"admin:orders:{val}:0")

    rows.append([
        _filter_btn("Все", "all"),
        _filter_btn("🆕 Новые", "new"),
        _filter_btn("✅ Подтв.", "confirmed"),
    ])
    rows.append([
        _filter_btn("❌ Отмен.", "cancelled"),
        _filter_btn("🏁 Заверш.", "completed"),
    ])
    rows.append([cb("🔙 Меню администратора", "admin:menu")])
    return inline_kb(rows)


def admin_order_detail_kb(order_id: int, status: str, back_status: str = "all", back_page: int = 0) -> dict:
    rows: list[list[dict]] = []
    if status not in ("confirmed", "completed"):
        rows.append([cb("✅ Подтвердить заказ", f"adm_ok:{order_id}:{back_status}:{back_page}")])
    if status not in ("cancelled", "completed"):
        rows.append([cb("❌ Отменить / Отклонить", f"adm_no:{order_id}:{back_status}:{back_page}")])
    if status == "confirmed":
        rows.append([cb("🏁 Поездка завершена", f"adm_done:{order_id}:{back_status}:{back_page}")])
    rows.append([cb("🔙 К списку заказов", f"admin:orders:{back_status}:{back_page}")])
    rows.append([cb("🔙 Меню администратора", "admin:menu")])
    return inline_kb(rows)


def admin_calendar_kb(year: int, month: int) -> dict:
    """Календарь админки — другие callback prefix чтобы не конфликтовать с booking."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    rows: list[list[dict]] = []
    rows.append([
        cb("◀️", f"admcal:nav:{prev_year}:{prev_month}"),
        cb(f"{_MONTHS_RU[month]} {year}", "admcal:ignore"),
        cb("▶️", f"admcal:nav:{next_year}:{next_month}"),
    ])
    for week in _cal.monthcalendar(year, month):
        row: list[dict] = []
        for day in week:
            if day == 0:
                row.append(cb("·", "admcal:ignore"))
            else:
                row.append(cb(str(day), f"admcal:day:{day:02d}.{month:02d}.{year}"))
        rows.append(row)
    rows.append([cb("🔙 Меню администратора", "admin:menu")])
    return inline_kb(rows)


def admin_range_calendar_kb(year: int, month: int, stage: str, start_date: str = "") -> dict:
    """
    Двухэтапный календарь диапазона. stage='start' или 'end'.
    Для stage='end' в callback включается start_date (DD.MM.YYYY).
    """
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    tail = f":{start_date}" if stage == "end" and start_date else ""
    rows: list[list[dict]] = []
    title = "📅 Выберите НАЧАЛО" if stage == "start" else f"📅 КОНЕЦ (нач.: {start_date})"
    rows.append([cb(title, "admrng:ignore")])
    rows.append([
        cb("◀️", f"admrng:{stage}:nav:{prev_year}:{prev_month}{tail}"),
        cb(f"{_MONTHS_RU[month]} {year}", "admrng:ignore"),
        cb("▶️", f"admrng:{stage}:nav:{next_year}:{next_month}{tail}"),
    ])
    for week in _cal.monthcalendar(year, month):
        row: list[dict] = []
        for day in week:
            if day == 0:
                row.append(cb("·", "admrng:ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                row.append(cb(str(day), f"admrng:{stage}:day:{date_str}{tail}"))
        rows.append(row)
    rows.append([cb("🔙 Меню администратора", "admin:menu")])
    return inline_kb(rows)


# ═══════════════════════════ АДМИН-НАСТРОЙКИ ═════════════════════════════════


def admin_settings_menu_kb() -> dict:
    return inline_kb([
        [cb("📝 Тексты", "adm_set:texts"), cb("🖼 Фото", "adm_set:photo")],
        [cb("🔀 Этапы", "adm_set:steps"), cb("💰 Цены", "adm_set:prices")],
        [cb("🗺 Маршруты", "adm_set:routes"), cb("📋 Опции", "adm_set:options")],
        [cb("🔙 Меню администратора", "admin:menu")],
    ])


def admin_texts_list_kb(text_keys: list[str], labels: dict) -> dict:
    rows: list[list[dict]] = []
    for key in text_keys:
        label = labels.get(key, key)
        rows.append([cb(label, f"adm_set:text:{key}")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)


def admin_text_detail_kb(key: str) -> dict:
    return inline_kb([
        [cb("✏️ Изменить текст", f"adm_set:text_edit:{key}")],
        [cb("🔄 Сбросить по умолч.", f"adm_set:text_reset:{key}")],
        [cb("🔙 К списку текстов", "adm_set:texts")],
    ])


def admin_photo_kb(has_photo: bool) -> dict:
    rows: list[list[dict]] = [[cb("📤 Загрузить новое фото", "adm_set:photo_upload")]]
    if has_photo:
        rows.append([cb("🗑 Удалить фото", "adm_set:photo_del")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)


def admin_steps_kb(step_keys: list[str], labels: dict, get_bool) -> dict:
    rows: list[list[dict]] = []
    for key in step_keys:
        enabled = get_bool(key)
        icon = "✅ Включён" if enabled else "❌ Выключен"
        label = labels.get(key, key)
        rows.append([cb(f"{icon} — {label}", f"adm_set:step_toggle:{key}")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)


def admin_prices_list_kb(price_keys: list[str], labels: dict, get_int) -> dict:
    rows: list[list[dict]] = []
    for key in price_keys:
        val = get_int(key)
        label = labels.get(key, key)
        rows.append([cb(f"{label}: {val:,} ₽", f"adm_set:price:{key}")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)


def admin_routes_list_kb(routes: list[dict], page: int, total: int, per_page: int = 8) -> dict:
    import math as _math
    total_pages = max(1, _math.ceil(total / per_page))
    rows: list[list[dict]] = []
    for r in routes:
        active = "✅" if r["is_active"] else "🚫"
        rows.append([cb(
            f"{active} {r['from_city']} → {r['to_city']}  {r['price']:,} ₽",
            f"adm_set:route:{r['id']}",
        )])
    nav: list[dict] = []
    if page > 0:
        nav.append(cb("◀️", f"adm_set:routes_pg:{page - 1}"))
    nav.append(cb(f"{page + 1}/{total_pages}", "adm_set:noop"))
    if page < total_pages - 1:
        nav.append(cb("▶️", f"adm_set:routes_pg:{page + 1}"))
    rows.append(nav)
    rows.append([cb("➕ Добавить маршрут", "adm_set:route_add")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)


def admin_route_detail_kb(route_id: int) -> dict:
    return inline_kb([
        [cb("✏️ Изменить цену", f"adm_set:route_edit:{route_id}")],
        [cb("🗑 Удалить маршрут", f"adm_set:route_del:{route_id}")],
        [cb("🔙 К маршрутам", "adm_set:routes")],
    ])


def admin_options_kb(option_keys: list[str], labels: dict, get_bool) -> dict:
    rows: list[list[dict]] = []
    for key in option_keys:
        enabled = get_bool(key)
        icon = "✅" if enabled else "❌"
        label = labels.get(key, key)
        rows.append([cb(f"{icon} {label}", f"adm_set:opt_toggle:{key}")])
    rows.append([cb("🔙 Настройки", "adm_set:menu")])
    return inline_kb(rows)
