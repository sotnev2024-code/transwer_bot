import aiosqlite
from shared.config import DB_PATH
from shared.routes_data import ROUTE_PRICES as _SEED_ROUTES


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL-режим: разрешает параллельное чтение (и запись одного писателя)
        # из двух процессов — критично для одновременной работы Telegram- и MAX-ботов.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'telegram',
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(telegram_id, platform)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'telegram',
                from_city TEXT NOT NULL,
                to_city TEXT NOT NULL,
                trip_date TEXT NOT NULL,
                trip_time TEXT NOT NULL,
                passengers INTEGER NOT NULL DEFAULT 1,
                has_children INTEGER DEFAULT 0,
                children_count INTEGER DEFAULT 0,
                baggage TEXT DEFAULT 'standard',
                need_minivan INTEGER DEFAULT 0,
                stops TEXT DEFAULT 'none',
                client_name TEXT,
                client_phone TEXT,
                calculated_price INTEGER DEFAULT 0,
                final_price INTEGER,
                status TEXT DEFAULT 'new',
                manager_comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS route_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_city TEXT NOT NULL,
                to_city TEXT NOT NULL,
                price INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                UNIQUE(from_city, to_city)
            )
        """)
        # Seed routes from code if table is empty
        async with db.execute("SELECT COUNT(*) FROM route_prices") as cur:
            cnt = (await cur.fetchone())[0]
        if cnt == 0:
            for (fc, tc), price in _SEED_ROUTES.items():
                await db.execute(
                    "INSERT OR IGNORE INTO route_prices (from_city, to_city, price) VALUES (?, ?, ?)",
                    (fc, tc, price),
                )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, kind)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER UNIQUE NOT NULL,
                telegram_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'telegram',
                rating INTEGER NOT NULL,
                review_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Маппинг сообщений бота в чате менеджера → клиент.
        # Используется чтобы менеджер мог "ответить" реплаем на любое сообщение
        # бота в чате, и ответ ушёл клиенту в его исходный мессенджер.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS manager_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'request',
                label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, message_id)
            )
        """)
        # ── Миграция существующих БД: добавить platform, если её нет ──
        await _migrate_add_platform_column(db)
        await db.commit()


async def _migrate_add_platform_column(db: aiosqlite.Connection) -> None:
    """
    Миграции существующей БД на мульти-платформенную схему.

    1. Добавляет колонку `platform` в users / orders / reviews (если ещё нет).
       Все старые записи получают platform='telegram'.
    2. Пересобирает таблицу `users`, если там старый constraint
       `UNIQUE(telegram_id)` — заменяет на `UNIQUE(telegram_id, platform)`.
       Это нужно чтобы `save_user` мог делать ON CONFLICT по (telegram_id, platform).
    """
    # ── 1. platform column ──
    for table in ("users", "orders", "reviews"):
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        if "platform" not in cols:
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN platform TEXT NOT NULL DEFAULT 'telegram'"
            )
    await db.commit()

    # ── 2. users table: заменить UNIQUE(telegram_id) на UNIQUE(telegram_id, platform) ──
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ) as cur:
        row = await cur.fetchone()
    if row:
        sql = row[0] or ""
        has_new_constraint = "UNIQUE(telegram_id, platform)" in sql
        has_old_constraint = "telegram_id INTEGER UNIQUE" in sql or "telegram_id	INTEGER UNIQUE" in sql
        if not has_new_constraint and has_old_constraint:
            # Пересобираем users с новой схемой, сохраняя данные.
            await db.execute("""
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'telegram',
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(telegram_id, platform)
                )
            """)
            await db.execute("""
                INSERT INTO users_new (id, telegram_id, platform, username, first_name, last_name, created_at)
                SELECT id,
                       telegram_id,
                       COALESCE(platform, 'telegram'),
                       username, first_name, last_name, created_at
                FROM users
            """)
            await db.execute("DROP TABLE users")
            await db.execute("ALTER TABLE users_new RENAME TO users")
            await db.commit()


async def save_inbox_link(
    chat_id: int,
    message_id: int,
    user_id: int,
    platform: str,
    kind: str = "request",
    label: str | None = None,
) -> None:
    """
    Сохраняет связь сообщения бота в чате менеджера → конечный клиент.
    Менеджер сможет ответить реплаем на это сообщение, и бот доставит
    ответ клиенту в нужный мессенджер.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO manager_inbox (chat_id, message_id, user_id, platform, kind, label)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                user_id = excluded.user_id,
                platform = excluded.platform,
                kind = excluded.kind,
                label = excluded.label
        """, (chat_id, message_id, user_id, platform, kind, label))
        await db.commit()


async def get_inbox_link(chat_id: int, message_id: int) -> dict | None:
    """Найти, кому изначально принадлежит сообщение в чате менеджера."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM manager_inbox WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def save_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    platform: str = "telegram",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, platform, username, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id, platform) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name
        """, (telegram_id, platform, username, first_name, last_name))
        await db.commit()


async def create_order(data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO orders (
                telegram_id, platform, from_city, to_city, trip_date, trip_time,
                passengers, has_children, children_count, baggage,
                need_minivan, stops, client_name, client_phone,
                calculated_price, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        """, (
            data["telegram_id"],
            data.get("platform", "telegram"),
            data["from_city"],
            data["to_city"],
            data["trip_date"],
            data["trip_time"],
            data["passengers"],
            data["has_children"],
            data["children_count"],
            data["baggage"],
            data["need_minivan"],
            data["stops"],
            data["client_name"],
            data["client_phone"],
            data["calculated_price"],
        ))
        await db.commit()
        return cursor.lastrowid


async def get_user_orders(telegram_id: int, platform: str = "telegram") -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders
            WHERE telegram_id = ? AND platform = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (telegram_id, platform)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_order_by_id(order_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def cancel_order(order_id: int, telegram_id: int, platform: str = "telegram") -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE orders
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND telegram_id = ? AND platform = ?
                  AND status NOT IN ('cancelled', 'completed')
        """, (order_id, telegram_id, platform))
        await db.commit()
        return cursor.rowcount > 0


async def update_order_status(order_id: int, status: str, manager_comment: str | None = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE orders
            SET status = ?, manager_comment = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, manager_comment, order_id))
        await db.commit()
        return cursor.rowcount > 0


async def update_order_final_price(order_id: int, final_price: int) -> bool:
    """Устанавливает финальную цену и подтверждает заказ."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE orders
            SET final_price = ?, status = 'confirmed',
                manager_comment = 'Подтверждён менеджером с финальной ценой',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (final_price, order_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_all_orders_for_admin(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# ─────────────────────────── Запросы для админ-панели ───────────────────────

ADMIN_PER_PAGE = 8


async def get_orders_paginated(page: int = 0, status: str = "all") -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        offset = page * ADMIN_PER_PAGE
        if status == "all":
            query = "SELECT * FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (ADMIN_PER_PAGE, offset)
        else:
            query = "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (status, ADMIN_PER_PAGE, offset)
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_orders_total_count(status: str = "all") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "all":
            async with db.execute("SELECT COUNT(*) FROM orders") as cursor:
                row = await cursor.fetchone()
        else:
            async with db.execute(
                "SELECT COUNT(*) FROM orders WHERE status = ?", (status,)
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else 0


async def get_admin_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users: int = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(DISTINCT telegram_id) FROM orders"
        ) as cursor:
            users_with_orders: int = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status"
        ) as cursor:
            rows = await cursor.fetchall()
            orders_by_status: dict[str, int] = {r[0]: r[1] for r in rows}

        total_orders = sum(orders_by_status.values())

        async with db.execute(
            "SELECT SUM(calculated_price) FROM orders WHERE status != 'cancelled'"
        ) as cursor:
            total_revenue: int = (await cursor.fetchone())[0] or 0

        avg_price = (
            round(total_revenue / (total_orders - orders_by_status.get("cancelled", 0)))
            if total_orders - orders_by_status.get("cancelled", 0) > 0
            else 0
        )

        return {
            "total_users": total_users,
            "users_with_orders": users_with_orders,
            "conversion_rate": (
                round(users_with_orders / total_users * 100, 1) if total_users > 0 else 0
            ),
            "total_orders": total_orders,
            "orders_by_status": orders_by_status,
            "total_revenue": total_revenue,
            "avg_price": avg_price,
        }


async def get_orders_by_date(date_str: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE trip_date = ? ORDER BY trip_time ASC",
            (date_str,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_orders_by_date_range(start_iso: str, end_iso: str) -> list[dict]:
    """
    Возвращает заказы с trip_date в диапазоне [start_iso, end_iso] включительно.
    Даты передаются в формате ISO: YYYY-MM-DD.
    В БД trip_date хранится как DD.MM.YYYY — конвертируем через substr().
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *,
                   substr(trip_date, 7, 4) || '-' ||
                   substr(trip_date, 4, 2) || '-' ||
                   substr(trip_date, 1, 2) AS _iso_date
            FROM orders
            WHERE _iso_date BETWEEN ? AND ?
            ORDER BY _iso_date ASC, trip_time ASC
            """,
            (start_iso, end_iso),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_confirmed_orders_for_reminders() -> list[dict]:
    """Заказы в статусе confirmed с датой/временем — для отправки напоминаний."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders
            WHERE status = 'confirmed'
            ORDER BY trip_date, trip_time
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def check_notification_sent(order_id: int, kind: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM notifications WHERE order_id = ? AND kind = ?",
            (order_id, kind),
        ) as cursor:
            return (await cursor.fetchone()) is not None


async def mark_notification_sent(order_id: int, kind: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO notifications (order_id, kind) VALUES (?, ?)",
            (order_id, kind),
        )
        await db.commit()


async def save_review(
    order_id: int,
    telegram_id: int,
    rating: int,
    text: str | None,
    platform: str = "telegram",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO reviews (order_id, telegram_id, platform, rating, review_text)
            VALUES (?, ?, ?, ?, ?)
        """, (order_id, telegram_id, platform, rating, text))
        await db.commit()


async def get_review_by_order(order_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reviews WHERE order_id = ?", (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_review_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), AVG(rating) FROM reviews") as cursor:
            row = await cursor.fetchone()
            return {
                "total_reviews": row[0] or 0,
                "avg_rating": round(row[1], 1) if row[1] else 0,
            }


# ─────────────────────────── Маршруты (route_prices) ──────────────────────


async def get_all_routes(active_only: bool = False) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM route_prices"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY from_city, to_city"
        async with db.execute(q) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_route_price(from_city: str, to_city: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT price FROM route_prices WHERE from_city = ? AND to_city = ? AND is_active = 1",
            (from_city, to_city),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_route_by_id(route_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM route_prices WHERE id = ?", (route_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_route(from_city: str, to_city: str, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO route_prices (from_city, to_city, price, is_active)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(from_city, to_city) DO UPDATE SET price = excluded.price, is_active = 1
        """, (from_city, to_city, price))
        await db.commit()
        return cur.lastrowid


async def delete_route(route_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM route_prices WHERE id = ?", (route_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_departure_cities() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT DISTINCT from_city FROM route_prices WHERE is_active = 1 ORDER BY from_city"
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def get_destination_cities(from_city: str | None = None) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        if from_city:
            async with db.execute(
                "SELECT DISTINCT to_city FROM route_prices WHERE from_city = ? AND is_active = 1 ORDER BY to_city",
                (from_city,),
            ) as cursor:
                return [row[0] for row in await cursor.fetchall()]
        else:
            async with db.execute(
                "SELECT DISTINCT to_city FROM route_prices WHERE is_active = 1 ORDER BY to_city"
            ) as cursor:
                return [row[0] for row in await cursor.fetchall()]


async def get_routes_paginated(page: int = 0, per_page: int = 8) -> tuple[list[dict], int]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM route_prices") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT * FROM route_prices ORDER BY from_city, to_city LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total


async def get_all_users_for_export() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                u.telegram_id,
                u.platform,
                u.username,
                u.first_name,
                u.last_name,
                u.created_at,
                COUNT(o.id)              AS orders_count,
                MAX(o.created_at)        AS last_order_date,
                SUM(o.calculated_price)  AS total_spent
            FROM users u
            LEFT JOIN orders o
                ON u.telegram_id = o.telegram_id AND u.platform = o.platform
            GROUP BY u.telegram_id, u.platform
            ORDER BY u.created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
