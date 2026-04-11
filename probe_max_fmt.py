"""
Probe №3 — проверка двух вещей:
  1. Какой формат текста MAX рендерит жирным:
       a) plain  : *bold*           (single-asterisk)
       b) plain  : **bold**         (double-asterisk)
       c) format=markdown : *bold*
       d) format=markdown : **bold**
       e) format=html : <b>bold</b>
  2. Как выглядит update от нажатия request_contact (где лежит телефон)

Запустить:
    .venv/Scripts/python.exe probe_max_fmt.py

Что нужно от тебя:
  - Запусти скрипт
  - Открой MAX, найди бота, напиши "тест"
  - Бот пришлёт 5 сообщений — посмотри какие из них с жирным текстом, скажи мне номера
  - В последнем сообщении будет кнопка «📱 Отправить телефон» — нажми, поделись контактом
  - Скинь весь вывод
"""

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from shared.config import MAX_BOT_TOKEN

BASE = "https://platform-api.max.ru"


def dump(label, data):
    print(f"\n========== {label} ==========")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(repr(data) if not isinstance(data, str) else data)


async def get_one_update(c, marker, want_type=None, timeout_iters=20):
    for _ in range(timeout_iters):
        params = {"timeout": 30, "limit": 10}
        if marker:
            params["marker"] = marker
        r = await c.get(f"{BASE}/updates", params=params)
        data = r.json()
        if data.get("marker"):
            marker = data["marker"]
        for upd in data.get("updates") or []:
            if want_type is None or upd.get("update_type") == want_type:
                return upd, marker
    return None, marker


async def main():
    headers = {"Authorization": MAX_BOT_TOKEN}
    async with httpx.AsyncClient(timeout=35.0, headers=headers) as c:
        marker = None

        # 1) Получаем chat_id
        print("\n⏳ Жду 'тест' от тебя в MAX...")
        upd, marker = await get_one_update(c, marker, want_type="message_created")
        chat_id = ((upd.get("message") or {}).get("recipient") or {}).get("chat_id")
        print(f"\n✅ chat_id = {chat_id}")

        # 2) Отправляем 5 разных вариантов форматирования
        variants = [
            ("№1 (без format, single)",  {"text": "№1 *жирный?* конец"}),
            ("№2 (без format, double)",  {"text": "№2 **жирный?** конец"}),
            ("№3 (format=markdown, single)", {"text": "№3 *жирный?* конец", "format": "markdown"}),
            ("№4 (format=markdown, double)", {"text": "№4 **жирный?** конец", "format": "markdown"}),
            ("№5 (format=html, <b>)",    {"text": "№5 <b>жирный?</b> конец", "format": "html"}),
        ]
        for label, body in variants:
            r = await c.post(f"{BASE}/messages", params={"chat_id": chat_id}, json=body)
            print(f"  {label}: HTTP {r.status_code}")
            if r.status_code >= 400:
                print(f"    ERR: {r.text[:200]}")

        # 3) Сообщение с кнопкой request_contact
        kb = {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"type": "request_contact", "text": "📱 Отправить телефон"}]
                ]
            }
        }
        r = await c.post(
            f"{BASE}/messages",
            params={"chat_id": chat_id},
            json={"text": "👉 Нажми кнопку и поделись контактом:", "attachments": [kb]},
        )
        print(f"\n  request_contact button: HTTP {r.status_code}")

        # 4) Ждём update от нажатия contact
        print("\n⏳ Жду пока ты поделишься контактом через кнопку...")
        upd, marker = await get_one_update(c, marker, want_type=None, timeout_iters=30)
        if upd:
            dump("RAW UPDATE FROM CONTACT SHARE", upd)
            # Дополнительно: если есть message с attachments, разберём их
            msg = upd.get("message") or {}
            body = msg.get("body") or {}
            atts = body.get("attachments") or []
            dump("attachments", atts)
        else:
            print("\n⚠️ Не дождался — попробуй запустить ещё раз и нажать на кнопку быстрее")


if __name__ == "__main__":
    asyncio.run(main())
