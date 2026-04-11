# Алтай Трансфер — боты Telegram + MAX

Два независимых бота для приёма заявок на трансфер по Алтайскому краю и Республике Алтай:

- **Telegram-бот** — на [aiogram 3](https://github.com/aiogram/aiogram), полная функциональность + админ-панель
- **MAX-бот** — на прямом HTTP-клиенте к [platform-api.max.ru](https://dev.max.ru/), пользовательские функции (без админки)

Оба бота **работают с одной базой данных SQLite** и **общим набором настроек**. Все заявки (из обоих мессенджеров) уходят в единый Telegram-чат менеджера — там одни и те же кнопки «Принять / Отклонить / Указать цену» работают с обоими ботами.

---

## Возможности

| Фича | Telegram | MAX |
|------|:--:|:--:|
| Главное меню с фото | ✅ | ✅ *(без фото)* |
| 10-шаговое бронирование | ✅ | ✅ |
| Календарь выбора даты | ✅ | ✅ |
| Геокодинг произвольного адреса (OSM/OSRM) | ✅ | ✅ |
| Сохранение ненайденного адреса как текст | ✅ | ✅ |
| Калькулятор цены | ✅ | ✅ |
| Мои заказы (история + отмена) | ✅ | ✅ |
| Связаться с менеджером | ✅ | ✅ |
| Отзывы после поездки | ✅ | ✅ |
| Напоминания 24 ч / 1 ч | ✅ | ✅ *(через TG-бот)* |
| Админ-панель `/admin` | ✅ | — |

Менеджер в одном Telegram-чате принимает/отклоняет/назначает финальную цену — и клиент получает ответ в том мессенджере, откуда была заявка (Telegram или MAX).

---

## Структура проекта

```
transfer_bot/
├── shared/                     # общий код (импортируется обоими ботами)
│   ├── config.py               # загрузка .env (оба токена + chat ids)
│   ├── database.py             # SQLite CRUD с колонкой `platform`
│   ├── price_calculator.py     # расчёт цены
│   ├── settings_store.py       # кэш настроек с авто-refresh каждые 60 сек
│   ├── routes_data.py          # маршруты, координаты, справочники
│   ├── geo_calculator.py       # Nominatim + OSRM
│   └── notifier.py             # кросс-платформенные уведомления клиенту
│
├── tg_bot/                     # Telegram-бот (aiogram 3)
│   ├── bot.py                  # entry point
│   ├── states.py
│   ├── keyboards.py
│   └── handlers/
│       ├── start.py
│       ├── booking.py
│       ├── price_check.py
│       ├── my_orders.py
│       ├── manager_transfer.py
│       ├── manager_actions.py  # управление заказами менеджером
│       ├── admin.py            # админ-панель
│       ├── admin_settings.py   # редактор настроек
│       ├── reviews.py
│       └── notifications.py    # планировщик напоминаний (обслуживает обе платформы)
│
├── max_bot/                    # MAX messenger бот
│   ├── bot.py                  # entry point (long polling)
│   ├── max_client.py           # HTTP-клиент platform-api.max.ru
│   ├── dispatcher.py           # мини-роутер апдейтов
│   ├── fsm.py                  # in-memory FSM
│   ├── keyboards.py
│   ├── notify_manager.py       # отправка заявок в Telegram-чат менеджера
│   └── handlers/
│       ├── start.py
│       ├── booking.py
│       ├── price_check.py
│       ├── my_orders.py
│       ├── manager_transfer.py
│       └── reviews.py
│
├── deploy/                     # systemd-сервисы
│   ├── transfer-tg-bot.service
│   └── transfer-max-bot.service
│
├── transfer_bot.db             # общая SQLite (создаётся при первом запуске)
├── .env                        # ваш конфиг (не коммитится)
├── .env.example                # шаблон
├── requirements.txt
└── README.md
```

---

## Развёртывание на Ubuntu 22.04 (timeweb VPS)

### 1. Подготовка сервера

```bash
# Залогиниться на сервер (root или с sudo)
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git
```

### 2. Создать пользователя для бота

```bash
sudo useradd -r -s /bin/false -d /opt/transfer_bot botuser
sudo mkdir -p /opt/transfer_bot
sudo chown botuser:botuser /opt/transfer_bot
```

### 3. Загрузить код

Вариант A — через scp с локальной машины:
```bash
# На локальной машине, из папки transfer_bot/
scp -r * user@your-vps:/tmp/transfer_bot/
# На сервере:
sudo mv /tmp/transfer_bot/* /opt/transfer_bot/
sudo chown -R botuser:botuser /opt/transfer_bot
```

Вариант B — через git (рекомендуется):
```bash
sudo -u botuser git clone <your-repo-url> /opt/transfer_bot
```

### 4. Виртуальное окружение и зависимости

```bash
cd /opt/transfer_bot
sudo -u botuser python3.11 -m venv .venv
sudo -u botuser .venv/bin/pip install --upgrade pip
sudo -u botuser .venv/bin/pip install -r requirements.txt
```

### 5. Настроить `.env`

```bash
sudo -u botuser cp .env.example .env
sudo -u botuser nano .env
```

Заполнить:
```
BOT_TOKEN=ваш_токен_tg_бота
MANAGER_CHAT_ID=ваш_tg_chat_id_для_заявок
ADMIN_IDS=ваш_tg_id
MAX_BOT_TOKEN=ваш_max_токен
DB_PATH=/opt/transfer_bot/transfer_bot.db
```

### 6. Проверить, что боты запускаются вручную

```bash
cd /opt/transfer_bot
sudo -u botuser .venv/bin/python -m tg_bot.bot
# Ctrl+C после того как увидите "Telegram-бот запущен"

sudo -u botuser .venv/bin/python -m max_bot.bot
# Ctrl+C после того как увидите "MAX-бот запущен"
```

Если обе команды стартуют без ошибок — можно переходить к systemd.

### 7. Установить systemd-сервисы

```bash
sudo cp /opt/transfer_bot/deploy/transfer-tg-bot.service /etc/systemd/system/
sudo cp /opt/transfer_bot/deploy/transfer-max-bot.service /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable --now transfer-tg-bot.service
sudo systemctl enable --now transfer-max-bot.service
```

### 8. Проверить, что всё работает

```bash
sudo systemctl status transfer-tg-bot.service
sudo systemctl status transfer-max-bot.service

# Логи в реальном времени
sudo journalctl -u transfer-tg-bot.service -f
sudo journalctl -u transfer-max-bot.service -f
```

---

## Обновление кода на сервере

```bash
cd /opt/transfer_bot
sudo -u botuser git pull                       # если через git
sudo -u botuser .venv/bin/pip install -r requirements.txt
sudo systemctl restart transfer-tg-bot.service transfer-max-bot.service
```

---

## Архитектурные детали

### Общая БД

Используется **SQLite с WAL-режимом** (включается автоматически в `shared/database.py`). WAL разрешает параллельное чтение + одного писателя, чего достаточно для одновременной работы двух ботов. Файл базы один на оба процесса.

**Таблица `orders`** содержит колонку `platform` (`telegram` / `max`). По ней определяется, в какой мессенджер отправлять уведомления клиенту. Миграция добавляет колонку к существующим БД и ставит всем старым записям `platform='telegram'`.

### Кросс-платформенные уведомления

Когда менеджер нажимает в Telegram «Принять заказ» или «Указать цену», Telegram-бот через модуль `shared/notifier.py` отправляет подтверждение клиенту в **тот мессенджер, откуда была заявка**. notifier держит HTTP-клиенты к обоим API и выбирает нужный по полю `order.platform`.

### Единый чат менеджера

Оба бота отправляют уведомления о новых заявках в **один и тот же Telegram-чат** (`MANAGER_CHAT_ID`). MAX-бот использует для этого Telegram Bot API напрямую. Кнопки `mgr_accept` / `mgr_reject` / `mgr_set_price` в таких уведомлениях обрабатываются Telegram-ботом (его `manager_actions.py`), который умеет отвечать клиенту через notifier в нужную платформу.

### Настройки

Таблица `settings` (тексты, наценки, переключатели шагов) общая. Каждый бот держит её копию в памяти (`settings_store._cache`) и **перезагружает раз в 60 секунд**, чтобы подхватывать изменения, сделанные другим процессом через админ-панель.

### Напоминания 24 ч / 1 ч

Планировщик запущен **только в Telegram-боте** (чтобы не было дубликатов). Он достаёт все `confirmed`-заказы из обеих платформ и отправляет напоминания через notifier.

### Админ-панель

Доступна только в Telegram через `/admin`. Админ видит заказы из обоих мессенджеров — в списке у заказов из MAX появляется бейдж «💬 MAX».

---

## Логика расчёта цены

| Параметр | Надбавка |
|---|---|
| Базовая цена маршрута (до 3 пасс.) | по таблице `route_prices` |
| Каждый пассажир сверх 3 | +500 ₽ |
| Минивэн | +1 500 ₽ |
| Детское кресло (за штуку) | +300 ₽ |
| Крупный/объёмный багаж | +500 ₽ |
| 1–2 остановки по дороге | +700 ₽ |
| 3+ остановки | +1 500 ₽ |
| Произвольный адрес (расчёт по км) | 30 ₽/км × расстояние (OSRM) |

Наценки хранятся в таблице `settings` и редактируются через админ-панель без рестарта ботов.

---

## Статусы заказов

| Код | Статус |
|---|---|
| `new` | 🆕 Новый (ожидает обработки) |
| `confirmed` | ✅ Подтверждён менеджером |
| `in_progress` | 🚗 В пути |
| `completed` | 🏁 Завершён |
| `cancelled` | ❌ Отменён |
