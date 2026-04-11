"""
Централизованное хранилище настроек бота.
Все тексты, цены, переключатели и фото хранятся в таблице settings (key→value).
Кэш в памяти, чтобы не читать БД на каждом сообщении.
"""

import json
import time
import aiosqlite
from shared.config import DB_PATH

_cache: dict[str, str] = {}
_cache_loaded_at: float = 0.0
# Периодический refresh кэша: если прошло больше N секунд с последней загрузки,
# следующее обращение вызовет перезагрузку. Это нужно чтобы MAX-бот видел
# изменения настроек, сделанные через Telegram-админку (и наоборот).
CACHE_TTL_SECONDS = 60.0

# ─────────────────────── DEFAULTS ────────────────────────────────────────────

DEFAULTS: dict[str, str] = {
    # ── Фото главного меню ──
    "menu_photo_file_id": "",

    # ── Тексты ──
    "text_welcome": (
        "👋 <b>Добро пожаловать в сервис трансфера по Алтайскому краю!</b>\n\n"
        "Организуем индивидуальные и групповые поездки из Барнаула, Новосибирска, "
        "Горно-Алтайска и других городов — в Чемал, Манжерок, Бирюзовую Катунь, "
        "Телецкое озеро и другие популярные места.\n\n"
        "🕐 Работаем 24/7\n"
        "🚗 Комфортные автомобили и минивэны\n"
        "✅ Индивидуальный подход\n\n"
        "Выберите действие:"
    ),
    "text_help": (
        "ℹ️ <b>Как пользоваться ботом:</b>\n\n"
        "1. Нажмите <b>«Оформить трансфер»</b> — бот проведёт вас по всем шагам\n"
        "2. <b>«Узнать стоимость»</b> — быстрый расчёт без оформления\n"
        "3. <b>«Мои заказы»</b> — история и статус ваших бронирований\n"
        "4. <b>«Связаться с менеджером»</b> — нестандартные маршруты и вопросы\n\n"
        "По любым вопросам: /start — вернуться в главное меню"
    ),
    "text_order_created": (
        "✅ <b>Заявка #{order_id} принята!</b>\n\n"
        "📍 {from_city} → {to_city}\n"
        "{distance_line}"
        "📅 {trip_date} в {trip_time}\n"
        "👥 Пассажиров: {passengers}\n"
        "💰 Предв. стоимость: <b>{price_text}</b>\n\n"
        "👤 {client_name} · {phone}\n\n"
        "Менеджер свяжется с вами для подтверждения поездки. Спасибо! 🙏"
    ),
    "text_order_confirmed": (
        "✅ <b>Заказ #{order_id} подтверждён!</b>\n\n"
        "📍 {from_city} → {to_city}\n"
        "📅 {trip_date} в {trip_time}\n\n"
        "Водитель свяжется с вами накануне поездки. Ждём вас! 🚗"
    ),
    "text_reminder_24h": (
        "🔔 <b>Напоминание о поездке!</b>\n\n"
        "Завтра у вас запланирован трансфер:\n"
        "📍 {from_city} → {to_city}\n"
        "📅 {trip_date} в {trip_time}\n\n"
        "Заказ <b>#{order_id}</b>. Водитель свяжется с вами.\n"
        "Хорошей поездки! 🚗"
    ),
    "text_reminder_1h": (
        "⏰ <b>Поездка через 1 час!</b>\n\n"
        "📍 {from_city} → {to_city}\n"
        "🕐 Время отправления: {trip_time}\n\n"
        "Заказ <b>#{order_id}</b>. Пожалуйста, будьте готовы. 🚗"
    ),
    "text_trip_completed": (
        "🏁 <b>Поездка #{order_id} завершена!</b>\n\n"
        "📍 {from_city} → {to_city}\n"
        "📅 {trip_date}\n\n"
        "Спасибо, что воспользовались нашим сервисом!\n"
        "Пожалуйста, оцените поездку:"
    ),
    "text_review_thanks": (
        "Спасибо за отзыв {stars}! Ваше мнение важно для нас.\n"
        "Ждём вас снова 🚗"
    ),

    # ── Переключатели шагов бронирования ──
    "step_children_enabled": "1",
    "step_baggage_enabled": "1",
    "step_minivan_enabled": "1",
    "step_stops_enabled": "1",

    # ── Наценки ──
    "price_per_extra_passenger": "500",
    "price_minivan_surcharge": "1500",
    "price_child_seat": "300",
    "price_large_baggage": "500",
    "price_stops_1_2": "700",
    "price_stops_3plus": "1500",
    "price_per_km": "30",

    # ── Переключатели отдельных вариантов ответов ──
    "option_baggage_none_enabled": "1",
    "option_baggage_standard_enabled": "1",
    "option_baggage_large_enabled": "1",
    "option_stops_none_enabled": "1",
    "option_stops_1_2_enabled": "1",
    "option_stops_3plus_enabled": "1",
    "option_stops_custom_enabled": "1",
}

# Человекочитаемые названия настроек
SETTING_LABELS: dict[str, str] = {
    "text_welcome": "Приветствие (главное меню)",
    "text_help": "Текст помощи (/help)",
    "text_order_created": "Подтверждение заказа клиенту",
    "text_order_confirmed": "Заказ подтверждён администратором",
    "text_reminder_24h": "Напоминание за 24 ч",
    "text_reminder_1h": "Напоминание за 1 ч",
    "text_trip_completed": "Поездка завершена",
    "text_review_thanks": "Благодарность за отзыв",
    "menu_photo_file_id": "Фото главного меню",
    "step_children_enabled": "Вопрос про детей",
    "step_baggage_enabled": "Вопрос про багаж",
    "step_minivan_enabled": "Вопрос про минивэн",
    "step_stops_enabled": "Вопрос про остановки",
    "price_per_extra_passenger": "Доп. пассажир (₽)",
    "price_minivan_surcharge": "Минивэн (₽)",
    "price_child_seat": "Детское кресло (₽)",
    "price_large_baggage": "Крупный багаж (₽)",
    "price_stops_1_2": "Остановки 1-2 (₽)",
    "price_stops_3plus": "Остановки 3+ (₽)",
    "price_per_km": "Цена за км (₽)",
    "option_baggage_none_enabled": "Багаж: «Без багажа»",
    "option_baggage_standard_enabled": "Багаж: «Стандартный»",
    "option_baggage_large_enabled": "Багаж: «Крупный»",
    "option_stops_none_enabled": "Остановки: «Без остановок»",
    "option_stops_1_2_enabled": "Остановки: «1-2»",
    "option_stops_3plus_enabled": "Остановки: «3+»",
    "option_stops_custom_enabled": "Остановки: «Нестандартный»",
}

TEXT_KEYS = [k for k in DEFAULTS if k.startswith("text_")]
STEP_KEYS = [k for k in DEFAULTS if k.startswith("step_")]
PRICE_KEYS = [k for k in DEFAULTS if k.startswith("price_")]
OPTION_KEYS = [k for k in DEFAULTS if k.startswith("option_")]


# ─────────────────────── DB Operations ───────────────────────────────────────

async def _init_settings_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def load_all_settings() -> None:
    """Загружает все настройки из БД в кэш. Вызывать при старте бота."""
    await _init_settings_table()
    global _cache, _cache_loaded_at
    _cache = dict(DEFAULTS)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM settings") as cursor:
            rows = await cursor.fetchall()
            for key, value in rows:
                _cache[key] = value
    _cache_loaded_at = time.time()


async def maybe_refresh_cache() -> None:
    """
    Перезагружает кэш из БД, если он старше CACHE_TTL_SECONDS.
    Нужно вызывать из фоновой задачи каждого бота — так изменения
    настроек из Telegram-админки подхватываются в MAX-боте (и наоборот).
    """
    if time.time() - _cache_loaded_at >= CACHE_TTL_SECONDS:
        await load_all_settings()


async def save_setting(key: str, value: str) -> None:
    global _cache_loaded_at
    _cache[key] = value
    _cache_loaded_at = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, (key, value))
        await db.commit()


async def delete_setting(key: str) -> None:
    _cache.pop(key, None)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()


# ─────────────────────── Getters ─────────────────────────────────────────────

def get(key: str) -> str:
    return _cache.get(key, DEFAULTS.get(key, ""))


def get_int(key: str) -> int:
    try:
        return int(get(key))
    except (ValueError, TypeError):
        return int(DEFAULTS.get(key, "0"))


def get_bool(key: str) -> bool:
    return get(key) in ("1", "true", "True", "yes")


def get_text(key: str, **kwargs) -> str:
    """Возвращает текст с подстановкой переменных через .format(**kwargs)."""
    tpl = get(key)
    if kwargs:
        try:
            return tpl.format(**kwargs)
        except (KeyError, IndexError):
            return tpl
    return tpl


def get_menu_photo() -> str | None:
    fid = get("menu_photo_file_id")
    return fid if fid else None


def is_step_enabled(step: str) -> bool:
    return get_bool(f"step_{step}_enabled")


# ── Pricing helpers ──

def get_surcharges() -> dict:
    return {
        "extra_passenger": get_int("price_per_extra_passenger"),
        "minivan": get_int("price_minivan_surcharge"),
        "child_seat": get_int("price_child_seat"),
        "large_baggage": get_int("price_large_baggage"),
        "stops_1_2": get_int("price_stops_1_2"),
        "stops_3plus": get_int("price_stops_3plus"),
        "per_km": get_int("price_per_km"),
    }


def is_option_enabled(option_key: str) -> bool:
    return get_bool(f"option_{option_key}_enabled")
