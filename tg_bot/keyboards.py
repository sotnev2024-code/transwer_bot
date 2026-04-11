import calendar as _cal
from datetime import datetime, timedelta, date as _date
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from shared import settings_store

_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚗 Оформить трансфер", callback_data="action:book")
    builder.button(text="💰 Узнать стоимость", callback_data="action:price")
    builder.button(text="📋 Мои заказы", callback_data="action:my_orders")
    builder.button(text="📞 Связаться с менеджером", callback_data="action:manager")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def departure_city_kb(cities: list[str] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if cities:
        for city in cities:
            builder.button(text=city, callback_data=f"from:{city}")
    builder.button(text="Другой город", callback_data="from:Другой город")
    builder.button(text="📍 Указать адрес", callback_data="from:📍 Указать адрес")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(2)
    return builder.as_markup()


def destination_city_kb(cities: list[str] | None = None, exclude_city: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if cities:
        for city in cities:
            if city != exclude_city:
                builder.button(text=city, callback_data=f"to:{city}")
    builder.button(text="Другой пункт", callback_data="to:Другой пункт")
    builder.button(text="📍 Указать место", callback_data="to:📍 Указать место")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(2)
    return builder.as_markup()


def date_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    today = datetime.now()
    labels = ["Сегодня", "Завтра", "Послезавтра"]
    for i, label in enumerate(labels):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        builder.button(text=f"{label} ({date_str})", callback_data=f"date:{date_str}")
    builder.button(text="📅 Другая дата", callback_data="date:custom")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def time_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    times = [
        "05:00", "06:00", "07:00", "08:00", "09:00", "10:00",
        "11:00", "12:00", "13:00", "14:00", "15:00", "16:00",
        "17:00", "18:00", "19:00", "20:00", "21:00", "22:00",
    ]
    for t in times:
        builder.button(text=t, callback_data=f"time:{t}")
    builder.button(text="⏰ Другое время", callback_data="time:custom")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(3)
    return builder.as_markup()


def passengers_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 9):
        builder.button(text=str(i), callback_data=f"passengers:{i}")
    builder.button(text="9+", callback_data="passengers:custom")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(3)
    return builder.as_markup()


def children_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👶 Да, есть дети", callback_data="children:yes")
    builder.button(text="✅ Нет детей", callback_data="children:no")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(2)
    return builder.as_markup()


def children_count_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 5):
        builder.button(text=f"{i} реб.", callback_data=f"children_count:{i}")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(2)
    return builder.as_markup()


def baggage_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    opts = [
        ("baggage_none", "👜 Без багажа", "baggage:none"),
        ("baggage_standard", "🧳 Стандартный", "baggage:standard"),
        ("baggage_large", "📦 Много вещей / крупный", "baggage:large"),
    ]
    for key, label, cb in opts:
        if settings_store.is_option_enabled(key):
            builder.button(text=label, callback_data=cb)
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def minivan_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚐 Да, нужен минивэн", callback_data="minivan:yes")
    builder.button(text="🚗 Нет, обычный автомобиль", callback_data="minivan:no")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def stops_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sc = settings_store.get_surcharges()
    opts = [
        ("stops_none", "🚀 Без остановок", "stops:none"),
        ("stops_1_2", f"📍 1–2 остановки (+{sc['stops_1_2']:,} ₽)", "stops:1-2"),
        ("stops_3plus", f"📍📍 3+ остановки (+{sc['stops_3plus']:,} ₽)", "stops:3+"),
        ("stops_custom", "🗺️ Нестандартный маршрут", "stops:custom"),
    ]
    for key, label, cb in opts:
        if settings_store.is_option_enabled(key):
            builder.button(text=label, callback_data=cb)
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def confirm_order_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить заказ", callback_data="confirm:yes")
    builder.button(text="✏️ Изменить данные", callback_data="confirm:edit")
    builder.button(text="❌ Отменить", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def order_created_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои заказы", callback_data="action:my_orders")
    builder.button(text="🔄 Новый заказ", callback_data="action:book")
    builder.button(text="🏠 Главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def my_orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status_icons = {
        "new": "🆕",
        "confirmed": "✅",
        "cancelled": "❌",
        "completed": "🏁",
        "in_progress": "🚗",
    }
    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        text = f"{icon} №{order['id']} | {order['from_city']} → {order['to_city']} | {order['trip_date']}"
        builder.button(text=text, callback_data=f"order:{order['id']}")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def order_detail_kb(order_id: int, status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status not in ("cancelled", "completed"):
        builder.button(text="❌ Отменить заказ", callback_data=f"cancel_order:{order_id}")
    builder.button(text="⬅️ К списку заказов", callback_data="action:my_orders")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


def confirm_cancel_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отменить заказ", callback_data=f"confirm_cancel:{order_id}")
    builder.button(text="🔙 Нет, вернуться", callback_data=f"order:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def manager_order_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять заказ", callback_data=f"mgr_accept:{order_id}")
    builder.button(text="❌ Отклонить", callback_data=f"mgr_reject:{order_id}")
    builder.button(text="💰 Указать цену", callback_data=f"mgr_set_price:{order_id}")
    builder.button(text="📋 Показать контакт", callback_data=f"mgr_contact:{order_id}")
    builder.adjust(2)
    return builder.as_markup()


def price_check_result_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚗 Оформить заказ", callback_data="action:book")
    builder.button(text="📞 Связаться с менеджером", callback_data="action:manager")
    builder.button(text="🏠 В главное меню", callback_data="action:menu")
    builder.adjust(1)
    return builder.as_markup()


# ═══════════════ КЛАВИАТУРЫ ДЛЯ ОТЗЫВОВ ════════════════════════════════════


def review_rating_kb(order_id: int) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    stars_row: list[InlineKeyboardButton] = []
    for i in range(1, 6):
        stars_row.append(InlineKeyboardButton(
            text="⭐" * i, callback_data=f"review_rate:{order_id}:{i}",
        ))
    keyboard.append(stars_row[:3])
    keyboard.append(stars_row[3:])
    keyboard.append([InlineKeyboardButton(
        text="⏩ Пропустить отзыв", callback_data=f"review_skip:{order_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def review_text_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⏩ Пропустить комментарий", callback_data=f"review_notext:{order_id}",
        )],
    ])


# ═══════════════════ ПОДТВЕРЖДЕНИЕ АДРЕСА ════════════════════════════════════


def address_confirm_kb(side: str) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения найденного адреса.
    side = 'from' или 'to'
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Верно", callback_data=f"addr_ok:{side}"),
            InlineKeyboardButton(text="✏️ Ввести снова", callback_data=f"addr_retry:{side}"),
        ],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="action:menu")],
    ])


def address_not_found_kb(side: str) -> InlineKeyboardMarkup:
    """
    Клавиатура когда геокодинг не нашёл адрес.
    Позволяет сохранить введённый текст как есть и продолжить бронирование.
    side = 'from' или 'to'
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💾 Сохранить адрес и продолжить",
            callback_data=f"addr_save_text:{side}",
        )],
        [InlineKeyboardButton(text="✏️ Ввести снова", callback_data=f"addr_retry:{side}")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="action:menu")],
    ])


# ════════════════════ КАЛЕНДАРЬ ДЛЯ ПОЛЬЗОВАТЕЛЯ ════════════════════════════


def booking_calendar_kb(year: int, month: int) -> InlineKeyboardMarkup:
    """Инлайн-календарь для выбора даты в сценарии бронирования (bk_cal:*)."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    today = _date.today()
    keyboard: list[list[InlineKeyboardButton]] = []

    # Заголовок: ◀️  Месяц Год  ▶️
    keyboard.append([
        InlineKeyboardButton(text="◀️", callback_data=f"bk_cal:nav:{prev_year}:{prev_month}"),
        InlineKeyboardButton(text=f"{_MONTHS_RU[month]} {year}", callback_data="bk_cal:ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"bk_cal:nav:{next_year}:{next_month}"),
    ])

    # Дни недели
    keyboard.append([
        InlineKeyboardButton(text=d, callback_data="bk_cal:ignore") for d in _WEEKDAYS_RU
    ])

    # Сетка дней
    for week in _cal.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="bk_cal:ignore"))
            else:
                d_obj = _date(year, month, day)
                is_today = (d_obj == today)
                is_past = (d_obj < today)
                if is_today:
                    label = f"[{day}]"          # сегодня в скобках
                elif is_past:
                    label = f"·{day}·"          # прошедшие визуально затемнены
                else:
                    label = str(day)
                date_str = f"{day:02d}.{month:02d}.{year}"
                row.append(InlineKeyboardButton(
                    text=label, callback_data=f"bk_cal:day:{date_str}"
                ))
        keyboard.append(row)

    # Нижняя панель
    keyboard.append([
        InlineKeyboardButton(text="✍️ Ввести дату вручную", callback_data="bk_cal:manual"),
    ])
    keyboard.append([
        InlineKeyboardButton(text="🏠 В главное меню", callback_data="action:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ═══════════ КНОПКА «ПОДЕЛИТЬСЯ КОНТАКТОМ» (ReplyKeyboard) ════════════════


def request_contact_kb() -> ReplyKeyboardMarkup:
    """Reply-клавиатура с кнопкой быстрой отправки контакта."""
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text="📱 Поделиться контактом", request_contact=True),
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Или введите номер вручную...",
    )


# ═══════════════════════════ АДМИН-ПАНЕЛЬ ════════════════════════════════════


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заказы", callback_data="admin:orders:all:0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📅 Поездки на дату", callback_data="admin:calendar")],
        [InlineKeyboardButton(text="🗓 Поездки за период", callback_data="admin:range")],
        [InlineKeyboardButton(text="📤 Выгрузить пользователей CSV", callback_data="admin:export")],
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="adm_set:menu")],
        [InlineKeyboardButton(text="🏠 В главное меню бота", callback_data="action:menu")],
    ])


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Меню администратора", callback_data="admin:menu")],
    ])


def admin_orders_kb(
    orders: list[dict],
    page: int,
    total_pages: int,
    status: str,
) -> InlineKeyboardMarkup:
    status_icons = {
        "new": "🆕", "confirmed": "✅", "cancelled": "❌",
        "completed": "🏁", "in_progress": "🚗",
    }
    keyboard: list[list[InlineKeyboardButton]] = []

    for order in orders:
        icon = status_icons.get(order["status"], "📋")
        label = (
            f"{icon} №{order['id']} | "
            f"{order['from_city']} → {order['to_city']} | "
            f"{order['trip_date']}"
        )
        keyboard.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"adm_ord:{order['id']}:{status}:{page}",
            )
        ])

    # Pagination row
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ Пред.", callback_data=f"admin:orders:{status}:{page - 1}"
        ))
    nav.append(InlineKeyboardButton(
        text=f"{page + 1}/{total_pages}", callback_data="adm:pg_info"
    ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            text="След. ▶️", callback_data=f"admin:orders:{status}:{page + 1}"
        ))
    keyboard.append(nav)

    # Status filter row 1
    def _filter_btn(label: str, val: str) -> InlineKeyboardButton:
        active = status == val
        return InlineKeyboardButton(
            text=f"[{label}]" if active else label,
            callback_data=f"admin:orders:{val}:0",
        )

    keyboard.append([
        _filter_btn("Все", "all"),
        _filter_btn("🆕 Новые", "new"),
        _filter_btn("✅ Подтв.", "confirmed"),
    ])
    keyboard.append([
        _filter_btn("❌ Отмен.", "cancelled"),
        _filter_btn("🏁 Заверш.", "completed"),
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Меню администратора", callback_data="admin:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_order_detail_kb(
    order_id: int, status: str, back_status: str = "all", back_page: int = 0
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    if status not in ("confirmed", "completed"):
        keyboard.append([InlineKeyboardButton(
            text="✅ Подтвердить заказ",
            callback_data=f"adm_ok:{order_id}:{back_status}:{back_page}",
        )])
    if status not in ("cancelled", "completed"):
        keyboard.append([InlineKeyboardButton(
            text="❌ Отменить / Отклонить",
            callback_data=f"adm_no:{order_id}:{back_status}:{back_page}",
        )])
    if status == "confirmed":
        keyboard.append([InlineKeyboardButton(
            text="🏁 Поездка завершена",
            callback_data=f"adm_done:{order_id}:{back_status}:{back_page}",
        )])
    keyboard.append([InlineKeyboardButton(
        text="🔙 К списку заказов",
        callback_data=f"admin:orders:{back_status}:{back_page}",
    )])
    keyboard.append([InlineKeyboardButton(
        text="🔙 Меню администратора", callback_data="admin:menu"
    )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def calendar_kb(year: int, month: int) -> InlineKeyboardMarkup:
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    keyboard: list[list[InlineKeyboardButton]] = []

    # Header: ◀️  Месяц Год  ▶️
    keyboard.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal:nav:{prev_year}:{prev_month}"),
        InlineKeyboardButton(
            text=f"{_MONTHS_RU[month]} {year}", callback_data="cal:ignore"
        ),
        InlineKeyboardButton(text="▶️", callback_data=f"cal:nav:{next_year}:{next_month}"),
    ])

    # Weekday headers
    keyboard.append([
        InlineKeyboardButton(text=d, callback_data="cal:ignore") for d in _WEEKDAYS_RU
    ])

    # Day grid
    for week in _cal.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal:ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                row.append(InlineKeyboardButton(
                    text=str(day), callback_data=f"cal:day:{date_str}"
                ))
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(text="🔙 Меню администратора", callback_data="admin:menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def range_calendar_kb(
    year: int,
    month: int,
    stage: str,             # "start" или "end"
    start_date: str = "",   # для stage="end" — заранее выбранная нач. дата DD.MM.YYYY
) -> InlineKeyboardMarkup:
    """
    Двухэтапный календарь выбора диапазона дат.
    stage="start" — выбор начальной даты; callback `calrng:start:day:DD.MM.YYYY`.
    stage="end"   — выбор конечной даты; callback `calrng:end:day:DD.MM.YYYY:START`.
    Навигация: `calrng:{stage}:nav:Y:M[:START]`.
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
    keyboard: list[list[InlineKeyboardButton]] = []

    # Заголовок с подсказкой этапа
    title = "📅 Выберите НАЧАЛО периода" if stage == "start" else f"📅 КОНЕЦ (начало: {start_date})"
    keyboard.append([InlineKeyboardButton(text=title, callback_data="calrng:ignore")])

    # Нав.
    keyboard.append([
        InlineKeyboardButton(
            text="◀️",
            callback_data=f"calrng:{stage}:nav:{prev_year}:{prev_month}{tail}",
        ),
        InlineKeyboardButton(
            text=f"{_MONTHS_RU[month]} {year}", callback_data="calrng:ignore"
        ),
        InlineKeyboardButton(
            text="▶️",
            callback_data=f"calrng:{stage}:nav:{next_year}:{next_month}{tail}",
        ),
    ])

    # Дни недели
    keyboard.append([
        InlineKeyboardButton(text=d, callback_data="calrng:ignore") for d in _WEEKDAYS_RU
    ])

    # Сетка
    for week in _cal.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="calrng:ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                row.append(InlineKeyboardButton(
                    text=str(day),
                    callback_data=f"calrng:{stage}:day:{date_str}{tail}",
                ))
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(text="🔙 Меню администратора", callback_data="admin:menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ═══════════════ КЛАВИАТУРЫ НАСТРОЕК АДМИНА ═══════════════════════════════


def admin_settings_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Тексты", callback_data="adm_set:texts"),
         InlineKeyboardButton(text="🖼 Фото", callback_data="adm_set:photo")],
        [InlineKeyboardButton(text="🔀 Этапы", callback_data="adm_set:steps"),
         InlineKeyboardButton(text="💰 Цены", callback_data="adm_set:prices")],
        [InlineKeyboardButton(text="🗺 Маршруты", callback_data="adm_set:routes"),
         InlineKeyboardButton(text="📋 Опции", callback_data="adm_set:options")],
        [InlineKeyboardButton(text="🔙 Меню администратора", callback_data="admin:menu")],
    ])


def admin_texts_list_kb(text_keys: list[str], labels: dict) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for key in text_keys:
        label = labels.get(key, key)
        keyboard.append([InlineKeyboardButton(text=label, callback_data=f"adm_set:text:{key}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_text_detail_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"adm_set:text_edit:{key}")],
        [InlineKeyboardButton(text="🔄 Сбросить по умолч.", callback_data=f"adm_set:text_reset:{key}")],
        [InlineKeyboardButton(text="🔙 К списку текстов", callback_data="adm_set:texts")],
    ])


def admin_photo_kb(has_photo: bool) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    kb.append([InlineKeyboardButton(text="📤 Загрузить новое фото", callback_data="adm_set:photo_upload")])
    if has_photo:
        kb.append([InlineKeyboardButton(text="🗑 Удалить фото", callback_data="adm_set:photo_del")])
    kb.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_steps_kb() -> InlineKeyboardMarkup:
    steps = settings_store.STEP_KEYS
    labels = settings_store.SETTING_LABELS
    keyboard: list[list[InlineKeyboardButton]] = []
    for key in steps:
        enabled = settings_store.get_bool(key)
        icon = "✅ Включён" if enabled else "❌ Выключен"
        label = labels.get(key, key)
        keyboard.append([InlineKeyboardButton(
            text=f"{icon} — {label}", callback_data=f"adm_set:step_toggle:{key}",
        )])
    keyboard.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_prices_list_kb() -> InlineKeyboardMarkup:
    keys = settings_store.PRICE_KEYS
    labels = settings_store.SETTING_LABELS
    keyboard: list[list[InlineKeyboardButton]] = []
    for key in keys:
        val = settings_store.get_int(key)
        label = labels.get(key, key)
        keyboard.append([InlineKeyboardButton(
            text=f"{label}: {val:,} ₽", callback_data=f"adm_set:price:{key}",
        )])
    keyboard.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


import math as _math


def admin_routes_list_kb(
    routes: list[dict], page: int, total: int, per_page: int = 8,
) -> InlineKeyboardMarkup:
    total_pages = max(1, _math.ceil(total / per_page))
    keyboard: list[list[InlineKeyboardButton]] = []
    for r in routes:
        active = "✅" if r["is_active"] else "🚫"
        keyboard.append([InlineKeyboardButton(
            text=f"{active} {r['from_city']} → {r['to_city']}  {r['price']:,} ₽",
            callback_data=f"adm_set:route:{r['id']}",
        )])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_set:routes_pg:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="adm_set:noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_set:routes_pg:{page + 1}"))
    keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="➕ Добавить маршрут", callback_data="adm_set:route_add")])
    keyboard.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_route_detail_kb(route_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"adm_set:route_edit:{route_id}")],
        [InlineKeyboardButton(text="🗑 Удалить маршрут", callback_data=f"adm_set:route_del:{route_id}")],
        [InlineKeyboardButton(text="🔙 К маршрутам", callback_data="adm_set:routes")],
    ])


def admin_options_kb() -> InlineKeyboardMarkup:
    keys = settings_store.OPTION_KEYS
    labels = settings_store.SETTING_LABELS
    keyboard: list[list[InlineKeyboardButton]] = []
    for key in keys:
        enabled = settings_store.get_bool(key)
        icon = "✅" if enabled else "❌"
        label = labels.get(key, key)
        keyboard.append([InlineKeyboardButton(
            text=f"{icon} {label}", callback_data=f"adm_set:opt_toggle:{key}",
        )])
    keyboard.append([InlineKeyboardButton(text="🔙 Настройки", callback_data="adm_set:menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
